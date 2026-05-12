"""Built-in memory recall tool."""

from __future__ import annotations

import json

from langchain.tools import tool
from langgraph.config import get_config

from src.agents.memory.store import MEMORY_SCOPE_GLOBAL, MEMORY_SCOPE_WORKSPACE
from src.agents.memory.vector_store import get_memory_vector_store
from src.config.memory_config import get_memory_config


@tool("recall", parse_docstring=True)
def recall_tool(query: str) -> str:
    """Search long-term memory for facts relevant to a query.

    Use this when you need to retrieve context from prior conversations that is
    not present in the immediate working context.

    Args:
        query: What to search for in memory.
    """
    text = str(query or "").strip()
    if not text:
        return "No query provided."

    cfg = get_memory_config()
    runtime_cfg = get_config()
    configurable = runtime_cfg.get("configurable", {}) if isinstance(runtime_cfg, dict) else {}
    workspace_id = configurable.get("thread_id")
    scopes: list[tuple[str, str | None]] = []
    if cfg.workspace_scope_enabled and workspace_id:
        scopes.append((MEMORY_SCOPE_WORKSPACE, str(workspace_id)))
    if cfg.global_scope_enabled:
        scopes.append((MEMORY_SCOPE_GLOBAL, "global"))
    if not scopes:
        return "Memory scopes are disabled."

    results = get_memory_vector_store().query(
        query=text,
        scopes=scopes,
        top_k=cfg.recall_top_k,
    )
    if not results:
        return "No relevant memory found."

    payload = [
        {
            "id": row.get("id"),
            "scope": row.get("scope"),
            "content": row.get("content"),
            "category": row.get("category"),
            "confidence": row.get("confidence"),
            "score": row.get("score"),
            "source": row.get("source"),
        }
        for row in results
    ]
    return json.dumps({"query": text, "results": payload}, ensure_ascii=False)

