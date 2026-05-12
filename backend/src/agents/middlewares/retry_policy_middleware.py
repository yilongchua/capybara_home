"""Retry policy middleware for tool calls."""

from __future__ import annotations

import asyncio
import fnmatch
import time
from collections.abc import Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.retry_config import RetryConfig, RetryRuleConfig, get_retry_config

RETRY_ATTEMPTS_CONTEXT_KEY = "_phase_b_retry_attempts"
RETRY_PROGRESS_GUARD_KEY = "_phase_b_retry_turn"


def _is_retryable(exc: Exception, rule: RetryRuleConfig) -> bool:
    text = str(exc).lower()
    if not text:
        return False
    return any(fragment.lower() in text for fragment in rule.retryable_errors)


class RetryPolicyMiddleware(AgentMiddleware[AgentState]):
    """Retries tool calls for configured retryable failures."""

    def __init__(self, config: RetryConfig | None = None):
        super().__init__()
        self._config = config or get_retry_config()

    def _rule_for(self, tool_name: str) -> RetryRuleConfig | None:
        for rule in self._config.rules:
            if fnmatch.fnmatchcase(tool_name, rule.tool):
                return rule
        if self._config.default:
            return RetryRuleConfig(tool=tool_name, max_attempts=self._config.max_attempts, backoff_ms=self._config.backoff_ms)
        return None

    def _mark_retry(self, request: ToolCallRequest, attempt: int, rule: RetryRuleConfig, error: Exception) -> None:
        context = request.runtime.context or {}
        attempt_map = context.get(RETRY_ATTEMPTS_CONTEXT_KEY)
        if not isinstance(attempt_map, dict):
            attempt_map = {}
            context[RETRY_ATTEMPTS_CONTEXT_KEY] = attempt_map
        tool_call_id = request.tool_call.get("id") or request.tool_call.get("name") or "tool"
        attempt_map[str(tool_call_id)] = attempt
        context[RETRY_PROGRESS_GUARD_KEY] = bool(rule.idempotent)
        append_runtime_event(
            request.runtime,
            {
                "source": "retry_policy_middleware",
                "tool": request.tool_call.get("name"),
                "attempt": attempt,
                "max_attempts": rule.max_attempts,
                "idempotent": rule.idempotent,
                "error": str(error)[:400],
            },
        )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        if not self._config.enabled:
            return handler(request)
        tool_name = str(request.tool_call.get("name") or "unknown")
        rule = self._rule_for(tool_name)
        if rule is None:
            return handler(request)

        attempt = 0
        while True:
            try:
                return handler(request)
            except Exception as exc:
                attempt += 1
                if attempt >= rule.max_attempts or not _is_retryable(exc, rule):
                    raise
                self._mark_retry(request, attempt, rule, exc)
                time.sleep(rule.backoff_ms / 1000)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        if not self._config.enabled:
            return await handler(request)
        tool_name = str(request.tool_call.get("name") or "unknown")
        rule = self._rule_for(tool_name)
        if rule is None:
            return await handler(request)

        attempt = 0
        while True:
            try:
                return await handler(request)
            except Exception as exc:
                attempt += 1
                if attempt >= rule.max_attempts or not _is_retryable(exc, rule):
                    raise
                self._mark_retry(request, attempt, rule, exc)
                await asyncio.sleep(rule.backoff_ms / 1000)
