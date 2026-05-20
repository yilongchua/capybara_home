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


def _is_sync_sqlite_async_invocation_error(exc: BaseException) -> bool:
    message = str(exc)
    return "SqliteSaver does not support async methods" in message


async def _ainvoke_with_temporary_async_checkpointer(
    client: Any,
    state: dict[str, Any],
    *,
    config: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    """Retry ``ainvoke`` using an async checkpointer for daemon-only flows.

    Background daemon flows run ``ainvoke`` from a sync thread and can hit a
    sync/async checkpoint mismatch when the default cached checkpointer is a
    ``SqliteSaver``. We recover by rebuilding the agent with a temporary async
    checkpointer for this one invocation.
    """
    from src.agents.checkpointer.async_provider import make_checkpointer

    original_checkpointer = getattr(client, "_checkpointer", None)
    original_agent = getattr(client, "_agent", None)
    original_agent_config_key = getattr(client, "_agent_config_key", None)

    async with make_checkpointer() as async_checkpointer:
        try:
            client._checkpointer = async_checkpointer  # noqa: SLF001
            client.reset_agent()  # noqa: SLF001
            client._ensure_agent(config)  # noqa: SLF001
            return await client._agent.ainvoke(state, config=config, context=context)  # noqa: SLF001
        finally:
            # Restore the previous client state so daemon retries remain isolated.
            client._checkpointer = original_checkpointer  # noqa: SLF001
            client._agent = original_agent  # noqa: SLF001
            client._agent_config_key = original_agent_config_key  # noqa: SLF001


def invoke_client_agent_async(
    client: Any,
    state: dict[str, Any],
    *,
    config: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    """Run client agent ``ainvoke`` from a daemon thread with async-CP recovery."""
    client._ensure_agent(config)  # noqa: SLF001
    try:
        return invoke_agent_async(
            client._agent,  # noqa: SLF001
            state,
            config=config,
            context=context,
        )
    except Exception as exc:
        if not _is_sync_sqlite_async_invocation_error(exc):
            raise
        return asyncio.run(
            _ainvoke_with_temporary_async_checkpointer(
                client,
                state,
                config=config,
                context=context,
            )
        )
