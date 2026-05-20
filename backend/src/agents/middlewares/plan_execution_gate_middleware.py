"""Gate execution tools while plan is still draft or awaiting clarifications."""

from __future__ import annotations

from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

_ALLOWED_WHEN_DRAFT = {
    "ask_clarification",
    "write_todos",
    "recall",
}


def _is_read_only_tool(tool_name: str) -> bool:
    return tool_name.startswith("read_") or tool_name.startswith("list_") or tool_name.startswith("get_")


class PlanExecutionGateState(AgentState):
    plan: dict[str, Any] | None


def _normalize_plan_status(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"draft", "approved", "executing", "completed"}:
        return value
    return "draft"


class PlanExecutionGateMiddleware(AgentMiddleware[PlanExecutionGateState]):
    """Prevents execution tool usage until draft plans are explicitly approved."""

    state_schema = PlanExecutionGateState

    def _build_block_command(self, request: ToolCallRequest, message: str) -> Command:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=message,
                        tool_call_id=request.tool_call.get("id", ""),
                        name=request.tool_call.get("name", "tool"),
                    )
                ]
            },
        )

    def _maybe_block(self, request: ToolCallRequest) -> Command | None:
        state = request.runtime.state if request.runtime is not None else {}
        plan = state.get("plan") if isinstance(state, dict) else None
        if not isinstance(plan, dict):
            return None

        plan_status = _normalize_plan_status(plan.get("status"))
        if plan_status != "draft":
            return None

        tool_name = str(request.tool_call.get("name") or "")
        clarification_pending = bool(plan.get("clarification_pending"))

        if clarification_pending and tool_name != "ask_clarification":
            question = str(plan.get("clarification_question") or "Please answer the pending clarification before execution.")
            return self._build_block_command(
                request,
                (
                    "[plan_gate] Clarification is required before plan execution. "
                    "Call `ask_clarification` first.\n"
                    f"Pending question: {question}"
                ),
            )

        if tool_name in _ALLOWED_WHEN_DRAFT or _is_read_only_tool(tool_name):
            return None

        plan_id = str(plan.get("plan_id") or "").strip()
        plan_hint = f" Plan ID: {plan_id}." if plan_id else ""
        return self._build_block_command(
            request,
            (
                "[plan_gate] Plan is still draft. Execution tools are blocked until explicit plan approval "
                f"via the Execute Plan action in the UI (or enable auto-mode).{plan_hint} "
                "Do not substitute training-data answers for blocked research tools."
            ),
        )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        blocked = self._maybe_block(request)
        if blocked is not None:
            return blocked
        return handler(request)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        blocked = self._maybe_block(request)
        if blocked is not None:
            return blocked
        return await handler(request)
