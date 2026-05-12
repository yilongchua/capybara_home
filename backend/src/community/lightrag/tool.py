"""LightRAG internal query tool for objective-driven graph evidence retrieval."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from langchain.tools import tool

from src.config import get_app_config

logger = logging.getLogger(__name__)


def _lightrag_config() -> dict[str, Any]:
    cfg = get_app_config().knowledge_vault.lightrag
    return {
        "enabled": bool(getattr(cfg, "enabled", False)),
        "base_url": str(getattr(cfg, "base_url", "http://localhost:9621")).rstrip("/"),
        "timeout_seconds": float(getattr(cfg, "timeout_seconds", 12.0)),
        "default_mode": str(getattr(cfg, "default_mode", "hybrid")),
        "max_top_k": int(getattr(cfg, "max_top_k", 20)),
    }


@tool("query_lightrag", parse_docstring=True)
def query_lightrag_tool(
    query: str,
    mode: str | None = None,
    top_k: int = 8,
    filters: dict[str, Any] | None = None,
) -> str:
    """Query LightRAG for graph-oriented evidence and multi-hop relationships.

    Use this tool for objective-driven research when the agent needs relationship
    discovery, cross-entity linkage, and provenance-rich graph context.

    Args:
        query: Natural language graph query.
        mode: Retrieval mode (e.g. local/global/hybrid). Defaults to configured mode.
        top_k: Number of results to return. Capped by config max_top_k.
        filters: Optional provider-specific filter payload.
    """
    cfg = _lightrag_config()
    if not cfg["enabled"]:
        return json.dumps(
            {
                "ok": False,
                "error": "lightrag_disabled",
                "message": "LightRAG integration is disabled. Enable knowledge_vault.lightrag.enabled in config.",
            },
            ensure_ascii=False,
        )

    if not query.strip():
        return json.dumps(
            {"ok": False, "error": "empty_query", "message": "query cannot be empty."},
            ensure_ascii=False,
        )

    capped_top_k = max(1, min(int(top_k), int(cfg["max_top_k"])))
    payload = {
        "query": query,
        "mode": str(mode or cfg["default_mode"]),
        "top_k": capped_top_k,
        "filters": filters or {},
    }

    candidate_paths = ["/query", "/v1/query", "/api/query"]
    headers = {"Content-Type": "application/json"}

    with httpx.Client(timeout=cfg["timeout_seconds"]) as client:
        last_error = None
        for path in candidate_paths:
            url = f"{cfg['base_url']}{path}"
            try:
                response = client.post(url, json=payload, headers=headers)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                body = response.json()
                return json.dumps(
                    {
                        "ok": True,
                        "query": query,
                        "mode": payload["mode"],
                        "top_k": capped_top_k,
                        "endpoint": path,
                        "result": body,
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"

    logger.warning("query_lightrag failed for all candidate endpoints: %s", last_error)
    return json.dumps(
        {
            "ok": False,
            "error": "lightrag_query_failed",
            "message": "Unable to query LightRAG endpoint.",
            "details": last_error,
            "base_url": cfg["base_url"],
        },
        ensure_ascii=False,
    )
