"""BM25 keyword search over the compiled knowledge vault markdown pages."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

VALID_CATEGORIES = ("sources", "entities", "concepts", "syntheses", "queries")

# BM25 tuning parameters
_K1 = 1.5
_B = 0.75
# Maximum characters to include in an excerpt snippet
_EXCERPT_CHARS = 400
# Context window around the first matched token (characters)
_EXCERPT_WINDOW = 200


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-style frontmatter from a markdown string.

    Returns (frontmatter_dict, body_text). Mirrors the parser in
    src.control_plane.vault_learning so we do not import that heavy module.
    """
    if not text.startswith("---\n"):
        return {}, text
    marker = "\n---\n"
    end = text.find(marker, 4)
    if end == -1:
        return {}, text
    block = text[4:end]
    body = text[end + len(marker) :]
    frontmatter: dict[str, Any] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        try:
            frontmatter[key] = json.loads(raw_value)
        except Exception:
            frontmatter[key] = raw_value.strip('"')
    return frontmatter, body.lstrip("\n")


def _tokenize(text: str) -> list[str]:
    """Lowercase word-token extraction."""
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def _token_freq(tokens: list[str]) -> dict[str, int]:
    freq: dict[str, int] = {}
    for tok in tokens:
        freq[tok] = freq.get(tok, 0) + 1
    return freq


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], avg_dl: float) -> float:
    """Compute a BM25 relevance score between query tokens and a document."""
    if not query_tokens or not doc_tokens:
        return 0.0
    dl = len(doc_tokens)
    freq = _token_freq(doc_tokens)
    score = 0.0
    for qt in set(query_tokens):
        tf = freq.get(qt, 0)
        if tf == 0:
            continue
        numerator = tf * (_K1 + 1)
        denominator = tf + _K1 * (1 - _B + _B * dl / max(avg_dl, 1))
        score += numerator / denominator
    return score


def _excerpt(body: str, query_tokens: list[str]) -> str:
    """Return a short excerpt from body centred on the first query token hit."""
    lower = body.lower()
    best_pos = len(body)
    for qt in query_tokens:
        pos = lower.find(qt)
        if pos != -1 and pos < best_pos:
            best_pos = pos

    if best_pos == len(body):
        # No token found — return the beginning
        snippet = body[:_EXCERPT_CHARS]
    else:
        start = max(0, best_pos - _EXCERPT_WINDOW)
        end = min(len(body), best_pos + _EXCERPT_WINDOW)
        snippet = ("..." if start > 0 else "") + body[start:end].strip() + ("..." if end < len(body) else "")

    # Collapse excessive whitespace
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet[:_EXCERPT_CHARS]


class VaultSearcher:
    """Keyword (BM25) search over a knowledge vault's ``02_compiled/`` directory.

    The searcher is designed to be instantiated once and reused. It reads pages
    from disk on every ``search()`` call so results always reflect the latest
    vault state without requiring a restart.
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root.expanduser().resolve()
        self.compiled_dir = self.vault_root / "02_compiled"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_pages(self, categories: list[str]) -> list[dict[str, Any]]:
        """Walk the requested compiled sub-directories and parse each .md file."""
        pages: list[dict[str, Any]] = []
        for cat in categories:
            cat_dir = self.compiled_dir / cat
            if not cat_dir.is_dir():
                continue
            for path in sorted(cat_dir.glob("*.md")):
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                frontmatter, body = _parse_frontmatter(raw)
                full_text = body
                # Boost title match by prepending title tokens into the search text
                title = str(frontmatter.get("title", path.stem))
                tags = frontmatter.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",") if t.strip()]
                pages.append(
                    {
                        "path": str(path),
                        "category": cat,
                        "title": title,
                        "tags": tags if isinstance(tags, list) else [],
                        "source_url": frontmatter.get("source_url") or frontmatter.get("url") or "",
                        "body": body,
                        # Searchable text: title repeated for weight + body
                        "text": f"{title} {title} {' '.join(tags)} {full_text}",
                    }
                )
        return pages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        categories: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search the vault and return ranked result dicts.

        Args:
            query: Natural-language search query.
            categories: Subset of vault categories to search. Defaults to all.
            limit: Maximum number of results to return.

        Returns:
            List of result dicts ordered by descending BM25 score. Each dict
            contains: title, category, score, excerpt, tags, source_url, path.
        """
        cats = [c for c in (categories or list(VALID_CATEGORIES)) if c in VALID_CATEGORIES]
        pages = self._load_pages(cats)
        if not pages:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        # Pre-tokenise all docs and compute average document length
        tokenised = [_tokenize(page["text"]) for page in pages]
        avg_dl = sum(len(t) for t in tokenised) / len(tokenised)

        scored: list[tuple[dict[str, Any], float]] = [
            (page, _bm25_score(query_tokens, doc_tokens, avg_dl))
            for page, doc_tokens in zip(pages, tokenised)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        results: list[dict[str, Any]] = []
        for page, score in scored[:limit]:
            if score == 0.0:
                break
            results.append(
                {
                    "title": page["title"],
                    "category": page["category"],
                    "score": round(score, 4),
                    "excerpt": _excerpt(page["body"], query_tokens),
                    "tags": page["tags"],
                    "source_url": page["source_url"],
                    "path": page["path"],
                }
            )
        return results
