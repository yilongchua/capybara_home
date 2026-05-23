"""Web search tool powered by local websearch backend (e.g. SearXNG)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from langchain.tools import tool

from src.config import get_app_config
from src.config.routing_config import get_routing_config
from src.control_plane.service import get_control_plane_service
from src.security.search_guardrails import enforce_query_guardrails

logger = logging.getLogger(__name__)
_RETRY_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 0.2
_DEFAULT_MAX_CONCURRENT_REQUESTS = 3
_DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS = 10.0
_DEFAULT_SIMPLIFIED_QUERY_MAX_TERMS = 12
_DEFAULT_SIMPLIFIED_QUERY_MAX_CHARS = 180
_WEB_SEARCH_SEMAPHORES: dict[int, asyncio.Semaphore] = {}
_WEB_SEARCH_SEMAPHORES_LOCK = asyncio.Lock()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _resolve_timeout_seconds(tool_extra: dict[str, Any], backend_timeout: Any) -> tuple[float, int, str]:
    """Resolve web_search backend timeout with explicit precedence.

    Two separate timeouts govern different phases of execution:
    - effective_timeout_s: bounds each individual HTTP request (httpx client)
    - routing_timeout_s:   bounds the entire tool call wall-clock (middleware asyncio.wait_for)

    The HTTP timeout must be <= the routing timeout; if it exceeds it, the HTTP
    client will never time out naturally before the middleware cancels the coroutine,
    making the HTTP-level timeout useless and masking the actual cancellation source.

    Precedence for HTTP timeout:
      1) tools.web_search.timeout_seconds (tool_extra)
      2) tool_backends.websearch.timeout_seconds (backend config)
      3) routing.timeouts.tools.web_search (fallback)
    """
    routing_timeout_s = int(get_routing_config().timeouts.for_tool("web_search"))
    timeout_source = "routing.timeouts.tools.web_search"

    tool_timeout = tool_extra.get("timeout_seconds")
    if tool_timeout is not None:
        timeout_source = "tools.web_search.timeout_seconds"
        effective_timeout_s = float(tool_timeout)
    elif backend_timeout is not None:
        timeout_source = "tool_backends.websearch.timeout_seconds"
        effective_timeout_s = float(backend_timeout)
    else:
        effective_timeout_s = float(routing_timeout_s)

    if effective_timeout_s > routing_timeout_s:
        logger.warning(
            "web_search HTTP timeout (%ss via %s) exceeds routing tool timeout (%ss). "
            "The middleware will cancel the tool before the HTTP client can time out — "
            "set tool_backends.websearch.timeout_seconds <= routing.timeouts.tools.web_search.",
            effective_timeout_s,
            timeout_source,
            routing_timeout_s,
        )

    return effective_timeout_s, routing_timeout_s, timeout_source


def _load_web_search_config() -> dict[str, Any]:
    app_config = get_app_config()
    tool_cfg = app_config.get_tool_config("web_search")
    tool_extra = tool_cfg.model_extra if tool_cfg is not None else {}
    backend_cfg = app_config.tool_backends.websearch
    backend_enabled = (
        bool(backend_cfg.get("enabled", False))
        if isinstance(backend_cfg, dict)
        else bool(getattr(backend_cfg, "enabled", False))
    )
    backend_base_url = (
        backend_cfg.get("base_url")
        if isinstance(backend_cfg, dict)
        else getattr(backend_cfg, "base_url", None)
    )
    backend_timeout = (
        backend_cfg.get("timeout_seconds")
        if isinstance(backend_cfg, dict)
        else getattr(backend_cfg, "timeout_seconds", None)
    )

    base_url = str(
        tool_extra.get("base_url")
        or backend_base_url
        or "http://127.0.0.1:9000"
    )
    timeout_seconds, routing_timeout_s, timeout_source = _resolve_timeout_seconds(tool_extra, backend_timeout)
    return {
        "enabled": backend_enabled,
        "base_url": base_url.rstrip("/"),
        "path": str(tool_extra.get("path", "/search")),
        "method": str(tool_extra.get("method", "POST")).upper(),
        "api_style": str(tool_extra.get("api_style", "auto")).lower(),
        "timeout_seconds": timeout_seconds,
        "routing_timeout_seconds": routing_timeout_s,
        "timeout_source": timeout_source,
        "max_results": int(tool_extra.get("max_results", 8)),
        "secret_key": tool_extra.get("secret_key"),
        "engines": _as_list(tool_extra.get("engines")),
        "language": tool_extra.get("language"),
        "safesearch": int(tool_extra.get("safesearch", 1)),
        "headers": tool_extra.get("headers", {}) if isinstance(tool_extra.get("headers", {}), dict) else {},
        "max_concurrent_requests": max(1, int(tool_extra.get("max_concurrent_requests", _DEFAULT_MAX_CONCURRENT_REQUESTS))),
        "queue_wait_timeout_seconds": max(0.1, float(tool_extra.get("queue_wait_timeout_seconds", _DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS))),
        "simplify_queries": bool(tool_extra.get("simplify_queries", True)),
        "simplified_query_max_terms": max(3, int(tool_extra.get("simplified_query_max_terms", _DEFAULT_SIMPLIFIED_QUERY_MAX_TERMS))),
        "simplified_query_max_chars": max(32, int(tool_extra.get("simplified_query_max_chars", _DEFAULT_SIMPLIFIED_QUERY_MAX_CHARS))),
    }


def _simplify_query(query: str, *, max_terms: int, max_chars: int) -> str:
    normalized = " ".join((query or "").strip().split())
    if not normalized:
        return ""

    # Keep common search operators and punctuation, but remove instruction-like filler.
    cleaned = re.sub(r"^[\"'`\s]+|[\"'`\s]+$", "", normalized)
    cleaned = re.sub(r"\b(please|could you|can you|help me|find|search for|look up)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = normalized

    words = cleaned.split()
    if len(words) <= max_terms and len(cleaned) <= max_chars:
        return cleaned

    # Prefer content words when trimming long prompts into a web-search query.
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "to",
        "in",
        "on",
        "with",
        "about",
        "comprehensive",
        "analysis",
        "summarize",
        "explain",
        "please",
        "latest",
        "recent",
    }
    trimmed_terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9][\w:/\.-]*", cleaned):
        if token.lower() in stop_words and len(trimmed_terms) > 0:
            continue
        trimmed_terms.append(token)
        if len(trimmed_terms) >= max_terms:
            break

    candidate = " ".join(trimmed_terms).strip() or " ".join(words[:max_terms]).strip()
    return candidate[:max_chars].strip() or cleaned[:max_chars].strip()


async def _get_web_search_semaphore(limit: int) -> asyncio.Semaphore:
    async with _WEB_SEARCH_SEMAPHORES_LOCK:
        sem = _WEB_SEARCH_SEMAPHORES.get(limit)
        if sem is None:
            sem = asyncio.Semaphore(limit)
            _WEB_SEARCH_SEMAPHORES[limit] = sem
        return sem


async def _acquire_web_search_slot(limit: int, timeout_seconds: float) -> tuple[asyncio.Semaphore, float]:
    sem = await _get_web_search_semaphore(limit)
    wait_start = perf_counter()
    await asyncio.wait_for(sem.acquire(), timeout=timeout_seconds)
    waited_ms = (perf_counter() - wait_start) * 1000.0
    return sem, waited_ms


def _normalize_results(raw_results: list[Any], max_results: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for result in raw_results:
        if not isinstance(result, dict):
            continue

        url = str(result.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        normalized.append(
            {
                "title": str(result.get("title") or "").strip(),
                "url": url,
                "snippet": str(result.get("snippet") or result.get("content") or "").strip(),
                "extracted_content": str(result.get("extracted_content") or "").strip(),
                "source": str(result.get("engine") or "").strip(),
            }
        )
        if len(normalized) >= max_results:
            break

    return normalized


def _render_result_markdown(*, query: str, item: dict[str, Any]) -> str:
    title = str(item.get("title") or item.get("url") or "Web Search Result").strip()
    url = str(item.get("url") or "").strip()
    snippet = str(item.get("snippet") or "").strip()
    extracted = str(item.get("extracted_content") or "").strip()

    lines = [f"# {title}", "", f"- Source URL: {url}", f"- Query: {query}", ""]
    if snippet:
        lines.extend(["## Snippet", "", snippet, ""])
    lines.extend(["## Content", "", extracted or snippet or f"Source: {url}", ""])
    return "\n".join(lines).strip() + "\n"


async def _request_json_with_retry(
    *,
    client: httpx.AsyncClient,
    request_kwargs: dict[str, Any],
    attempts: int = _RETRY_ATTEMPTS,
    base_backoff_seconds: float = _RETRY_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """Issue an HTTP request with small retry/backoff for transient latency issues."""
    last_exc: Exception | None = None

    for attempt_idx in range(attempts):
        try:
            response = await client.request(**request_kwargs)
            response.raise_for_status()
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else {}
        except asyncio.CancelledError:
            # Preserve cooperative cancellation so tool timeout middleware can interrupt cleanly.
            raise
        except httpx.HTTPStatusError:
            raise
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt_idx >= attempts - 1:
                raise
            await asyncio.sleep(base_backoff_seconds * (attempt_idx + 1))

    if last_exc is not None:
        raise last_exc
    return {}


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for current information via the configured backend.

    Args:
        query: User-facing query text. May be simplified into a shorter
            human-like search phrase when ``simplify_queries`` is enabled.
        max_results: Maximum number of results requested by the caller
            (still clamped by config limits).

    Notes:
        Calls are throttled through an internal async queue controlled by
        ``max_concurrent_requests`` and ``queue_wait_timeout_seconds``.
    """
    started_at = perf_counter()
    try:
        enforce_query_guardrails(query, tool_name="web_search")

        cfg = _load_web_search_config()
        if not cfg["enabled"]:
            return json.dumps(
                {
                    "ok": False,
                    "error": "Web search backend is disabled in config (tool_backends.websearch.enabled=false).",
                },
                ensure_ascii=False,
            )
        if cfg["method"] not in {"GET", "POST"}:
            return json.dumps({"ok": False, "error": "Unsupported method. Use GET or POST."}, ensure_ascii=False)

        endpoint = f"{cfg['base_url']}/{cfg['path'].lstrip('/')}"
        effective_max_results = max(1, min(int(max_results), max(1, int(cfg["max_results"]))))
        effective_query = (
            _simplify_query(
                query,
                max_terms=int(cfg["simplified_query_max_terms"]),
                max_chars=int(cfg["simplified_query_max_chars"]),
            )
            if cfg["simplify_queries"]
            else query
        )
        if not effective_query:
            effective_query = query.strip()

        # CapyHome local websearch backend expects JSON body:
        # {"query": "...", "max_results": N}
        capyhome_payload: dict[str, Any] = {
            "query": effective_query,
            "max_results": effective_max_results,
            "write_markdown_package": True,
            "package_name": effective_query,
        }
        if cfg["engines"]:
            capyhome_payload["engines"] = cfg["engines"]
        if cfg["language"]:
            capyhome_payload["language"] = str(cfg["language"])
        if cfg["secret_key"]:
            capyhome_payload["secret_key"] = cfg["secret_key"]

        # SearXNG-style compatibility payload.
        searx_payload: dict[str, Any] = {
            "q": effective_query,
            "format": "json",
            "categories": "general",
            "safesearch": str(cfg["safesearch"]),
        }
        if cfg["secret_key"]:
            searx_payload["secret_key"] = cfg["secret_key"]
        if cfg["engines"]:
            searx_payload["engines"] = ",".join(cfg["engines"])
        if cfg["language"]:
            searx_payload["language"] = str(cfg["language"])

        body: dict[str, Any] = {}
        capyhome_error: Exception | None = None

        sem, queue_wait_ms = await _acquire_web_search_slot(
            int(cfg["max_concurrent_requests"]),
            float(cfg["queue_wait_timeout_seconds"]),
        )
        try:
            async with httpx.AsyncClient(timeout=cfg["timeout_seconds"]) as client:
                # Prefer capyhome JSON API, with optional searxng fallback for compatibility.
                if cfg["api_style"] in {"auto", "capyhome"}:
                    try:
                        capyhome_headers = {"Content-Type": "application/json", **cfg["headers"]}
                        body = await _request_json_with_retry(
                            client=client,
                            request_kwargs={
                                "method": "POST",
                                "url": endpoint,
                                "headers": capyhome_headers,
                                "json": capyhome_payload,
                            },
                        )
                    except Exception as exc:
                        capyhome_error = exc
                        if cfg["api_style"] == "capyhome":
                            raise

                if cfg["api_style"] == "searxng" or (cfg["api_style"] == "auto" and not body):
                    request_kwargs: dict[str, Any] = {
                        "method": cfg["method"],
                        "url": endpoint,
                        "headers": cfg["headers"],
                    }
                    if cfg["method"] == "GET":
                        request_kwargs["params"] = searx_payload
                    else:
                        request_kwargs["data"] = searx_payload
                    body = await _request_json_with_retry(client=client, request_kwargs=request_kwargs)
        finally:
            sem.release()

        if not body and capyhome_error is not None:
            raise capyhome_error

        raw_results = body.get("results", []) if isinstance(body, dict) else []
        results = _normalize_results(raw_results, effective_max_results)
        package_info = body.get("package") if isinstance(body, dict) else None

        queue_report: dict[str, Any] | None = None
        try:
            app_cfg = get_app_config()
            vault_cfg = app_cfg.knowledge_vault
            if vault_cfg.enabled and vault_cfg.search_results_queue_enabled:
                package_markdown_path = str((package_info or {}).get("markdown_path") or "").strip()
                if package_markdown_path and Path(package_markdown_path).exists():
                    package_markdown_path = str(Path(package_markdown_path).resolve())

                queue_results: list[dict[str, Any]] = []
                for item in results:
                    markdown_content = _render_result_markdown(query=query, item=item)
                    queue_item = {
                        **item,
                        # Ingestion pipeline consumes extracted_content; force markdown to preserve structure.
                        "extracted_content": markdown_content,
                    }
                    if package_markdown_path:
                        queue_item["source_markdown_path"] = package_markdown_path
                    queue_results.append(queue_item)

                manager = get_control_plane_service()._default_vault_manager()
                queue_report = manager.enqueue_search_results(query=query, results=queue_results)
        except Exception:
            logger.exception("web_search queue append failed")

        return json.dumps(
            {
                "ok": True,
                "query": query,
                "executed_query": effective_query,
                "total_results": len(results),
                "results": results,
                "package": package_info,
                "queue": queue_report,
                "web_search_runtime": {
                    "max_concurrent_requests": int(cfg["max_concurrent_requests"]),
                    "queue_wait_ms": round(queue_wait_ms, 1),
                    "elapsed_ms": round((perf_counter() - started_at) * 1000.0, 1),
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("web_search failed")
        return json.dumps({"ok": False, "error": str(exc), "query": query, "web_search_runtime": {"elapsed_ms": round((perf_counter() - started_at) * 1000.0, 1)}}, ensure_ascii=False)
