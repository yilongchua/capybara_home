"""Tests for bounded background executor helpers."""

from __future__ import annotations

from threading import Semaphore
from unittest.mock import MagicMock

import pytest

import src.agents.background as background_module


def test_submit_background_task_releases_capacity_when_submit_fails(monkeypatch):
    cap = Semaphore(1)
    monkeypatch.setattr(background_module, "_CAPACITY", cap)
    failing_executor = MagicMock()
    failing_executor.submit.side_effect = RuntimeError("executor closed")
    monkeypatch.setattr(background_module, "_EXECUTOR", failing_executor)

    assert background_module.submit_background_task("x", lambda: None) is False
    # Permit should be released after submit failure.
    assert cap.acquire(blocking=False) is True


def test_run_with_timeout_releases_capacity_when_cancelled_before_start(monkeypatch):
    cap = Semaphore(1)
    monkeypatch.setattr(background_module, "_CAPACITY", cap)

    pending_future = MagicMock()
    pending_future.result.side_effect = background_module.FutureTimeoutError()
    pending_future.cancel.return_value = True
    fake_executor = MagicMock()
    fake_executor.submit.return_value = pending_future
    monkeypatch.setattr(background_module, "_EXECUTOR", fake_executor)

    with pytest.raises(TimeoutError):
        background_module.run_with_timeout("y", lambda: "ok", timeout=0.01)
    # Permit should be released when cancel succeeded before task start.
    assert cap.acquire(blocking=False) is True
