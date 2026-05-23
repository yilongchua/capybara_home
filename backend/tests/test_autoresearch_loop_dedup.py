"""Unit tests for the autoresearch dedup classifier.

The classifier is a pure function over (candidates, existing_questions,
threshold, optional vault_lookup) so these tests need no I/O, no LLM, no
control-plane state.
"""

from __future__ import annotations

from src.control_plane.autoresearch_loop.dedup import (
    DedupVerdict,
    classify_questions,
    jaccard,
)


def test_jaccard_identical_tokens_returns_one() -> None:
    a = {"alpha", "beta"}
    assert jaccard(a, a) == 1.0


def test_jaccard_disjoint_sets_returns_zero() -> None:
    assert jaccard({"x"}, {"y"}) == 0.0


def test_jaccard_empty_set_is_zero() -> None:
    assert jaccard(set(), {"x"}) == 0.0
    assert jaccard({"x"}, set()) == 0.0


def test_classify_marks_empty_candidate_as_duplicate() -> None:
    [(_, verdict)] = classify_questions(
        candidates=[{"content": "   "}],
        existing_questions=[],
        similarity_threshold=0.85,
    )
    assert verdict.is_duplicate is True
    assert verdict.reason == "empty"


def test_classify_novel_when_no_existing_or_vault_match() -> None:
    [(_, verdict)] = classify_questions(
        candidates=[{"content": "How do you make soba noodles from scratch?"}],
        existing_questions=[],
        similarity_threshold=0.85,
    )
    assert verdict.is_duplicate is False
    assert verdict.reason == "novel"
    assert verdict.novelty == 1.0  # nothing to compare against


def test_classify_detects_ledger_duplicate_via_jaccard() -> None:
    existing = [
        {"id": "q-soba-ingredients", "content": "What ingredients are in soba noodles?"},
    ]
    candidates = [{"content": "What ingredients are in soba noodles?"}]  # exact repeat
    [(_, verdict)] = classify_questions(
        candidates=candidates,
        existing_questions=existing,
        similarity_threshold=0.85,
    )
    assert verdict.is_duplicate is True
    assert verdict.reason == "ledger"
    assert verdict.duplicate_of == "q-soba-ingredients"


def test_classify_near_duplicate_below_threshold_passes() -> None:
    """A high-but-sub-threshold Jaccard should not collapse the question."""
    existing = [
        {"id": "q-soba-ingredients", "content": "What ingredients are in soba noodles?"},
    ]
    candidates = [{"content": "Where do soba ingredients come from?"}]  # share ~half tokens
    [(_, verdict)] = classify_questions(
        candidates=candidates,
        existing_questions=existing,
        similarity_threshold=0.99,  # extreme threshold so this can't qualify
    )
    assert verdict.is_duplicate is False
    assert 0.0 < verdict.novelty < 1.0


def test_classify_uses_vault_lookup_with_rrf_threshold() -> None:
    """If the vault returns a hit at RRF score >= 0.02, mark as vault duplicate."""

    def vault_lookup(_query: str) -> list[dict[str, object]]:
        return [{"id": "soba-101", "score": 0.025, "title": "Soba 101"}]

    [(_, verdict)] = classify_questions(
        candidates=[{"content": "How do you make soba noodles from scratch?"}],
        existing_questions=[],
        similarity_threshold=0.85,
        vault_lookup=vault_lookup,
    )
    assert verdict.is_duplicate is True
    assert verdict.reason == "vault"
    assert verdict.duplicate_of and verdict.duplicate_of.startswith("vault:")
    assert verdict.novelty == 0.0  # confirmed duplicate → fully covered


def test_classify_ignores_vault_hits_below_rrf_threshold() -> None:
    """A weak vault hit (score < 0.02) must not be treated as a duplicate."""

    def vault_lookup(_query: str) -> list[dict[str, object]]:
        return [{"id": "soba-weak", "score": 0.005, "title": "Weak match"}]

    [(_, verdict)] = classify_questions(
        candidates=[{"content": "How do you make soba noodles from scratch?"}],
        existing_questions=[],
        similarity_threshold=0.85,
        vault_lookup=vault_lookup,
    )
    assert verdict.is_duplicate is False
    assert verdict.reason == "novel"


def test_classify_vault_lookup_raising_does_not_crash_classifier() -> None:
    def vault_lookup(_query: str) -> list[dict[str, object]]:
        raise RuntimeError("vault search backend down")

    [(_, verdict)] = classify_questions(
        candidates=[{"content": "How do you make soba noodles from scratch?"}],
        existing_questions=[],
        similarity_threshold=0.85,
        vault_lookup=vault_lookup,
    )
    # Lookup failures fall back to ledger-only — should still produce a verdict.
    assert isinstance(verdict, DedupVerdict)
    assert verdict.is_duplicate is False


def test_classify_preserves_input_order() -> None:
    candidates = [
        {"content": "What is soba?"},
        {"content": "How is soba made?"},
        {"content": "Where to find soba in Tokyo?"},
    ]
    verdicts = classify_questions(
        candidates=candidates,
        existing_questions=[],
        similarity_threshold=0.85,
    )
    assert [c["content"] for c, _ in verdicts] == [c["content"] for c in candidates]
