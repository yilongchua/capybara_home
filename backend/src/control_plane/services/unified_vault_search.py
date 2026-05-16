from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.community.knowledge_vault_search.vector_index import VaultVectorIndex
from src.config import get_app_config
from src.control_plane.vault_text_utils import parse_frontmatter as _parse_frontmatter

VALID_CATEGORIES = ("sources", "entities", "concepts", "syntheses", "queries")

_K1 = 1.5
_B = 0.75
_EXCERPT_CHARS = 400
_EXCERPT_WINDOW = 200


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def _token_freq(tokens: list[str]) -> dict[str, int]:
    freq: dict[str, int] = {}
    for token in tokens:
        freq[token] = freq.get(token, 0) + 1
    return freq


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], avg_dl: float) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    dl = len(doc_tokens)
    freq = _token_freq(doc_tokens)
    score = 0.0
    for query_token in set(query_tokens):
        tf = freq.get(query_token, 0)
        if tf == 0:
            continue
        numerator = tf * (_K1 + 1)
        denominator = tf + _K1 * (1 - _B + _B * dl / max(avg_dl, 1))
        score += numerator / denominator
    return score


def _excerpt(body: str, query_tokens: list[str]) -> str:
    lower = body.lower()
    best_pos = len(body)
    for query_token in query_tokens:
        pos = lower.find(query_token)
        if pos != -1 and pos < best_pos:
            best_pos = pos

    if best_pos == len(body):
        snippet = body[:_EXCERPT_CHARS]
    else:
        start = max(0, best_pos - _EXCERPT_WINDOW)
        end = min(len(body), best_pos + _EXCERPT_WINDOW)
        snippet = ("..." if start > 0 else "") + body[start:end].strip() + ("..." if end < len(body) else "")

    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet[:_EXCERPT_CHARS]


@dataclass(slots=True)
class CompiledVaultPage:
    id: str
    title: str
    category: str
    kind: str
    path: str
    tags: list[str]
    source_url: str
    body: str
    text: str
    updated_at: str


class UnifiedVaultSearchService:
    """Shared lexical search over compiled vault pages."""

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root.expanduser().resolve()
        self.compiled_dir = self.vault_root / "02_compiled"
        try:
            vault_cfg = get_app_config().knowledge_vault
            self._vector_enabled = bool(vault_cfg.vector_search_enabled)
            self._rrf_k = max(1, int(vault_cfg.hybrid_rrf_k))
            self._vector_index = (
                VaultVectorIndex(
                    self.vault_root,
                    dimensions=int(vault_cfg.vector_dimensions),
                    chunk_chars=int(vault_cfg.vector_chunk_chars),
                    overlap_chars=int(vault_cfg.vector_chunk_overlap_chars),
                    backend=str(vault_cfg.vector_backend),
                    embedding_model=str(vault_cfg.vector_embedding_model),
                )
                if self._vector_enabled
                else None
            )
        except Exception:
            self._vector_enabled = False
            self._rrf_k = 60
            self._vector_index = None

    def _page_updated_at(self, path: Path, frontmatter: dict[str, Any]) -> str:
        updated_at = str(frontmatter.get("updated_at") or frontmatter.get("fetched_at") or "").strip()
        if updated_at:
            return updated_at
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()

    def _load_pages(self, categories: list[str]) -> list[CompiledVaultPage]:
        pages: list[CompiledVaultPage] = []
        for category in categories:
            category_dir = self.compiled_dir / category
            if not category_dir.is_dir():
                continue
            for path in sorted(category_dir.glob("*.md")):
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                frontmatter, body = _parse_frontmatter(raw)
                title = str(frontmatter.get("title", path.stem))
                tags = frontmatter.get("tags", [])
                if isinstance(tags, str):
                    tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
                pages.append(
                    CompiledVaultPage(
                        id=str(frontmatter.get("id") or frontmatter.get("source_id") or path.stem),
                        title=title,
                        category=category,
                        kind=category,
                        path=str(path),
                        tags=tags if isinstance(tags, list) else [],
                        source_url=str(frontmatter.get("source_url") or frontmatter.get("url") or ""),
                        body=body,
                        text=f"{title} {title} {' '.join(tags if isinstance(tags, list) else [])} {body}",
                        updated_at=self._page_updated_at(path, frontmatter),
                    )
                )
        return pages

    def _scored_results(
        self,
        query: str,
        *,
        categories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        cats = [category for category in (categories or list(VALID_CATEGORIES)) if category in VALID_CATEGORIES]
        pages = self._load_pages(cats)
        if not pages:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        tokenized = [_tokenize(page.text) for page in pages]
        avg_dl = sum(len(tokens) for tokens in tokenized) / len(tokenized)
        scored: list[tuple[CompiledVaultPage, float]] = [
            (page, _bm25_score(query_tokens, doc_tokens, avg_dl))
            for page, doc_tokens in zip(pages, tokenized)
        ]
        scored = [(page, score) for page, score in scored if score > 0.0]
        scored.sort(key=lambda item: item[1], reverse=True)

        results: list[dict[str, Any]] = []
        for rank, (page, score) in enumerate(scored, start=1):
            excerpt = _excerpt(page.body, query_tokens)
            results.append(
                {
                    "rank": rank,
                    "score": round(score, 4),
                    "id": page.id,
                    "kind": page.kind,
                    "category": page.category,
                    "title": page.title,
                    "path": page.path,
                    "snippet": excerpt,
                    "excerpt": excerpt,
                    "tags": page.tags,
                    "source_url": page.source_url,
                    "updated_at": page.updated_at,
                    "lexical_rank": rank,
                }
            )
        if not self._vector_index:
            return results

        vector_hits = self._vector_index.search(query, categories=cats, limit=max(20, len(results) or 10))
        vector_rank_by_path = {str(item.get("path") or ""): rank for rank, item in enumerate(vector_hits, start=1)}
        vector_by_path = {str(item.get("path") or ""): item for item in vector_hits}

        merged: dict[str, dict[str, Any]] = {str(item["path"]): dict(item) for item in results}
        for path, vector_item in vector_by_path.items():
            if path in merged:
                merged[path]["vector_rank"] = vector_rank_by_path[path]
                merged[path]["vector_score"] = float(vector_item.get("score") or 0.0)
                continue
            merged[path] = {
                "rank": 0,
                "score": 0.0,
                "id": vector_item.get("page_id"),
                "kind": vector_item.get("category"),
                "category": vector_item.get("category"),
                "title": vector_item.get("title"),
                "path": vector_item.get("path"),
                "snippet": _excerpt(str(vector_item.get("text") or ""), query_tokens),
                "excerpt": _excerpt(str(vector_item.get("text") or ""), query_tokens),
                "tags": [],
                "source_url": "",
                "updated_at": vector_item.get("updated_at"),
                "vector_rank": vector_rank_by_path[path],
                "vector_score": float(vector_item.get("score") or 0.0),
            }

        fused: list[dict[str, Any]] = []
        for item in merged.values():
            lexical_rank = int(item.get("lexical_rank") or 0)
            vector_rank = int(item.get("vector_rank") or 0)
            fused_score = 0.0
            if lexical_rank > 0:
                fused_score += 1.0 / (self._rrf_k + lexical_rank)
            if vector_rank > 0:
                fused_score += 1.0 / (self._rrf_k + vector_rank)
            item["score"] = round(fused_score or float(item.get("score") or 0.0), 6)
            fused.append(item)

        fused.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        for rank, item in enumerate(fused, start=1):
            item["rank"] = rank
        return fused

    def search(
        self,
        query: str,
        *,
        categories: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        results = self._scored_results(query, categories=categories)
        return results[: max(1, int(limit))]

    def search_payload(
        self,
        query: str,
        *,
        categories: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        all_results = self._scored_results(query, categories=categories)
        results = all_results[: max(1, int(limit))]
        return {
            "query": query,
            "total": len(all_results),
            "items": [
                {
                    "rank": item["rank"],
                    "score": item["score"],
                    "id": item["id"],
                    "kind": item["kind"],
                    "title": item["title"],
                    "path": item["path"],
                    "snippet": item["snippet"],
                    "updated_at": item["updated_at"],
                }
                for item in results
            ],
        }

    def vector_status(self) -> dict[str, Any]:
        if not self._vector_index:
            return {"enabled": False, "chunk_count": 0, "built_at": None}
        return self._vector_index.status()


class VaultSearcher(UnifiedVaultSearchService):
    """Backwards-compatible alias for the shared vault search service."""
