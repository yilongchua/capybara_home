"""Tests for thread deletion gateway routes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.config.paths import Paths
from src.gateway.routers import threads


class _ThreadsClient:
    def __init__(self, existing_thread_ids: set[str] | None = None, failing_thread_ids: set[str] | None = None):
        self.deleted: list[str] = []
        self.existing_thread_ids = existing_thread_ids or set()
        self.failing_thread_ids = failing_thread_ids or set()

    async def delete(self, thread_id: str):
        if thread_id in self.failing_thread_ids:
            raise RuntimeError(f"boom:{thread_id}")
        if thread_id not in self.existing_thread_ids:
            raise _NotFoundError("missing")
        self.deleted.append(thread_id)
        self.existing_thread_ids.remove(thread_id)

    async def search(self, *, limit: int, offset: int):  # noqa: ARG002
        items = sorted(self.existing_thread_ids)
        page = items[offset : offset + limit]
        return [{"thread_id": thread_id} for thread_id in page]


class _Client:
    def __init__(self, thread_client: _ThreadsClient):
        self.threads = thread_client


class _NotFoundError(Exception):
    status_code = 404


@pytest.fixture()
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    paths = Paths(tmp_path)
    monkeypatch.setattr(threads, "get_paths", lambda: paths)
    return paths


def test_delete_thread_removes_langgraph_history_and_local_files(paths: Paths, monkeypatch: pytest.MonkeyPatch):
    thread_id = "thread-1"
    thread_dir = paths.thread_dir(thread_id)
    (thread_dir / "user-data" / "workspace").mkdir(parents=True)
    (thread_dir / "user-data" / "workspace" / "plan.md").write_text("test", encoding="utf-8")

    client = _ThreadsClient(existing_thread_ids={thread_id})
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(client))

    response = asyncio.run(threads.delete_thread(thread_id))

    assert response.thread_id == thread_id
    assert response.deleted is True
    assert response.files_deleted is True
    assert client.deleted == [thread_id]
    assert not thread_dir.exists()


def test_delete_thread_is_idempotent_when_langgraph_or_files_are_missing(paths: Paths, monkeypatch: pytest.MonkeyPatch):
    thread_id = "thread-missing"
    client = _ThreadsClient(existing_thread_ids=set())
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(client))

    response = asyncio.run(threads.delete_thread(thread_id))

    assert response.deleted is False
    assert response.files_deleted is False


def test_delete_all_threads_deletes_each_thread_and_reports_failures(paths: Paths, monkeypatch: pytest.MonkeyPatch):
    for thread_id in ("thread-a", "thread-b", "thread-c"):
        (paths.thread_dir(thread_id) / "user-data" / "workspace").mkdir(parents=True)

    client = _ThreadsClient(
        existing_thread_ids={"thread-a", "thread-b", "thread-c"},
        failing_thread_ids={"thread-b"},
    )
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(client))

    response = asyncio.run(threads.delete_all_threads())

    assert response.deleted_count == 2
    assert response.files_deleted_count == 2
    assert response.failed_thread_ids == ["thread-b"]
    assert not paths.thread_dir("thread-a").exists()
    assert paths.thread_dir("thread-b").exists()
    assert not paths.thread_dir("thread-c").exists()
