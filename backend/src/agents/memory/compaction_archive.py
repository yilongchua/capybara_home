"""Compaction archive persistence helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config.paths import get_paths


def _utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _compaction_log_path(thread_id: str) -> Path:
    return get_paths().thread_dir(thread_id) / "compaction_log.jsonl"


def append_compaction_entry(thread_id: str, payload: dict[str, Any]) -> Path:
    """Append one compaction event entry to the thread archive."""
    path = _compaction_log_path(thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": _utc_now_iso_z(), **payload}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_compaction_entries(thread_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Read recent compaction archive entries for a thread."""
    path = _compaction_log_path(thread_id)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-max(1, limit) :]

