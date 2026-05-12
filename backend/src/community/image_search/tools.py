"""Image search tool (images category)."""

import json
import logging
from typing import Any

import httpx
from langchain.tools import tool

from src.config import get_app_config

logger = logging.getLogger(__name__)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _load_image_search_config() -> dict[str, Any]:
    image_cfg = get_app_config().get_tool_config("image_search")
    image_extra = image_cfg.model_extra if image_cfg is not None else {}

    # Reuse web_search base URL by default so image_search and web_search stay aligned.
    web_cfg = get_app_config().get_tool_config("web_search")
    web_extra = web_cfg.model_extra if web_cfg is not None else {}

    base_url = str(image_extra.get("base_url") or web_extra.get("base_url") or "http://localhost:8080")
    return {
        "base_url": base_url,
        "path": str(image_extra.get("path", "/search")),
        "method": str(image_extra.get("method", "GET")).upper(),
        "max_results": int(image_extra.get("max_results", 5)),
        "timeout_seconds": float(image_extra.get("timeout_seconds", 12.0)),
        "secret_key": image_extra.get("secret_key") or web_extra.get("secret_key"),
        "engines": _as_list(image_extra.get("engines")),
        "language": image_extra.get("language"),
        "safesearch": image_extra.get("safesearch", 1),
        "headers": image_extra.get("headers", {}) if isinstance(image_extra.get("headers", {}), dict) else {},
    }


def _normalize_image_results(raw_results: list[Any], max_results: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_images: set[str] = set()

    for result in raw_results:
        if not isinstance(result, dict):
            continue

        image_url = str(result.get("img_src") or result.get("thumbnail_src") or "").strip()
        source_url = str(result.get("url") or "").strip()
        if not image_url or image_url in seen_images:
            continue
        seen_images.add(image_url)

        normalized.append(
            {
                "title": str(result.get("title", "")).strip(),
                "image_url": image_url,
                "thumbnail_url": str(result.get("thumbnail_src") or image_url).strip(),
                "source_url": source_url,
            }
        )
        if len(normalized) >= max_results:
            break

    return normalized


@tool("image_search", parse_docstring=True)
def image_search_tool(query: str, max_results: int = 5) -> str:
    """Search images.

    Args:
        query: Search terms for image discovery.
        max_results: Maximum number of images to return.
    """
    try:
        cfg = _load_image_search_config()
        if cfg["method"] not in {"GET", "POST"}:
            return json.dumps(
                {"error": "Unsupported SearXNG method. Use GET or POST."},
                ensure_ascii=False,
            )

        endpoint = f"{cfg['base_url'].rstrip('/')}/{cfg['path'].lstrip('/')}"
        effective_max_results = max(1, min(int(max_results), max(1, int(cfg["max_results"]))))

        payload: dict[str, Any] = {
            "q": query,
            "categories": "images",
            "format": "json",
            "safesearch": str(cfg["safesearch"]),
        }
        if cfg["secret_key"]:
            payload["secret_key"] = cfg["secret_key"]
        if cfg["engines"]:
            payload["engines"] = ",".join(cfg["engines"])
        if cfg["language"]:
            payload["language"] = str(cfg["language"])

        request_kwargs: dict[str, Any] = {
            "method": cfg["method"],
            "url": endpoint,
            "headers": cfg["headers"],
            "timeout": cfg["timeout_seconds"],
        }
        if cfg["method"] == "GET":
            request_kwargs["params"] = payload
        else:
            request_kwargs["data"] = payload

        response = httpx.request(**request_kwargs)
        response.raise_for_status()
        body = response.json()
        raw_results = body.get("results", []) if isinstance(body, dict) else []
        normalized_results = _normalize_image_results(raw_results, effective_max_results)

        if not normalized_results:
            return json.dumps({"error": "No images found", "query": query}, ensure_ascii=False)

        return json.dumps(
            {
                "query": query,
                "total_results": len(normalized_results),
                "results": normalized_results,
                "usage_hint": "Use the image_url values as visual references.",
            },
            indent=2,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("image_search failed")
        return json.dumps({"error": str(exc), "query": query}, ensure_ascii=False)
