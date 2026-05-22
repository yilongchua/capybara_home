"""Tests for PhaseToolFilterMiddleware — hides execution tools while plan is draft."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.agents.middlewares.phase_tool_filter_middleware import (
    _DRAFT_HIDDEN_TOOLS,
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


def test_approved_plan_does_not_filter() -> None:
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
    for tool_name in ("web_search", "query_knowledge_vault", "query_lightrag",
                      "search_internal_documents", "task", "write_file", "str_replace"):
        assert tool_name in _DRAFT_HIDDEN_TOOLS
