"""Cap the size of tool ToolMessage content before it lands in agent state.

Background: in run-c0425b71bd, three parallel web_search results plus three
bash outputs ballooned the prompt across rounds. By the 4th model call the
prompt was large enough that the local model took 232s. Tool authors aren't
the right place to enforce a cap because the same tool might legitimately
return a large blob in another context — the right place is at the agent
boundary, just before the result is folded back into history.

Caps come from `routing.tool_result_caps` (per-tool) with a fallback to
`routing.tool_result_default_chars`. Set 0 in the per-tool map to disable
truncation for that tool. Truncation appends `TRUNCATION_MARKER` so the
model can detect and adapt.

Adaptive: web_search results that lack the WebSearchSummaryMiddleware marker
are truncated to `routing.unsummarized_web_search_chars` (default 3500)
instead of the regular `web_search` cap. This prevents synthesis from being
fed multiple raw 12 KB excerpts when summarization was skipped — the failure
mode in thread-cd90decb.
"""

from __future__ import annotations

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.routing_config import RoutingTimeoutsConfig, get_routing_config

logger = logging.getLogger(__name__)

TRUNCATION_MARKER = "\n\n[truncated by ToolResultTruncationMiddleware]"

# Substring that WebSearchSummaryMiddleware appends when it successfully
# summarized a result. Kept in sync with `_SUMMARY_SUFFIX` in that file.
_WEB_SEARCH_SUMMARY_MARKER = "[Summarized by web_search_summary_middleware"

_WEB_SEARCH_TOOL_NAMES = frozenset(
    {
        "web_search",
        "search",
        "searxng",
        "tavily_search_results_json",
        "duckduckgo_search",
    }
)


def _is_web_search(tool_name: str) -> bool:
    if not tool_name:
        return False
    lower = tool_name.lower()
    return lower in _WEB_SEARCH_TOOL_NAMES or "web_search" in lower or "searx" in lower


class ToolResultTruncationMiddleware(AgentMiddleware[AgentState]):
    """Clamp ToolMessage content to a per-tool char budget."""

    def __init__(self, config: RoutingTimeoutsConfig | None = None):
        super().__init__()
        self._config = config or get_routing_config().timeouts

    def _cap_for(self, tool_name: str, content: str) -> int | None:
        cap = self._config.truncation_cap_for(tool_name)
        if cap is None:
            return None
        # Adaptive: when the upstream summarizer skipped (timeout/failure),
        # the content lacks the summary marker. Drop to the smaller cap so
        # synthesis isn't drowning in raw HTML excerpts.
        if _is_web_search(tool_name) and _WEB_SEARCH_SUMMARY_MARKER not in content:
            adaptive_cap = int(self._config.unsummarized_web_search_chars)
            if adaptive_cap > 0 and adaptive_cap < cap:
                return adaptive_cap
        return cap

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        result = await handler(request)
        if not isinstance(result, ToolMessage):
            return result
        content = getattr(result, "content", "")
        if not isinstance(content, str):
            return result
        tool_name = str(request.tool_call.get("name") or "")
        cap = self._cap_for(tool_name, content)
        if cap is None or len(content) <= cap:
            return result
        truncated = content[: max(0, cap - len(TRUNCATION_MARKER))] + TRUNCATION_MARKER
        append_runtime_event(
            request.runtime,
            {
                "source": "tool_result_truncation_middleware",
                "tool": tool_name,
                "original_chars": len(content),
                "kept_chars": len(truncated),
                "summarized": _WEB_SEARCH_SUMMARY_MARKER in content,
            },
        )
        return ToolMessage(
            content=truncated,
            tool_call_id=getattr(result, "tool_call_id", "") or request.tool_call.get("id", ""),
            name=tool_name or getattr(result, "name", None),
        )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        return handler(request)
