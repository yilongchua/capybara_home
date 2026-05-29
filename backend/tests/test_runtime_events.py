from types import MappingProxyType, SimpleNamespace

from src.agents.middlewares.run_scoped import get_run_store
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


def test_runtime_events_compact_after_single_consumer_grace() -> None:
    runtime = SimpleNamespace(context={})
    append_runtime_event(runtime, {"source": "test", "event": "a"})
    append_runtime_event(runtime, {"source": "test", "event": "b"})

    first_drain = drain_runtime_events(runtime, consumer="activity_timeline")
    assert [e["event"] for e in first_drain] == ["a", "b"]
    assert len(get_run_store(runtime)["_phase_a_runtime_events"]) == 2

    assert drain_runtime_events(runtime, consumer="activity_timeline") == []
    assert get_run_store(runtime)["_phase_a_runtime_events"] == []


def test_runtime_events_do_not_require_mutable_context() -> None:
    runtime = SimpleNamespace(context=MappingProxyType({"thread_id": "thread-1"}))
    append_runtime_event(runtime, {"source": "test", "event": "a"})

    assert [event["event"] for event in drain_runtime_events(runtime, consumer="trace")] == ["a"]
    assert "_phase_a_runtime_events" not in runtime.context
