"""Utilities for cross-middleware runtime events.

The event bus lives in run-scoped scratch storage, not ThreadState. Events are
transient coordination signals between middlewares and should not be
checkpointed.

Multiple consumers (e.g. trajectory logger + execution trace persistence)
need to read the same events. We therefore maintain per-consumer cursors rather
than globally popping the queue on first read.
"""

from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Any

from langgraph.runtime import Runtime

from src.agents.middlewares.run_scoped import get_run_store

RUNTIME_EVENTS_KEY = "_phase_a_runtime_events"
RUNTIME_EVENTS_CURSOR_KEY = "_phase_a_runtime_events_cursor"
RUNTIME_EVENTS_SINGLE_CONSUMER_GRACE_KEY = "_phase_a_runtime_events_single_consumer_grace"
_EVENTS_LOCK = Lock()


def append_runtime_event(runtime: Runtime, event: dict[str, Any]) -> None:
    """Append a structured runtime event for other middlewares to consume."""
    store = get_run_store(runtime)
    with _EVENTS_LOCK:
        events = store.get(RUNTIME_EVENTS_KEY)
        if not isinstance(events, list):
            events = []
            store[RUNTIME_EVENTS_KEY] = events
        events.append(deepcopy(event))


def _compact_runtime_events(store: dict[str, Any]) -> None:
    events = store.get(RUNTIME_EVENTS_KEY)
    cursors = store.get(RUNTIME_EVENTS_CURSOR_KEY)
    if not isinstance(events, list) or not isinstance(cursors, dict) or not events:
        return

    valid_cursor_values: list[int] = []
    for value in cursors.values():
        if isinstance(value, int) and value >= 0:
            valid_cursor_values.append(value)
    if len(valid_cursor_values) < 2:
        # Keep a one-drain grace period before compacting for a sole consumer.
        # This preserves the existing late-consumer handoff within a middleware
        # cycle, while preventing unbounded queues when only one consumer is
        # enabled for a long-running thread.
        if len(cursors) != 1:
            return
        consumer, value = next(iter(cursors.items()))
        if not isinstance(value, int) or value <= 0:
            return
        if store.get(RUNTIME_EVENTS_SINGLE_CONSUMER_GRACE_KEY) != consumer:
            store[RUNTIME_EVENTS_SINGLE_CONSUMER_GRACE_KEY] = consumer
            return
        min_cursor = min(value, len(events))
        if min_cursor >= len(events):
            store[RUNTIME_EVENTS_KEY] = []
            cursors[consumer] = 0
        else:
            store[RUNTIME_EVENTS_KEY] = events[min_cursor:]
            cursors[consumer] = max(0, value - min_cursor)
        store.pop(RUNTIME_EVENTS_SINGLE_CONSUMER_GRACE_KEY, None)
        return

    min_cursor = min(valid_cursor_values)
    if min_cursor <= 0:
        return
    if min_cursor >= len(events):
        store[RUNTIME_EVENTS_KEY] = []
        for key in list(cursors.keys()):
            cursors[key] = 0
        store.pop(RUNTIME_EVENTS_SINGLE_CONSUMER_GRACE_KEY, None)
        return

    store[RUNTIME_EVENTS_KEY] = events[min_cursor:]
    for key, value in list(cursors.items()):
        if isinstance(value, int):
            cursors[key] = max(0, value - min_cursor)
    store.pop(RUNTIME_EVENTS_SINGLE_CONSUMER_GRACE_KEY, None)


def drain_runtime_events(runtime: Runtime, *, consumer: str = "default") -> list[dict[str, Any]]:
    """Return pending runtime events for a named consumer.

    Consumers read from independent cursors, so one reader does not starve the
    others. Each call advances that consumer's cursor.
    """
    store = get_run_store(runtime)
    with _EVENTS_LOCK:
        events = store.get(RUNTIME_EVENTS_KEY, [])
        if not isinstance(events, list):
            return []

        cursor_map = store.get(RUNTIME_EVENTS_CURSOR_KEY)
        if not isinstance(cursor_map, dict):
            cursor_map = {}
            store[RUNTIME_EVENTS_CURSOR_KEY] = cursor_map

        start = cursor_map.get(consumer, 0)
        if not isinstance(start, int) or start < 0:
            start = 0
        start = min(start, len(events))
        pending = events[start:]
        cursor_map[consumer] = len(events)
        _compact_runtime_events(store)
    return [e for e in pending if isinstance(e, dict)]
