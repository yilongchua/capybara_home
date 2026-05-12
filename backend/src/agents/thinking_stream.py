"""Callback that streams thinking/reasoning tokens as LangGraph custom events.

Supports two formats:
- DeepSeek / OpenAI-compat: ``chunk.additional_kwargs["reasoning_content"]``
- Anthropic extended thinking: ``chunk.content[i]["type"] == "thinking"``
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

_THINKING_EVENT = "thinking_chunk"


def _extract_thinking_delta(chunk: Any) -> str:
    """Return the thinking delta from a streaming chunk, or empty string."""
    # DeepSeek R1 / OpenAI-compat reasoning gateway
    additional = getattr(chunk, "additional_kwargs", None) or {}
    reasoning = additional.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        return reasoning

    # Anthropic extended thinking blocks (content is a list of dicts)
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "thinking":
                text = block.get("thinking") or block.get("partial_thinking") or ""
                if isinstance(text, str) and text:
                    return text

    return ""


class ThinkingStreamCallback(BaseCallbackHandler):
    """Emits ``thinking_chunk`` custom events into the LangGraph stream."""

    def __init__(self) -> None:
        super().__init__()
        self._writer: Any = None

    def on_chat_model_start(self, serialized: dict, messages: list, **kwargs: Any) -> None:
        # Capture the stream writer at call-start so it is available in on_llm_new_token.
        # get_stream_writer() is context-var based and valid here because we are still
        # inside the LangGraph execution context.
        try:
            from langgraph.config import get_stream_writer

            self._writer = get_stream_writer()
        except Exception:
            self._writer = None

    def on_llm_new_token(self, token: str, *, chunk: Any = None, **kwargs: Any) -> None:
        if self._writer is None or chunk is None:
            return
        delta = _extract_thinking_delta(chunk)
        if not delta:
            return
        try:
            self._writer({"type": _THINKING_EVENT, "content": delta})
        except Exception:
            pass

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self._writer = None
