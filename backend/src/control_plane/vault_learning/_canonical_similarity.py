"""Pure similarity signals for canonical entity/concept merging.

Three signals, composed by `propose_merges`:
- Lexical: normalized-form overlap (token-set Jaccard + character-bigram Jaccard).
- Abbreviation: initialism / prefix match for short labels.
- Co-occurrence: Jaccard over source sets and neighbor sets.

Pure functions — no vault, no IO — so they can be tested in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "ltd", "limited", "llc", "llp", "plc",
    "corp", "corporation", "co", "company", "gmbh", "ag", "sa",
    "pte", "sdn", "bhd", "pvt", "private", "holdings", "group",
}

_STOPWORDS = {"the", "and", "of", "for", "in", "to", "a", "an", "&"}


def normalize_label(label: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\s]+", " ", str(label or "")).lower()
    tokens = [t for t in s.split() if t and t not in _STOPWORDS and t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def normalized_compact(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(label or "").lower())


def initialism_of(label: str) -> str:
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", str(label or "")) if t and t.lower() not in _STOPWORDS]
    if len(tokens) < 2:
        return ""
    return "".join(t[0] for t in tokens).lower()


def is_abbreviation_candidate(label: str) -> bool:
    raw = str(label or "")
    letters_only = re.sub(r"[^A-Za-z]", "", raw)
    if not letters_only:
        return False
    if 2 <= len(letters_only) <= 5 and (letters_only.isupper() or raw.isupper()):
        return True
    compact = re.sub(r"[^A-Za-z0-9]", "", raw)
    if 2 <= len(letters_only) <= 4 and len(compact) <= 5:
        return True
    return False


def is_abbreviation_of(short_label: str, long_label: str) -> bool:
    short = re.sub(r"[^A-Za-z]", "", str(short_label or "")).lower()
    if not short:
        return False
    initialism = initialism_of(long_label)
    if initialism and short == initialism:
        return True
    long_compact = normalized_compact(long_label)
    if not long_compact or len(short) < 2 or len(short) > 4:
        return False
    if long_compact.startswith(short):
        return True
    # ISO-style codes like "SG" / "sgp" → "Singapore": same first letter
    # plus a subsequence match against the long form's letters.
    if short[0] != long_compact[0]:
        return False
    cursor = 0
    for char in short:
        cursor = long_compact.find(char, cursor)
        if cursor == -1:
            return False
        cursor += 1
    return True


def lexical_similarity(label_a: str, label_b: str) -> float:
    a = normalize_label(label_a)
    b = normalize_label(label_b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_compact = normalized_compact(a)
    b_compact = normalized_compact(b)
    if a_compact and a_compact == b_compact:
        return 0.95
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if tokens_a and tokens_b:
        token_jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    else:
        token_jaccard = 0.0

    def _bigrams(s: str) -> set[str]:
        if len(s) < 2:
            return {s} if s else set()
        return {s[i : i + 2] for i in range(len(s) - 1)}

    bg_a = _bigrams(a_compact)
    bg_b = _bigrams(b_compact)
    bg_jaccard = len(bg_a & bg_b) / len(bg_a | bg_b) if (bg_a and bg_b) else 0.0
    return max(token_jaccard, bg_jaccard)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


@dataclass
class SurfaceForm:
    slug: str
    label: str
    kind: str
    sources: set[str] = field(default_factory=set)
    neighbors: set[str] = field(default_factory=set)
    domain_counts: dict[str, int] = field(default_factory=dict)

    @property
    def degree(self) -> int:
        return len(self.sources)

    @property
    def dominant_domain(self) -> str | None:
        if not self.domain_counts:
            return None
        best_tag, best_count = max(self.domain_counts.items(), key=lambda kv: (kv[1], kv[0]))
        total = sum(self.domain_counts.values())
        if total == 0 or best_count / total < 0.5:
            return None
        return best_tag


@dataclass
class MergeCandidate:
    canonical_slug: str
    alias_slug: str
    kind: str
    canonical_label: str
    alias_label: str
    signals: dict[str, Any]
    confidence: float
    action: str
    domain_hint: str | None
    evidence_sources: list[str]
    reason: str


@dataclass(frozen=True)
class MergeThresholds:
    """Tunable thresholds for the auto/review/skip decision matrix.

    Defaults match the original hardcoded values; consumers should pass an
    instance constructed from ``app_config.knowledge_vault.canonical`` so
    the user-visible settings tab can override them at runtime.
    """

    auto_lexical_strong: float = 0.95
    auto_lexical_high: float = 0.9
    auto_lexical_high_cooc: float = 0.2
    auto_abbreviation_cooc: float = 0.3
    auto_lexical_mid: float = 0.75
    auto_lexical_mid_cooc: float = 0.5
    review_abbreviation_cooc: float = 0.2
    review_cooc_strong: float = 0.6
    review_lexical: float = 0.7
    review_abbreviation_alone: bool = True


DEFAULT_THRESHOLDS = MergeThresholds()


def _pick_canonical(a: SurfaceForm, b: SurfaceForm) -> tuple[SurfaceForm, SurfaceForm]:
    if a.degree != b.degree:
        return (a, b) if a.degree > b.degree else (b, a)
    if len(a.label) != len(b.label):
        return (a, b) if len(a.label) > len(b.label) else (b, a)
    return (a, b) if a.slug < b.slug else (b, a)


def _confidence_and_action(
    *,
    lexical: float,
    abbreviation: bool,
    cooccurrence: float,
    same_source: bool,
    thresholds: MergeThresholds,
) -> tuple[float, str, str]:
    if lexical >= thresholds.auto_lexical_strong:
        return (min(0.99, lexical), "auto", f"lexical:{lexical:.2f}")
    if lexical >= thresholds.auto_lexical_high and cooccurrence >= thresholds.auto_lexical_high_cooc:
        return (min(0.99, lexical + 0.05), "auto", f"lexical:{lexical:.2f}+cooccurrence:{cooccurrence:.2f}")
    if abbreviation and same_source and cooccurrence >= thresholds.auto_abbreviation_cooc:
        return (0.9, "auto", f"abbreviation+same_source+cooccurrence:{cooccurrence:.2f}")
    if lexical >= thresholds.auto_lexical_mid and cooccurrence >= thresholds.auto_lexical_mid_cooc:
        return (0.85, "auto", f"lexical:{lexical:.2f}+cooccurrence:{cooccurrence:.2f}")
    if abbreviation and cooccurrence >= thresholds.review_abbreviation_cooc:
        return (0.65, "review", f"abbreviation+cooccurrence:{cooccurrence:.2f}")
    if cooccurrence >= thresholds.review_cooc_strong:
        return (0.55, "review", f"cooccurrence:{cooccurrence:.2f}")
    if lexical >= thresholds.review_lexical:
        return (0.55, "review", f"lexical:{lexical:.2f}")
    if abbreviation and thresholds.review_abbreviation_alone:
        return (0.4, "review", "abbreviation")
    return (0.0, "skip", "")


def propose_merges(
    surfaces: dict[str, SurfaceForm],
    *,
    thresholds: MergeThresholds | None = None,
) -> list[MergeCandidate]:
    thresholds = thresholds or DEFAULT_THRESHOLDS
    candidates: list[MergeCandidate] = []
    items = list(surfaces.values())
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            if a.kind != b.kind or a.slug == b.slug:
                continue
            # Per-domain disambiguation: reject pairs whose dominant domains conflict.
            domain_a = a.dominant_domain
            domain_b = b.dominant_domain
            if domain_a and domain_b and domain_a != domain_b:
                continue
            lexical = lexical_similarity(a.label, b.label)
            abbreviation = False
            if is_abbreviation_candidate(a.label) and is_abbreviation_of(a.label, b.label):
                abbreviation = True
            elif is_abbreviation_candidate(b.label) and is_abbreviation_of(b.label, a.label):
                abbreviation = True
            source_jaccard = jaccard(a.sources, b.sources)
            neighbor_jaccard = jaccard(a.neighbors, b.neighbors)
            cooccurrence = max(source_jaccard, neighbor_jaccard)
            same_source = bool(a.sources & b.sources)
            if lexical < 0.5 and not abbreviation and cooccurrence < 0.5:
                continue
            confidence, action, reason = _confidence_and_action(
                lexical=lexical,
                abbreviation=abbreviation,
                cooccurrence=cooccurrence,
                same_source=same_source,
                thresholds=thresholds,
            )
            if action == "skip":
                continue
            canonical, alias = _pick_canonical(a, b)
            evidence = sorted(canonical.sources | alias.sources)[:20]
            domain_hint = canonical.dominant_domain or alias.dominant_domain
            candidates.append(
                MergeCandidate(
                    canonical_slug=canonical.slug,
                    alias_slug=alias.slug,
                    kind=canonical.kind,
                    canonical_label=canonical.label,
                    alias_label=alias.label,
                    signals={
                        "lexical": round(lexical, 3),
                        "abbreviation": abbreviation,
                        "cooccurrence": round(cooccurrence, 3),
                        "source_jaccard": round(source_jaccard, 3),
                        "neighbor_jaccard": round(neighbor_jaccard, 3),
                        "same_source": same_source,
                    },
                    confidence=round(confidence, 3),
                    action=action,
                    domain_hint=domain_hint,
                    evidence_sources=evidence,
                    reason=reason,
                )
            )
    candidates.sort(key=lambda c: (-c.confidence, c.canonical_slug, c.alias_slug))
    return candidates


__all__ = [
    "SurfaceForm",
    "MergeCandidate",
    "MergeThresholds",
    "DEFAULT_THRESHOLDS",
    "normalize_label",
    "normalized_compact",
    "initialism_of",
    "is_abbreviation_candidate",
    "is_abbreviation_of",
    "lexical_similarity",
    "jaccard",
    "propose_merges",
]
