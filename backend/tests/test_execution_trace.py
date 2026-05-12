from types import SimpleNamespace

from src.agents.execution_trace import (
    TRACE_MAX_EVENTS_PER_RUN,
    TRACE_MAX_PAYLOAD_CHARS,
    TRACE_MAX_RUNS_RETAINED,
    create_trace_event,
    execution_trace_update,
    extract_reasoning_from_message,
    extract_token_usage_from_message,
    merge_execution_trace,
)


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context={})


def test_create_trace_event_truncates_large_payload() -> None:
    runtime = _runtime()
    huge = {"text": "x" * (TRACE_MAX_PAYLOAD_CHARS + 200)}
    event = create_trace_event(
        runtime,
        stage="harness",
        event_type="oversized_payload",
        status="info",
        payload=huge,
    )

    assert event["payload_truncated"] is True
    assert event["payload_original_chars"] > TRACE_MAX_PAYLOAD_CHARS
    assert event["payload"].get("_truncated") is True


def test_merge_execution_trace_dedupes_by_event_id_and_sorts() -> None:
    runtime = _runtime()
    event_a = create_trace_event(
        runtime,
        stage="lead",
        event_type="model_call_start",
        status="running",
        payload={"step": "a"},
    )
    event_b = create_trace_event(
        runtime,
        stage="lead",
        event_type="model_call_end",
        status="completed",
        payload={"step": "b"},
    )
    duplicate_event_a = dict(event_a)
    duplicate_event_a["status"] = "completed"

    left = execution_trace_update([event_b, event_a])
    right = execution_trace_update([duplicate_event_a])
    merged = merge_execution_trace(left, right)

    run = merged["runs"][event_a["run_id"]]
    assert len(run["events"]) == 2
    assert run["events"][0]["id"] == event_a["id"]
    assert run["events"][0]["status"] == "completed"
    assert run["events"][1]["id"] == event_b["id"]


def test_extract_reasoning_and_token_usage_from_ai_message_like() -> None:
    message = SimpleNamespace(
        additional_kwargs={"reasoning_content": "Chain of thought fragment"},
        content="Final answer",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
            }
        },
        usage_metadata=None,
    )

    reasoning = extract_reasoning_from_message(message)
    usage = extract_token_usage_from_message(message)

    assert reasoning == "Chain of thought fragment"
    assert usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


def test_merge_execution_trace_enforces_retention_caps() -> None:
    runtime = _runtime()
    runs = []
    for i in range(TRACE_MAX_RUNS_RETAINED + 4):
        run_id = f"run-{i}"
        events = []
        for j in range(TRACE_MAX_EVENTS_PER_RUN + 6):
            event = create_trace_event(
                runtime,
                stage="lead",
                event_type="model_response",
                status="completed",
                payload={"i": i, "j": j},
            )
            event["run_id"] = run_id
            event["id"] = f"{run_id}:{j}"
            event["seq"] = j
            event["timestamp"] = float(j)
            events.append(event)
        runs.append(execution_trace_update(events))

    merged = execution_trace_update([])
    for run in runs:
        merged = merge_execution_trace(merged, run)

    assert len(merged["runs"]) <= TRACE_MAX_RUNS_RETAINED
    assert all(len(run["events"]) <= TRACE_MAX_EVENTS_PER_RUN for run in merged["runs"].values())
