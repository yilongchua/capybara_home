"""Tests for retry policy middleware."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from src.agents.middlewares.retry_policy_middleware import RETRY_ATTEMPTS_CONTEXT_KEY, RetryPolicyMiddleware
from src.config.retry_config import RetryConfig, RetryRuleConfig


def _request():
    return SimpleNamespace(
        tool_call={"name": "web_search", "id": "tc-1", "args": {"query": "x"}},
        runtime=SimpleNamespace(context={"thread_id": "thread-1"}),
    )


def test_retries_retryable_error_and_succeeds():
    middleware = RetryPolicyMiddleware(
        RetryConfig(
            enabled=True,
            rules=[
                RetryRuleConfig(
                    tool="web_search",
                    max_attempts=2,
                    backoff_ms=0,
                    retryable_errors=["timeout"],
                    idempotent=True,
                )
            ],
        )
    )
    request = _request()
    attempts = {"count": 0}

    def handler(req):  # noqa: ARG001
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("timeout while calling provider")
        return ToolMessage(content="ok", tool_call_id="tc-1", name="web_search")

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert attempts["count"] == 2
    assert request.runtime.context[RETRY_ATTEMPTS_CONTEXT_KEY]["tc-1"] == 1


def test_task_timeout_rule_retries_once_and_then_succeeds():
    middleware = RetryPolicyMiddleware(
        RetryConfig(
            enabled=True,
            rules=[
                RetryRuleConfig(
                    tool="task",
                    max_attempts=2,
                    backoff_ms=0,
                    retryable_errors=["timeout"],
                    idempotent=False,
                )
            ],
        )
    )
    request = SimpleNamespace(
        tool_call={"name": "task", "id": "tc-task-timeout", "args": {"description": "x"}},
        runtime=SimpleNamespace(context={"thread_id": "thread-1"}),
    )
    attempts = {"count": 0}

    def handler(req):  # noqa: ARG001
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("task timeout while polling")
        return ToolMessage(content="ok", tool_call_id="tc-task-timeout", name="task")

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert attempts["count"] == 2
    assert request.runtime.context[RETRY_ATTEMPTS_CONTEXT_KEY]["tc-task-timeout"] == 1
