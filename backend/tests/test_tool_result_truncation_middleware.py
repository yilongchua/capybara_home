"""Tests for ToolResultTruncationMiddleware."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from src.agents.middlewares.tool_result_truncation_middleware import (
    TRUNCATION_MARKER,
    ToolResultTruncationMiddleware,
)


def _request(name: str):
    return SimpleNamespace(
        tool_call={"name": name, "id": "tc-1"},
        runtime=SimpleNamespace(context={"thread_id": "t1"}),
        state={},
    )


def test_truncates_oversized_web_search_result():
    middleware = ToolResultTruncationMiddleware()
    big = "x" * 50000  # default web_search cap is 12000

    async def handler(_req):
        return ToolMessage(content=big, tool_call_id="tc-1", name="web_search")

    result = asyncio.run(middleware.awrap_tool_call(_request("web_search"), handler))
    assert isinstance(result, ToolMessage)
    assert result.content.endswith(TRUNCATION_MARKER)
    assert len(result.content) <= 12000
    assert result.tool_call_id == "tc-1"
    assert result.name == "web_search"


def test_no_truncation_under_cap():
    middleware = ToolResultTruncationMiddleware()
    small = "ok"

    async def handler(_req):
        return ToolMessage(content=small, tool_call_id="tc-1", name="web_search")

    result = asyncio.run(middleware.awrap_tool_call(_request("web_search"), handler))
    assert result.content == small
    assert TRUNCATION_MARKER not in result.content


def test_unknown_tool_passes_through():
    """We only truncate tools we know about — unknown tools are left alone
    so we don't surprise authors with silent truncation of structured payloads."""
    middleware = ToolResultTruncationMiddleware()
    big = "y" * 100000

    async def handler(_req):
        return ToolMessage(content=big, tool_call_id="tc-1", name="custom_tool")

    result = asyncio.run(middleware.awrap_tool_call(_request("custom_tool"), handler))
    assert result.content == big


def test_non_string_content_passes_through():
    middleware = ToolResultTruncationMiddleware()

    async def handler(_req):
        # Some tools return list[dict] content payloads. Don't try to clamp them.
        return ToolMessage(
            content=[{"type": "text", "text": "z" * 50000}],
            tool_call_id="tc-1",
            name="web_search",
        )

    result = asyncio.run(middleware.awrap_tool_call(_request("web_search"), handler))
    # Untouched
    assert isinstance(result.content, list)
