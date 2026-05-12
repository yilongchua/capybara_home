"""Internal document search proxy.

Wraps the MCP ``search_indexed_documents`` tool under a stable
``search_internal_documents`` name so agent prompts and skills can
reference it without knowing the underlying server name.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

_indexed_search_target: BaseTool | None = None


def register_internal_search_target(mcp_tool: BaseTool | None) -> None:
    """Register (or clear) the MCP tool that backs internal document search."""
    global _indexed_search_target
    _indexed_search_target = mcp_tool
    if mcp_tool is not None:
        logger.debug("Registered internal search target: %s", mcp_tool.name)
    else:
        logger.debug("Cleared internal search target")


@tool("search_internal_documents")
def search_internal_documents_tool(query: str) -> Any:
    """Search indexed internal documents. Delegates to the configured MCP search_indexed_documents tool."""
    if _indexed_search_target is None:
        return "No indexed document search tool is configured."
    return _indexed_search_target.invoke({"query": query})
