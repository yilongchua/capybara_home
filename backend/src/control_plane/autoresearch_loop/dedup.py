"""Dedup new questions against the existing ledger and the vault.

We keep the dedup signal cheap and explainable: token-set Jaccard similarity
plus a vault keyword search. Embedding-based dedup can be slotted in later
behind the same ``classify_questions`` boundary without changing the loop.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "does",
        "for", "from", "have", "how", "in", "is", "it", "of", "on", "or",
        "should", "so", "that", "the", "this", "to", "vs", "was", "we",
        "what", "when", "where", "which", "who", "why", "with", "you", "your",
    }
)


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    return {tok for tok in raw if tok not in _STOPWORDS and len(tok) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


@dataclass
class DedupVerdict:
    is_duplicate: bool
    duplicate_of: str | None  # ledger question id, or vault entry slug
    novelty: float            # 1.0 - max_similarity, clipped to [0, 1]
    reason: str               # short tag: "ledger", "vault", "novel"


def classify_questions(
    *,
    candidates: list[dict[str, Any]],
    existing_questions: list[dict[str, Any]],
    similarity_threshold: float,
    vault_lookup: callable | None = None,
) -> list[tuple[dict[str, Any], DedupVerdict]]:
    """Classify each candidate as novel or duplicate.

    Args:
        candidates: new question dicts from the generator.
        existing_questions: prior ledger nodes.
        similarity_threshold: Jaccard cutoff above which a candidate is treated
            as a duplicate of an existing question.
        vault_lookup: optional callable taking a query string and returning a
            list of vault hits ``[{"id": str, "score": float, "title": str}, ...]``.
            If provided, top hits with score above 0.5 also mark duplicates.

    Returns:
        A list of ``(candidate, verdict)`` tuples in the same order as input.
    """
    existing_tokens = [
        (str(node.get("id", "")), _tokens(str(node.get("content", ""))))
        for node in existing_questions
        if str(node.get("content", "")).strip()
    ]
    out: list[tuple[dict[str, Any], DedupVerdict]] = []
    for cand in candidates:
        cand_text = str(cand.get("content", "")).strip()
        if not cand_text:
            out.append((cand, DedupVerdict(True, None, 0.0, "empty")))
            continue
        cand_tokens = _tokens(cand_text)

        best_sim = 0.0
        best_id: str | None = None
        for qid, toks in existing_tokens:
            sim = jaccard(cand_tokens, toks)
            if sim > best_sim:
                best_sim = sim
                best_id = qid

        if best_sim >= similarity_threshold and best_id:
            out.append(
                (
                    cand,
                    DedupVerdict(
                        is_duplicate=True,
                        duplicate_of=best_id,
                        novelty=max(0.0, 1.0 - best_sim),
                        reason="ledger",
                    ),
                )
            )
            continue

        if vault_lookup is not None:
            try:
                hits = vault_lookup(cand_text) or []
            except Exception:
                logger.exception("autoresearch dedup: vault_lookup failed")
                hits = []
            # Vault search uses Reciprocal Rank Fusion with k=60: max possible score
            # is 1/61 + 1/61 ≈ 0.033 (rank-1 in both backends), and a rank-1 hit in
            # one backend alone scores ≈ 0.016. So 0.02 catches "near top of at
            # least one backend" without requiring saturation in both.
            VAULT_RRF_DUP_THRESHOLD = 0.02
            for hit in hits[:3]:
                score = float(hit.get("score") or 0.0)
                if score >= VAULT_RRF_DUP_THRESHOLD:
                    out.append(
                        (
                            cand,
                            DedupVerdict(
                                is_duplicate=True,
                                duplicate_of=f"vault:{hit.get('id') or hit.get('title') or 'unknown'}",
                                novelty=0.0,
                                reason="vault",
                            ),
                        )
                    )
                    break
            else:
                out.append(
                    (
                        cand,
                        DedupVerdict(
                            is_duplicate=False,
                            duplicate_of=None,
                            novelty=max(0.0, 1.0 - best_sim),
                            reason="novel",
                        ),
                    )
                )
                continue
            continue

        out.append(
            (
                cand,
                DedupVerdict(
                    is_duplicate=False,
                    duplicate_of=None,
                    novelty=max(0.0, 1.0 - best_sim),
                    reason="novel",
                ),
            )
        )
    return out
