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

_ALLOWED_IN_PLAN_MODE = _ALLOWED_WHEN_DRAFT | {
    "bash",
    "ls",
    "read_file",
    "view_image",
    "web_search",
    "query_knowledge_vault",
    "query_lightrag",
    "search_internal_documents",
}

_BASH_MUTATION_TOKENS = (
    ">",
    ">>",
    "tee ",
    " rm ",
    " mv ",
    " cp ",
    " chmod ",
    " chown ",
    " sed -i",
    " perl -pi",
    " git apply",
    " git commit",
    " git add",
    " touch ",
    " mkdir ",
    " install ",
)


def _is_read_only_tool(tool_name: str) -> bool:
    return tool_name.startswith("read_") or tool_name.startswith("list_") or tool_name.startswith("get_")


def _is_plan_mode(runtime: Any) -> bool:
    context = getattr(runtime, "context", None) or {}
    return str(context.get("mode") or "").strip().lower() == "plan"


def _is_plan_safe_bash(command: str) -> bool:
    lowered = f" {command.lower()} "
    return not any(token in lowered for token in _BASH_MUTATION_TOKENS)


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
        state = request.state if isinstance(getattr(request, "state", None), dict) else {}
        if not state:
            runtime_obj = getattr(request, "runtime", None)
            state = getattr(runtime_obj, "state", {}) if isinstance(getattr(runtime_obj, "state", None), dict) else {}
        plan = state.get("plan") if isinstance(state, dict) else None
        tool_name = str(request.tool_call.get("name") or "")
        tool_args = request.tool_call.get("args") or {}
        in_plan_mode = _is_plan_mode(request.runtime)
        if in_plan_mode:
            if tool_name == "bash":
                command = str(tool_args.get("command") or "")
                if _is_plan_safe_bash(command):
                    return None
                return self._build_block_command(
                    request,
                    (
                        "[plan_gate] Plan Mode allows bash only for read-only investigation. "
                        "Use inspection commands such as rg, ls, cat, sed -n, pytest, or git status; do not mutate files or state."
                    ),
                )
            if tool_name in _ALLOWED_IN_PLAN_MODE or _is_read_only_tool(tool_name):
                return None
            return self._build_block_command(
                request,
                (
                    "[plan_gate] You are still in Plan Mode. Do not execute the work yet. "
                    "Refine `plan.md`, update todos, gather read-only scope context, or ask clarification instead."
                ),
            )

        if not isinstance(plan, dict):
            return None

        plan_status = _normalize_plan_status(plan.get("status"))
        if plan_status != "draft":
            return None

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
