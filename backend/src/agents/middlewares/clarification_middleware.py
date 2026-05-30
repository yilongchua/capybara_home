"""Middleware for queueing clarification requests and gating on the DAG.

Default behaviour is non-blocking: when the agent calls
``ask_user_for_clarification``, this middleware appends the question to
``ThreadState.clarifications`` and lets the run continue on todos that are
not gated by an unanswered clarification. Multiple questions can therefore
accumulate within a single turn — the frontend surfaces them as tabs in a
side panel and the user answers in a batch.

The run is interrupted via ``Command(goto=END)`` only when one of:

  1. ``urgency == "blocking"`` is passed.
  2. After appending, the DAG has at least one pending clarification *and*
     zero ready todos remain in ``state.todo_graph.ready_ids`` (no useful
     parallel work the agent can still do).

Auto mode bypasses the queue entirely when a recommended option exists —
the recommended label is injected as an answer and the run proceeds.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.agents.middlewares.todo_dag_middleware import compute_effective_ready_ids

logger = logging.getLogger(__name__)


def _resolve_auto_mode(runtime: Runtime, state: dict[str, Any]) -> bool:
    """Resolve auto_mode with precedence: configurable > runtime.context > state.

    Mirrors the pre-refactor precedence so an explicit
    `configurable["auto_mode"]=False` from the frontend still overrides a
    stale `state["auto_mode"]=True`. We use explicit `in` checks (not `.get`)
    so a present-but-falsy value is honored.
    """
    config = getattr(runtime, "config", None)
    configurable = config.get("configurable") if isinstance(config, dict) else None
    if isinstance(configurable, dict) and "auto_mode" in configurable:
        return bool(configurable["auto_mode"])
    runtime_ctx = getattr(runtime, "context", None)
    if isinstance(runtime_ctx, dict) and "auto_mode" in runtime_ctx:
        return bool(runtime_ctx["auto_mode"])
    return bool(state.get("auto_mode", False))


def _normalize_question(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def _planner_clarification_duplicate(question: str, plan: Any) -> bool:
    """True iff `question` matches a clarification already surfaced inline by the planner.

    The planner emits `plan_created` with `clarifications: [...]` inline AND a
    `planner_clarification_required` HumanMessage telling the model to call
    `ask_user_for_clarification`. When the model follows that prompt it would
    otherwise create a duplicate entry in `state.clarifications`, surfacing two
    UI panels for the same question. This check lets `wrap_tool_call` short-circuit.
    """
    if not isinstance(plan, dict):
        return False
    candidates = plan.get("clarifications")
    if not isinstance(candidates, list):
        return False
    needle = _normalize_question(question)
    if not needle:
        return False
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        if _normalize_question(entry.get("question")) == needle:
            return True
    return False


class ClarificationMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    auto_mode: bool
    clarifications: list[dict[str, Any]]
    clarification_pending: bool
    todo_graph: dict[str, Any] | None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _has_pending_clarifications(clarifications: list[dict[str, Any]] | None) -> bool:
    if not clarifications:
        return False
    for entry in clarifications:
        if isinstance(entry, dict) and str(entry.get("status") or "pending") == "pending":
            return True
    return False


def _has_any_ready_after_blocks(
    todo_graph: dict[str, Any] | None,
    clarifications_with_new: list[dict[str, Any]],
) -> bool:
    """True iff at least one todo remains ready after gating on pending clarifications.

    Used by the interrupt-decision logic to detect "no useful parallel work
    left" — if every ready todo is gated by a pending clarification, halt
    and surface the questions. Computed inline from nodes so the decision
    is correct even mid-turn (before TodoDagMiddleware.before_model has
    refreshed state.todo_graph.ready_ids).
    """
    if not isinstance(todo_graph, dict):
        return False
    nodes = todo_graph.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return False
    return bool(compute_effective_ready_ids(nodes, clarifications_with_new))


def _had_any_ready_todos(todo_graph: dict[str, Any] | None) -> bool:
    """True iff the DAG had at least one ready todo before considering clarifications."""
    if not isinstance(todo_graph, dict):
        return False
    nodes = todo_graph.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return False
    # Use the pre-clarification base computation.
    return bool(compute_effective_ready_ids(nodes, None))


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """Queues clarification requests; only interrupts when the DAG is stuck.

    Default path (deferrable + DAG still has unblocked work):
        - Append the question to ``ThreadState.clarifications`` with
          ``status="pending"`` and the agent-supplied ``blocks`` list.
        - Return a normal ``ToolMessage`` so the agent can continue calling
          tools in the same turn (it may want to ask another question, or
          start work on an unblocked todo).
        - Set ``clarification_pending=True`` so the frontend popup mounts.

    Interrupt path (``urgency="blocking"`` or all ready todos blocked):
        - Append the question, then return ``Command(goto=END)`` to halt
          the run. The user answers via ``POST /api/threads/{id}/clarify``;
          the resume picks up where this left off.

    Auto-mode bypass:
        - When ``auto_mode=True`` and the question has a recommended option,
          mark the entry as answered with the recommended label and inject
          the answer into the message stream without interrupting.
    """

    state_schema = ClarificationMiddlewareState

    @override
    def before_model(self, state: ClarificationMiddlewareState, runtime: Runtime) -> dict | None:
        # auto_mode is now resolved on-demand inside wrap_tool_call via
        # _resolve_auto_mode(runtime, request.state). No side-effects on ctx.
        return None

    @override
    async def abefore_model(self, state: ClarificationMiddlewareState, runtime: Runtime) -> dict | None:
        return None

    def _build_entry(self, args: dict, tool_call_id: str) -> dict[str, Any]:
        """Coerce tool args into a Clarification record."""
        options_raw = args.get("options") or []
        options: list[dict[str, Any]] = []
        for opt in options_raw:
            if not isinstance(opt, dict):
                continue
            label = str(opt.get("label") or "").strip()
            if not label:
                continue
            entry: dict[str, Any] = {"label": label}
            description = opt.get("description")
            if description:
                entry["description"] = str(description)
            if opt.get("recommended"):
                entry["recommended"] = True
            options.append(entry)

        blocks_raw = args.get("blocks") or []
        blocks: list[str] = []
        if isinstance(blocks_raw, list):
            for tid in blocks_raw:
                tid_s = str(tid).strip()
                if tid_s:
                    blocks.append(tid_s)

        urgency = str(args.get("urgency") or "deferrable").strip()
        if urgency not in {"deferrable", "blocking"}:
            urgency = "deferrable"

        return {
            "id": f"clarif-{uuid.uuid4().hex[:8]}",
            "question": str(args.get("question") or "").strip(),
            "clarification_type": str(args.get("clarification_type") or "missing_info"),
            "context": (str(args["context"]) if args.get("context") else None),
            "options": options,
            "blocks": blocks,
            "urgency": urgency,  # type: ignore[typeddict-item]
            "status": "pending",
            "answer": None,
            "asked_at": _utc_now_iso(),
            "tool_call_id": tool_call_id or None,
        }

    def _get_recommended_label(self, args: dict) -> str | None:
        for option in args.get("options") or []:
            if isinstance(option, dict) and option.get("recommended"):
                label = str(option.get("label") or "").strip()
                if label:
                    return label
        return None

    def _format_breadcrumb(self, entry: dict[str, Any]) -> str:
        """One-line ToolMessage content. The full UI lives in the side panel."""
        question = entry.get("question") or ""
        if entry.get("urgency") == "blocking":
            return f"🤚 Blocking clarification queued: {question}"
        return f"🤚 Clarification queued: {question}  — see panel"

    def _handle_clarification(
        self,
        request: ToolCallRequest,
        existing_clarifications: list[dict[str, Any]] | None,
        todo_graph: dict[str, Any] | None,
    ) -> Command:
        args = request.tool_call.get("args", {}) or {}
        tool_call_id = request.tool_call.get("id", "") or ""
        state = getattr(request, "state", None) or {}
        auto_mode = _resolve_auto_mode(request.runtime, state)

        question_text = str(args.get("question") or "").strip()
        if _planner_clarification_duplicate(question_text, state.get("plan")):
            logger.info(
                "Skipping duplicate clarification '%s' — already surfaced inline by planner",
                question_text,
            )
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Clarification already pending in the inline panel — "
                                "the user will answer there. Continue with other ready work."
                            ),
                            tool_call_id=tool_call_id,
                            name="ask_user_for_clarification",
                        )
                    ],
                }
            )

        entry = self._build_entry(args, tool_call_id)

        # Auto-mode bypass: if a recommended option exists, pre-answer the
        # clarification and don't interrupt.
        if auto_mode:
            recommended = self._get_recommended_label(args)
            if recommended:
                entry["status"] = "answered"
                entry["answer"] = recommended
                entry["answered_at"] = _utc_now_iso()
                logger.info("Auto mode: auto-selecting '%s' for clarification: %s", recommended, entry.get("question"))
                return Command(
                    update={
                        "clarifications": [entry],
                        # Pending stays as-is (depends on other entries in state).
                        "messages": [
                            ToolMessage(
                                content=f"[Auto Mode] Selected: {recommended}",
                                tool_call_id=tool_call_id,
                                name="ask_user_for_clarification",
                            )
                        ],
                    }
                )
            logger.info("Auto mode: no recommended option for clarification '%s'; falling through to normal queue", entry.get("question"))

        # Decide whether to interrupt.
        urgency = entry.get("urgency", "deferrable")
        next_clarifications = list(existing_clarifications or []) + [entry]

        # The "DAG starved" interrupt only triggers when there *was* useful
        # work to start with — if there were no ready todos at all
        # (e.g. the run hasn't planned anything yet), we don't treat a single
        # deferrable clarification as a halt signal.
        had_ready = _had_any_ready_todos(todo_graph)
        ready_remain = _has_any_ready_after_blocks(todo_graph, next_clarifications)

        should_interrupt = urgency == "blocking" or (
            had_ready and not ready_remain and _has_pending_clarifications(next_clarifications)
        )

        update: dict[str, Any] = {
            "clarifications": [entry],
            "clarification_pending": True,
            "messages": [
                ToolMessage(
                    content=self._format_breadcrumb(entry),
                    tool_call_id=tool_call_id,
                    name="ask_user_for_clarification",
                )
            ],
        }

        if should_interrupt:
            logger.info(
                "Interrupting run on clarification '%s' (urgency=%s, ready_remain=%s)",
                entry.get("question"),
                urgency,
                ready_remain,
            )
            return Command(update=update, goto=END)

        logger.info(
            "Queued clarification '%s' (urgency=%s, blocks=%s); run continues",
            entry.get("question"),
            urgency,
            entry.get("blocks"),
        )
        return Command(update=update)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != "ask_user_for_clarification":
            return handler(request)
        state = getattr(request, "state", None) or {}
        return self._handle_clarification(
            request,
            existing_clarifications=state.get("clarifications"),
            todo_graph=state.get("todo_graph"),
        )

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != "ask_user_for_clarification":
            return await handler(request)
        state = getattr(request, "state", None) or {}
        return self._handle_clarification(
            request,
            existing_clarifications=state.get("clarifications"),
            todo_graph=state.get("todo_graph"),
        )
