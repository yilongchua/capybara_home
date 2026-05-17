"""Prompt logging callback for LLM pre-call tracing.

Writes every chat model input prompt to timestamped files for prompt tuning.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage

from src.config.paths import get_paths

_TRUE_VALUES = {"1", "true", "yes", "on"}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _is_enabled() -> bool:
    raw = os.getenv("CAPYBARA_PROMPT_LOGGING_ENABLED", "1").strip().lower()
    return raw in _TRUE_VALUES


def _safe_name(value: str) -> str:
    normalized = _SAFE_NAME_RE.sub("_", value.strip())
    return normalized.strip("_.") or "unknown"


def _detect_actor(serialized: dict[str, Any], kwargs: dict[str, Any]) -> str:
    name = str((serialized or {}).get("name") or "").lower()
    tags = [str(tag).lower() for tag in (kwargs.get("tags") or []) if tag is not None]
    haystack = " ".join([name, *tags])
    if "tool" in haystack:
        return "tool"
    if "subagent" in haystack:
        return "sub_agent"
    return "lead_agent"


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _messages_to_text(messages: list[BaseMessage]) -> str:
    lines: list[str] = []
    for idx, msg in enumerate(messages, start=1):
        role = getattr(msg, "type", msg.__class__.__name__).lower()
        content = _extract_text(getattr(msg, "content", ""))
        lines.append(f"[{idx}] role={role}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_output_dir(thread_id: str | None) -> Path:
    default_virtual = Path("/mnt/user-data/workspace/.prompts")
    override = os.getenv("CAPYBARA_PROMPT_LOG_DIR", "").strip()
    if override:
        return Path(override)
    if thread_id:
        return get_paths().sandbox_work_dir(thread_id) / ".prompts"
    return default_virtual


class PromptLoggingCallback(BaseCallbackHandler):
    """Logs every chat model prompt to a text file before model invocation."""

    def on_chat_model_start(self, serialized: dict, messages: list, **kwargs: Any) -> None:
        if not _is_enabled():
            return
        try:
            from langgraph.config import get_config

            cfg = get_config()
            configurable = cfg.get("configurable", {}) if isinstance(cfg, dict) else {}
            thread_id_value = configurable.get("thread_id")
            thread_id = str(thread_id_value) if thread_id_value else None
        except Exception:
            thread_id = None

        purpose = _safe_name(str(os.getenv("CAPYBARA_PROMPT_LOG_PURPOSE", "prompt_tuning")))
        actor = _detect_actor(serialized if isinstance(serialized, dict) else {}, kwargs)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        output_dir = _resolve_output_dir(thread_id)

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return

        try:
            batches = messages if isinstance(messages, list) else []
            for batch_idx, batch in enumerate(batches, start=1):
                if not isinstance(batch, list):
                    continue
                suffix = f"_b{batch_idx}" if len(batches) > 1 else ""
                file_path = output_dir / f"{timestamp}_{actor}_{purpose}{suffix}.txt"
                payload = {
                    "timestamp_utc": timestamp,
                    "purpose": purpose,
                    "actor": actor,
                    "thread_id": thread_id,
                    "model_name": (serialized or {}).get("name"),
                    "invocation_params": kwargs.get("invocation_params"),
                    "message_count": len(batch),
                }
                text = _messages_to_text(batch)
                file_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n\n" + text, encoding="utf-8")
        except Exception:
            return
