"""Work Mode middleware for automatic phase-loop execution.

Drives the ReAct loop in Work Mode: every cycle, before_model() finds the next
ready todo, injects a HumanMessage instruction, and emits SSE events for phase
tracking.  When all phases are complete it returns None, letting the model
produce a summary and terminate.

Phase completion is detected at the *start* of each cycle by diffing current
completed IDs against the snapshot taken at the end of the previous cycle —
no after_model() hook required.

Import rule: _materialize_ready_ids is imported from todo_dag_middleware; never
copy or re-implement it (it excludes both "completed" and "blocked" nodes).

SSE rule: All SSE events use get_stream_writer() — same mechanism as
task_started/title_update.  append_runtime_event() is for inter-middleware
logging only and does NOT reach the frontend.

Instruction rule: The work_mode_instruction HumanMessage must end with
"Do NOT output any text — the system will automatically assign the next phase."
If the model outputs text the ReAct loop terminates before all phases complete.

Auto-cycle (Phase 4): when auto_mode=True in the runtime context, plan_adapted
and complexity_escalation events automatically spawn a daemon thread that
re-invokes the agent with mode="plan" after the current run finishes (same
pattern as ProFollowupMiddleware).  Adaptation attempts are capped at 2; on the
third the user must intervene manually.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime

from src.agents.middlewares.plan_execution import format_clarification_context_for_work
from src.agents.middlewares.runtime_events import RUNTIME_EVENTS_KEY, append_runtime_event
from src.agents.middlewares.todo_dag_middleware import _materialize_ready_ids

logger = logging.getLogger(__name__)

_MAX_AUTO_ADAPTATION_ATTEMPTS = 2
_WORK_MODE_REPEAT_THRESHOLD = 5
_WORD_RE = re.compile(r"\b\w+\b")
_COMPLEX_KEYWORDS = (
    "plan",
    "analyze",
    "analyse",
    "compare",
    "design",
    "build",
    "implement",
    "refactor",
    "migrate",
    "audit",
    "review",
    "investigate",
    "explore",
    "research",
    "end-to-end",
    "comprehensive",
    "all of",
    "multi-step",
    "roadmap",
    "architecture",
    "proposal",
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _is_report_todo(todo_content: str) -> bool:
    lowered = (todo_content or "").lower()
    return "report" in lowered or "comprehensive" in lowered


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content)


def _has_keyword(text: str, keyword: str) -> bool:
    if " " in keyword or "-" in keyword:
        return keyword in text
    return keyword in set(_WORD_RE.findall(text))


def _classify_complexity(user_prompt: str) -> str:
    text = user_prompt.strip()
    lowered = text.lower()
    if not text or len(text) < 25:
        return "trivial"
    if any(_has_keyword(lowered, kw) for kw in _COMPLEX_KEYWORDS):
        return "complex"
    if len(text) > 300 or "\n" in text:
        return "complex"
    return "moderate"


def _latest_human_prompt(messages: list[Any]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) != "human":
            continue
        text = _extract_text(getattr(message, "content", ""))
        if text.strip():
            return text
    return ""


def _runtime_user_prompt(runtime_context: dict[str, Any], messages: list[Any]) -> str:
    """Resolve the best prompt for complexity classification.

    Prefer the raw user turn text from runtime context because middleware may
    prepend operational guidance blocks (e.g. <mounted_folder>) to the last
    HumanMessage before Work Mode runs.
    """
    current_turn = str(runtime_context.get("current_turn_text") or "").strip()
    if current_turn:
        return current_turn
    original_request = str(runtime_context.get("original_user_request") or "").strip()
    if original_request:
        return original_request
    return _latest_human_prompt(messages)


class WorkModeMiddlewareState(AgentState):
    """Compatible with the ThreadState schema."""

    todo_graph: NotRequired[dict | None]
    plan: NotRequired[dict | None]
    plan_history: NotRequired[list[dict] | None]
    work_mode: NotRequired[dict | None]
    phase_execution: NotRequired[dict | None]
    complexity_tier: NotRequired[str | None]
    deferred_task_calls: NotRequired[list[dict] | None]


def _normalize_plan_status(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"draft", "approved", "executing", "completed"}:
        return value
    return "draft"


def _update_plan_history_status(history: list[dict] | None, plan_id: str | None, status: str) -> list[dict] | None:
    if not history or not plan_id:
        return history
    updated: list[dict] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        if str(item.get("plan_id") or "").strip() == plan_id:
            updated.append({**item, "status": status})
        else:
            updated.append(item)
    return updated


def _run_plan_mode_rerun(
    *,
    thread_id: str,
    requested_model_name: str | None,
    system_message: str,
) -> None:
    """Daemon target: re-invoke the agent with mode='plan' after current run finishes.

    Mirrors _run_background_followup in ProFollowupMiddleware. Sleeps briefly to
    let the Work Mode run reach its checkpoint before starting a new run on the
    same thread (LangGraph serialises runs per thread via the checkpoint lock).
    """
    from src.agents.middlewares.daemon_agent_invoke import invoke_client_agent_async
    from src.client import CapyHomeClient

    time.sleep(2.0)
    try:
        client = CapyHomeClient(
            model_name=requested_model_name,
            thinking_enabled=True,
            subagent_enabled=True,
            plan_mode=True,
        )
        config = client._get_runnable_config(  # noqa: SLF001
            thread_id,
            model_name=requested_model_name,
            thinking_enabled=True,
            subagent_enabled=True,
        )
        config["configurable"].update(
            {
                "mode": "plan",
                "is_plan_mode": True,
            }
        )
        invoke_client_agent_async(
            client,
            {"messages": [HumanMessage(name="work_mode_plan_rerun", content=system_message)]},
            config=config,
            context={
                "thread_id": thread_id,
                "mode": "plan",
                "is_plan_mode": True,
                "model_name": requested_model_name,
            },
        )
    except Exception:
        logger.exception("Auto Plan Mode re-invocation failed for thread %s", thread_id)


def _spawn_plan_rerun(
    *,
    thread_id: str,
    requested_model_name: str | None,
    system_message: str,
    thread_name_suffix: str = "",
) -> None:
    """Spawn a daemon thread to re-invoke with mode='plan'."""
    worker = threading.Thread(
        target=_run_plan_mode_rerun,
        kwargs={
            "thread_id": thread_id,
            "requested_model_name": requested_model_name,
            "system_message": system_message,
        },
        name=f"work-mode-plan-rerun-{thread_id[:8]}{thread_name_suffix}",
        daemon=True,
    )
    worker.start()


class WorkModeMiddleware(AgentMiddleware[WorkModeMiddlewareState]):
    """Drives automatic phase-loop execution in Work Mode.

    Runs every ReAct cycle. Each call to before_model():
    1. Detects newly completed todos from the previous cycle (via snapshot diff)
    2. Emits phase_completed SSE for each newly completed todo
    3. Finds the next ready (non-completed, unblocked) todo
    4. Emits phase_started SSE and injects a HumanMessage instruction
    5. Returns None when all phases are done → model summarises and terminates

    Phase 4 (auto-cycle): when auto_mode=True in runtime context, blocked plans
    and complex requests automatically trigger a Plan Mode re-run (capped at 2).
    """

    state_schema = WorkModeMiddlewareState

    def __init__(self) -> None:
        super().__init__()
        # Snapshot of completed todo IDs from the previous cycle.
        # None = first call; seeded from current state to suppress spurious
        # phase_completed events when resuming a thread mid-execution.
        self._completed_before: frozenset[str] | None = None

    def _ephemeral_work_instruction(self, state: dict[str, Any] | None) -> str | None:
        if not isinstance(state, dict):
            return None
        phase_execution = state.get("phase_execution")
        if not isinstance(phase_execution, dict):
            return None
        instruction_text = str(phase_execution.get("ephemeral_instruction_text") or "").strip()
        if not instruction_text:
            return None
        todo_id = str(phase_execution.get("last_todo_id") or "").strip()
        if not todo_id:
            return None
        todo_graph = state.get("todo_graph")
        nodes = todo_graph.get("nodes") if isinstance(todo_graph, dict) else None
        if not isinstance(nodes, list):
            return None
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("id") or "") != todo_id:
                continue
            status = str(node.get("status") or "").strip().lower()
            if status in {"completed", "blocked"}:
                return None
            return instruction_text
        return None

    def _with_ephemeral_instruction(self, request: ModelRequest) -> ModelRequest:
        request_state = request.state if isinstance(getattr(request, "state", None), dict) else None
        if request_state is None:
            runtime_obj = getattr(request, "runtime", None)
            runtime_state = getattr(runtime_obj, "state", None)
            request_state = runtime_state if isinstance(runtime_state, dict) else None
        instruction_text = self._ephemeral_work_instruction(request_state)
        if not instruction_text:
            return request
        msg = SystemMessage(name="work_mode_instruction", content=f"<work_mode_instruction>\n{instruction_text}\n</work_mode_instruction>")
        return request.override(messages=[msg, *request.messages])

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._with_ephemeral_instruction(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._with_ephemeral_instruction(request))

    @override
    def before_model(self, state: WorkModeMiddlewareState, runtime: Runtime) -> dict[str, Any] | None:  # noqa: ARG002
        runtime_context: dict = getattr(runtime, "context", None) or {}
        auto_mode: bool = bool(runtime_context.get("auto_mode"))
        thread_id: str | None = runtime_context.get("thread_id")
        requested_model_name: str | None = runtime_context.get("model_name")
        plan_state = dict(state.get("plan") or {})
        plan_history = [item for item in (state.get("plan_history") or []) if isinstance(item, dict)]
        plan_status = _normalize_plan_status(plan_state.get("status"))

        graph = state.get("todo_graph") or {}
        nodes: list[dict] | None = graph.get("nodes") if isinstance(graph, dict) else None
        graph_update: dict[str, Any] | None = None

        # ── No plan yet ────────────────────────────────────────────────────────
        if not nodes:
            complexity_tier = state.get("complexity_tier")
            if not complexity_tier:
                prompt = _runtime_user_prompt(runtime_context, state.get("messages", []) or [])
                if prompt:
                    complexity_tier = _classify_complexity(prompt)
                    if complexity_tier:
                        if complexity_tier == "complex":
                            self._handle_complexity_escalation(
                                auto_mode=auto_mode,
                                thread_id=thread_id,
                                requested_model_name=requested_model_name,
                            )
                        return {"complexity_tier": complexity_tier}
            if complexity_tier == "complex":
                self._handle_complexity_escalation(
                    auto_mode=auto_mode,
                    thread_id=thread_id,
                    requested_model_name=requested_model_name,
                )
            return None

        if plan_state:
            if plan_status not in {"approved", "executing", "completed"}:
                return None

        # ── Self-heal stale in-progress todos ──────────────────────────────────
        # If a previous run was interrupted (reload/crash/manual stop), todos can
        # remain "in_progress" even though no subagent is currently running.
        # Re-queue them as pending so Work Mode can retry automatically.
        deferred_calls = state.get("deferred_task_calls") or []
        running_deferred = [
            item for item in deferred_calls
            if isinstance(item, dict) and item.get("status") not in {"completed", "failed", "timed_out"}
        ]
        stale_in_progress_ids = [
            str(n.get("id"))
            for n in nodes
            if isinstance(n, dict) and n.get("status") == "in_progress" and n.get("id")
        ]
        can_self_heal_in_progress = plan_status in {"approved", "executing"}
        if stale_in_progress_ids and not running_deferred and can_self_heal_in_progress:
            repaired_nodes: list[dict] = []
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_id = str(node.get("id") or "")
                if node_id and node_id in stale_in_progress_ids:
                    repaired_nodes.append({**node, "status": "pending"})
                else:
                    repaired_nodes.append(node)
            nodes = repaired_nodes
            graph_update = {**graph, "nodes": repaired_nodes}

        # ── Detect newly completed todos from previous cycle ───────────────────
        current_completed: frozenset[str] = frozenset(
            n["id"] for n in nodes if n.get("status") == "completed"
        )
        # First cycle: seed from current state so we don't re-emit phase_completed
        # for todos that were already done before this run started (resume case).
        if self._completed_before is None:
            self._completed_before = current_completed
        newly_completed = current_completed - self._completed_before

        writer = get_stream_writer()

        if newly_completed:
            node_by_id = {n["id"]: n for n in nodes}
            for todo_id in newly_completed:
                node = node_by_id.get(todo_id)
                if node is None:
                    continue
                phase_index = next((i for i, n in enumerate(nodes) if n["id"] == todo_id), 0)
                try:
                    writer({
                        "type": "phase_completed",
                        "source": "work_mode_middleware",
                        "todo_id": todo_id,
                        "content": node.get("content", ""),
                        "phase_index": phase_index,
                        "completed_at": _utc_now_iso(),
                    })
                except Exception:
                    logger.exception("Failed to emit phase_completed SSE for %s", todo_id)

        # Snapshot current completed set for next cycle's diff
        self._completed_before = current_completed

        # ── Find next ready todo ───────────────────────────────────────────────
        ready_ids = _materialize_ready_ids(nodes)
        node_by_id = {n["id"]: n for n in nodes}

        pending_ready = [
            nid for nid in ready_ids
            if node_by_id.get(nid, {}).get("status") not in {"completed", "in_progress"}
        ]
        has_in_progress = any(
            isinstance(n, dict) and n.get("status") == "in_progress"
            for n in nodes
        )

        # ── Plan adaptation: nodes exist but none are ready ────────────────────
        # Exclude in_progress — a running todo is not a sign the plan is stuck.
        # Blocked items still represent unfinished work and should trigger adaptation
        # when nothing is ready.
        pending_nodes = [n for n in nodes if n.get("status") not in {"completed", "in_progress"}]
        if not pending_ready and pending_nodes and not has_in_progress:
            return self._handle_plan_adapted(
                state=state,
                nodes=nodes,
                pending_nodes=pending_nodes,
                auto_mode=auto_mode,
                thread_id=thread_id,
                requested_model_name=requested_model_name,
            )

        # ── All phases complete ────────────────────────────────────────────────
        if not pending_ready:
            if plan_state and plan_status in {"approved", "executing"}:
                plan_id = str(plan_state.get("plan_id") or "").strip() or None
                update_payload: dict[str, Any] = {
                    "plan": {
                        **plan_state,
                        "status": "completed",
                        "completed_at": _utc_now_iso(),
                    },
                    "plan_history": _update_plan_history_status(plan_history, plan_id, "completed"),
                }
                if graph_update is not None:
                    update_payload["todo_graph"] = graph_update
                return update_payload
            return None

        # ── Emit phase_started and inject instruction ──────────────────────────
        next_todo = node_by_id[pending_ready[0]]
        next_todo_id = str(next_todo.get("id") or "")
        phase_index = next((i for i, n in enumerate(nodes) if n["id"] == next_todo["id"]), 0)
        total_phases = len(nodes)

        try:
            writer({
                "type": "phase_started",
                "source": "work_mode_middleware",
                "todo_id": next_todo["id"],
                "content": next_todo.get("content", ""),
                "subagent_type": next_todo.get("subagent_type"),
                "phase_index": phase_index,
                "total_phases": total_phases,
            })
        except Exception:
            logger.exception("Failed to emit phase_started SSE for %s", next_todo["id"])

        todo_content = next_todo.get("content", "")
        rationale = str(next_todo.get("rationale") or "").strip()
        rationale_block = f"\nRationale: {rationale}" if rationale else ""
        subagent_hint = ""
        if next_todo.get("subagent_type"):
            subagent_hint = f" Use a {next_todo['subagent_type']} subagent if available."

        clarification_block = ""
        if isinstance(plan_state, dict):
            clarification_text = format_clarification_context_for_work(plan_state)
            if clarification_text:
                clarification_block = f"\n{clarification_text}\n"

        report_contract = ""
        if _is_report_todo(todo_content):
            report_contract = (
                "\nUse a two-stage generation contract for speed+accuracy:\n"
                "Stage A: produce a compact outline plus section-level claims list before drafting full content.\n"
                "Stage B: expand into the final report from the outline and essential evidence only.\n"
                "Add confidence tags (high/medium/low) for key claims with weak support.\n"
                "Write the final report to /mnt/user-data/workspace/ (e.g. report.md) and call `present_files` so the user receives it.\n"
                "Before final write_file, self-check for duplicate table rows, repeated long paragraphs, heading numbering consistency, and required sections.\n"
            )
        existing_pe: dict = dict(state.get("phase_execution") or {})
        repeat_counts_raw = existing_pe.get("repeat_counts") if isinstance(existing_pe.get("repeat_counts"), dict) else {}
        repeat_counts: dict[str, int] = {}
        for key, value in dict(repeat_counts_raw or {}).items():
            try:
                repeat_counts[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        forced_reconcile_raw = existing_pe.get("forced_reconcile_done") if isinstance(existing_pe.get("forced_reconcile_done"), dict) else {}
        forced_reconcile_done: dict[str, bool] = {str(key): bool(value) for key, value in dict(forced_reconcile_raw or {}).items()}
        last_todo_id = str(existing_pe.get("last_todo_id") or "").strip()
        repeat_count = repeat_counts.get(next_todo_id, 0) + 1 if last_todo_id == next_todo_id else 1
        repeat_counts[next_todo_id] = repeat_count
        threshold = _WORK_MODE_REPEAT_THRESHOLD
        should_force_reconcile = (
            repeat_count > threshold
            and not forced_reconcile_done.get(next_todo_id, False)
        )
        runtime_events = (getattr(runtime, "context", None) or {}).get(RUNTIME_EVENTS_KEY, [])
        dangling_todo_update = any(
            isinstance(evt, dict)
            and evt.get("event") == "todo_update_dangling"
            and str(evt.get("tool_name") or "") == "write_todos"
            for evt in (runtime_events if isinstance(runtime_events, list) else [])
        )
        should_force_reconcile = should_force_reconcile or (dangling_todo_update and not forced_reconcile_done.get(next_todo_id, False))

        instruction_body = (
            f"Execute the following task now: {todo_content}.{subagent_hint}{rationale_block}\n"
            f"{clarification_block}"
            f"{report_contract}"
            f"When done, call write_todos to mark todo id '{next_todo['id']}' as completed.\n"
            f"If write_todos is unexpectedly unavailable, state that explicitly and include the intended status update for todo id '{next_todo['id']}'.\n"
            f"Do NOT output any text — the system will automatically assign the next phase.\n"
        )
        instruction_kind = "task"
        if should_force_reconcile:
            forced_reconcile_done[next_todo_id] = True
            instruction_kind = "reconcile"
            append_runtime_event(
                runtime,
                {
                    "source": "work_mode_middleware",
                    "event": "todo_reconcile_forced",
                    "todo_id": next_todo_id,
                    "repeat_count": repeat_count,
                    "trigger": "dangling_write_todos" if dangling_todo_update else "repeat_threshold",
                },
            )
            instruction_body = (
                f"Reconcile todo state now for todo id '{next_todo['id']}' only.\n"
                f"Call write_todos immediately with an explicit status update for '{next_todo['id']}' "
                "(`completed` if done, otherwise `in_progress` or `blocked` with a short reason).\n"
                "Do not call other tools in this turn.\n"
                "If write_todos is unexpectedly unavailable, state that explicitly and include the intended status update.\n"
                "Do NOT output any text — the system will automatically assign the next phase.\n"
            )
        # ── Update phase_execution state ───────────────────────────────────────
        phase_results: list[dict] = list(existing_pe.get("phase_results") or [])

        existing_idx = next((i for i, r in enumerate(phase_results) if r.get("todo_id") == next_todo["id"]), None)
        new_entry: dict = {
            "phase_index": phase_index,
            "todo_id": next_todo["id"],
            "content": todo_content,
            "status": "in_progress",
            "subagent_type": next_todo.get("subagent_type"),
        }
        if existing_idx is not None:
            phase_results[existing_idx] = new_entry
        else:
            phase_results.append(new_entry)

        for todo_id in newly_completed:
            repeat_counts.pop(todo_id, None)
            forced_reconcile_done.pop(todo_id, None)
            idx = next((i for i, r in enumerate(phase_results) if r.get("todo_id") == todo_id), None)
            if idx is not None and phase_results[idx].get("status") != "completed":
                phase_results[idx] = {
                    **phase_results[idx],
                    "status": "completed",
                    "completed_at": _utc_now_iso(),
                }

        plan_update = None
        if plan_state and plan_status == "approved":
            plan_id = str(plan_state.get("plan_id") or "").strip() or None
            plan_update = {
                **plan_state,
                "status": "executing",
                "execution_started_at": str(plan_state.get("execution_started_at") or _utc_now_iso()),
            }
            plan_history = _update_plan_history_status(plan_history, plan_id, "executing") or plan_history

        update_payload: dict[str, Any] = {
            "work_mode": {
                "active": True,
                "plan_source": "prior_run",
                "current_phase_index": phase_index,
                "total_phases": total_phases,
                "phases_completed": len(current_completed),
            },
            "phase_execution": {
                **existing_pe,
                "current_phase": phase_index,
                "total_phases": total_phases,
                "phase_results": phase_results,
                "repeat_counts": repeat_counts,
                "forced_reconcile_done": forced_reconcile_done,
                "last_todo_id": next_todo_id,
                "last_instruction_kind": instruction_kind,
                "ephemeral_instruction_text": instruction_body.strip(),
            },
        }
        if graph_update is not None:
            update_payload["todo_graph"] = graph_update
        if plan_update is not None:
            update_payload["plan"] = plan_update
            update_payload["plan_history"] = plan_history
        return update_payload

    @override
    async def abefore_model(self, state: WorkModeMiddlewareState, runtime: Runtime) -> dict[str, Any] | None:
        return self.before_model(state, runtime)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _handle_complexity_escalation(
        self,
        *,
        auto_mode: bool,
        thread_id: str | None,
        requested_model_name: str | None,
    ) -> None:
        """Emit complexity_escalation SSE. If auto_mode, spawn a Plan Mode re-run."""
        try:
            writer = get_stream_writer()
            writer({
                "type": "complexity_escalation",
                "source": "work_mode_middleware",
                "complexity_tier": "complex",
                "recommended_action": "plan_mode",
                "message": "This request looks complex. Switching to Plan Mode is recommended.",
            })
        except Exception:
            logger.exception("Failed to emit complexity_escalation SSE")

        if auto_mode and isinstance(thread_id, str) and thread_id:
            _spawn_plan_rerun(
                thread_id=thread_id,
                requested_model_name=requested_model_name,
                system_message=(
                    "Generate a detailed structured plan for the previous user request. "
                    "Work Mode detected this request is too complex for direct execution."
                ),
                thread_name_suffix="-escalation",
            )
            logger.info("Auto-cycle: spawned Plan Mode re-run due to complexity_escalation for thread %s", thread_id)

    def _handle_plan_adapted(
        self,
        *,
        state: WorkModeMiddlewareState,
        nodes: list[dict],
        pending_nodes: list[dict],
        auto_mode: bool,
        thread_id: str | None,
        requested_model_name: str | None,
    ) -> dict[str, Any] | None:
        """Emit plan_adapted SSE. If auto_mode and under the attempt limit, spawn a Plan Mode re-run."""
        existing_pe: dict = dict(state.get("phase_execution") or {})
        current_attempts: int = int(existing_pe.get("adaptation_attempts") or 0)

        blocked_ids = [n["id"] for n in nodes if n.get("status") == "blocked"]
        pending_ids = [n["id"] for n in pending_nodes]

        try:
            writer = get_stream_writer()
            writer({
                "type": "plan_adapted",
                "source": "work_mode_middleware",
                "blocked_ids": blocked_ids,
                "message": (
                    f"{len(pending_nodes)} pending todo(s) have unmet dependencies. "
                    "The plan needs revision."
                ),
                "adaptation_attempt": current_attempts + 1,
                "max_attempts": _MAX_AUTO_ADAPTATION_ATTEMPTS,
            })
        except Exception:
            logger.exception("Failed to emit plan_adapted SSE")

        new_attempts = current_attempts + 1

        # Cap auto-cycle at _MAX_AUTO_ADAPTATION_ATTEMPTS; beyond that require user confirmation.
        if auto_mode and isinstance(thread_id, str) and thread_id and current_attempts < _MAX_AUTO_ADAPTATION_ATTEMPTS:
            blocked_context = ", ".join(blocked_ids) if blocked_ids else "none"
            pending_context = ", ".join(pending_ids)
            _spawn_plan_rerun(
                thread_id=thread_id,
                requested_model_name=requested_model_name,
                system_message=(
                    "The current Work Mode execution has encountered blocked todos. "
                    f"Blocked todo IDs: [{blocked_context}]. "
                    f"Pending (unstarted) todo IDs: [{pending_context}]. "
                    "Please revise the plan to resolve these dependency issues and generate "
                    "an updated plan that can be executed without circular or unresolved dependencies."
                ),
                thread_name_suffix=f"-adapt{new_attempts}",
            )
            logger.info(
                "Auto-cycle: spawned Plan Mode re-run (adaptation attempt %d/%d) for thread %s",
                new_attempts, _MAX_AUTO_ADAPTATION_ATTEMPTS, thread_id,
            )
        elif auto_mode and current_attempts >= _MAX_AUTO_ADAPTATION_ATTEMPTS:
            logger.warning(
                "Auto-cycle adaptation limit reached (%d attempts) for thread %s — user intervention required",
                current_attempts, thread_id,
            )

        return {
            "phase_execution": {
                **existing_pe,
                "plan_adapted": True,
                "adaptation_notes": f"Blocked todos: {blocked_ids}",
                "adaptation_attempts": new_attempts,
            },
        }


def _create_work_mode(ctx: Any) -> WorkModeMiddleware | None:
    """Factory: returns None for all non-work modes (skips middleware)."""
    if not getattr(ctx, "is_work_mode", False):
        return None
    return WorkModeMiddleware()
