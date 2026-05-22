"""Scope-discovery search tool for Plan Mode.

Exposes ``scope_search_tool`` — a thin wrapper around ``web_search_tool`` that
caps results at 3 and frames the tool as scope-discovery only. Used during
Plan Mode (before a plan is approved) so the LLM can narrow scope without
performing full content-gathering research.
"""

from .tools import scope_search_tool

__all__ = ["scope_search_tool"]
