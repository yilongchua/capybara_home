from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.models.factory import create_chat_model

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_SURROUNDING_QUOTES_RE = re.compile(r'^(["\'`]+)(.*?)(\1)$')

_MASKING_SYSTEM_PROMPT = """You anonymize search queries before web search.

Rewrite the user query so it preserves search intent while masking sensitive specifics.

Rules:
- Replace company names, product names, personal names, internal project names, and exact identifiers with generic but descriptive phrases.
- Soften exact money values, counts, dates, and case-specific details into approximate language when possible.
- Keep the rewritten query useful for public web search.
- Do not mention that you are anonymizing or masking.
- Output exactly one rewritten query and nothing else.
"""


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return " ".join(chunks).strip()
    return str(content).strip()


def _normalize_masked_query(text: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", text).strip()
    match = _SURROUNDING_QUOTES_RE.match(normalized)
    if match:
        normalized = match.group(2).strip()
    return normalized


def rewrite_search_query_for_privacy(
    query: str,
    *,
    model_name: str | None = None,
) -> str:
    normalized_query = _WHITESPACE_RE.sub(" ", query).strip()
    if not normalized_query:
        return normalized_query

    try:
        try:
            model = create_chat_model(
                name=model_name,
                thinking_enabled=False,
                reasoning_effort="minimal",
            )
        except Exception:
            logger.warning(
                "Falling back to default model for search masking",
                exc_info=True,
            )
            model = create_chat_model(
                thinking_enabled=False,
                reasoning_effort="minimal",
            )

        response = model.invoke(
            [
                SystemMessage(content=_MASKING_SYSTEM_PROMPT),
                HumanMessage(content=normalized_query),
            ]
        )
        masked_query = _normalize_masked_query(_extract_text(response.content))
        if not masked_query:
            raise ValueError("Masking model returned an empty query.")
        return masked_query
    except Exception as exc:
        raise ValueError(
            "Failed to mask the web search query while privacy lock is enabled."
        ) from exc
