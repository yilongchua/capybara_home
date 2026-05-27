"""Tests for clarification middleware auto-mode behavior."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.middlewares.clarification_middleware import ClarificationMiddleware


def _runtime(*, auto_mode_in_context: bool = False, auto_mode_in_config: bool | None = None):
    config = {}
    if auto_mode_in_config is not None:
        config = {"configurable": {"auto_mode": auto_mode_in_config}}
    return SimpleNamespace(
        context={"auto_mode": auto_mode_in_context},
        config=config,
    )


def _request(*, context: dict | None = None, options: list[dict] | None = None):
    return SimpleNamespace(
        tool_call={
            "name": "ask_user_for_clarification",
            "id": "tc-1",
            "args": {
                "question": "Which option?",
                "clarification_type": "approach_choice",
                "options": options
                or [
                    {"label": "Recommended", "recommended": True, "description": "Best default"},
                    {"label": "Fallback", "recommended": False, "description": "Alternative"},
                ],
            },
        },
        runtime=SimpleNamespace(context=context or {}, state={}),
        state={},
    )


def test_before_model_caches_auto_mode_from_runtime_context():
    middleware = ClarificationMiddleware()
    runtime = _runtime(auto_mode_in_context=True, auto_mode_in_config=None)

    middleware.before_model({"auto_mode": False}, runtime)

    assert runtime.context["_clarification_auto_mode"] is True


def test_wrap_tool_call_auto_selects_recommended_option_from_context_auto_mode():
    middleware = ClarificationMiddleware()
    request = _request(context={"_clarification_auto_mode": True})

    result = middleware.wrap_tool_call(request, lambda _req: ToolMessage(content="unused", tool_call_id="tc-1", name="ask_user_for_clarification"))

    assert isinstance(result, Command)
    message = result.update["messages"][0]
    assert message.content == "[Auto Mode] Selected: Recommended"
