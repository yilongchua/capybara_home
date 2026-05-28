"""First-turn execution gate.

Mode-based filtering (plan vs work) is resolved up-front at agent build time:
the catalog file selection in `src/tools/tools.py` picks
`internal_tools_plan.json` or `internal_tools_work.json` for the JSON-driven
tools, and `_COMMUNITY_TOOL_MODES` scopes community tools to the right mode.
Plan-status transitions (draft → approved) are inter-graph — plan_agent
terminates before work_agent runs — so they don't need a runtime filter either.

What remains is purely behavioral: on the very first turn of a Work-Mode run
that has no plan (i.e. work_agent invoked directly, no Plan-Mode handoff), we
hide execution tools so the LLM is forced to reason before reaching for
bash / write_file / web_search / task. From turn 2 onward the full catalog is
exposed.
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


# Tools that mutate state, dispatch subagents, or hit the network. Hidden on
# the first turn of a no-plan Work-Mode run so the LLM has to reason first.
_EXECUTION_TOOLS: frozenset[str] = frozenset(
    {
        "bash",
        "write_file",
        "str_replace",
        "task",
        "web_search",
        "query_knowledge_vault",
        "search_internal_documents",
        "save_to_knowledge_vault",
    }
)


class PhaseToolFilterState(AgentState):
    plan: NotRequired[dict | None]


def _runtime_context(runtime: Runtime | None) -> dict[str, Any]:
    context = getattr(runtime, "context", None) if runtime is not None else None
    return context if isinstance(context, dict) else {}


def _is_plan_mode(runtime: Runtime | None) -> bool:
    ctx = _runtime_context(runtime)
    # Prefer canonical ``current_mode``; fall back to legacy ``mode`` / ``is_plan_mode``
    # for runs whose context predates the field rename.
    raw = ctx.get("current_mode") or ctx.get("mode") or ("plan" if ctx.get("is_plan_mode") else "")
    return str(raw).strip().lower() == "plan"


def _should_filter(state: dict[str, Any], runtime: Runtime | None) -> bool:
    """Return True only for the first-turn warm-up in Work Mode without a plan.

    Everything else is handled by catalog selection up-front:
      * Plan Mode → plan catalog already excludes execution tools.
      * Work Mode post-handoff → plan dict present, agent has been reasoned about.
      * Work Mode mid-conversation → at least one AI message exists.
    """
    if not isinstance(state, dict):
        return False
    if isinstance(state.get("plan"), dict):
        return False
    if _is_plan_mode(runtime):
        return False
    # Work Mode, no plan: gate the very first model call (no prior AI msg).
    messages = state.get("messages")
    if not isinstance(messages, list):
        return False
    has_ai_messages = any(getattr(m, "type", None) == "ai" for m in messages)
    return not has_ai_messages


def _filter_tools(tools: list[Any], blocked: frozenset[str]) -> tuple[list[Any], list[str]]:
    kept: list[Any] = []
    hidden: list[str] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if name is None and isinstance(tool, dict):
            name = tool.get("name")
        if isinstance(name, str) and name in blocked:
            hidden.append(name)
            continue
        kept.append(tool)
    return kept, hidden


class PhaseToolFilterMiddleware(AgentMiddleware[PhaseToolFilterState]):
    """Hide execution tools from the LLM on the first turn of a no-plan run."""

    state_schema = PhaseToolFilterState

    def __init__(self) -> None:
        super().__init__()

    def _maybe_rewrite(self, request: ModelRequest) -> ModelRequest:
        state = request.state if isinstance(getattr(request, "state", None), dict) else {}
        runtime = getattr(request, "runtime", None)
        tools = list(getattr(request, "tools", []) or [])
        if not tools or not _should_filter(state, runtime):
            return request
        kept, hidden = _filter_tools(tools, _EXECUTION_TOOLS)
        if not hidden:
            return request
        append_runtime_event(
            runtime,
            {
                "source": "phase_tool_filter",
                "decision": "tools_hidden",
                "phase": "first_turn",
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
