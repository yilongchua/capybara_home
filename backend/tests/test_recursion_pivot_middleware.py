"""Tests for RecursionBudgetPivotMiddleware."""

from __future__ import annotations

import concurrent.futures
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.recursion_pivot_middleware import (
    RecursionBudgetPivotMiddleware,
    _parse_evaluator_response,
)
from src.config.recursion_pivot_config import RecursionPivotConfig


def _runtime(recursion_limit: int = 100) -> SimpleNamespace:
    return SimpleNamespace(
        config={"recursion_limit": recursion_limit, "configurable": {}},
        context={"original_user_request": "Solve the problem.", "thread_id": "thread-1"},
    )


def _mw(*, config: RecursionPivotConfig, evaluator_response: str | Exception = "DECISION: KEEP\nDIRECTIVE: stay\nREASON: progress is fine") -> RecursionBudgetPivotMiddleware:
    router = MagicMock()
    router.resolve.return_value = "test-evaluator-model"
    mw = RecursionBudgetPivotMiddleware(router=router, requested_model=None, config=config)

    def _fake_invoke(_prompt: str) -> str:
        if isinstance(evaluator_response, Exception):
            raise evaluator_response
        return evaluator_response

    mw._invoke_evaluator = _fake_invoke  # type: ignore[method-assign]
    return mw


def _state(message_count: int) -> dict:
    # Each step ≈ 2 messages (AI + tool/human). Generate that many AI messages
    # so step_count = message_count // 2.
    return {"messages": [AIMessage(content=f"step {i}") for i in range(message_count)]}


def test_disabled_config_returns_none():
    mw = _mw(config=RecursionPivotConfig(enabled=False, thresholds=[0.5]))
    assert mw.before_model(_state(200), _runtime(recursion_limit=100)) is None


def test_below_threshold_is_noop():
    mw = _mw(config=RecursionPivotConfig(enabled=True, thresholds=[0.8]))
    # step = 10 messages // 2 = 5, recursion_limit=100, threshold @ 80 -> no fire
    assert mw.before_model(_state(10), _runtime(recursion_limit=100)) is None


def test_below_min_recursion_limit_is_noop():
    mw = _mw(config=RecursionPivotConfig(enabled=True, thresholds=[0.5], min_recursion_limit=20))
    # recursion_limit=10 < min_recursion_limit=20 -> skip entirely
    assert mw.before_model(_state(200), _runtime(recursion_limit=10)) is None


def test_keep_decision_consumes_threshold_without_injecting():
    mw = _mw(
        config=RecursionPivotConfig(enabled=True, thresholds=[0.8]),
        evaluator_response="DECISION: KEEP\nDIRECTIVE: keep going\nREASON: making progress",
    )
    # step = 160 // 2 = 80, recursion_limit=100, threshold 0.8 -> crossover at 80, fires
    result = mw.before_model(_state(160), _runtime(recursion_limit=100))
    assert result is not None
    assert "messages" not in result  # no injection on KEEP
    assert result["recursion_pivot"]["fired_thresholds"] == [0]
    assert result["recursion_pivot"]["last_decision"] == "KEEP"


def test_pivot_decision_injects_steering_message():
    mw = _mw(
        config=RecursionPivotConfig(enabled=True, thresholds=[0.8]),
        evaluator_response="DECISION: PIVOT\nDIRECTIVE: switch to using the bash tool directly instead of subagents\nREASON: subagents are too slow",
    )
    result = mw.before_model(_state(160), _runtime(recursion_limit=100))
    assert result is not None
    messages = result.get("messages") or []
    assert len(messages) == 1
    injected = messages[0]
    assert isinstance(injected, HumanMessage)
    assert injected.name == "recursion_pivot_steering"
    assert "switch to using the bash tool directly" in injected.content
    assert "source='recursion_pivot'" in injected.content
    assert result["recursion_pivot"]["last_decision"] == "PIVOT"


def test_threshold_fires_at_most_once():
    mw = _mw(
        config=RecursionPivotConfig(enabled=True, thresholds=[0.8]),
        evaluator_response="DECISION: PIVOT\nDIRECTIVE: do X\nREASON: stuck",
    )
    state = _state(160)
    runtime = _runtime(recursion_limit=100)
    first = mw.before_model(state, runtime)
    assert first is not None
    # Carry pivot state forward; advance step count further (still past threshold).
    state = {**state, "recursion_pivot": first["recursion_pivot"], "messages": _state(180)["messages"]}
    second = mw.before_model(state, runtime)
    assert second is None  # already fired, no further action


def test_multiple_thresholds_fire_in_sequence():
    mw = _mw(
        config=RecursionPivotConfig(enabled=True, thresholds=[0.5, 0.8]),
        evaluator_response="DECISION: KEEP\nDIRECTIVE: keep going\nREASON: ok",
    )
    runtime = _runtime(recursion_limit=100)

    # First crossing at step 50.
    state = _state(100)
    first = mw.before_model(state, runtime)
    assert first is not None
    assert first["recursion_pivot"]["fired_thresholds"] == [0]

    # Between thresholds: no-op.
    state = {"messages": _state(120)["messages"], "recursion_pivot": first["recursion_pivot"]}
    between = mw.before_model(state, runtime)
    assert between is None

    # Second crossing at step 80.
    state = {"messages": _state(160)["messages"], "recursion_pivot": first["recursion_pivot"]}
    second = mw.before_model(state, runtime)
    assert second is not None
    assert second["recursion_pivot"]["fired_thresholds"] == [0, 1]


def test_evaluator_timeout_with_skip_continues():
    mw = _mw(
        config=RecursionPivotConfig(enabled=True, thresholds=[0.8], on_evaluator_failure="skip"),
        evaluator_response=concurrent.futures.TimeoutError("hung"),
    )
    result = mw.before_model(_state(160), _runtime(recursion_limit=100))
    assert result is not None
    assert "messages" not in result
    assert result["recursion_pivot"]["last_decision"] == "FAILED"
    assert "jump_to" not in result


def test_evaluator_timeout_with_terminate_ends_run():
    mw = _mw(
        config=RecursionPivotConfig(enabled=True, thresholds=[0.8], on_evaluator_failure="terminate"),
        evaluator_response=concurrent.futures.TimeoutError("hung"),
    )
    result = mw.before_model(_state(160), _runtime(recursion_limit=100))
    assert result is not None
    assert result.get("jump_to") == "end"
    messages = result.get("messages") or []
    assert messages and isinstance(messages[0], HumanMessage)
    assert messages[0].name == "recursion_pivot_warning"


def test_evaluator_generic_exception_with_skip():
    mw = _mw(
        config=RecursionPivotConfig(enabled=True, thresholds=[0.8], on_evaluator_failure="skip"),
        evaluator_response=RuntimeError("model unreachable"),
    )
    result = mw.before_model(_state(160), _runtime(recursion_limit=100))
    assert result is not None
    assert "messages" not in result
    assert result["recursion_pivot"]["last_decision"] == "FAILED"


def test_missing_recursion_limit_is_noop():
    mw = _mw(config=RecursionPivotConfig(enabled=True, thresholds=[0.8]))
    runtime = SimpleNamespace(config={}, context={})
    assert mw.before_model(_state(200), runtime) is None


def test_threshold_validator_rejects_out_of_range():
    with pytest.raises(ValueError):
        RecursionPivotConfig(thresholds=[1.5])
    with pytest.raises(ValueError):
        RecursionPivotConfig(thresholds=[0.0])
    with pytest.raises(ValueError):
        RecursionPivotConfig(thresholds=[])


def test_thresholds_are_sorted_and_deduped():
    cfg = RecursionPivotConfig(thresholds=[0.9, 0.5, 0.5, 0.7])
    assert cfg.thresholds == [0.5, 0.7, 0.9]


def test_parse_response_pivot():
    pivot, directive, reason = _parse_evaluator_response(
        "DECISION: PIVOT\nDIRECTIVE: switch to writing a script first\nREASON: tool calls are looping"
    )
    assert pivot is True
    assert "switch to writing a script first" in directive
    assert "tool calls are looping" in reason


def test_parse_response_keep():
    pivot, directive, reason = _parse_evaluator_response("DECISION: KEEP\nDIRECTIVE: continue\nREASON: progressing well")
    assert pivot is False


def test_parse_response_multiline_directive():
    pivot, directive, _ = _parse_evaluator_response(
        "DECISION: PIVOT\nDIRECTIVE: stop using web_search\nand instead read the docs file directly\nREASON: dead end"
    )
    assert pivot is True
    assert "read the docs file directly" in directive


def test_parse_response_unparseable_defaults_to_keep():
    pivot, directive, reason = _parse_evaluator_response("garbage output from the model")
    assert pivot is False
    assert directive == ""
    assert reason == ""


def test_pivot_with_empty_directive_does_not_inject():
    """Safety net: if evaluator says PIVOT but provides no directive, do not inject a blank reminder."""
    mw = _mw(
        config=RecursionPivotConfig(enabled=True, thresholds=[0.8]),
        evaluator_response="DECISION: PIVOT\nDIRECTIVE:\nREASON: confused",
    )
    result = mw.before_model(_state(160), _runtime(recursion_limit=100))
    assert result is not None
    assert "messages" not in result
