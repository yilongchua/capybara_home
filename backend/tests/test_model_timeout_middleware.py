"""Tests for ModelTimeoutMiddleware.

Regression for the run-c0425b71bd hang: a single model call took 232s and the
subsequent tool call never finished. This middleware bounds both model and
tool calls per stage/tool, and returns a structured warning instead of
hanging.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from src.agents.middlewares.model_timeout_middleware import (
    TIMEOUT_MESSAGE_FINGERPRINT,
    ModelTimeoutMiddleware,
)
from src.config.routing_config import RoutingTimeoutsConfig


def _model_request(stage: str | None = "generator"):
    runtime = SimpleNamespace(context={"thread_id": "t1", "stage": stage})
    return SimpleNamespace(
        runtime=runtime,
        messages=[],
        state={},
    )


def _tool_request(name: str = "write_todos"):
    runtime = SimpleNamespace(context={"thread_id": "t1"})
    return SimpleNamespace(
        runtime=runtime,
        tool_call={"name": name, "id": "tc-1", "args": {}},
        state={},
    )


def test_model_call_timeout_returns_warning():
    cfg = RoutingTimeoutsConfig(default=10, stages={"generator": 2})
    middleware = ModelTimeoutMiddleware(cfg)

    async def slow_handler(_req):
        await asyncio.sleep(5)
        return ModelResponse(result=[AIMessage(content="never reached")])

    result = asyncio.run(middleware.awrap_model_call(_model_request("generator"), slow_handler))
    assert isinstance(result, ModelResponse)
    assert len(result.result) == 1
    msg = result.result[0]
    assert isinstance(msg, AIMessage)
    assert TIMEOUT_MESSAGE_FINGERPRINT in msg.content
    assert "generator" in msg.content


def test_model_call_under_budget_passes_through():
    cfg = RoutingTimeoutsConfig(default=10, stages={"generator": 10})
    middleware = ModelTimeoutMiddleware(cfg)

    async def fast_handler(_req):
        return ModelResponse(result=[AIMessage(content="hi")])

    result = asyncio.run(middleware.awrap_model_call(_model_request("generator"), fast_handler))
    assert result.result[0].content == "hi"


def test_disabled_config_skips_timeout():
    cfg = RoutingTimeoutsConfig(enabled=False, default=10)
    middleware = ModelTimeoutMiddleware(cfg)
    completed = {"flag": False}

    async def slow_but_completing_handler(_req):
        await asyncio.sleep(0.05)
        completed["flag"] = True
        return ModelResponse(result=[AIMessage(content="ok")])

    result = asyncio.run(middleware.awrap_model_call(_model_request(), slow_but_completing_handler))
    assert completed["flag"] is True
    assert result.result[0].content == "ok"


def test_tool_call_timeout_returns_synthetic_tool_message():
    """write_todos hanging was the run-c0425b71bd terminal symptom."""
    cfg = RoutingTimeoutsConfig(tools={"write_todos": 2}, tools_default=10)
    middleware = ModelTimeoutMiddleware(cfg)

    async def hanging_tool(_req):
        await asyncio.sleep(5)
        return ToolMessage(content="never", tool_call_id="tc-1", name="write_todos")

    result = asyncio.run(middleware.awrap_tool_call(_tool_request("write_todos"), hanging_tool))
    assert isinstance(result, ToolMessage)
    assert TIMEOUT_MESSAGE_FINGERPRINT in result.content
    assert result.tool_call_id == "tc-1"
    assert result.name == "write_todos"


def test_per_tool_timeout_override():
    cfg = RoutingTimeoutsConfig(tools={"web_search": 1}, tools_default=10)
    middleware = ModelTimeoutMiddleware(cfg)

    async def slow_search(_req):
        await asyncio.sleep(3)
        return ToolMessage(content="x", tool_call_id="tc-1", name="web_search")

    result = asyncio.run(middleware.awrap_tool_call(_tool_request("web_search"), slow_search))
    assert TIMEOUT_MESSAGE_FINGERPRINT in result.content


def test_for_stage_and_for_tool_lookup():
    cfg = RoutingTimeoutsConfig(stages={"planner": 5}, default=99, tools={"bash": 7}, tools_default=42)
    assert cfg.for_stage("planner") == 5
    assert cfg.for_stage("missing") == 99
    assert cfg.for_stage(None) == 99
    assert cfg.for_tool("bash") == 7
    assert cfg.for_tool("missing") == 42


@pytest.mark.parametrize("stage,expected_label", [("planner", "planner"), (None, "generator")])
def test_timeout_message_includes_stage_label(stage, expected_label):
    cfg = RoutingTimeoutsConfig(default=10, stages={"planner": 10})
    middleware = ModelTimeoutMiddleware(cfg)

    async def slow_handler(_req):
        await asyncio.sleep(15)
        return ModelResponse(result=[])

    result = asyncio.run(middleware.awrap_model_call(_model_request(stage), slow_handler))
    msg = result.result[0]
    assert expected_label in msg.content
