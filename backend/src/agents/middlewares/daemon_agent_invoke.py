"""Invoke LangGraph agents from sync daemon threads when tools are async-only."""

from __future__ import annotations

import asyncio
from typing import Any


def invoke_agent_async(
    agent: Any,
    state: dict[str, Any],
    *,
    config: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    """Run ``agent.ainvoke`` from a sync context (e.g. a ``threading.Thread`` worker).

    Tools such as ``web_search`` are async-only and raise
    ``NotImplementedError('StructuredTool does not support sync invocation.')``
    when the graph is driven with sync ``invoke()``. Background handoffs must use
    this helper instead.
    """
    return asyncio.run(agent.ainvoke(state, config=config, context=context))
