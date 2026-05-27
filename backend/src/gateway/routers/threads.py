"""Thread management APIs that coordinate LangGraph state and local thread files."""

from __future__ import annotations

import os
import shutil
from time import time
from uuid import uuid4

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


def _thread_id_candidates(thread_id: str) -> list[str]:
    candidates: list[str] = []
    for candidate in (thread_id, thread_id.strip("/").split("/")[-1]):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _delete_thread_directory(thread_id: str) -> bool:
    files_deleted = False
    for candidate in _thread_id_candidates(thread_id):
        try:
            thread_dir = get_paths().thread_dir(candidate)
        except ValueError:
            continue
        if thread_dir.exists():
            shutil.rmtree(thread_dir)
            files_deleted = True
    return files_deleted


async def _delete_langgraph_thread(thread_id: str) -> bool:
    from langgraph_sdk import get_client

    client = get_client(url=_langgraph_url())
    first_error: Exception | None = None
    saw_not_found = False

    for candidate in _thread_id_candidates(thread_id):
        try:
            await client.threads.delete(candidate)
            return True
        except Exception as exc:
            if _extract_status_code(exc) == 404:
                saw_not_found = True
                continue
            if first_error is None:
                first_error = exc
            continue

    if first_error is not None:
        raise first_error
    if saw_not_found:
        return False
    return False


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


class HardStopThreadResponse(BaseModel):
    thread_id: str
    cancelled_subagents: int
    patched_tool_calls: int
    state_patched: bool


_NON_BLOCKING_TOOL_CALL_NAMES = {"ask_user_for_clarification", "present_files"}


def _extract_state_values(state: object) -> dict:
    values = state.get("values") if isinstance(state, dict) else getattr(state, "values", None)
    return values if isinstance(values, dict) else {}


def _message_type(message: object) -> str | None:
    if isinstance(message, dict):
        raw = message.get("type")
    else:
        raw = getattr(message, "type", None)
    return str(raw) if raw is not None else None


def _tool_call_id(message: object) -> str | None:
    if isinstance(message, dict):
        raw = message.get("tool_call_id")
    else:
        raw = getattr(message, "tool_call_id", None)
    return str(raw) if raw is not None else None


def _tool_calls(message: object) -> list[dict]:
    raw = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
    return [item for item in (raw or []) if isinstance(item, dict)]


def _patch_dangling_tool_calls(messages: list[object]) -> tuple[list[object], int]:
    if not messages:
        return messages, 0

    last_human_index = -1
    for index in range(len(messages) - 1, -1, -1):
        if _message_type(messages[index]) == "human":
            last_human_index = index
            break

    existing_tool_ids = {
        tool_call_id
        for message in messages[last_human_index + 1 :]
        if _message_type(message) == "tool"
        for tool_call_id in [_tool_call_id(message)]
        if tool_call_id
    }
    patched_tool_ids: set[str] = set()
    patched_count = 0
    next_messages: list[object] = []

    for index, message in enumerate(messages):
        next_messages.append(message)
        if index <= last_human_index or _message_type(message) != "ai":
            continue
        for tool_call in _tool_calls(message):
            tool_call_id = str(tool_call.get("id") or "").strip()
            tool_name = str(tool_call.get("name") or "unknown").strip() or "unknown"
            if (
                not tool_call_id
                or tool_call_id in existing_tool_ids
                or tool_call_id in patched_tool_ids
                or tool_name in _NON_BLOCKING_TOOL_CALL_NAMES
            ):
                continue
            next_messages.append(
                {
                    "id": f"hard-stop-tool-{tool_call_id}-{uuid4()}",
                    "type": "tool",
                    "name": tool_name,
                    "tool_call_id": tool_call_id,
                    "status": "error",
                    "content": "[run_stopped]\nTool call was stopped by the user before it returned a result.",
                }
            )
            patched_tool_ids.add(tool_call_id)
            patched_count += 1

    return next_messages, patched_count


def _stopped_work_mode(values: dict) -> dict | None:
    work_mode = values.get("work_mode")
    if not isinstance(work_mode, dict):
        return None
    return {
        **work_mode,
        "active": False,
        "stopped": True,
        "stopped_at": time(),
    }


@router.post(
    "/threads/{thread_id}/hard-stop",
    response_model=HardStopThreadResponse,
    summary="Hard Stop Thread",
    description="Stop app-managed background work and patch dangling tool calls left by an interrupted run.",
)
async def hard_stop_thread(thread_id: str) -> HardStopThreadResponse:
    try:
        from langgraph_sdk import get_client

        from src.subagents.executor import cancel_background_tasks_for_thread

        client = get_client(url=_langgraph_url())
        state = await client.threads.get_state(thread_id)
        values = _extract_state_values(state)
        messages = values.get("messages")
        next_messages, patched_tool_calls = _patch_dangling_tool_calls(messages if isinstance(messages, list) else [])
        cancelled_subagents = cancel_background_tasks_for_thread(thread_id)

        update_payload: dict = {}
        if patched_tool_calls > 0:
            update_payload["messages"] = next_messages
        stopped_work_mode = _stopped_work_mode(values)
        if stopped_work_mode is not None:
            update_payload["work_mode"] = stopped_work_mode

        if update_payload:
            await client.threads.update_state(thread_id, update_payload)

        return HardStopThreadResponse(
            thread_id=thread_id,
            cancelled_subagents=cancelled_subagents,
            patched_tool_calls=patched_tool_calls,
            state_patched=bool(update_payload),
        )
    except HTTPException:
        raise
    except Exception as exc:
        status_code = _extract_status_code(exc)
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.") from exc
        raise HTTPException(status_code=502, detail=f"Failed to hard-stop thread: {exc}") from exc


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
