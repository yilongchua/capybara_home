"""Pure text/time utilities used by the vault learning subsystem.

Extracted from ``vault_learning.py`` so the same helpers can be reused by
neighbouring modules without depending on ``VaultLearningManager``.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "item"


def strip_html(value: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", value)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_title(html: str, fallback: str) -> str:
    match = re.search(r"(?is)<title>(.*?)</title>", html)
    if match:
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        if title:
            return title
    return fallback


def word_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9]+", query.lower()) if token]


def frontmatter_dump(payload: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in payload.items():
        if isinstance(value, list):
            serialized = "[" + ", ".join(json.dumps(str(item)) for item in value) + "]"
        elif isinstance(value, bool):
            serialized = "true" if value else "false"
        elif value is None:
            serialized = '""'
        elif isinstance(value, (int, float)):
            serialized = str(value)
        else:
            serialized = json.dumps(str(value))
        lines.append(f"{key}: {serialized}")
    lines.append("---")
    return "\n".join(lines)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
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


__all__ = [
    "utcnow",
    "utcnow_iso",
    "slugify",
    "strip_html",
    "extract_title",
    "word_tokens",
    "frontmatter_dump",
    "parse_frontmatter",
]
