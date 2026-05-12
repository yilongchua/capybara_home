"""Utilities for cross-middleware runtime events.

The event bus lives on ``runtime.context`` as a pragmatic shortcut: a per-run
scratch channel between middlewares that does not deserve its own ThreadState
reducer.

Multiple consumers (e.g. trajectory logger + execution trace persistence)
need to read the same events. We therefore maintain per-consumer cursors rather
than globally popping the queue on first read.
"""

from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Any

from langgraph.runtime import Runtime

RUNTIME_EVENTS_KEY = "_phase_a_runtime_events"
RUNTIME_EVENTS_CURSOR_KEY = "_phase_a_runtime_events_cursor"
_EVENTS_LOCK = Lock()


def append_runtime_event(runtime: Runtime, event: dict[str, Any]) -> None:
    """Append a structured runtime event for other middlewares to consume."""
    context = getattr(runtime, "context", None)
    if context is None:
        return
    with _EVENTS_LOCK:
        events = context.get(RUNTIME_EVENTS_KEY)
        if not isinstance(events, list):
            events = []
            context[RUNTIME_EVENTS_KEY] = events
        events.append(deepcopy(event))


def _compact_runtime_events(context: dict[str, Any]) -> None:
    events = context.get(RUNTIME_EVENTS_KEY)
    cursors = context.get(RUNTIME_EVENTS_CURSOR_KEY)
    if not isinstance(events, list) or not isinstance(cursors, dict) or not events:
        return

    valid_cursor_values: list[int] = []
    for value in cursors.values():
        if isinstance(value, int) and value >= 0:
            valid_cursor_values.append(value)
    # Keep the queue intact until we have at least two active consumers.
    # This prevents early readers from compacting events before the second
    # consumer (e.g. execution_trace vs trajectory) has observed them.
    if len(valid_cursor_values) < 2:
        return
    if not valid_cursor_values:
        return

    min_cursor = min(valid_cursor_values)
    if min_cursor <= 0:
        return
    if min_cursor >= len(events):
        context[RUNTIME_EVENTS_KEY] = []
        for key in list(cursors.keys()):
            cursors[key] = 0
        return

    context[RUNTIME_EVENTS_KEY] = events[min_cursor:]
    for key, value in list(cursors.items()):
        if isinstance(value, int):
            cursors[key] = max(0, value - min_cursor)


def drain_runtime_events(runtime: Runtime, *, consumer: str = "default") -> list[dict[str, Any]]:
    """Return pending runtime events for a named consumer.

    Consumers read from independent cursors, so one reader does not starve the
    others. Each call advances that consumer's cursor.
    """
    context = getattr(runtime, "context", None)
    if context is None:
        return []
    with _EVENTS_LOCK:
        events = context.get(RUNTIME_EVENTS_KEY, [])
        if not isinstance(events, list):
            return []

        cursor_map = context.get(RUNTIME_EVENTS_CURSOR_KEY)
        if not isinstance(cursor_map, dict):
            cursor_map = {}
            context[RUNTIME_EVENTS_CURSOR_KEY] = cursor_map

        start = cursor_map.get(consumer, 0)
        if not isinstance(start, int) or start < 0:
            start = 0
        start = min(start, len(events))
        pending = events[start:]
        cursor_map[consumer] = len(events)
        _compact_runtime_events(context)
    return [e for e in pending if isinstance(e, dict)]
