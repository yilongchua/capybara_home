"""Small shared LLM helpers for the autoresearch loop.

We keep the contract narrow: a single ``invoke_json`` helper that calls the
configured local model and returns a parsed dict, or an empty dict on any
failure. Errors are swallowed (logged at module init time) so the loop can
fall back to a defensive empty-list path rather than crashing the iteration.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # Try the whole string first (handles arrays as top-level)
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Fall back to extracting the first {...} or [...] block
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = raw.find(open_ch)
        end = raw.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            chunk = raw[start : end + 1]
            try:
                return json.loads(chunk)
            except Exception:
                continue
    return None


def invoke_json(prompt: str, *, model_name: str | None = None) -> Any:
    """Invoke the configured chat model and parse the response as JSON.

    Returns ``None`` if the model can't be created or the response can't be
    parsed. Callers should handle ``None`` defensively (treat as no output).
    """
    try:
        from src.config import get_app_config
        from src.models.factory import create_chat_model
    except Exception:
        logger.exception("autoresearch llm: failed to import model dependencies")
        return None

    try:
        app_config = get_app_config()
    except Exception:
        logger.exception("autoresearch llm: failed to load app config")
        return None
    if not app_config.models:
        logger.warning("autoresearch llm: no models configured")
        return None

    try:
        model = create_chat_model(name=model_name or None, thinking_enabled=False)
        response = model.invoke(prompt)
    except Exception:
        logger.exception("autoresearch llm: model invocation failed")
        return None

    content = response.content if hasattr(response, "content") else response
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                text_parts.append(str(block["text"]))
        raw = "\n".join(text_parts)
    else:
        raw = str(content or "")

    return _extract_json(raw)
