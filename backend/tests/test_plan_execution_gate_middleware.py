"""Tests for draft-plan execution gating middleware."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.middlewares.plan_execution_gate_middleware import PlanExecutionGateMiddleware


def _request(tool_name: str, *, plan: dict | None = None):
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": "tc-1", "args": {}},
        runtime=SimpleNamespace(context={}, state={"plan": plan or {}}),
        state={},
    )


def _handler(_: object) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id="tc-1", name="handler")


def test_draft_plan_blocks_execution_tools():
    middleware = PlanExecutionGateMiddleware()
    result = middleware.wrap_tool_call(_request("write_file", plan={"status": "draft"}), _handler)
    assert isinstance(result, Command)
    message = result.update["messages"][0]
    assert "[plan_gate]" in str(message.content)


def test_draft_plan_allows_clarification_and_todo_updates():
    middleware = PlanExecutionGateMiddleware()
    for tool_name in ("ask_clarification", "write_todos"):
        result = middleware.wrap_tool_call(_request(tool_name, plan={"status": "draft"}), _handler)
        assert isinstance(result, ToolMessage)
        assert result.content == "ok"


def test_approved_plan_allows_execution():
    middleware = PlanExecutionGateMiddleware()
    result = middleware.wrap_tool_call(_request("write_file", plan={"status": "approved"}), _handler)
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"


def test_pending_clarification_blocks_non_clarification_tools():
    middleware = PlanExecutionGateMiddleware()
    result = middleware.wrap_tool_call(
        _request(
            "bash",
            plan={"status": "draft", "clarification_pending": True, "clarification_question": "What years should this cover?"},
        ),
        _handler,
    )
    assert isinstance(result, Command)
    message = result.update["messages"][0]
    assert "What years should this cover?" in str(message.content)
