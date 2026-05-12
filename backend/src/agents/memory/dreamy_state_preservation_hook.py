"""Dreamy-mode state preservation before summarization."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.paths import get_paths

logger = logging.getLogger(__name__)


def _utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resumption_file(thread_id: str) -> Path:
    return get_paths().thread_dir(thread_id) / "dreamy_resumption.json"


def dreamy_state_preservation_hook(event) -> None:
    """Persist Dreamy resumption-critical state before compaction removes context."""
    context = getattr(event.runtime, "context", None) or {}
    if not isinstance(context, dict):
        return
    if not context.get("dreamy_mode"):
        return
    if not event.thread_id:
        return
    state = event.state if isinstance(getattr(event, "state", None), dict) else {}

    # Preserve dreamy anchor snippets from the to-be-summarized window.
    anchors: list[dict[str, Any]] = []
    for msg in list(event.messages_to_summarize):
        if getattr(msg, "type", None) != "human":
            continue
        if getattr(msg, "name", None) != "dreamy_anchor":
            continue
        anchors.append(
            {
                "id": getattr(msg, "id", None),
                "content": str(getattr(msg, "content", "") or ""),
            }
        )

    payload = {
        "ts": _utc_now_iso_z(),
        "dreamy_intent": state.get("dreamy_intent"),
        "task_memory": state.get("task_memory"),
        "dreamy_anchor_messages": anchors[-5:],
    }
    try:
        path = _resumption_file(event.thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        append_runtime_event(
            event.runtime,
            {
                "source": "dreamy_state_preservation",
                "event": "dreamy_state_preserved",
                "thread_id": event.thread_id,
                "path": str(path),
                "anchors": len(anchors),
            },
        )
    except Exception:
        logger.exception("Failed to persist dreamy resumption state for thread %s", event.thread_id)


def load_dreamy_resumption(thread_id: str) -> dict[str, Any] | None:
    """Load preserved dreamy resumption state."""
    path = _resumption_file(thread_id)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

