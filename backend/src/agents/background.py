"""Shared bounded executor for best-effort background agent work."""

from __future__ import annotations

import atexit
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Semaphore
from typing import Any

logger = logging.getLogger(__name__)

_MAX_WORKERS = max(1, int(os.getenv("CAPYHOME_BACKGROUND_MAX_WORKERS", "4")))
_MAX_QUEUED = max(_MAX_WORKERS, int(os.getenv("CAPYHOME_BACKGROUND_MAX_QUEUED", "32")))
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="capyhome-bg")
_CAPACITY = Semaphore(_MAX_QUEUED)


def _shutdown_executor() -> None:
    _EXECUTOR.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_executor)


def submit_background_task(name: str, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> bool:
    """Submit background work if executor capacity is available."""
    if not _CAPACITY.acquire(blocking=False):
        logger.warning("Background executor is full; dropping task %s", name)
        return False

    def _run() -> None:
        try:
            fn(*args, **kwargs)
        finally:
            _CAPACITY.release()

    try:
        _EXECUTOR.submit(_run)
    except RuntimeError:
        _CAPACITY.release()
        logger.warning("Background executor rejected task %s", name, exc_info=True)
        return False
    return True


def run_with_timeout(name: str, fn: Callable[[], Any], timeout: float) -> Any:
    """Run a callable on the shared executor and wait up to *timeout* seconds."""
    if not _CAPACITY.acquire(blocking=False):
        raise TimeoutError(f"Background executor is full before {name}")

    def _run() -> Any:
        try:
            return fn()
        finally:
            _CAPACITY.release()

    future = _EXECUTOR.submit(_run)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        if future.cancel():
            # If the task never started, _run() won't release the permit.
            _CAPACITY.release()
        raise TimeoutError(f"{name} timed out after {timeout}s") from exc
