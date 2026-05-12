"""Phase-gated tool disclosure middleware."""

from __future__ import annotations

from collections.abc import Callable
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.tool_disclosure_config import ToolDisclosureConfig, get_tool_disclosure_config


class ToolDisclosureState(AgentState):
    """State subset used by tool disclosure middleware."""

    plan: NotRequired[dict | None]
    todo_graph: NotRequired[dict | None]


class ToolDisclosureMiddleware(AgentMiddleware[ToolDisclosureState]):
    """Enforce phase-specific allow-lists for tool execution."""

    state_schema = ToolDisclosureState

    def __init__(self, config: ToolDisclosureConfig | None = None):
        super().__init__()
        self._config = config or get_tool_disclosure_config()

    def _resolve_phase(self, state: ToolDisclosureState, request: ToolCallRequest) -> str:
        context = getattr(request.runtime, "context", None) or {}
        hinted = context.get("tool_disclosure_phase")
        if isinstance(hinted, str) and hinted:
            return hinted

        plan = state.get("plan") or {}
        evaluation_status = str(plan.get("evaluation_status") or "")
        if evaluation_status in {"passed", "max_attempts_reached"}:
            return "evaluator"

        if plan:
            return "generator"
        return self._config.default_phase

    def _is_allowed(self, phase: str, tool_name: str) -> bool:
        allowed = self._config.allowed_tools_for(phase)
        if not allowed:
            return True
        return tool_name in set(allowed)

    def _blocked_message(self, request: ToolCallRequest, phase: str, tool_name: str) -> ToolMessage:
        append_runtime_event(
            request.runtime,
            {
                "source": "tool_disclosure_middleware",
                "decision": "blocked",
                "phase": phase,
                "tool": tool_name,
            },
        )
        return ToolMessage(
            content=(
                f"[tool_disclosure_blocked] Tool `{tool_name}` is not allowed in phase `{phase}`. "
                "Execution continues without this tool."
            ),
            tool_call_id=request.tool_call.get("id", ""),
            name=tool_name,
        )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        if not self._config.enabled:
            return handler(request)

        state = request.state or {}
        tool_name = str(request.tool_call.get("name") or "unknown")
        phase = self._resolve_phase(state, request)
        if not self._is_allowed(phase, tool_name):
            return self._blocked_message(request, phase, tool_name)
        return handler(request)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        if not self._config.enabled:
            return await handler(request)

        state = request.state or {}
        tool_name = str(request.tool_call.get("name") or "unknown")
        phase = self._resolve_phase(state, request)
        if not self._is_allowed(phase, tool_name):
            return self._blocked_message(request, phase, tool_name)
        return await handler(request)
