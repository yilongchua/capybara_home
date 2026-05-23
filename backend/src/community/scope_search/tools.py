"""Scope-discovery search tool — a thin Plan-Mode wrapper around web_search.

The lead agent is given ``scope_search`` (instead of ``web_search``) while a
plan is in draft. This shapes behavior at the prompt level: the LLM literally
cannot call ``web_search`` because the tool is hidden from its catalog by
``PhaseToolFilterMiddleware``. ``scope_search`` exposes the same underlying
SearXNG/CapyHome backend with a smaller result cap and a different description
that frames the call as scope-discovery only — narrowing sub-topics, identifying
sources, definitions, or scope dimensions BEFORE the user approves the plan.

Full content-gathering happens in Work Mode via ``web_search`` after approval.
"""

from __future__ import annotations

from langchain.tools import tool

from src.community.web_search.tools import web_search_tool

_SCOPE_SEARCH_MAX_RESULTS = 3


@tool("scope_search", parse_docstring=True)
async def scope_search_tool(query: str) -> str:
    """Scope-discovery search for Plan Mode.

    Use this BEFORE plan approval to narrow research scope — identify sub-topics,
    candidate sources, definitions, or taxonomy. Returns at most 3 concise results.
    This is NOT for full content gathering; that happens in Work Mode via
    ``web_search`` after the plan is approved.

    Examples of appropriate scope queries:
        - "types of crystals studied in cultural anthropology"
        - "top sources for restaurant reviews"
        - "definition of grounding crystals"

    Examples of inappropriate (content-gathering) queries — wait for plan approval:
        - "crystals spiritual protection grounding luck love history"
        - "best Italian restaurants in San Francisco with reviews"

    Args:
        query: short scope-clarifying phrase. Keep it tight — under ~12 keywords.
    """
    # Delegate to web_search with a hard cap of 3 results. We invoke via the
    # tool's underlying coroutine so the caller-facing JSON shape matches what
    # the LLM already knows from web_search.
    return await web_search_tool.ainvoke({"query": query, "max_results": _SCOPE_SEARCH_MAX_RESULTS})
