"""Stop criteria for the autoresearch loop.

Currently a single signal: novelty decay. Among the last ``window`` generated
questions, what fraction were classified as duplicates? When that exceeds the
configured threshold, the loop is saturated and the objective is marked
``completed_endpoint``.
"""

from __future__ import annotations

from typing import Any


def compute_novelty_rate(
    *,
    questions: list[dict[str, Any]],
    window: int,
) -> float:
    """Return novel fraction (1.0 = all novel) over the last ``window`` generated questions."""
    if not questions or window <= 0:
        return 1.0
    # Look at the most recent generator-emitted questions; skip user/reflector-injected
    # entries so the signal reflects what the generator is producing.
    recent = [
        node
        for node in questions
        if node.get("asked_by") in ("generator", None)
    ][-window:]
    if not recent:
        return 1.0
    duplicates = sum(1 for node in recent if node.get("status") == "duplicate")
    novel = len(recent) - duplicates
    return novel / len(recent) if recent else 1.0


def should_stop(
    *,
    questions: list[dict[str, Any]],
    novelty_decay_threshold: float,
    window: int,
) -> tuple[bool, float, str]:
    """Decide whether the loop has saturated.

    Returns ``(stop, novelty_rate, reason)``.
    ``stop=True`` means the objective should be marked complete.
    """
    novelty_rate = compute_novelty_rate(questions=questions, window=window)
    if len([n for n in questions if n.get("asked_by") in ("generator", None)]) < window:
        # Don't trigger stop until we have at least ``window`` generator questions.
        return False, novelty_rate, "warming_up"
    decay = 1.0 - novelty_rate
    if decay >= novelty_decay_threshold:
        return True, novelty_rate, "novelty_decay"
    return False, novelty_rate, "active"
