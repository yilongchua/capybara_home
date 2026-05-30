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

Plan Mode entry: fully user-initiated via the UI (Shift+Tab). Work Mode never
auto-escalates to Plan Mode. When a plan paints itself into a corner (all
remaining todos blocked), a plan_adapted SSE event fires so the UI can surface
the stall; the user decides whether to switch into Plan Mode to revise.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime

from src.agents.middlewares.plan_execution import format_clarification_context_for_work
from src.agents.middlewares.runtime_events import RUNTIME_EVENTS_KEY, append_runtime_event
from src.agents.middlewares.todo_dag_middleware import _materialize_ready_ids

logger = logging.getLogger(__name__)

_WORK_MODE_REPEAT_THRESHOLD = 5
_IN_PROGRESS_SELF_HEAL_GRACE_SECONDS = 60
_INSTRUCTION_FIELD_MAX_CHARS = 4000
# Cap the SSE replay buffer so a persistently flaky stream writer can't blow
# up state. Oldest events are dropped first.
_MAX_SSE_BUFFER = 50


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _is_stale_timestamp(value: Any, *, now: datetime, grace_seconds: int = _IN_PROGRESS_SELF_HEAL_GRACE_SECONDS) -> bool:
    parsed = _parse_utc_iso(value)
    if parsed is None:
        return True
    return (now - parsed).total_seconds() >= grace_seconds


def _instruction_text(value: Any, *, max_chars: int = _INSTRUCTION_FIELD_MAX_CHARS) -> str:
    text = str(value or "")
    if len(text) > max_chars:
        text = f"{text[:max_chars]}...[truncated]"
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _is_report_todo(node: dict[str, Any]) -> bool:
    kind = str(node.get("kind") or node.get("todo_kind") or "").strip().lower()
    artifact_type = str(node.get("artifact_type") or node.get("output_type") or "").strip().lower()
    if kind == "report" or artifact_type == "report":
        return True
    artifacts = node.get("artifacts")
    if isinstance(artifacts, list):
        return any(str(item).strip().lower().endswith((".md", ".pdf")) and "report" in str(item).lower() for item in artifacts)
    return False


class WorkModeMiddlewareState(AgentState):
    """Compatible with the ThreadState schema."""

    todo_graph: NotRequired[dict | None]
    plan: NotRequired[dict | None]
    plan_history: NotRequired[list[dict] | None]
    work_mode: NotRequired[dict | None]
    phase_execution: NotRequired[dict | None]
    deferred_task_calls: NotRequired[list[dict] | None]


_KNOWN_PLAN_STATUSES = {"draft", "approved", "executing", "completed"}


def _normalize_plan_status(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in _KNOWN_PLAN_STATUSES:
        return value
    if value:
        logger.warning("Unknown plan status %r coerced to 'draft'", value)
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


class WorkModeMiddleware(AgentMiddleware[WorkModeMiddlewareState]):
    """Drives automatic phase-loop execution in Work Mode.

    Runs every ReAct cycle. Each call to before_model():
    1. Detects newly completed todos from the previous cycle (via snapshot diff)
    2. Emits phase_completed SSE for each newly completed todo
    3. Finds the next ready (non-completed, unblocked) todo
    4. Emits phase_started SSE and injects a HumanMessage instruction
    5. Returns None when all phases are done → model summarises and terminates

    When a plan stalls (no ready todos but pending ones remain), a plan_adapted
    SSE fires so the UI can prompt the user to switch into Plan Mode. Work Mode
    never auto-escalates on its own.
    """

    state_schema = WorkModeMiddlewareState

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
        instruction_todo_id = str(phase_execution.get("ephemeral_instruction_todo_id") or "").strip()
        if instruction_todo_id and instruction_todo_id != todo_id:
            return None
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
        plan_state = dict(state.get("plan") or {})
        plan_history = [item for item in (state.get("plan_history") or []) if isinstance(item, dict)]
        plan_status = _normalize_plan_status(plan_state.get("status"))

        graph = state.get("todo_graph") or {}
        nodes: list[dict] | None = graph.get("nodes") if isinstance(graph, dict) else None
        graph_update: dict[str, Any] | None = None
        existing_pe: dict = dict(state.get("phase_execution") or {})

        # ── No plan yet ────────────────────────────────────────────────────────
        if not nodes:
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
        in_progress_started_at = existing_pe.get("in_progress_started_at") if isinstance(existing_pe.get("in_progress_started_at"), dict) else {}
        now = datetime.now(UTC)
        stale_in_progress_ids = []
        for node in nodes:
            if not isinstance(node, dict) or node.get("status") != "in_progress" or not node.get("id"):
                continue
            node_id = str(node.get("id"))
            if _is_stale_timestamp(in_progress_started_at.get(node_id), now=now):
                stale_in_progress_ids.append(node_id)
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
        completed_snapshot_raw = existing_pe.get("completed_snapshot_ids")
        if isinstance(completed_snapshot_raw, list):
            completed_before = frozenset(str(item) for item in completed_snapshot_raw if str(item).strip())
        else:
            # First cycle: seed from current state so we don't re-emit
            # phase_completed for todos that were already done before this run
            # started (resume case).
            completed_before = current_completed
        newly_completed = current_completed - completed_before

        # SSE replay buffer (#21): emit failures keep events queued in
        # `phase_execution.pending_sse_events` so a flaky stream writer can't
        # permanently desync the UI from server state. We flush backlog before
        # sending new events; once an emit fails this cycle, remaining events
        # for this cycle go straight to the buffer (no retry storm).
        sse_pending_in = list(existing_pe.get("pending_sse_events") or [])
        sse_buffer: list[dict] = list(sse_pending_in)
        sse_emit_disabled = False

        def _safe_emit(event: dict) -> None:
            nonlocal sse_emit_disabled, sse_buffer
            if sse_emit_disabled:
                sse_buffer.append(event)
                return
            try:
                writer = get_stream_writer()
                while sse_buffer:
                    writer(sse_buffer[0])
                    sse_buffer.pop(0)
                writer(event)
            except Exception:
                logger.exception("SSE emit failed for %s; buffering", event.get("type"))
                sse_emit_disabled = True
                sse_buffer.append(event)

        def _finalize_sse_buffer() -> list[dict]:
            return sse_buffer[-_MAX_SSE_BUFFER:]

        def _sse_state_changed() -> bool:
            return sse_buffer != sse_pending_in

        if newly_completed:
            node_by_id = {n["id"]: n for n in nodes}
            for todo_id in newly_completed:
                node = node_by_id.get(todo_id)
                if node is None:
                    continue
                phase_index = next((i for i, n in enumerate(nodes) if n["id"] == todo_id), 0)
                _safe_emit({
                    "type": "phase_completed",
                    "source": "work_mode_middleware",
                    "todo_id": todo_id,
                    "content": node.get("content", ""),
                    "phase_index": phase_index,
                    "completed_at": _utc_now_iso(),
                })

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
                safe_emit=_safe_emit,
                finalize_sse_buffer=_finalize_sse_buffer,
            )
        if not pending_ready and has_in_progress:
            if existing_pe.get("ephemeral_instruction_text"):
                return {
                    "phase_execution": {
                        **existing_pe,
                        "completed_snapshot_ids": sorted(current_completed),
                        "ephemeral_instruction_text": "",
                        "ephemeral_instruction_todo_id": "",
                        "pending_sse_events": _finalize_sse_buffer(),
                    }
                }
            if _sse_state_changed():
                return {
                    "phase_execution": {
                        **existing_pe,
                        "pending_sse_events": _finalize_sse_buffer(),
                    }
                }
            return None

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
                    "phase_execution": {
                        **existing_pe,
                        "completed_snapshot_ids": sorted(current_completed),
                        "ephemeral_instruction_text": "",
                        "ephemeral_instruction_todo_id": "",
                        "pending_sse_events": _finalize_sse_buffer(),
                    },
                }
                if graph_update is not None:
                    update_payload["todo_graph"] = graph_update
                return update_payload
            if existing_pe.get("ephemeral_instruction_text"):
                return {
                    "phase_execution": {
                        **existing_pe,
                        "completed_snapshot_ids": sorted(current_completed),
                        "ephemeral_instruction_text": "",
                        "ephemeral_instruction_todo_id": "",
                        "pending_sse_events": _finalize_sse_buffer(),
                    }
                }
            if _sse_state_changed():
                return {
                    "phase_execution": {
                        **existing_pe,
                        "pending_sse_events": _finalize_sse_buffer(),
                    }
                }
            return None

        # ── Emit phase_started and inject instruction ──────────────────────────
        next_todo = node_by_id[pending_ready[0]]
        next_todo_id = str(next_todo.get("id") or "")
        phase_index = next((i for i, n in enumerate(nodes) if n["id"] == next_todo["id"]), 0)
        total_phases = len(nodes)

        safe_phase_content = _instruction_text(next_todo.get("content", ""))
        _safe_emit({
            "type": "phase_started",
            "source": "work_mode_middleware",
            "todo_id": next_todo["id"],
            "content": safe_phase_content,
            "subagent_type": next_todo.get("subagent_type"),
            "phase_index": phase_index,
            "total_phases": total_phases,
        })

        raw_todo_content = next_todo.get("content", "")
        todo_content = _instruction_text(raw_todo_content)
        safe_todo_id = _instruction_text(next_todo.get("id", ""))
        rationale = _instruction_text(str(next_todo.get("rationale") or "").strip())
        rationale_block = f"\nRationale: {rationale}" if rationale else ""
        subagent_hint = ""
        if next_todo.get("subagent_type"):
            subagent_hint = f" Use a {_instruction_text(next_todo['subagent_type'])} subagent if available."

        clarification_block = ""
        if isinstance(plan_state, dict):
            clarification_text = format_clarification_context_for_work(plan_state)
            if clarification_text:
                clarification_block = f"\n{_instruction_text(clarification_text)}\n"

        report_contract = ""
        if _is_report_todo(next_todo):
            report_contract = (
                "\nUse a two-stage generation contract for speed+accuracy:\n"
                "Stage A: produce a compact outline plus section-level claims list before drafting full content.\n"
                "Stage B: expand into the final report from the outline and essential evidence only.\n"
                "Add confidence tags (high/medium/low) for key claims with weak support.\n"
                "Write the final report to /mnt/user-data/workspace/ (e.g. report.md) and call `present_files` so the user receives it.\n"
                "Before final write_file, self-check for duplicate table rows, repeated long paragraphs, heading numbering consistency, and required sections.\n"
            )
        repeat_counts_raw = existing_pe.get("repeat_counts") if isinstance(existing_pe.get("repeat_counts"), dict) else {}
        repeat_counts: dict[str, int] = {}
        for key, value in dict(repeat_counts_raw or {}).items():
            try:
                repeat_counts[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        forced_reconcile_raw = existing_pe.get("forced_reconcile_done") if isinstance(existing_pe.get("forced_reconcile_done"), dict) else {}
        forced_reconcile_done: dict[str, bool] = {str(key): bool(value) for key, value in dict(forced_reconcile_raw or {}).items()}
        in_progress_started_at = {str(key): str(value) for key, value in dict(in_progress_started_at or {}).items() if str(key).strip() and str(value).strip()}
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
            f"When done, call write_todos to mark todo id '{safe_todo_id}' as completed.\n"
            f"If write_todos is unexpectedly unavailable, state that explicitly and include the intended status update for todo id '{safe_todo_id}'.\n"
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
                f"Reconcile todo state now for todo id '{safe_todo_id}' only.\n"
                f"Call write_todos immediately with an explicit status update for '{safe_todo_id}' "
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
            "content": raw_todo_content,
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
            in_progress_started_at.pop(todo_id, None)
            idx = next((i for i, r in enumerate(phase_results) if r.get("todo_id") == todo_id), None)
            if idx is not None and phase_results[idx].get("status") != "completed":
                phase_results[idx] = {
                    **phase_results[idx],
                    "status": "completed",
                    "completed_at": _utc_now_iso(),
                }

        if next_todo_id not in in_progress_started_at:
            in_progress_started_at[next_todo_id] = _utc_now_iso()

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
                "pending_sse_events": _finalize_sse_buffer(),
                "repeat_counts": repeat_counts,
                "forced_reconcile_done": forced_reconcile_done,
                "in_progress_started_at": in_progress_started_at,
                "last_todo_id": next_todo_id,
                "last_instruction_kind": instruction_kind,
                "ephemeral_instruction_text": instruction_body.strip(),
                "ephemeral_instruction_todo_id": next_todo_id,
                "completed_snapshot_ids": sorted(current_completed),
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

    def _handle_plan_adapted(
        self,
        *,
        state: WorkModeMiddlewareState,
        nodes: list[dict],
        pending_nodes: list[dict],
        safe_emit: Callable[[dict], None] | None = None,
        finalize_sse_buffer: Callable[[], list[dict]] | None = None,
    ) -> dict[str, Any] | None:
        """Emit a plan_adapted SSE so the UI can surface the stall.

        Work Mode does not auto-respawn Plan Mode — the user decides whether to
        switch into Plan Mode to revise the plan. The SSE is emitted once per
        distinct stall topology: the (blocked_ids, pending_ids) signature is
        stored in state and the event only re-fires when the user changes the
        plan enough to alter that signature. `adaptation_attempts` only advances
        when a new SSE actually fires, so it stays meaningful as "times the UI
        was told."

        The ``safe_emit`` / ``finalize_sse_buffer`` callbacks integrate with the
        cycle-level replay buffer (#21) so a failed plan_adapted emit is
        re-tried on the next cycle instead of being lost.
        """
        existing_pe: dict = dict(state.get("phase_execution") or {})
        current_attempts: int = int(existing_pe.get("adaptation_attempts") or 0)

        blocked_ids = sorted(n["id"] for n in nodes if n.get("status") == "blocked")
        pending_ids = sorted(n["id"] for n in pending_nodes)
        stall_signature = [blocked_ids, pending_ids]
        last_signature = existing_pe.get("plan_adapted_stall_signature")
        should_emit = stall_signature != last_signature

        if should_emit:
            event = {
                "type": "plan_adapted",
                "source": "work_mode_middleware",
                "blocked_ids": blocked_ids,
                "message": (
                    f"{len(pending_nodes)} pending todo(s) have unmet dependencies. "
                    "Switch to Plan Mode to revise the plan."
                ),
                "adaptation_attempt": current_attempts + 1,
            }
            if safe_emit is not None:
                safe_emit(event)
            else:
                # Standalone caller (no cycle-level buffer). Best-effort emit.
                try:
                    get_stream_writer()(event)
                except Exception:
                    logger.exception("Failed to emit plan_adapted SSE")

        phase_execution_update: dict[str, Any] = {
            **existing_pe,
            "plan_adapted": True,
            "adaptation_notes": f"Blocked todos: {blocked_ids}",
            "adaptation_attempts": current_attempts + (1 if should_emit else 0),
            "plan_adapted_stall_signature": stall_signature,
            "ephemeral_instruction_text": "",
            "ephemeral_instruction_todo_id": "",
        }
        if finalize_sse_buffer is not None:
            phase_execution_update["pending_sse_events"] = finalize_sse_buffer()

        return {"phase_execution": phase_execution_update}


def _create_work_mode(ctx: Any) -> WorkModeMiddleware | None:
    """Factory: returns None for all non-work modes (skips middleware)."""
    if not getattr(ctx, "is_work_mode", False):
        return None
    return WorkModeMiddleware()
