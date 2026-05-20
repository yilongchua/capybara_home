"""Activity timeline schema + helpers.

This module powers user-facing activity updates such as:
- Capybara is thinking...
- Capybara is working on ...
- Baby Capy is working on ...
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, TypedDict

from langgraph.config import get_stream_writer

ACTIVITY_SCHEMA_VERSION = "v1"
ACTIVITY_STREAM_EVENT_TYPE = "activity_event.v1"
ACTIVITY_RUN_ID_KEY = "_activity_timeline_run_id"
ACTIVITY_SEQ_KEY = "_activity_timeline_seq"
ACTIVITY_MAX_EVENTS_RETAINED = 1200


class ActivityEvent(TypedDict, total=False):
    id: str
    schema: str
    run_id: str
    seq: int
    timestamp: float
    actor: Literal["capybara", "baby_capy", "system"]
    kind: str
    line: str
    task_id: str | None
    group_id: str | None
    group_kind: str | None
    group_title: str | None
    group_role: str | None
    subagent_type: str | None
    description: str | None
    tool_summary: str | None
    assistant_message_id: str | None
    payload: dict[str, Any]


class ActivityTimelineState(TypedDict, total=False):
    version: str
    events: list[ActivityEvent]


class ContextMetricsState(TypedDict, total=False):
    token_count: int
    message_count: int
    context_updated_at: float
    compaction_count: int
    last_compaction_at: float
    messages_compressed: int
    messages_kept: int


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _resolve_run_id(runtime: Any) -> str:
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict):
        return "run-unknown"

    native_run_id = context.get("run_id")
    if isinstance(native_run_id, str) and native_run_id:
        context[ACTIVITY_RUN_ID_KEY] = native_run_id
        return native_run_id

    existing = context.get(ACTIVITY_RUN_ID_KEY)
    if isinstance(existing, str) and existing:
        return existing

    generated = f"run-{uuid.uuid4().hex[:12]}"
    context[ACTIVITY_RUN_ID_KEY] = generated
    return generated


def _next_seq(runtime: Any) -> int:
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict):
        return 1
    current = context.get(ACTIVITY_SEQ_KEY, 0)
    if not isinstance(current, int) or current < 0:
        current = 0
    current += 1
    context[ACTIVITY_SEQ_KEY] = current
    return current


def create_activity_event(
    runtime: Any,
    *,
    actor: Literal["capybara", "baby_capy", "system"],
    kind: str,
    line: str,
    task_id: str | None = None,
    group_id: str | None = None,
    group_kind: str | None = None,
    group_title: str | None = None,
    group_role: str | None = None,
    subagent_type: str | None = None,
    description: str | None = None,
    tool_summary: str | None = None,
    assistant_message_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ActivityEvent:
    run_id = _resolve_run_id(runtime)
    seq = _next_seq(runtime)
    timestamp = time.time()
    event: ActivityEvent = {
        "id": f"{run_id}:{seq}",
        "schema": ACTIVITY_SCHEMA_VERSION,
        "run_id": run_id,
        "seq": seq,
        "timestamp": timestamp,
        "actor": actor,
        "kind": kind,
        "line": line,
        "task_id": task_id,
        "group_id": group_id,
        "group_kind": group_kind,
        "group_title": group_title,
        "group_role": group_role,
        "subagent_type": subagent_type,
        "description": description,
        "tool_summary": tool_summary,
        "assistant_message_id": assistant_message_id,
        "payload": payload or {},
    }
    return event


def stream_activity_event(event: ActivityEvent) -> None:
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": ACTIVITY_STREAM_EVENT_TYPE,
                "schema": ACTIVITY_SCHEMA_VERSION,
                **event,
            }
        )
    except Exception:
        return


def _dedupe_sort_events(events: list[ActivityEvent]) -> list[ActivityEvent]:
    by_id: dict[str, ActivityEvent] = {}
    without_id: list[ActivityEvent] = []
    for event in events:
        event_id = event.get("id")
        if isinstance(event_id, str) and event_id:
            by_id[event_id] = event
        else:
            without_id.append(event)
    deduped = list(by_id.values()) + without_id
    deduped.sort(
        key=lambda item: (
            float(item.get("timestamp") or 0.0),
            int(item.get("seq") or 0),
            str(item.get("id") or ""),
        )
    )
    if len(deduped) > ACTIVITY_MAX_EVENTS_RETAINED:
        return deduped[-ACTIVITY_MAX_EVENTS_RETAINED:]
    return deduped


def merge_activity_timeline(existing: ActivityTimelineState | None, new: ActivityTimelineState | None) -> ActivityTimelineState:
    if existing is None:
        return new or {"version": ACTIVITY_SCHEMA_VERSION, "events": []}
    if new is None:
        return existing

    old_events = existing.get("events") if isinstance(existing.get("events"), list) else []
    new_events = new.get("events") if isinstance(new.get("events"), list) else []
    merged_events = _dedupe_sort_events(
        [event for event in [*old_events, *new_events] if isinstance(event, dict)]
    )
    return {
        "version": ACTIVITY_SCHEMA_VERSION,
        "events": merged_events,
    }


def activity_timeline_update(events: list[ActivityEvent]) -> ActivityTimelineState:
    return {
        "version": ACTIVITY_SCHEMA_VERSION,
        "events": events,
    }


def merge_context_metrics(existing: ContextMetricsState | None, new: ContextMetricsState | None) -> ContextMetricsState:
    if existing is None:
        return new or {}
    if new is None:
        return existing

    current = dict(existing)
    incoming = dict(new)

    current_ts = float(current.get("context_updated_at") or 0.0)
    incoming_ts = float(incoming.get("context_updated_at") or current_ts)
    if incoming_ts >= current_ts:
        if "token_count" in incoming and isinstance(incoming.get("token_count"), int):
            current["token_count"] = int(incoming["token_count"])
        if "message_count" in incoming and isinstance(incoming.get("message_count"), int):
            current["message_count"] = int(incoming["message_count"])
        current["context_updated_at"] = incoming_ts

    if isinstance(incoming.get("compaction_count"), int):
        current["compaction_count"] = max(
            int(current.get("compaction_count") or 0),
            int(incoming["compaction_count"]),
        )
    if isinstance(incoming.get("last_compaction_at"), (int, float)):
        current["last_compaction_at"] = max(
            float(current.get("last_compaction_at") or 0.0),
            float(incoming["last_compaction_at"]),
        )
    if isinstance(incoming.get("messages_compressed"), int):
        current["messages_compressed"] = int(incoming["messages_compressed"])
    if isinstance(incoming.get("messages_kept"), int):
        current["messages_kept"] = int(incoming["messages_kept"])

    return current


def context_metrics_update(payload: dict[str, Any]) -> ContextMetricsState:
    return _as_dict(payload)
