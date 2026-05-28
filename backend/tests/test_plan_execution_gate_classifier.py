"""Tests for the scope-intent classifier inside PlanExecutionGateMiddleware."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from src.agents.middlewares import plan_execution_gate_middleware as gate_mod
from src.agents.middlewares.plan_execution_gate_middleware import PlanExecutionGateMiddleware


def _request(tool_name: str, *, plan: dict | None = None, query: str = "", messages: list | None = None):
    state = {
        "plan": plan or {},
        "messages": messages or [HumanMessage(content="Research crystals end-to-end")],
    }
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": f"tc-{tool_name}", "args": {"query": query}},
        runtime=SimpleNamespace(context={}, state=state),
        state=state,
    )


def _handler(_: object) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id="tc-X", name="handler")


def _stub_model(verdict: str):
    """Return a model object whose .invoke returns a verdict string."""
    response = SimpleNamespace(content=verdict)
    return SimpleNamespace(invoke=lambda _msgs: response)


def test_classifier_scope_verdict_allows_web_search(monkeypatch) -> None:
    middleware = PlanExecutionGateMiddleware(requested_model=None)
    monkeypatch.setattr(gate_mod, "create_chat_model", lambda **_: _stub_model("scope"))
    monkeypatch.setattr(gate_mod, "resolve_model_name", lambda _: "test-model")
    result = middleware.wrap_tool_call(
        _request("web_search", plan={"status": "draft"}, query="types of crystals studied in anthropology"),
        _handler,
    )
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"


def test_classifier_content_verdict_blocks_web_search(monkeypatch) -> None:
    middleware = PlanExecutionGateMiddleware(requested_model=None)
    monkeypatch.setattr(gate_mod, "create_chat_model", lambda **_: _stub_model("content"))
    monkeypatch.setattr(gate_mod, "resolve_model_name", lambda _: "test-model")
    result = middleware.wrap_tool_call(
        _request("web_search", plan={"status": "draft"}, query="crystals spiritual protection grounding history"),
        _handler,
    )
    assert isinstance(result, Command)
    message = result.update["messages"][0]
    assert "scope-clarifying search only" in str(message.content)


def test_classifier_failure_fails_closed(monkeypatch) -> None:
    middleware = PlanExecutionGateMiddleware(requested_model=None)

    def boom(**_):
        raise RuntimeError("model unreachable")

    monkeypatch.setattr(gate_mod, "create_chat_model", boom)
    monkeypatch.setattr(gate_mod, "resolve_model_name", lambda _: "test-model")
    result = middleware.wrap_tool_call(
        _request("web_search", plan={"status": "draft"}, query="anything"),
        _handler,
    )
    # On classifier failure we fail-closed and block.
    assert isinstance(result, Command)


def test_classifier_caches_verdict_per_tool_call_id(monkeypatch) -> None:
    middleware = PlanExecutionGateMiddleware(requested_model=None)
    call_count = {"n": 0}

    def make_model(**_):
        def invoke(_msgs):
            call_count["n"] += 1
            return SimpleNamespace(content="scope")
        return SimpleNamespace(invoke=invoke)

    monkeypatch.setattr(gate_mod, "create_chat_model", make_model)
    monkeypatch.setattr(gate_mod, "resolve_model_name", lambda _: "test-model")

    request = _request("web_search", plan={"status": "draft"}, query="taxonomy of crystals")
    middleware.wrap_tool_call(request, _handler)
    # Same tool_call_id again — should use cache.
    middleware.wrap_tool_call(request, _handler)
    assert call_count["n"] == 1


def test_recall_allowed_when_draft(monkeypatch) -> None:
    middleware = PlanExecutionGateMiddleware(requested_model=None)
    # recall is in _ALLOWED_WHEN_DRAFT — it must NOT trigger the classifier
    # nor require any LLM call. Sentinel: any model call should be unreachable.
    monkeypatch.setattr(gate_mod, "create_chat_model", lambda **_: pytest.fail("classifier should not run for recall"))
    result = middleware.wrap_tool_call(
        _request("recall", plan={"status": "draft"}, query="prior research on crystal market data"),
        _handler,
    )
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"
