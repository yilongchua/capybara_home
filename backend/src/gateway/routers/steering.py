"""Steering API for queued one-shot thread steering intent injection."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.memory.compaction_archive import append_compaction_entry
from src.agents.steering_queue_store import enqueue_steering_intent

router = APIRouter(prefix="/api", tags=["steering"])

_MAX_STEERING_CHARS = 4000
_COMPACTION_KEEP_RECENT = 12
_COMPACTION_MIN_MESSAGES = 16


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


class SteerRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=_MAX_STEERING_CHARS, description="One-shot steering text.")
    intent_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional client-provided idempotency key for steering intent append.",
    )


class SteerResponse(BaseModel):
    thread_id: str
    acknowledged: bool
    intent_id: str
    status: Literal["accepted", "duplicate", "conflict", "failed"]


class ExecutePlanRequest(BaseModel):
    plan_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional explicit plan id to execute; defaults to current active plan.",
    )


class ExecutePlanResponse(BaseModel):
    thread_id: str
    acknowledged: bool
    plan_id: str | None = None
    plan_status: str | None = None
    status: Literal["accepted", "duplicate", "conflict", "failed"]


class CompactThreadResponse(BaseModel):
    thread_id: str
    status: Literal["accepted", "no_op", "failed"]
    message: str
    compressed_messages: int = 0
    kept_messages: int = 0


def _extract_state_values(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        values = raw.get("values")
        if isinstance(values, dict):
            return values
        return raw
    values = getattr(raw, "values", None)
    if isinstance(values, dict):
        return values
    return {}


def _normalized_pending_intents(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        message = entry.get("message")
        intent_id = entry.get("intent_id")
        if not isinstance(message, str) or not isinstance(intent_id, str):
            continue
        message_stripped = message.strip()
        intent_id_stripped = intent_id.strip()
        if not message_stripped or not intent_id_stripped:
            continue
        created_at = entry.get("created_at")
        created_at_value = created_at.strip() if isinstance(created_at, str) and created_at.strip() else datetime.now(UTC).isoformat()
        normalized.append(
            {
                "intent_id": intent_id_stripped,
                "message": message_stripped,
                "created_at": created_at_value,
            }
        )
    return normalized


def _detail_with_status(status: str, message: str) -> dict[str, str]:
    return {"status": status, "detail": message}


def _as_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return raw


def _as_plan_history(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _message_type(message: Any) -> str:
    if isinstance(message, dict):
        raw = message.get("type")
        if isinstance(raw, str):
            return raw
        role = message.get("role")
        if isinstance(role, str):
            role_lower = role.lower()
            if role_lower == "user":
                return "human"
            if role_lower == "assistant":
                return "ai"
            return role_lower
    return ""


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return " ".join(parts).strip()
    return ""


def _tool_call_ids(message: Any) -> set[str]:
    if not isinstance(message, dict):
        return set()
    raw_tool_calls = message.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        additional_kwargs = message.get("additional_kwargs")
        if isinstance(additional_kwargs, dict):
            raw_tool_calls = additional_kwargs.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return set()
    ids: set[str] = set()
    for tool_call in raw_tool_calls:
        if not isinstance(tool_call, dict):
            continue
        tool_call_id = tool_call.get("id")
        if isinstance(tool_call_id, str) and tool_call_id.strip():
            ids.add(tool_call_id.strip())
    return ids


def _tool_message_call_id(message: Any) -> str | None:
    if not isinstance(message, dict) or _message_type(message) != "tool":
        return None
    raw = message.get("tool_call_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _safe_compaction_cutoff(messages: list[Any], desired_cutoff: int) -> int:
    """Move cutoff back so preserved tool messages keep their AI tool calls."""
    cutoff = max(0, min(desired_cutoff, len(messages)))
    while cutoff > 0:
        preserved = messages[cutoff:]
        preserved_tool_calls: set[str] = set()
        orphan_tool_id: str | None = None
        for msg in preserved:
            preserved_tool_calls.update(_tool_call_ids(msg))
            tool_call_id = _tool_message_call_id(msg)
            if tool_call_id and tool_call_id not in preserved_tool_calls:
                orphan_tool_id = tool_call_id
                break
        if orphan_tool_id is None:
            return cutoff
        matching_ai_index = next(
            (
                index
                for index in range(cutoff - 1, -1, -1)
                if orphan_tool_id in _tool_call_ids(messages[index])
            ),
            None,
        )
        if matching_ai_index is None:
            # Existing history is already malformed; skip the orphan instead of
            # preserving an invalid tool message after the synthetic summary.
            first_orphan = next(
                (
                    index
                    for index in range(cutoff, len(messages))
                    if _tool_message_call_id(messages[index]) == orphan_tool_id
                ),
                cutoff,
            )
            cutoff = min(len(messages), first_orphan + 1)
            continue
        cutoff = matching_ai_index
    return cutoff


def _compact_messages(messages: list[Any]) -> tuple[list[Any], dict[str, Any]] | None:
    if len(messages) < _COMPACTION_MIN_MESSAGES:
        return None

    cutoff = _safe_compaction_cutoff(messages, len(messages) - _COMPACTION_KEEP_RECENT)
    compressed = messages[:cutoff]
    preserved = messages[-_COMPACTION_KEEP_RECENT:]
    if cutoff != len(messages) - _COMPACTION_KEEP_RECENT:
        preserved = messages[cutoff:]
    if len(compressed) < 2:
        return None

    recent_user = next(
        (_message_text(msg) for msg in reversed(compressed) if _message_type(msg) == "human" and _message_text(msg)),
        "",
    )
    recent_ai = next(
        (_message_text(msg) for msg in reversed(compressed) if _message_type(msg) == "ai" and _message_text(msg)),
        "",
    )
    compressed_turns = len(
        [msg for msg in compressed if _message_type(msg) in {"human", "ai"}],
    )

    summary_lines = [
        "[summary_quality:fallback]",
        "[summary_source:manual_compaction]",
        "Manual compaction summary generated by /compact.",
        "",
        f"- Compressed turns: {compressed_turns}",
        f"- Recent user intent: {recent_user[:280] if recent_user else 'N/A'}",
        f"- Recent assistant response: {recent_ai[:280] if recent_ai else 'N/A'}",
    ]
    summary_message = {
        "id": f"manual-compaction-{uuid4()}",
        "type": "ai",
        "content": "\n".join(summary_lines),
    }
    next_messages = [summary_message, *preserved]
    metadata = {
        "messages_compressed": len(compressed),
        "messages_kept": len(next_messages),
        "summary_text": summary_message["content"],
    }
    return next_messages, metadata


@router.post(
    "/threads/{thread_id}/steer",
    response_model=SteerResponse,
    summary="Inject Steering Context",
    description="Append one-shot steering intent for injection before the next available model turn.",
)
async def steer_thread(thread_id: str, request: SteerRequest) -> SteerResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be blank.")
    if len(message) > _MAX_STEERING_CHARS:
        raise HTTPException(status_code=422, detail=f"message exceeds max length {_MAX_STEERING_CHARS}.")
    intent_id = request.intent_id.strip() if isinstance(request.intent_id, str) else str(uuid4())
    if not intent_id:
        raise HTTPException(status_code=422, detail="intent_id must not be blank when provided.")

    try:
        from langgraph_sdk import get_client

        client = get_client(url=_langgraph_url())
        # Keep explicit not-found semantics for unknown thread IDs.
        await client.threads.get_state(thread_id)

        enqueue_result = enqueue_steering_intent(
            thread_id=thread_id,
            intent_id=intent_id,
            message=message,
            created_at=datetime.now(UTC).isoformat(),
        )
        if enqueue_result["status"] == "conflict":
            raise HTTPException(
                status_code=409,
                detail=_detail_with_status(
                    "conflict",
                    "intent_id already exists with a different message.",
                ),
            )
        return SteerResponse(
            thread_id=thread_id,
            acknowledged=True,
            intent_id=enqueue_result["intent"]["intent_id"],
            status=enqueue_result["status"],
        )
    except HTTPException:
        raise
    except Exception as exc:
        status_code = _extract_status_code(exc)
        if status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=_detail_with_status("failed", f"Thread '{thread_id}' not found."),
            ) from exc
        if status_code == 400:
            raise HTTPException(
                status_code=400,
                detail=_detail_with_status("failed", f"Invalid steering request: {exc}"),
            ) from exc
        if status_code in {409, 423}:
            raise HTTPException(
                status_code=status_code,
                detail=_detail_with_status("conflict", f"Steering conflict: {exc}"),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=_detail_with_status("failed", f"Failed to steer thread: {exc}"),
        ) from exc


@router.post(
    "/threads/{thread_id}/plan/execute",
    response_model=ExecutePlanResponse,
    summary="Execute Approved Plan",
    description="Approve the current draft plan for execution and switch lifecycle status to approved.",
)
async def execute_plan(thread_id: str, request: ExecutePlanRequest) -> ExecutePlanResponse:
    requested_plan_id = request.plan_id.strip() if isinstance(request.plan_id, str) else None
    try:
        from langgraph_sdk import get_client

        client = get_client(url=_langgraph_url())
        state = await client.threads.get_state(thread_id)
        values = _extract_state_values(state)
        plan = _as_plan(values.get("plan"))
        if not plan:
            return ExecutePlanResponse(
                thread_id=thread_id,
                acknowledged=False,
                status="conflict",
                plan_status=None,
                plan_id=None,
            )

        plan_id = str(plan.get("plan_id") or "").strip() or None
        if requested_plan_id and plan_id and requested_plan_id != plan_id:
            return ExecutePlanResponse(
                thread_id=thread_id,
                acknowledged=False,
                plan_id=plan_id,
                plan_status=str(plan.get("status") or ""),
                status="conflict",
            )

        current_status = str(plan.get("status") or "draft").strip().lower() or "draft"
        if current_status in {"approved", "executing"}:
            return ExecutePlanResponse(
                thread_id=thread_id,
                acknowledged=True,
                plan_id=plan_id,
                plan_status=current_status,
                status="duplicate",
            )
        if current_status == "completed":
            return ExecutePlanResponse(
                thread_id=thread_id,
                acknowledged=False,
                plan_id=plan_id,
                plan_status=current_status,
                status="conflict",
            )
        if bool(plan.get("clarification_pending")):
            return ExecutePlanResponse(
                thread_id=thread_id,
                acknowledged=False,
                plan_id=plan_id,
                plan_status=current_status,
                status="conflict",
            )

        approved_at = datetime.now(UTC).isoformat()
        next_plan = {
            **plan,
            "status": "approved",
            "approved_at": approved_at,
            "awaiting_execution_approval": False,
        }

        history = _as_plan_history(values.get("plan_history"))
        if plan_id:
            next_history: list[dict[str, Any]] = []
            for item in history:
                item_id = str(item.get("plan_id") or "").strip()
                if item_id == plan_id:
                    next_history.append({**item, "status": "approved"})
                else:
                    next_history.append(item)
            history = next_history

        await client.threads.update_state(
            thread_id,
            {
                "plan": next_plan,
                "plan_history": history,
            },
        )
        return ExecutePlanResponse(
            thread_id=thread_id,
            acknowledged=True,
            plan_id=plan_id,
            plan_status="approved",
            status="accepted",
        )
    except HTTPException:
        raise
    except Exception as exc:
        status_code = _extract_status_code(exc)
        if status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=_detail_with_status("failed", f"Thread '{thread_id}' not found."),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=_detail_with_status("failed", f"Failed to execute plan: {exc}"),
        ) from exc


@router.post(
    "/threads/{thread_id}/compact",
    response_model=CompactThreadResponse,
    summary="Force Thread Compaction",
    description="Deterministically compact thread messages without waiting for threshold-based summarization triggers.",
)
async def compact_thread(thread_id: str) -> CompactThreadResponse:
    try:
        from langgraph_sdk import get_client

        client = get_client(url=_langgraph_url())
        state = await client.threads.get_state(thread_id)
        values = _extract_state_values(state)
        messages = values.get("messages")
        if not isinstance(messages, list):
            return CompactThreadResponse(
                thread_id=thread_id,
                status="no_op",
                message="No messages available for compaction.",
            )

        compacted = _compact_messages(messages)
        if compacted is None:
            return CompactThreadResponse(
                thread_id=thread_id,
                status="no_op",
                message="Not enough history to compact yet.",
            )
        next_messages, metadata = compacted

        context_metrics = values.get("context_metrics")
        if not isinstance(context_metrics, dict):
            context_metrics = {}
        compaction_count = int(context_metrics.get("compaction_count") or 0) + 1
        updated_context_metrics = {
            **context_metrics,
            "compaction_count": compaction_count,
            "last_compaction_at": time.time(),
            "message_count": len(next_messages),
            "messages_compressed": metadata["messages_compressed"],
            "messages_kept": metadata["messages_kept"],
        }

        await client.threads.update_state(
            thread_id,
            {
                "messages": next_messages,
                "context_metrics": updated_context_metrics,
            },
        )

        append_compaction_entry(
            thread_id,
            {
                "trigger": "manual",
                "trigger_threshold": None,
                "trigger_observed": len(messages),
                "messages_compressed": metadata["messages_compressed"],
                "messages_kept": metadata["messages_kept"],
                "summary_text": metadata["summary_text"],
                "summary_quality": "fallback",
                "summary_source": "manual_compaction",
                "summary_error": None,
                "model_used": "",
            },
        )

        return CompactThreadResponse(
            thread_id=thread_id,
            status="accepted",
            message="Thread compaction completed.",
            compressed_messages=int(metadata["messages_compressed"]),
            kept_messages=int(metadata["messages_kept"]),
        )
    except HTTPException:
        raise
    except Exception as exc:
        status_code = _extract_status_code(exc)
        if status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=_detail_with_status("failed", f"Thread '{thread_id}' not found."),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=_detail_with_status("failed", f"Failed to compact thread: {exc}"),
        ) from exc
