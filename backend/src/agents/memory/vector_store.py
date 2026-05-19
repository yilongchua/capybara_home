"""Local-first memory retrieval/index utilities backed by SQLite.

This module keeps a lightweight index of memory facts that supports scoped
retrieval (`global` + `workspace`) without requiring any external service.
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config.memory_config import get_memory_config
from src.config.paths import get_paths

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


def _utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_z(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize_scope_id(scope_id: str | None) -> str:
    return str(scope_id or "_default")


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _lexical_score(query: str, content: str) -> float:
    q = _tokenize(query)
    if not q:
        return 0.0
    c = _tokenize(content)
    if not c:
        return 0.0
    overlap = len(q & c) / max(1, len(q))
    if query.strip() and query.lower() in (content or "").lower():
        overlap += 0.25
    return min(1.0, overlap)


def _decay_multiplier(created_at: str | None, *, half_life_days: int, enabled: bool) -> float:
    if not enabled:
        return 1.0
    created = _parse_iso_z(created_at)
    if created is None:
        return 1.0
    age_days = max(0.0, (datetime.now(UTC) - created).total_seconds() / 86400.0)
    return math.exp(-age_days / max(1.0, float(half_life_days)))


class MemoryVectorStore:
    """SQLite-backed scoped memory index."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = get_paths().base_dir / "memory" / "memory.db"
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_facts (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT,
                    updated_at TEXT,
                    source TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_facts_scope
                ON memory_facts(scope, scope_id)
                """
            )

    def upsert_facts(self, *, scope: str, scope_id: str | None, facts: list[dict[str, Any]]) -> None:
        sid = _normalize_scope_id(scope_id)
        now = _utc_now_iso_z()
        rows: list[tuple[Any, ...]] = []
        for fact in facts:
            fid = str(fact.get("id") or "").strip()
            if not fid:
                continue
            rows.append(
                (
                    fid,
                    scope,
                    sid,
                    str(fact.get("content") or ""),
                    str(fact.get("category") or "context"),
                    float(fact.get("confidence") or 0.5),
                    str(fact.get("createdAt") or now),
                    now,
                    str(fact.get("source") or ""),
                )
            )
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO memory_facts(id, scope, scope_id, content, category, confidence, created_at, updated_at, source)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    scope=excluded.scope,
                    scope_id=excluded.scope_id,
                    content=excluded.content,
                    category=excluded.category,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at,
                    source=excluded.source
                """,
                rows,
            )

    def delete_fact_ids(self, *, scope: str, scope_id: str | None, fact_ids: list[str]) -> None:
        ids = [str(fid).strip() for fid in fact_ids if str(fid).strip()]
        if not ids:
            return
        sid = _normalize_scope_id(scope_id)
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM memory_facts WHERE scope = ? AND scope_id = ? AND id IN ({placeholders})",
                [scope, sid, *ids],
            )

    def delete_scope(self, *, scope: str, scope_id: str | None) -> None:
        sid = _normalize_scope_id(scope_id)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM memory_facts WHERE scope = ? AND scope_id = ?",
                [scope, sid],
            )

    def query(
        self,
        *,
        query: str,
        scopes: list[tuple[str, str | None]],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if not scopes:
            return []
        cfg = get_memory_config()
        clauses: list[str] = []
        args: list[Any] = []
        for scope, scope_id in scopes:
            clauses.append("(scope = ? AND scope_id = ?)")
            args.extend([scope, _normalize_scope_id(scope_id)])
        where_clause = " OR ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, scope, scope_id, content, category, confidence, created_at, source
                FROM memory_facts
                WHERE {where_clause}
                """,
                args,
            ).fetchall()
        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            content = str(row["content"] or "")
            lexical = _lexical_score(query, content)
            decay = _decay_multiplier(
                str(row["created_at"] or ""),
                half_life_days=cfg.decay_half_life_days,
                enabled=cfg.decay_enabled,
            )
            confidence = float(row["confidence"] or 0.5)
            score = (0.65 * lexical) + (0.35 * confidence * decay)
            payload = {
                "id": row["id"],
                "scope": row["scope"],
                "scope_id": row["scope_id"],
                "content": content,
                "category": row["category"],
                "confidence": confidence,
                "createdAt": row["created_at"],
                "source": row["source"],
                "score": round(score, 6),
                "decay": round(decay, 6),
            }
            ranked.append((score, payload))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in ranked[: max(1, top_k)]]


_VECTOR_STORE: MemoryVectorStore | None = None


def get_memory_vector_store() -> MemoryVectorStore:
    global _VECTOR_STORE
    if _VECTOR_STORE is None:
        _VECTOR_STORE = MemoryVectorStore()
    return _VECTOR_STORE

