"""Shared timeout helper for middleware LLM calls.

Used by sync code paths that need a hard wall-clock cap on a blocking call
(e.g. ``model.invoke``). Async paths should prefer ``asyncio.wait_for``.

Caveat: the daemon thread keeps running in the background after ``TimeoutError``
is raised — we stop *waiting*, we do not interrupt the underlying HTTP/socket
work. This is acceptable for our use case (the thread dies with the process)
but callers should not assume side effects are cancelled.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


def run_with_timeout(fn: Callable[[], Any], timeout: float, label: str = "operation") -> Any:
    """Run ``fn()`` in a daemon thread, raising ``TimeoutError`` after ``timeout`` seconds."""
    result_holder: list[Any] = [None]
    exc_holder: list[BaseException | None] = [None]

    def worker() -> None:
        try:
            result_holder[0] = fn()
        except Exception as e:  # noqa: BLE001
            exc_holder[0] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise TimeoutError(f"{label} timed out after {timeout}s")
    if exc_holder[0] is not None:
        raise exc_holder[0]
    return result_holder[0]
