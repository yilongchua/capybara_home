"""Durable thread-scoped queue for steering intents.

Steering delivery must work even while LangGraph state updates are locked by an
active run. This store lives outside thread state and supports exactly-once
consumption semantics via atomic claim+mark-consumed transactions.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal, TypedDict

from src.config.paths import get_paths


class SteeringQueuedIntent(TypedDict):
    intent_id: str
    message: str
    created_at: str


class SteeringEnqueueResult(TypedDict):
    status: Literal["accepted", "duplicate", "conflict"]
    intent: SteeringQueuedIntent


_INIT_LOCK = Lock()
_INITIALIZED = False


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _db_path() -> Path:
    root = get_paths().base_dir / "steering"
    root.mkdir(parents=True, exist_ok=True)
    return root / "steering_queue.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _ensure_db() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS steering_intents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    queued_at TEXT NOT NULL,
                    consumed_at TEXT,
                    UNIQUE(thread_id, intent_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_steering_queue_pending
                ON steering_intents(thread_id, consumed_at, queued_at, id)
                """
            )
        _INITIALIZED = True


def enqueue_steering_intent(*, thread_id: str, intent_id: str, message: str, created_at: str | None = None) -> SteeringEnqueueResult:
    """Enqueue a steering intent with thread+intent idempotency."""
    _ensure_db()
    normalized_thread_id = str(thread_id or "").strip()
    normalized_intent_id = str(intent_id or "").strip()
    normalized_message = str(message or "").strip()
    if not normalized_thread_id or not normalized_intent_id or not normalized_message:
        raise ValueError("thread_id, intent_id and message must all be non-empty.")

    created = created_at.strip() if isinstance(created_at, str) and created_at.strip() else _utc_now_iso()
    queued = _utc_now_iso()
    payload: SteeringQueuedIntent = {
        "intent_id": normalized_intent_id,
        "message": normalized_message,
        "created_at": created,
    }

    with _connect() as conn:
        try:
            conn.execute(
                """
                INSERT INTO steering_intents(thread_id, intent_id, message, created_at, queued_at, consumed_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (normalized_thread_id, normalized_intent_id, normalized_message, created, queued),
            )
            return {
                "status": "accepted",
                "intent": payload,
            }
        except sqlite3.IntegrityError:
            row = conn.execute(
                """
                SELECT message, created_at
                FROM steering_intents
                WHERE thread_id = ? AND intent_id = ?
                LIMIT 1
                """,
                (normalized_thread_id, normalized_intent_id),
            ).fetchone()
            if row is None:
                raise
            existing_message = str(row["message"] or "").strip()
            existing_created_at = str(row["created_at"] or created)
            status: Literal["duplicate", "conflict"] = "duplicate" if existing_message == normalized_message else "conflict"
            return {
                "status": status,
                "intent": {
                    "intent_id": normalized_intent_id,
                    "message": existing_message,
                    "created_at": existing_created_at,
                },
            }


def claim_next_steering_intent(thread_id: str) -> SteeringQueuedIntent | None:
    """Atomically claim the next unconsumed intent for this thread.

    Returns exactly one intent and marks it consumed in the same transaction.
    """
    _ensure_db()
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return None

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT id, intent_id, message, created_at
            FROM steering_intents
            WHERE thread_id = ? AND consumed_at IS NULL
            ORDER BY queued_at ASC, id ASC
            LIMIT 1
            """,
            (normalized_thread_id,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None

        consumed_at = _utc_now_iso()
        cursor = conn.execute(
            """
            UPDATE steering_intents
            SET consumed_at = ?
            WHERE id = ? AND consumed_at IS NULL
            """,
            (consumed_at, int(row["id"])),
        )
        if cursor.rowcount != 1:
            conn.execute("ROLLBACK")
            return None

        conn.execute("COMMIT")
        return {
            "intent_id": str(row["intent_id"]),
            "message": str(row["message"]),
            "created_at": str(row["created_at"]),
        }


def list_pending_steering_intents(thread_id: str) -> list[SteeringQueuedIntent]:
    """Return pending (unconsumed) intents for diagnostics/tests."""
    _ensure_db()
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT intent_id, message, created_at
            FROM steering_intents
            WHERE thread_id = ? AND consumed_at IS NULL
            ORDER BY queued_at ASC, id ASC
            """,
            (normalized_thread_id,),
        ).fetchall()
    return [
        {
            "intent_id": str(row["intent_id"]),
            "message": str(row["message"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def reset_steering_queue_store_for_tests() -> None:
    """Reset singleton init state so tests can isolate DB state."""
    global _INITIALIZED
    _INITIALIZED = False
