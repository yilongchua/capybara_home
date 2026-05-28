"""Tests for PhaseToolFilterMiddleware — first-turn execution gate.

After the mode/phase refactor, mode-based filtering is resolved up-front by
the catalog selection in `src/tools/tools.py` (plan vs work catalog file) and
community-tool mode scoping (`_COMMUNITY_TOOL_MODES`). The middleware's only
remaining job is to hide execution tools on the very first turn of a no-plan
Work-Mode run, so the LLM is forced to reason before reaching for execution.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.phase_tool_filter_middleware import (
    _EXECUTION_TOOLS,
    PhaseToolFilterMiddleware,
)


def _named_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


def _model_request(*, tools: list, state: dict, runtime: SimpleNamespace) -> MagicMock:
    request = MagicMock()
    request.tools = tools
    request.state = state
    request.runtime = runtime
    request.override = MagicMock(side_effect=lambda **kwargs: SimpleNamespace(tools=kwargs.get("tools", tools), state=state, runtime=runtime))
    return request


def _run(middleware, request) -> set[str]:
    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    return {getattr(t, "name", None) for t in captured["tools"]}


def test_first_turn_work_mode_no_plan_hides_execution_tools() -> None:
    """Turn 1, Work Mode, no plan, no AI message yet → execution tools hidden.

    This is the only scenario the middleware still filters in. Without this
    guard the LLM would fire bash/web_search/task before having a reasoning
    turn.
    """
    middleware = PhaseToolFilterMiddleware()
    tools = [
        _named_tool("web_search"),
        _named_tool("query_knowledge_vault"),
        _named_tool("task"),
        _named_tool("bash"),
        _named_tool("write_file"),
        _named_tool("read_file"),
        _named_tool("ls"),
    ]
    state = {"messages": [HumanMessage(content="complex multi-step request")]}
    runtime = SimpleNamespace(context={"mode": "work"})
    visible = _run(middleware, _model_request(tools=tools, state=state, runtime=runtime))

    assert "web_search" not in visible
    assert "query_knowledge_vault" not in visible
    assert "task" not in visible
    assert "bash" not in visible
    assert "write_file" not in visible
    # Read-only tools stay available so the LLM can investigate.
    assert "read_file" in visible
    assert "ls" in visible


def test_first_turn_with_empty_messages_still_filters() -> None:
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("task"), _named_tool("read_file")]
    state: dict = {"messages": []}
    runtime = SimpleNamespace(context={"mode": "work"})
    visible = _run(middleware, _model_request(tools=tools, state=state, runtime=runtime))
    assert "web_search" not in visible
    assert "task" not in visible
    assert "read_file" in visible


def test_after_first_ai_message_exposes_full_catalog() -> None:
    """Turn 2+: the LLM has already had a reasoning turn — let everything through."""
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("task"), _named_tool("bash")]
    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
            HumanMessage(content="follow up"),
        ]
    }
    runtime = SimpleNamespace(context={"mode": "work"})
    visible = _run(middleware, _model_request(tools=tools, state=state, runtime=runtime))
    assert visible == {"web_search", "task", "bash"}


def test_plan_mode_does_not_filter() -> None:
    """Plan Mode catalog selection already excludes execution tools, so the
    middleware must not double-filter. It just passes the request through."""
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("read_file"), _named_tool("write_todos"), _named_tool("recall")]
    state = {"messages": [HumanMessage(content="hi")]}  # turn 1, no AI msg yet
    runtime = SimpleNamespace(context={"mode": "plan"})
    request = _model_request(tools=tools, state=state, runtime=runtime)
    _run(middleware, request)
    # No filtering happened — override was never called.
    request.override.assert_not_called()


def test_existing_plan_skips_filtering() -> None:
    """A plan dict in state means we're post-handoff (work_agent invoked with an
    approved plan), or mid-plan execution — either way, no first-turn warm-up."""
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("task"), _named_tool("bash")]
    state = {"plan": {"status": "approved"}, "messages": [HumanMessage(content="go")]}
    runtime = SimpleNamespace(context={"mode": "work"})
    request = _model_request(tools=tools, state=state, runtime=runtime)
    _run(middleware, request)
    request.override.assert_not_called()


def test_execution_tools_constant_locks_contract() -> None:
    """Sanity check: the tools we expect to gate on turn 1 are in the set."""
    for tool_name in (
        "bash",
        "write_file",
        "str_replace",
        "task",
        "web_search",
        "query_knowledge_vault",
        "save_to_knowledge_vault",
    ):
        assert tool_name in _EXECUTION_TOOLS


def test_request_with_no_tools_passes_through_unchanged() -> None:
    middleware = PhaseToolFilterMiddleware()
    state = {"messages": []}
    runtime = SimpleNamespace(context={"mode": "work"})
    request = _model_request(tools=[], state=state, runtime=runtime)
    _run(middleware, request)
    request.override.assert_not_called()
