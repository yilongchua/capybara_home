from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.security.search_masking import rewrite_search_query_for_privacy

logger = logging.getLogger(__name__)


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


class SearchPrivacyMiddleware(AgentMiddleware):
    """Rewrite outgoing web_search queries when workspace privacy lock is enabled."""

    def _should_mask_search(self, request: ToolCallRequest) -> bool:
        if request.tool_call.get("name") != "web_search":
            return False
        runtime_context = getattr(request.runtime, "context", {}) or {}
        return _is_enabled(runtime_context.get("mask_sensitive_search"))

    def _rewrite_request(self, request: ToolCallRequest) -> ToolCallRequest:
        if not self._should_mask_search(request):
            return request

        args = request.tool_call.get("args", {})
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return request

        runtime_context = getattr(request.runtime, "context", {}) or {}
        masked_query = rewrite_search_query_for_privacy(
            query,
            model_name=runtime_context.get("model_name"),
        )
        if masked_query == query:
            return request

        logger.info("Masked web_search query before provider request")
        return request.override(
            tool_call={
                **request.tool_call,
                "args": {
                    **args,
                    "query": masked_query,
                },
            }
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        return handler(self._rewrite_request(request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        rewritten_request = await asyncio.to_thread(self._rewrite_request, request)
        return await handler(rewritten_request)
