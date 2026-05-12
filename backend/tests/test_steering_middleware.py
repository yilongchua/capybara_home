"""Tests for steering intent middleware."""

from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.middlewares.steering_middleware import SteeringMiddleware


def _no_queue(_thread_id: str):
    return None


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context={"thread_id": "thread-1"})


def test_steering_middleware_injects_and_clears(monkeypatch):
    monkeypatch.setattr("src.agents.middlewares.steering_middleware.claim_next_steering_intent", _no_queue)
    middleware = SteeringMiddleware()
    state = {
        "messages": [HumanMessage(content="hello")],
        "pending_steering_intents": [
            {
                "intent_id": "intent-1",
                "message": "  Focus on security tradeoffs.  ",
                "created_at": "2026-05-08T00:00:00Z",
            },
            {
                "intent_id": "intent-2",
                "message": "Use explicit examples.",
                "created_at": "2026-05-08T00:00:01Z",
            },
        ],
    }

    update = middleware.before_model(state, _runtime())

    assert update is not None
    assert update["steering_context"] is None
    assert update["pending_steering_intents"] == [
        {
            "intent_id": "intent-2",
            "message": "Use explicit examples.",
            "created_at": "2026-05-08T00:00:01Z",
        }
    ]
    injected = update["messages"]
    assert len(injected) == 1
    assert isinstance(injected[0], SystemMessage)
    assert "Focus on security tradeoffs." in injected[0].content


def test_steering_middleware_noop_when_missing(monkeypatch):
    monkeypatch.setattr("src.agents.middlewares.steering_middleware.claim_next_steering_intent", _no_queue)
    middleware = SteeringMiddleware()
    state = {"messages": [HumanMessage(content="hello")]}

    update = middleware.before_model(state, _runtime())

    assert update is None


def test_steering_middleware_bridges_legacy_field(monkeypatch):
    monkeypatch.setattr("src.agents.middlewares.steering_middleware.claim_next_steering_intent", _no_queue)
    middleware = SteeringMiddleware()
    state = {
        "messages": [HumanMessage(content="hello")],
        "steering_context": "   Make sure to check auth edge-cases.   ",
    }

    update = middleware.before_model(state, _runtime())

    assert update is not None
    assert update["steering_context"] is None
    assert update["pending_steering_intents"] == []
    injected = update["messages"]
    assert len(injected) == 1
    assert isinstance(injected[0], SystemMessage)
    assert "check auth edge-cases." in injected[0].content


def test_steering_middleware_clears_blank_legacy_value(monkeypatch):
    monkeypatch.setattr("src.agents.middlewares.steering_middleware.claim_next_steering_intent", _no_queue)
    middleware = SteeringMiddleware()
    state = {
        "messages": [HumanMessage(content="hello")],
        "steering_context": "   ",
    }

    update = middleware.before_model(state, _runtime())

    assert update == {"steering_context": None, "pending_steering_intents": []}


def test_steering_middleware_consumes_thread_queue_first(monkeypatch):
    monkeypatch.setattr(
        "src.agents.middlewares.steering_middleware.claim_next_steering_intent",
        lambda _thread_id: {
            "intent_id": "intent-live-1",
            "message": "Prioritize bug fixes first.",
            "created_at": "2026-05-12T00:00:00Z",
        },
    )
    middleware = SteeringMiddleware()
    update = middleware.before_model({"messages": [HumanMessage(content="hello")]}, _runtime())
    assert update is not None
    assert update["steering_context"] is None
    assert isinstance(update["messages"][0], SystemMessage)
    assert "Prioritize bug fixes first." in update["messages"][0].content
