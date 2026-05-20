"""Tests for activity timeline middleware conversion + persistence."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.middlewares.activity_timeline_middleware import ActivityTimelineMiddleware
from src.agents.middlewares.runtime_events import append_runtime_event


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context={})


def test_before_model_converts_runtime_events_and_updates_context_metrics(monkeypatch) -> None:
    runtime = _runtime()
    middleware = ActivityTimelineMiddleware()
    state = {"messages": []}

    append_runtime_event(
        runtime,
        {
            "source": "task_tool",
            "event": "task_running",
            "task_id": "task-1",
            "group_id": "task-1",
            "subagent_type": "source-researcher",
            "description": "Research Bali remote work",
            "group_title": "source-researcher: Research Bali remote work",
            "tool_summary": "web_search: latest ai news",
        },
    )
    append_runtime_event(
        runtime,
        {
            "source": "summarization_middleware",
            "event": "context_tokens",
            "token_count": 256,
            "message_count": 9,
            "timestamp": 123.0,
        },
    )
    append_runtime_event(
        runtime,
        {
            "source": "summarization_middleware",
            "event": "compaction",
            "messages_compressed": 4,
            "messages_kept": 8,
            "timestamp": 124.0,
        },
    )

    streamed: list[dict] = []
    import src.agents.middlewares.activity_timeline_middleware as module

    monkeypatch.setattr(module, "stream_activity_event", lambda event: streamed.append(event))

    update = middleware.before_model(state, runtime)
    assert update is not None
    assert "activity_timeline" in update
    assert "context_metrics" in update

    lines = [event.get("line", "") for event in update["activity_timeline"]["events"]]
    assert any(line.startswith("Baby Capy - source-researcher is working on") for line in lines)
    assert any(line == "Capybara is thinking..." for line in lines)
    subagent_event = next(event for event in update["activity_timeline"]["events"] if event.get("actor") == "baby_capy")
    assert subagent_event.get("group_title") == "source-researcher: Research Bali remote work"
    assert subagent_event.get("group_role") == "step"

    context_metrics = update["context_metrics"]
    assert context_metrics["token_count"] == 256
    assert context_metrics["message_count"] == 9
    assert context_metrics["messages_compressed"] == 4
    assert context_metrics["messages_kept"] == 8
    assert context_metrics["compaction_count"] >= 1

    assert len(streamed) >= 2


def test_after_model_emits_thinking_and_response_events(monkeypatch) -> None:
    runtime = _runtime()
    middleware = ActivityTimelineMiddleware()

    ai_message = SimpleNamespace(
        type="ai",
        id="ai-1",
        tool_calls=[],
        content="Final response",
        additional_kwargs={"reasoning_content": "Need to verify before answering"},
    )
    state = {"messages": [ai_message]}

    streamed: list[dict] = []
    import src.agents.middlewares.activity_timeline_middleware as module

    monkeypatch.setattr(module, "stream_activity_event", lambda event: streamed.append(event))

    update = middleware.after_model(state, runtime)
    assert update is not None
    events = update["activity_timeline"]["events"]
    kinds = [event.get("kind") for event in events]
    assert "thinking" in kinds
    assert "model_response" in kinds
    lines = [event.get("line") for event in events]
    assert "Capybara is thinking..." in lines


def test_tool_wrap_persists_plan_gate_activity(monkeypatch) -> None:
    runtime = _runtime()
    middleware = ActivityTimelineMiddleware()
    request = ToolCallRequest(
        tool_call={"name": "web_search", "args": {"query": "iran news"}, "id": "call-1", "type": "tool_call"},
        tool=None,
        runtime=runtime,
        state={},
    )

    def _blocked_handler(_req: ToolCallRequest) -> Command:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="[plan_gate] Plan is still draft.",
                        tool_call_id="call-1",
                    )
                ]
            }
        )

    streamed: list[dict] = []
    import src.agents.middlewares.activity_timeline_middleware as module

    monkeypatch.setattr(module, "stream_activity_event", lambda event: streamed.append(event))

    result = middleware.wrap_tool_call(request, _blocked_handler)
    assert isinstance(result, Command)
    update = result.update or {}
    events = update.get("activity_timeline", {}).get("events", [])
    assert len(events) >= 1
    assert any(event.get("kind") == "plan_gate_blocked" for event in events)
