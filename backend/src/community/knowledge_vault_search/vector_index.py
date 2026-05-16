from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from src.config import get_app_config
from src.control_plane.vault_text_utils import parse_frontmatter as _parse_frontmatter

_DEFAULT_WINDOW = 1200
_DEFAULT_OVERLAP = 200


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm <= 0.0:
        return vec
    return vec / norm


def _hash_embed_text(text: str, *, dimensions: int) -> np.ndarray:
    vector = np.zeros(dimensions, dtype=np.float32)
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        slot = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vector[slot] += sign * weight
    return _normalize(vector)


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        *,
        model_name: str | None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._timeout_seconds = float(timeout_seconds)
        self._configured_model = str(model_name or "").strip() or None

    def _resolve_client_config(self) -> tuple[str | None, str | None, str | None]:
        try:
            app_config = get_app_config()
        except Exception:
            return None, None, None
        if not app_config.models:
            return None, None, None

        preferred_model_cfg = None
        if self._configured_model:
            preferred_model_cfg = app_config.get_model_config(self._configured_model)

        model_cfg = preferred_model_cfg or app_config.models[0]
        model_dump = model_cfg.model_dump(mode="python")
        base_url = str(model_dump.get("base_url") or "").strip()
        api_key = str(model_dump.get("api_key") or "").strip()
        model_name = str(self._configured_model or model_dump.get("model") or model_dump.get("name") or "").strip()
        if not base_url or not model_name:
            return None, None, None
        return base_url.rstrip("/"), api_key or None, model_name

    def embed_batch(self, texts: list[str]) -> list[np.ndarray] | None:
        if not texts:
            return []
        base_url, api_key, model_name = self._resolve_client_config()
        if not base_url or not model_name:
            return None
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    f"{base_url}/embeddings",
                    headers=headers,
                    json={
                        "model": model_name,
                        "input": texts,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return None

        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(data, list) or len(data) != len(texts):
            return None
        vectors: list[np.ndarray] = []
        for item in data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list) or not embedding:
                return None
            try:
                vector = np.array(embedding, dtype=np.float32)
            except Exception:
                return None
            vectors.append(_normalize(vector))
        return vectors

    def embed_one(self, text: str) -> np.ndarray | None:
        batched = self.embed_batch([text])
        if not batched:
            return None
        return batched[0]


class VaultVectorIndex:
    def __init__(
        self,
        vault_root: Path,
        *,
        dimensions: int = 256,
        chunk_chars: int = _DEFAULT_WINDOW,
        overlap_chars: int = _DEFAULT_OVERLAP,
        backend: str = "openai_compatible",
        embedding_model: str = "",
    ) -> None:
        self.vault_root = vault_root.expanduser().resolve()
        self.compiled_dir = self.vault_root / "02_compiled"
        self.state_dir = self.vault_root / ".vault_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.state_dir / "vector_index.json"
        self.matrix_path = self.state_dir / "vector_index.npz"
        self.dimensions = max(32, int(dimensions))
        self.chunk_chars = max(200, int(chunk_chars))
        self.overlap_chars = max(0, int(overlap_chars))
        self.backend = backend
        self.embedding_model = embedding_model.strip()
        self._embedder = OpenAICompatibleEmbedder(model_name=self.embedding_model)

    def _split_chunks(self, text: str) -> list[str]:
        normalized = text.strip()
        if not normalized:
            return []
        sections = [section.strip() for section in re.split(r"\n(?=#)", normalized) if section.strip()]
        if not sections:
            sections = [normalized]

        chunks: list[str] = []
        current = ""
        for section in sections:
            candidate = f"{current}\n\n{section}".strip() if current else section
            if len(candidate) <= self.chunk_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(section) <= self.chunk_chars:
                current = section
                continue
            start = 0
            step = max(1, self.chunk_chars - self.overlap_chars)
            while start < len(section):
                chunks.append(section[start : start + self.chunk_chars].strip())
                start += step
            current = ""
        if current:
            chunks.append(current)
        return [chunk for chunk in chunks if chunk]

    def _iter_pages(self) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        for category_dir in sorted(self.compiled_dir.iterdir() if self.compiled_dir.exists() else []):
            if not category_dir.is_dir():
                continue
            category = category_dir.name
            for path in sorted(category_dir.glob("*.md")):
                if path.name == "index.md":
                    continue
                raw = path.read_text(encoding="utf-8", errors="replace")
                frontmatter, body = _parse_frontmatter(raw)
                title = str(frontmatter.get("title") or path.stem.replace("-", " ").title())
                page_id = str(frontmatter.get("id") or frontmatter.get("source_id") or path.stem)
                updated_at = str(frontmatter.get("updated_at") or frontmatter.get("fetched_at") or datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat())
                pages.append(
                    {
                        "page_id": page_id,
                        "title": title,
                        "category": category,
                        "path": str(path),
                        "updated_at": updated_at,
                        "body": body,
                    }
                )
        return pages

    def _build_chunks(self) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for page in self._iter_pages():
            seed = f"# {page['title']}\n\n{page['body']}"
            for index, chunk_text in enumerate(self._split_chunks(seed)):
                chunks.append(
                    {
                        "chunk_id": f"{page['category']}:{Path(page['path']).stem}:{index}",
                        "page_id": page["page_id"],
                        "title": page["title"],
                        "category": page["category"],
                        "path": page["path"],
                        "text": chunk_text,
                        "updated_at": page["updated_at"],
                    }
                )
        return chunks

    def _embed_chunks(self, chunks: list[dict[str, Any]]) -> tuple[np.ndarray, str]:
        if not chunks:
            return np.empty((0, self.dimensions), dtype=np.float32), "none"
        texts = [str(item["text"]) for item in chunks]
        if self.backend == "openai_compatible":
            vectors = self._embedder.embed_batch(texts)
            if vectors and len(vectors) == len(chunks):
                matrix = np.vstack([_normalize(v.astype(np.float32)) for v in vectors])
                return matrix, "openai_compatible"
        matrix = np.vstack([_hash_embed_text(text, dimensions=self.dimensions) for text in texts]).astype(np.float32)
        return matrix, "hash_fallback"

    def build(self) -> dict[str, Any]:
        chunks = self._build_chunks()
        matrix, effective_backend = self._embed_chunks(chunks)
        built_at = datetime.now(UTC).isoformat()

        if matrix.size > 0:
            np.savez_compressed(self.matrix_path, embeddings=matrix)
        else:
            if self.matrix_path.exists():
                self.matrix_path.unlink()

        payload = {
            "backend": self.backend,
            "effective_backend": effective_backend,
            "embedding_model": self.embedding_model,
            "dimensions": int(matrix.shape[1]) if matrix.ndim == 2 and matrix.shape[0] > 0 else self.dimensions,
            "chunk_chars": self.chunk_chars,
            "overlap_chars": self.overlap_chars,
            "built_at": built_at,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }
        self.metadata_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    def load(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return self.build()
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return self.build()
        if int(payload.get("chunk_chars") or 0) != self.chunk_chars or int(payload.get("overlap_chars") or 0) != self.overlap_chars:
            return self.build()
        return payload

    def _load_matrix(self, expected_count: int) -> np.ndarray:
        if not self.matrix_path.exists():
            self.build()
        if not self.matrix_path.exists():
            return np.empty((0, self.dimensions), dtype=np.float32)
        try:
            with np.load(self.matrix_path) as data:
                matrix = np.array(data["embeddings"], dtype=np.float32)
        except Exception:
            self.build()
            with np.load(self.matrix_path) as data:
                matrix = np.array(data["embeddings"], dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != expected_count:
            rebuilt = self.build()
            chunk_count = int(rebuilt.get("chunk_count") or 0)
            if not self.matrix_path.exists() or chunk_count == 0:
                return np.empty((0, self.dimensions), dtype=np.float32)
            with np.load(self.matrix_path) as data:
                matrix = np.array(data["embeddings"], dtype=np.float32)
        return matrix

    def status(self) -> dict[str, Any]:
        payload = self.load()
        return {
            "enabled": True,
            "backend": str(payload.get("backend") or self.backend),
            "effective_backend": str(payload.get("effective_backend") or self.backend),
            "embedding_model": str(payload.get("embedding_model") or self.embedding_model or ""),
            "built_at": payload.get("built_at"),
            "chunk_count": int(payload.get("chunk_count") or 0),
            "dimensions": int(payload.get("dimensions") or self.dimensions),
        }

    def search(self, query: str, *, categories: list[str] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        payload = self.load()
        raw_chunks = payload.get("chunks", [])
        if not isinstance(raw_chunks, list) or not raw_chunks:
            return []
        matrix = self._load_matrix(len(raw_chunks))
        if matrix.shape[0] == 0:
            return []

        query_vector: np.ndarray | None = None
        if str(payload.get("effective_backend") or "").strip() == "openai_compatible":
            query_vector = self._embedder.embed_one(query)
        if query_vector is None:
            dims = matrix.shape[1] if matrix.ndim == 2 and matrix.shape[1] > 0 else self.dimensions
            query_vector = _hash_embed_text(query, dimensions=dims)
        query_vector = _normalize(query_vector.astype(np.float32))

        scores = matrix @ query_vector
        allowed_categories = {str(item) for item in (categories or []) if str(item).strip()}
        scored: list[dict[str, Any]] = []
        for idx, chunk in enumerate(raw_chunks):
            category = str(chunk.get("category") or "")
            if allowed_categories and category not in allowed_categories:
                continue
            score = float(scores[idx])
            if not math.isfinite(score):
                continue
            scored.append(
                {
                    "chunk_id": str(chunk.get("chunk_id") or ""),
                    "page_id": str(chunk.get("page_id") or ""),
                    "title": str(chunk.get("title") or ""),
                    "category": category,
                    "path": str(chunk.get("path") or ""),
                    "text": str(chunk.get("text") or ""),
                    "updated_at": str(chunk.get("updated_at") or ""),
                    "score": round(score, 6),
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)

        deduped: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for item in scored:
            if item["score"] <= 0:
                continue
            path = item["path"]
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            deduped.append(item)
            if len(deduped) >= max(1, int(limit)):
                break
        return deduped
