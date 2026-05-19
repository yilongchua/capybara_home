"""Circuit breaker for repeated web_search failures within a user run."""

from __future__ import annotations

import json
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from src.agents.middlewares.model_timeout_middleware import TIMEOUT_MESSAGE_FINGERPRINT

_CIRCUIT_OPEN_FINGERPRINT = "[web_search_circuit_open]"
_FAILURE_THRESHOLD = 2


def _message_type(message: Any) -> str:
    raw = getattr(message, "type", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        value = message.get("type")
        if isinstance(value, str):
            return value
    return ""


def _message_name(message: Any) -> str:
    raw = getattr(message, "name", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        value = message.get("name")
        if isinstance(value, str):
            return value
    return ""


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(message, dict):
        value = message.get("content", "")
        if isinstance(value, str):
            return value
    return str(content) if content else ""


def _is_real_human(message: Any) -> bool:
    return _message_type(message) == "human" and not _message_name(message)


def _is_web_search_failure(message: Any) -> bool:
    if _message_type(message) != "tool":
        return False
    name = _message_name(message).lower()
    if name and "web_search" not in name and "searx" not in name:
        return False
    content = _message_content(message)
    if TIMEOUT_MESSAGE_FINGERPRINT in content or _CIRCUIT_OPEN_FINGERPRINT in content:
        return True
    try:
        payload = json.loads(content)
    except Exception:
        return False
    if isinstance(payload, dict) and payload.get("ok") is False:
        return True
    return False


def _failure_count_since_latest_user(messages: list[Any]) -> int:
    start_idx = 0
    for idx, message in enumerate(messages):
        if _is_real_human(message):
            start_idx = idx + 1
    return sum(1 for message in messages[start_idx:] if _is_web_search_failure(message))


class WebSearchCircuitBreakerMiddleware(AgentMiddleware[AgentState]):
    """Blocks repeated web_search retries after a failed batch.

    The lead agent often retries another parallel web_search batch after two or
    more timeout/error ToolMessages are already in the same user run. This
    middleware turns those retries into a cheap ToolMessage and tells the model
    to use available results or fall back instead.
    """

    def _maybe_block(self, request: ToolCallRequest) -> ToolMessage | None:
        tool_name = str(request.tool_call.get("name") or "")
        if tool_name != "web_search":
            return None
        state = request.state or {}
        messages = state.get("messages", []) if isinstance(state, dict) else []
        failures = _failure_count_since_latest_user(list(messages or []))
        if failures < _FAILURE_THRESHOLD:
            return None
        return ToolMessage(
            name=tool_name,
            tool_call_id=request.tool_call.get("id", ""),
            content=(
                f"{_CIRCUIT_OPEN_FINGERPRINT}\n"
                f"web_search already failed {failures} time(s) in this user run. "
                "Skip further web_search retries for now. Use successful prior results, "
                "query_knowledge_vault/query_lightrag if available, or answer from established knowledge with clear caveats."
            ),
        )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage:
        blocked = self._maybe_block(request)
        if blocked is not None:
            return blocked
        return handler(request)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage:
        blocked = self._maybe_block(request)
        if blocked is not None:
            return blocked
        return await handler(request)
