"""Thread management APIs that coordinate LangGraph state and local thread files."""

from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config.paths import get_paths

router = APIRouter(prefix="/api", tags=["threads"])


def _langgraph_url() -> str:
    return os.getenv("CAPYBARA_LANGGRAPH_URL") or os.getenv("LANGGRAPH_URL") or "http://localhost:2024"


def _extract_status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _delete_thread_directory(thread_id: str) -> bool:
    thread_dir = get_paths().thread_dir(thread_id)
    if not thread_dir.exists():
        return False
    shutil.rmtree(thread_dir)
    return True


async def _delete_langgraph_thread(thread_id: str) -> bool:
    from langgraph_sdk import get_client

    client = get_client(url=_langgraph_url())
    try:
        await client.threads.delete(thread_id)
        return True
    except Exception as exc:
        if _extract_status_code(exc) == 404:
            return False
        raise


async def _list_thread_ids(limit: int = 100) -> list[str]:
    from langgraph_sdk import get_client

    client = get_client(url=_langgraph_url())
    thread_ids: list[str] = []
    offset = 0

    while True:
        page = await client.threads.search(limit=limit, offset=offset)
        if not page:
            break

        for item in page:
            if isinstance(item, dict):
                thread_id = item.get("thread_id")
            else:
                thread_id = getattr(item, "thread_id", None)
            if isinstance(thread_id, str) and thread_id:
                thread_ids.append(thread_id)

        if len(page) < limit:
            break
        offset += len(page)

    local_threads_dir = get_paths().base_dir / "threads"
    if local_threads_dir.exists():
        for entry in local_threads_dir.iterdir():
            if entry.is_dir():
                thread_ids.append(entry.name)

    return sorted(set(thread_ids))


class DeleteThreadResponse(BaseModel):
    thread_id: str
    deleted: bool = Field(description="True when the LangGraph thread existed and was deleted.")
    files_deleted: bool = Field(description="True when a local thread directory existed and was removed.")


class DeleteAllThreadsResponse(BaseModel):
    deleted_count: int
    files_deleted_count: int
    failed_thread_ids: list[str]


@router.delete(
    "/threads/{thread_id}",
    response_model=DeleteThreadResponse,
    summary="Delete Thread",
    description="Delete a thread's LangGraph history and remove its local thread directory.",
)
async def delete_thread(thread_id: str) -> DeleteThreadResponse:
    try:
        deleted = await _delete_langgraph_thread(thread_id)
        files_deleted = _delete_thread_directory(thread_id)
        return DeleteThreadResponse(
            thread_id=thread_id,
            deleted=deleted,
            files_deleted=files_deleted,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to delete thread: {exc}") from exc


@router.delete(
    "/threads",
    response_model=DeleteAllThreadsResponse,
    summary="Delete All Threads",
    description="Delete all LangGraph threads and remove their local thread directories.",
)
async def delete_all_threads() -> DeleteAllThreadsResponse:
    thread_ids = await _list_thread_ids()
    failed_thread_ids: list[str] = []
    deleted_count = 0
    files_deleted_count = 0

    for thread_id in thread_ids:
        try:
            deleted = await _delete_langgraph_thread(thread_id)
            files_deleted = _delete_thread_directory(thread_id)
        except Exception:
            failed_thread_ids.append(thread_id)
            continue

        if deleted:
            deleted_count += 1
        if files_deleted:
            files_deleted_count += 1

    return DeleteAllThreadsResponse(
        deleted_count=deleted_count,
        files_deleted_count=files_deleted_count,
        failed_thread_ids=failed_thread_ids,
    )
