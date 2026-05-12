from types import SimpleNamespace

from src.agents.middlewares.runtime_events import append_runtime_event, drain_runtime_events


def test_runtime_events_support_multiple_consumers() -> None:
    runtime = SimpleNamespace(context={})
    append_runtime_event(runtime, {"source": "test", "event": "a"})
    append_runtime_event(runtime, {"source": "test", "event": "b"})

    first_consumer = drain_runtime_events(runtime, consumer="trajectory")
    second_consumer = drain_runtime_events(runtime, consumer="execution_trace")

    assert [e["event"] for e in first_consumer] == ["a", "b"]
    assert [e["event"] for e in second_consumer] == ["a", "b"]
    assert drain_runtime_events(runtime, consumer="trajectory") == []
    assert drain_runtime_events(runtime, consumer="execution_trace") == []

