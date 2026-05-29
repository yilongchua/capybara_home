"""Web search summarization middleware — condenses large web_search results inline.

When a web_search tool returns more than ``web_search_summary.summary_threshold_chars`` characters,
this middleware makes a fast LLM call (Haiku, configurable timeout) to produce a
concise summary and replaces the ToolMessage content before it lands in state.
This prevents web_search from inflating the context window on every round.

The original character count is logged via runtime_events so operators can tune
the threshold.

Async path: `awrap_tool_call` uses `model.ainvoke()` and `asyncio.wait_for` so
N concurrent web_search results can summarize in parallel via the model
endpoint's load-balancer (Olla). The sync path retains the daemon-thread
fallback for embedded / non-async callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.background import run_with_timeout
from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.web_search_summary_config import get_web_search_summary_config
from src.models import create_chat_model, resolve_model_name

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT_TEMPLATE = """\
You are a research assistant. The following text is the raw result of a web search query.
Summarize it into a concise, factual paragraph (max 250 words) that captures all key findings.
Preserve: specific numbers, dates, names, URLs that are clearly important.
Do NOT add commentary, opinions, or phrases like "The search results show...".
Start directly with the key information.

Search query: {query}

Raw results:
{raw_content}
"""

_SUMMARY_SUFFIX = "\n\n[Summarized by web_search_summary_middleware — original: {orig_chars} chars]"


def _compact_results_from_content(content: str) -> list[dict[str, str]]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    raw_results = parsed.get("results")
    if not isinstance(raw_results, list):
        return []
    compact: list[dict[str, str]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        compact.append(
            {
                "title": str(item.get("title") or url).strip(),
                "url": url,
                "snippet": str(item.get("snippet") or "").strip()[:500],
            }
        )
    return compact


def _build_summarized_tool_content(*, query: str, summary: str, orig_chars: int, compact_results: list[dict[str, str]]) -> str:
    payload: dict[str, Any] = {
        "ok": True,
        "query": query,
        "summary": summary,
        "results": compact_results,
        "summarized": True,
        "original_chars": orig_chars,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _run_with_timeout(fn, timeout: float) -> Any:
    """Run fn() on the shared bounded background executor with a timeout."""
    return run_with_timeout("web_search_summary", fn, timeout)


class WebSearchSummaryMiddleware(AgentMiddleware[AgentState]):
    """Summarizes oversized web_search tool results before they enter the context window.

    Handles both sync and async tool calls. Summarization only triggers when:
    - The tool name matches a web_search tool (see _WEB_SEARCH_TOOL_NAMES)
    - The result content exceeds ``web_search_summary.summary_threshold_chars``
    If the LLM call fails or times out, the original (possibly truncated) content is kept.
    """

    _WEB_SEARCH_TOOL_NAMES = frozenset(
        {
            "web_search",
            "search",
            "searxng",
            "tavily_search_results_json",
            "duckduckgo_search",
        }
    )

    def __init__(self, *, requested_model: str | None, router: Any = None):  # noqa: ARG002
        # ``router`` accepted for backwards compatibility; ignored (single-model invariant).
        del router
        super().__init__()
        self._requested_model = requested_model
        self._config = get_web_search_summary_config()

    def _is_web_search(self, tool_name: str | None) -> bool:
        if not tool_name:
            return False
        lower = tool_name.lower()
        return lower in self._WEB_SEARCH_TOOL_NAMES or "web_search" in lower or "searx" in lower

    def _build_prompt_and_model(self, query: str, content: str) -> tuple[str, str]:
        prompt = _SUMMARY_PROMPT_TEMPLATE.replace("{query}", query).replace("{raw_content}", content)
        # Single-model invariant: use the chat-selected model directly.
        model_name = resolve_model_name(self._requested_model)
        return prompt, model_name

    def _record_summarized(self, runtime: Any, tool_name: str, orig_chars: int, result: str, model_name: str) -> None:
        append_runtime_event(
            runtime,
            {
                "source": "web_search_summary",
                "tool": tool_name,
                "decision": "summarized",
                "orig_chars": orig_chars,
                "summary_chars": len(result),
                "model": model_name,
            },
        )

    def _summarize(self, query: str, content: str, runtime: Any, tool_name: str) -> str | None:
        orig_chars = len(content)
        if orig_chars <= self._config.summary_threshold_chars:
            return None

        prompt, model_name = self._build_prompt_and_model(query, content)

        def _call_llm() -> str:
            model = create_chat_model(name=model_name, thinking_enabled=False)
            response = model.invoke(prompt)
            raw = response.content if isinstance(response.content, str) else str(response.content)
            return raw.strip()

        try:
            summary = _run_with_timeout(_call_llm, timeout=self._config.timeout_seconds)
        except TimeoutError:
            logger.warning("Web search summary timed out for tool '%s'; keeping original", tool_name)
            append_runtime_event(runtime, {"source": "web_search_summary", "tool": tool_name, "decision": "timeout_skipped", "orig_chars": orig_chars})
            return None
        except Exception:
            logger.exception("Web search summary failed for tool '%s'; keeping original", tool_name)
            return None

        suffix = _SUMMARY_SUFFIX.replace("{orig_chars}", str(orig_chars))
        summary_text = summary + suffix
        compact_results = _compact_results_from_content(content)
        result = _build_summarized_tool_content(
            query=query,
            summary=summary_text,
            orig_chars=orig_chars,
            compact_results=compact_results,
        )
        self._record_summarized(runtime, tool_name, orig_chars, result, model_name)
        return result

    async def _asummarize(self, query: str, content: str, runtime: Any, tool_name: str) -> str | None:
        """Async summarize: uses model.ainvoke + asyncio.wait_for so N concurrent
        web_search results don't serialize through the event loop. The sync path
        used Thread.join(timeout) inside an async middleware, which blocked the
        loop for up to `timeout_seconds` per call — three concurrent searches
        thus waited 3x in series and routinely hit `decision=timeout_skipped`
        (see thread-cd90decb finding #3).
        """
        orig_chars = len(content)
        if orig_chars <= self._config.summary_threshold_chars:
            return None

        prompt, model_name = self._build_prompt_and_model(query, content)

        async def _acall_llm() -> str:
            model = create_chat_model(name=model_name, thinking_enabled=False)
            response = await model.ainvoke(prompt)
            raw = response.content if isinstance(response.content, str) else str(response.content)
            return raw.strip()

        try:
            summary = await asyncio.wait_for(_acall_llm(), timeout=self._config.timeout_seconds)
        except TimeoutError:
            logger.warning("Web search summary timed out for tool '%s'; keeping original", tool_name)
            append_runtime_event(runtime, {"source": "web_search_summary", "tool": tool_name, "decision": "timeout_skipped", "orig_chars": orig_chars})
            return None
        except Exception:
            logger.exception("Web search summary failed for tool '%s'; keeping original", tool_name)
            return None

        suffix = _SUMMARY_SUFFIX.replace("{orig_chars}", str(orig_chars))
        summary_text = summary + suffix
        compact_results = _compact_results_from_content(content)
        result = _build_summarized_tool_content(
            query=query,
            summary=summary_text,
            orig_chars=orig_chars,
            compact_results=compact_results,
        )
        self._record_summarized(runtime, tool_name, orig_chars, result, model_name)
        return result

    def _process_result(self, request: ToolCallRequest, result: ToolMessage | Command) -> ToolMessage | Command:
        if not isinstance(result, ToolMessage):
            return result
        content = getattr(result, "content", "")
        if not isinstance(content, str):
            return result
        tool_name = str(request.tool_call.get("name") or "")
        if not self._is_web_search(tool_name):
            return result
        if not self._config.enabled:
            return result
        if len(content) <= self._config.summary_threshold_chars:
            return result

        query = str((request.tool_call.get("args") or {}).get("query") or "")
        summary = self._summarize(query, content, request.runtime, tool_name)
        if summary is None:
            return result

        return ToolMessage(
            content=summary,
            tool_call_id=getattr(result, "tool_call_id", "") or request.tool_call.get("id", ""),
            name=tool_name or getattr(result, "name", None),
        )

    async def _aprocess_result(self, request: ToolCallRequest, result: ToolMessage | Command) -> ToolMessage | Command:
        if not isinstance(result, ToolMessage):
            return result
        content = getattr(result, "content", "")
        if not isinstance(content, str):
            return result
        tool_name = str(request.tool_call.get("name") or "")
        if not self._is_web_search(tool_name):
            return result
        if not self._config.enabled:
            return result
        if len(content) <= self._config.summary_threshold_chars:
            return result

        query = str((request.tool_call.get("args") or {}).get("query") or "")
        summary = await self._asummarize(query, content, request.runtime, tool_name)
        if summary is None:
            return result

        return ToolMessage(
            content=summary,
            tool_call_id=getattr(result, "tool_call_id", "") or request.tool_call.get("id", ""),
            name=tool_name or getattr(result, "name", None),
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler,
    ) -> ToolMessage | Command:
        result = handler(request)
        return self._process_result(request, result)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler,
    ) -> ToolMessage | Command:
        result = await handler(request)
        return await self._aprocess_result(request, result)
