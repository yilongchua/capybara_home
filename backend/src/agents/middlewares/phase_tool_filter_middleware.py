"""Phase-aware tool-list shaping.

This middleware runs in ``wrap_model_call`` and rewrites the bound tool list
passed to the LLM based on whether the current plan is in draft or has been
approved. The LLM literally cannot call what it cannot see — this is a much
stronger behavioral signal than reactive runtime blocking.

While a plan is in ``draft`` status (or Plan Mode is explicitly active and no
plan exists yet), execution tools — ``web_search``, ``query_lightrag``,
``query_knowledge_vault``, ``search_internal_documents``, ``task``,
``write_file``, ``str_replace`` — are removed from the LLM's tool catalog.
``scope_search`` (a Plan-Mode wrapper around ``web_search``) remains visible so
the agent can still narrow scope before approval.

When the plan is ``approved`` / ``executing`` / ``completed`` (Work Mode), no
filtering applies and the full tool catalog passes through.

Pair with ``PlanExecutionGateMiddleware`` (defense in depth) and the runtime
classifier inside it (final fallback if a custom agent re-exposes tools).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event

logger = logging.getLogger(__name__)


_DRAFT_HIDDEN_TOOLS: frozenset[str] = frozenset(
    {
        # Execution-grade search tools — must wait for plan approval.
        "web_search",
        "query_knowledge_vault",
        "query_lightrag",
        "search_internal_documents",
        # Subagent dispatch and write tools.
        "task",
        "write_file",
        "str_replace",
    }
)


class PhaseToolFilterState(AgentState):
    plan: NotRequired[dict | None]


def _normalize_plan_status(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"draft", "approved", "executing", "completed"}:
        return value
    return ""


def _runtime_context(runtime: Runtime | None) -> dict[str, Any]:
    context = getattr(runtime, "context", None) if runtime is not None else None
    return context if isinstance(context, dict) else {}


def _is_plan_mode(runtime: Runtime | None) -> bool:
    return str(_runtime_context(runtime).get("mode") or "").strip().lower() == "plan"


def _should_filter(state: dict[str, Any], runtime: Runtime | None) -> bool:
    """Return True when execution tools must be hidden from the LLM."""
    plan = state.get("plan") if isinstance(state, dict) else None
    if isinstance(plan, dict):
        status = _normalize_plan_status(plan.get("status"))
        if status == "draft":
            return True
        # If a plan is explicitly approved/executing/completed, do not filter.
        if status in {"approved", "executing", "completed"}:
            return False
    # No plan yet but we are in Plan Mode — filter to keep the agent honest
    # until the planner emits a plan. Once the planner runs (it now runs
    # before this middleware on every turn), `plan` will be populated and the
    # status check above takes over.
    return _is_plan_mode(runtime)


def _filter_tools(tools: list[Any]) -> tuple[list[Any], list[str]]:
    kept: list[Any] = []
    hidden: list[str] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if name is None and isinstance(tool, dict):
            name = tool.get("name")
        if isinstance(name, str) and name in _DRAFT_HIDDEN_TOOLS:
            hidden.append(name)
            continue
        kept.append(tool)
    return kept, hidden


class PhaseToolFilterMiddleware(AgentMiddleware[PhaseToolFilterState]):
    """Hide execution tools from the LLM's tool catalog while plan is draft."""

    state_schema = PhaseToolFilterState

    def __init__(self) -> None:
        super().__init__()

    def _maybe_rewrite(self, request: ModelRequest) -> ModelRequest:
        state = request.state if isinstance(getattr(request, "state", None), dict) else {}
        runtime = getattr(request, "runtime", None)
        if not _should_filter(state, runtime):
            return request
        tools = list(getattr(request, "tools", []) or [])
        if not tools:
            return request
        kept, hidden = _filter_tools(tools)
        if not hidden:
            return request
        append_runtime_event(
            runtime,
            {
                "source": "phase_tool_filter",
                "decision": "tools_hidden",
                "phase": "draft",
                "hidden": hidden,
                "kept_count": len(kept),
            },
        )
        return request.override(tools=kept)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._maybe_rewrite(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._maybe_rewrite(request))
