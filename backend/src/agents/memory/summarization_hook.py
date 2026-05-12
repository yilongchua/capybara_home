"""Hook that flushes conversation to memory before summarization compresses it away."""

from __future__ import annotations

import logging

from src.agents.memory.queue import get_memory_queue
from src.agents.middlewares.memory_middleware import filter_messages_for_memory
from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.memory_config import get_memory_config

logger = logging.getLogger(__name__)


def memory_flush_hook(event) -> None:
    """Capture messages-about-to-be-summarized into long-term memory immediately.

    SummarizationMiddleware fires this hook before compressing old messages out of
    the context window.  Without this hook those messages are gone from state before
    the MemoryMiddleware's debounce timer fires, so any insights they contain are
    permanently lost.  By calling ``queue_immediate`` here we bypass the debounce
    and start a background thread that extracts facts from the to-be-summarized
    segment while they are still available.

    The hook is intentionally fire-and-forget: it must not raise or block the
    summarization path.
    """
    if not get_memory_config().enabled or not event.thread_id:
        return

    try:
        filtered = filter_messages_for_memory(list(event.messages_to_summarize))
    except Exception:
        logger.exception("memory_flush_hook: message filtering failed; skipping")
        return

    user_msgs = [m for m in filtered if getattr(m, "type", None) == "human"]
    ai_msgs = [m for m in filtered if getattr(m, "type", None) == "ai"]
    if not user_msgs or not ai_msgs:
        return

    try:
        queue = get_memory_queue()
        queue.queue_immediate(
            thread_id=event.thread_id,
            messages=filtered,
            agent_name=event.agent_name,
            workspace_id=event.thread_id,
        )
    except Exception:
        logger.exception("memory_flush_hook: queue_immediate failed; skipping")
        try:
            append_runtime_event(
                event.runtime,
                {
                    "source": "memory_flush_hook",
                    "event": "memory_flush_failed",
                    "thread_id": event.thread_id,
                    "message_count": len(filtered),
                },
            )
        except Exception:
            logger.error("memory_flush_hook: failed to emit failure runtime event")
