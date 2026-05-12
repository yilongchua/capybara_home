"""Tests for execution trace middleware runtime-event conversion."""

from __future__ import annotations

from types import SimpleNamespace

from src.agents.execution_trace import create_trace_event
from src.agents.middlewares.execution_trace_middleware import (
    ExecutionTraceMiddleware,
    _build_trace_update,
)
from src.agents.middlewares.runtime_events import append_runtime_event


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context={})


def test_build_trace_update_preserves_inline_trace_and_skips_restream(monkeypatch) -> None:
    runtime = _runtime()
    inline_trace = create_trace_event(
        runtime,
        stage="subagent",
        event_type="task_running",
        status="running",
        payload={"message_index": 1},
        token_usage={"input_tokens": 12, "output_tokens": 6, "total_tokens": 18},
        thinking={"source": "raw", "content": "Subagent reasoning sample"},
        turn_id="tc-1",
        assistant_message_id="ai-1",
        task_id="tc-1",
    )

    streamed: list[dict] = []
    import src.agents.middlewares.execution_trace_middleware as module

    monkeypatch.setattr(module, "stream_trace_event", lambda event: streamed.append(event))
    update = _build_trace_update(
        runtime,
        [
            {
                "source": "task_tool",
                "event": "task_running",
                "task_id": "tc-1",
                "trace_event": inline_trace,
                "trace_already_streamed": True,
            }
        ],
    )

    assert update is not None
    run = update["execution_trace"]["runs"][inline_trace["run_id"]]
    assert len(run["events"]) == 1
    assert run["events"][0]["id"] == inline_trace["id"]
    assert run["events"][0]["thinking"] == inline_trace["thinking"]
    assert run["events"][0]["token_usage"] == inline_trace["token_usage"]
    assert streamed == []


def test_after_model_persists_inline_runtime_traces_and_streams_only_new_events(monkeypatch) -> None:
    runtime = _runtime()
    middleware = ExecutionTraceMiddleware()

    inline_trace = create_trace_event(
        runtime,
        stage="subagent",
        event_type="task_completed",
        status="completed",
        payload={"subagent_type": "general-purpose"},
        thinking={"source": "summary", "content": "Subagent task completed."},
        turn_id="tc-2",
        assistant_message_id="ai-2",
        task_id="tc-2",
    )
    append_runtime_event(
        runtime,
        {
            "source": "task_tool",
            "event": "task_completed",
            "task_id": "tc-2",
            "trace_event": inline_trace,
            "trace_already_streamed": True,
        },
    )

    state = {
        "messages": [
            SimpleNamespace(
                type="ai",
                id="ai-2",
                tool_calls=[],
                content="final response",
                additional_kwargs={},
                response_metadata={"token_usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}},
                usage_metadata=None,
            )
        ]
    }

    streamed: list[dict] = []
    import src.agents.middlewares.execution_trace_middleware as module

    monkeypatch.setattr(module, "stream_trace_event", lambda event: streamed.append(event))
    update = middleware.after_model(state, runtime)

    assert update is not None
    run = update["execution_trace"]["runs"][inline_trace["run_id"]]
    event_ids = [event.get("id") for event in run["events"]]
    assert inline_trace["id"] in event_ids
    # Only the lead model response should be streamed from after_model; the
    # inline task trace was already streamed directly by task_tool.
    assert inline_trace["id"] not in [event.get("id") for event in streamed]
    assert any(event.get("stage") == "lead" and event.get("event_type") == "model_response" for event in streamed)

