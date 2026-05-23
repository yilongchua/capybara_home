"""Tests for PhaseToolFilterMiddleware — hides execution tools while plan is draft."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.phase_tool_filter_middleware import (
    _DRAFT_HIDDEN_TOOLS,
    _WORK_HIDDEN_TOOLS,
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


def test_draft_plan_hides_execution_tools_from_catalog() -> None:
    middleware = PhaseToolFilterMiddleware()
    tools = [
        _named_tool("web_search"),
        _named_tool("scope_search"),
        _named_tool("read_file"),
        _named_tool("task"),
        _named_tool("write_file"),
    ]
    state = {"plan": {"status": "draft"}}
    runtime = SimpleNamespace(context={"mode": "plan"})
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "web_search" not in visible_names
    assert "task" not in visible_names
    assert "write_file" not in visible_names
    # scope_search and read_file must remain visible
    assert "scope_search" in visible_names
    assert "read_file" in visible_names


def test_approved_plan_does_not_filter_execution_tools() -> None:
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("task")]
    state = {"plan": {"status": "approved"}}
    runtime = SimpleNamespace(context={"mode": "work"})
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "web_search" in visible_names
    assert "task" in visible_names


def test_work_mode_hides_scope_search() -> None:
    """Work Mode / approved plan: scope_search is removed so the LLM doesn't
    reach for it as a lightweight web_search substitute."""
    middleware = PhaseToolFilterMiddleware()
    tools = [
        _named_tool("web_search"),
        _named_tool("scope_search"),
        _named_tool("query_knowledge_vault"),
    ]
    state = {"plan": {"status": "approved"}}
    runtime = SimpleNamespace(context={"mode": "work"})
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "scope_search" not in visible_names
    assert "web_search" in visible_names
    assert "query_knowledge_vault" in visible_names


def test_work_mode_with_no_plan_hides_scope_search() -> None:
    """Mirror of the yoga thread: mode=None, no plan in state. scope_search
    must still be stripped so it can't be called outside Plan Mode.

    Includes a prior AI message so the first-turn default-deny branch does
    not apply — this test covers the steady-state work-mode case.
    """
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("scope_search")]
    state = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}
    runtime = SimpleNamespace(context={})  # mode is not "plan"
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "scope_search" not in visible_names
    assert "web_search" in visible_names


def test_plan_mode_without_plan_still_filters() -> None:
    """First turn: planner has not yet emitted a plan, but the user is in
    Plan Mode. We still filter so the LLM can't fire execution tools."""
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("scope_search")]
    state = {}  # no plan yet
    runtime = SimpleNamespace(context={"mode": "plan"})
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "web_search" not in visible_names
    assert "scope_search" in visible_names


def test_no_hidden_tools_means_request_passes_through_unchanged() -> None:
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("read_file"), _named_tool("ls")]
    state = {"plan": {"status": "draft"}}
    runtime = SimpleNamespace(context={"mode": "plan"})
    request = _model_request(tools=tools, state=state, runtime=runtime)
    handler = MagicMock(return_value="ok")
    middleware.wrap_model_call(request, handler)
    # override was not called because no filtering was needed
    request.override.assert_not_called()


def test_hidden_set_includes_expected_search_and_write_tools() -> None:
    # Locks the contract — these tools MUST be hidden in draft mode.
    for tool_name in ("web_search", "query_knowledge_vault",
                      "search_internal_documents", "task", "write_file", "str_replace"):
        assert tool_name in _DRAFT_HIDDEN_TOOLS


def test_work_hidden_set_includes_scope_search() -> None:
    # scope_search must be hidden in Work Mode / approved-plan state.
    assert "scope_search" in _WORK_HIDDEN_TOOLS


# ---------------------------------------------------------------------------
# Turn-1 default-deny: regression guards for issue 3
#
# Before the fix, work-mode + no-plan + no AI messages exposed the full
# execution catalog on the very first model call. The model would fire
# web_search / query_knowledge_vault / task before PlanExecutionGateMiddleware
# could classify them, wasting a model round-trip while the gate blocked the
# calls retrospectively. _should_filter now defaults to True on turn 1.
# ---------------------------------------------------------------------------


def test_first_turn_work_mode_with_no_plan_hides_execution_tools() -> None:
    """Turn 1: work mode, no plan, no AI messages yet → hide execution tools.

    This is the audit-thread scenario. Without this guard, the LLM fires
    web_search / task before the planner or gate has had a chance to react.
    """
    middleware = PhaseToolFilterMiddleware()
    tools = [
        _named_tool("web_search"),
        _named_tool("query_knowledge_vault"),
        _named_tool("task"),
        _named_tool("scope_search"),
        _named_tool("read_file"),
    ]
    state = {"messages": [HumanMessage(content="complex multi-step request")]}
    runtime = SimpleNamespace(context={"mode": "work"})
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "web_search" not in visible_names
    assert "query_knowledge_vault" not in visible_names
    assert "task" not in visible_names
    # scope_search and read-only tools must remain visible during the
    # pre-classification window.
    assert "scope_search" in visible_names
    assert "read_file" in visible_names


def test_first_turn_with_empty_messages_list_hides_execution_tools() -> None:
    """No messages key at all (or empty list) → still treat as turn 1."""
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("task")]
    state: dict = {"messages": []}
    runtime = SimpleNamespace(context={"mode": "work"})
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "web_search" not in visible_names
    assert "task" not in visible_names


def test_after_first_ai_message_work_mode_exposes_tools() -> None:
    """Turn 2+: at least one prior AI message → planner has had its chance.

    If no plan was created (simple query), let the full catalog through.
    """
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("task"), _named_tool("scope_search")]
    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
            HumanMessage(content="follow up"),
        ]
    }
    runtime = SimpleNamespace(context={"mode": "work"})
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "web_search" in visible_names
    assert "task" in visible_names
    # Steady-state work mode still hides scope_search.
    assert "scope_search" not in visible_names


def test_unknown_plan_status_treated_as_draft() -> None:
    """A plan dict with an unrecognized status should be conservative (draft-like)."""
    middleware = PhaseToolFilterMiddleware()
    tools = [_named_tool("web_search"), _named_tool("scope_search")]
    state = {"plan": {"status": "something-weird"}}
    runtime = SimpleNamespace(context={"mode": "work"})
    request = _model_request(tools=tools, state=state, runtime=runtime)

    captured: dict[str, list] = {}

    def handler(req):
        captured["tools"] = list(req.tools)
        return "ok"

    middleware.wrap_model_call(request, handler)
    visible_names = {getattr(t, "name", None) for t in captured["tools"]}
    assert "web_search" not in visible_names
    assert "scope_search" in visible_names
