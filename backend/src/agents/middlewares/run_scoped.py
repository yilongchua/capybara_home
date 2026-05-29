"""Per-runtime scratch storage for middleware coordination.

This is intentionally not part of ThreadState: values stored here are transient
within one LangGraph run and should not be checkpointed.
"""

from __future__ import annotations

from threading import Lock
from typing import Any
from weakref import WeakKeyDictionary

from langgraph.runtime import Runtime

_RUN_STORES: WeakKeyDictionary[Runtime, dict[str, Any]] = WeakKeyDictionary()
_FALLBACK_STORES: dict[int, dict[str, Any]] = {}
_LOCK = Lock()


def get_run_store(runtime: Runtime | None) -> dict[str, Any]:
    """Return mutable scratch storage scoped to *runtime* identity."""
    if runtime is None:
        return {}
    with _LOCK:
        try:
            store = _RUN_STORES.get(runtime)
        except TypeError:
            store = _FALLBACK_STORES.get(id(runtime))
            if store is None:
                store = {}
                _FALLBACK_STORES[id(runtime)] = store
            return store
        if store is None:
            store = {}
            _RUN_STORES[runtime] = store
        return store


def clear_run_store_key(runtime: Runtime | None, key: str) -> None:
    if runtime is None:
        return
    with _LOCK:
        try:
            store = _RUN_STORES.get(runtime)
        except TypeError:
            store = _FALLBACK_STORES.get(id(runtime))
        if isinstance(store, dict):
            store.pop(key, None)
