"""Unit tests for the autoresearch novelty-decay stop criterion."""

from __future__ import annotations

from src.control_plane.autoresearch_loop.stop_criteria import (
    compute_novelty_rate,
    should_stop,
)


def _gen(status: str) -> dict[str, str]:
    return {"asked_by": "generator", "status": status}


def test_novelty_rate_all_novel_returns_one() -> None:
    questions = [_gen("answered")] * 10
    assert compute_novelty_rate(questions=questions, window=10) == 1.0


def test_novelty_rate_all_duplicates_returns_zero() -> None:
    questions = [_gen("duplicate")] * 10
    assert compute_novelty_rate(questions=questions, window=10) == 0.0


def test_novelty_rate_mixed_in_window() -> None:
    # 7 novel, 3 duplicate in the last 10 → 0.7
    questions = [_gen("answered")] * 7 + [_gen("duplicate")] * 3
    assert compute_novelty_rate(questions=questions, window=10) == 0.7


def test_novelty_rate_ignores_reflector_and_user_questions() -> None:
    # Only generator-asked questions should count toward novelty signal.
    questions = (
        [_gen("answered")] * 5
        + [{"asked_by": "reflector", "status": "answered"}] * 5  # ignored
        + [_gen("duplicate")] * 5
    )
    # 5 novel + 5 duplicate generator questions → 0.5
    assert compute_novelty_rate(questions=questions, window=10) == 0.5


def test_novelty_rate_uses_only_most_recent_window() -> None:
    # 20 duplicates at the front, 10 novel at the back; window=10 → 1.0
    questions = [_gen("duplicate")] * 20 + [_gen("answered")] * 10
    assert compute_novelty_rate(questions=questions, window=10) == 1.0


def test_should_stop_warms_up_before_window_filled() -> None:
    # Only 5 generator questions; window=10 → not enough data, never stop.
    questions = [_gen("duplicate")] * 5
    stop, _rate, reason = should_stop(
        questions=questions, novelty_decay_threshold=0.7, window=10
    )
    assert stop is False
    assert reason == "warming_up"


def test_should_stop_triggers_on_decay_above_threshold() -> None:
    # 9 duplicates + 1 novel in the last 10 → decay 0.9 ≥ threshold 0.7
    questions = [_gen("duplicate")] * 9 + [_gen("answered")]
    stop, rate, reason = should_stop(
        questions=questions, novelty_decay_threshold=0.7, window=10
    )
    assert stop is True
    assert reason == "novelty_decay"
    assert rate == 0.1


def test_should_stop_remains_active_when_decay_below_threshold() -> None:
    # 5 duplicates + 5 novel → decay 0.5 < threshold 0.7
    questions = [_gen("duplicate")] * 5 + [_gen("answered")] * 5
    stop, _rate, reason = should_stop(
        questions=questions, novelty_decay_threshold=0.7, window=10
    )
    assert stop is False
    assert reason == "active"
