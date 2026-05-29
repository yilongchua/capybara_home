"""Activity timeline middleware.

Converts runtime/middleware/tool/subagent events into user-readable activity
lines and persists them in thread state.
"""

from __future__ import annotations

import time
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.agents.activity_timeline import (
    ActivityEvent,
    ActivityTimelineState,
    ContextMetricsState,
    activity_timeline_update,
    context_metrics_update,
    create_activity_event,
    merge_context_metrics,
    stream_activity_event,
)
from src.agents.middlewares.run_scoped import clear_run_store_key, get_run_store
from src.agents.middlewares.runtime_events import append_runtime_event, drain_runtime_events

_TOOL_INPUT_BY_TASK_ID_KEY = "_activity_tool_input_by_task_id"
_TOOL_INPUT_MAX_ENTRIES = 128
_TOOL_INPUT_TTL_SECONDS = 10 * 60
_LONG_RUNNING_TOOL_NAMES = frozenset(
    {
        "bash",
        "write_file",
        "str_replace",
        "read_file",
        "web_search",
        "query_knowledge_vault",
        "task",
        "write_todos",
    }
)


class ActivityTimelineMiddlewareState(AgentState):
    activity_timeline: NotRequired[ActivityTimelineState | None]
    context_metrics: NotRequired[ContextMetricsState | None]


# Reuse helper via re-export to avoid importing execution-trace module from UI path.
def extract_reasoning_from_message(message: Any) -> str | None:
    additional_kwargs = getattr(message, "additional_kwargs", None) or {}
    reasoning = additional_kwargs.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning.strip()

    content = getattr(message, "content", None)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                thinking = block.get("thinking")
                if isinstance(thinking, str) and thinking.strip():
                    return thinking.strip()
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _as_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _tool_summary(payload: dict[str, Any]) -> str | None:
    return _as_str(payload.get("tool_summary")) or _as_str(payload.get("tool_input")) or _as_str(payload.get("description"))


def _tool_input_preview(args: Any) -> str | None:
    args_dict = _as_dict(args)
    for key in ("query", "command", "path", "file_path", "filepath", "url", "description", "prompt"):
        value = _as_str(args_dict.get(key))
        if value:
            return value[:280]
    return _as_str(args)[:280] if isinstance(args, str) else None


def _subagent_label(payload: dict[str, Any]) -> str:
    return _as_str(payload.get("subagent_type")) or "task"


def _subagent_description(payload: dict[str, Any]) -> str:
    return _as_str(payload.get("description")) or "delegated task"


def _subagent_group_title(payload: dict[str, Any]) -> str:
    return _as_str(payload.get("group_title")) or f"{_subagent_label(payload)}: {_subagent_description(payload)}"


def _tool_input_store(runtime: Runtime) -> dict[str, dict[str, Any]]:
    store = get_run_store(runtime)
    raw = store.get(_TOOL_INPUT_BY_TASK_ID_KEY)
    if not isinstance(raw, dict):
        raw = {}
        store[_TOOL_INPUT_BY_TASK_ID_KEY] = raw
    return raw


def _prune_tool_input_store(store: dict[str, dict[str, Any]], *, now: float | None = None) -> None:
    now = time.time() if now is None else now
    for key, entry in list(store.items()):
        created_at = entry.get("created_at") if isinstance(entry, dict) else None
        if not isinstance(created_at, (int, float)) or now - float(created_at) > _TOOL_INPUT_TTL_SECONDS:
            store.pop(key, None)
    if len(store) <= _TOOL_INPUT_MAX_ENTRIES:
        return
    ordered = sorted(
        store.items(),
        key=lambda item: float(item[1].get("created_at") or 0) if isinstance(item[1], dict) else 0,
    )
    for key, _entry in ordered[: max(0, len(store) - _TOOL_INPUT_MAX_ENTRIES)]:
        store.pop(key, None)


def _remember_tool_input(runtime: Runtime, task_id: str | None, tool_input: str | None) -> None:
    if not task_id or not tool_input:
        return
    store = _tool_input_store(runtime)
    _prune_tool_input_store(store)
    store[task_id] = {"text": tool_input, "created_at": time.time()}


def _recall_tool_input(runtime: Runtime, task_id: str | None) -> str | None:
    if not task_id:
        return None
    store = get_run_store(runtime).get(_TOOL_INPUT_BY_TASK_ID_KEY)
    if not isinstance(store, dict):
        return None
    value = store.pop(task_id, None)
    if isinstance(value, dict):
        return _as_str(value.get("text"))
    return _as_str(value)


def _tool_output_preview(result: ToolMessage | Command) -> str | None:
    if isinstance(result, ToolMessage):
        return _as_str(result.content)
    if isinstance(result, Command):
        messages = (result.update or {}).get("messages") if isinstance(result.update, dict) else None
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, ToolMessage):
                return _as_str(last.content)
    return None


def _tool_label(tool_name: str) -> str:
    labels = {
        "bash": "Running shell command",
        "read_file": "Reading file",
        "write_file": "Writing file",
        "str_replace": "Editing file",
        "web_search": "Searching the web",
        "query_knowledge_vault": "Searching knowledge vault",
        "task": "Starting delegated task",
        "write_todos": "Updating todo list",
        "present_files": "Preparing files",
    }
    return labels.get(tool_name, f"Running {tool_name}")


def _format_tool_activity_line(tool_name: str, tool_input: str | None, *, completed: bool) -> str:
    label = _tool_label(tool_name)
    if tool_name in {"write_file", "str_replace", "read_file"} and tool_input:
        if not completed:
            return f"{label}: {tool_input}..."
        verb = "Wrote" if tool_name == "write_file" and completed else "Edited" if tool_name == "str_replace" and completed else "Read" if completed else label
        return f"{verb}: {tool_input}"
    if tool_name == "write_todos":
        return "Updated todo list" if completed else "Updating todo list..."
    if tool_input:
        suffix = "" if completed else "..."
        return f"{label}: {tool_input}{suffix}"
    return f"{label}{'' if completed else '...'}" if completed else f"{label}..."


def _format_todo_activity_line(event_type: str, payload: dict[str, Any]) -> str:
    reason_code = _as_str(payload.get("reason_code"))
    if event_type == "todo_update_validation_failed":
        error = _as_str(payload.get("error"))
        return f"Todo update failed validation: {error}" if error else "Todo update failed validation"
    if event_type == "todo_update_rejected":
        if reason_code:
            return f"Todo update rejected: {reason_code}"
        return "Todo update rejected"
    return "Updating todo list..."


def _format_plan_evaluator_line(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "ok":
        return "Plan evaluator approved the plan"
    if event_type == "issues_no_revision":
        return "Plan evaluator found issues and kept the current plan"
    if event_type == "revision_invalid":
        return "Plan evaluator ignored an invalid revision"
    if event_type == "revised":
        count = payload.get("new_todo_count")
        if isinstance(count, int):
            return f"Plan evaluator revised the plan with {count} todo(s)"
        return "Plan evaluator revised the plan"
    if event_type == "timeout_skipped":
        return "Plan evaluator timed out; continuing with the current plan"
    return "Plan evaluator is reviewing the plan..."


def _to_activity_event(runtime: Runtime, runtime_event: dict[str, Any]) -> ActivityEvent | None:
    event_type = str(runtime_event.get("event") or runtime_event.get("decision") or runtime_event.get("signal") or "")
    payload = dict(runtime_event)
    source = str(payload.get("source") or "")

    task_id = _as_str(payload.get("task_id"))
    group_id = _as_str(payload.get("group_id")) or task_id
    assistant_message_id = _as_str(payload.get("assistant_message_id"))
    summary = _tool_summary(payload)
    group_kind = _as_str(payload.get("group_kind"))
    group_title = _as_str(payload.get("group_title"))
    subagent_type = _as_str(payload.get("subagent_type"))
    description = _as_str(payload.get("description"))
    group_role: str | None = None

    actor = "capyhome"
    kind = event_type or "event"
    line: str | None = None

    if event_type in {"context_tokens", "compaction"}:
        actor = "system"

    if event_type == "tool_call_start":
        _remember_tool_input(runtime, task_id, _as_str(payload.get("tool_input")))
        tool = _as_str(payload.get("tool")) or "tool"
        if tool not in _LONG_RUNNING_TOOL_NAMES:
            return None
        tool_input = _as_str(payload.get("tool_input"))
        line = _format_tool_activity_line(tool, tool_input, completed=False)
    elif event_type == "tool_call_end":
        tool = _as_str(payload.get("tool")) or "tool"
        tool_input = _recall_tool_input(runtime, task_id) or _as_str(payload.get("tool_input"))
        tool_output = _as_str(payload.get("tool_output_preview")) or _as_str(payload.get("result_preview"))
        if tool_output and "[plan_gate]" in tool_output:
            kind = "plan_gate_blocked"
            line = "Waiting for plan approval before running tools"
            summary = tool_output[:280]
        elif tool_input:
            line = _format_tool_activity_line(tool, tool_input, completed=True)
        else:
            line = _format_tool_activity_line(tool, None, completed=True)
        if summary is None:
            summary = tool_output
    elif event_type == "model_response":
        tool_calls_count = payload.get("tool_calls_count")
        if isinstance(tool_calls_count, int) and tool_calls_count > 0:
            return None
        else:
            line = "CapyHome is working on finalizing the response..."
    elif event_type == "title_generation_start":
        line = "Generating chat title..."
    elif event_type == "planning_started":
        line = "Planner is evaluating request complexity..."
    elif event_type == "plan_created":
        todo_count = payload.get("todo_count")
        line = f"Plan created with {todo_count} todo(s)" if isinstance(todo_count, int) else "Plan created"
    elif event_type == "skipped_direct_answer":
        line = "Planner will answer directly without a separate plan"
    elif event_type == "parse_failed_fallback":
        line = "Planner is using a fallback plan structure"
    elif event_type == "plan_auto_approved":
        line = "Plan auto-approved - starting execution"
    elif source == "plan_evaluator":
        line = _format_plan_evaluator_line(event_type, payload)
    elif source == "write_todos_tool":
        line = _format_todo_activity_line(event_type, payload)
    elif event_type == "task_started":
        actor = "baby_capy"
        group_kind = group_kind or "subagent_task"
        group_title = group_title or _subagent_group_title(payload)
        subagent_type = subagent_type or _subagent_label(payload)
        description = description or _subagent_description(payload)
        group_role = "header"
        line = f"Baby Capy - {subagent_type} is working on {description}..."
    elif event_type == "task_running":
        actor = "baby_capy"
        group_kind = group_kind or "subagent_task"
        group_title = group_title or _subagent_group_title(payload)
        subagent_type = subagent_type or _subagent_label(payload)
        description = description or _subagent_description(payload)
        group_role = "step"
        line = f"Baby Capy - {subagent_type} is working on {summary}..." if summary else f"Baby Capy - {subagent_type} is working on delegated steps..."
    elif event_type == "task_completed":
        actor = "baby_capy"
        group_kind = group_kind or "subagent_task"
        group_title = group_title or _subagent_group_title(payload)
        subagent_type = subagent_type or _subagent_label(payload)
        description = description or _subagent_description(payload)
        group_role = "terminal"
        line = f"Baby Capy - {subagent_type} finished {description}"
    elif event_type in {"task_failed", "task_timed_out"}:
        actor = "baby_capy"
        group_kind = group_kind or "subagent_task"
        group_title = group_title or _subagent_group_title(payload)
        subagent_type = subagent_type or _subagent_label(payload)
        description = description or _subagent_description(payload)
        group_role = "terminal"
        line = f"Baby Capy - {subagent_type} hit an issue while working on {description}"
    elif event_type == "context_tokens":
        line = "CapyHome is thinking..."
    elif event_type == "compaction":
        line = "CapyHome is working on compressing context..."
    elif event_type == "rule_fail":
        line = "CapyHome is working on correcting the previous output..."
    elif event_type == "llm_verdict":
        line = "CapyHome is thinking..."
    elif event_type == "background_followup_started":
        line = "CapyHome is working on deeper background analysis..."

    if line is None:
        # Best-effort fallback only for harness/runtime events we still want visible.
        if source in {
            "planner_middleware",
            "plan_evaluator",
            "task_tool",
            "execution_trace_middleware",
            "activity_timeline_middleware",
            "write_todos_tool",
            "todo_failure_retry_middleware",
            "dangling_tool_call_middleware",
            "work_mode_middleware",
            "title_middleware",
        }:
            line = "CapyHome is working on the next step..."
        else:
            return None

    return create_activity_event(
        runtime,
        actor=actor,  # type: ignore[arg-type]
        kind=kind,
        line=line,
        task_id=task_id,
        group_id=group_id,
        group_kind=group_kind,
        group_title=group_title,
        group_role=group_role,
        subagent_type=subagent_type,
        description=description,
        tool_summary=summary,
        assistant_message_id=assistant_message_id,
        payload=payload,
    )


def _build_updates(runtime: Runtime, runtime_events: list[dict[str, Any]]) -> tuple[list[ActivityEvent], ContextMetricsState | None]:
    events: list[ActivityEvent] = []
    metrics_payload: dict[str, Any] = {}

    for runtime_event in runtime_events:
        event_type = str(runtime_event.get("event") or "")
        if event_type == "context_tokens":
            token_count = runtime_event.get("token_count")
            message_count = runtime_event.get("message_count")
            timestamp = runtime_event.get("timestamp")
            if isinstance(token_count, int):
                metrics_payload["token_count"] = token_count
            if isinstance(message_count, int):
                metrics_payload["message_count"] = message_count
            metrics_payload["context_updated_at"] = float(timestamp) if isinstance(timestamp, (int, float)) else time.time()

        if event_type == "compaction":
            ts = runtime_event.get("timestamp")
            prev_count = int(metrics_payload.get("compaction_count") or 0)
            metrics_payload["compaction_count"] = prev_count + 1
            metrics_payload["last_compaction_at"] = float(ts) if isinstance(ts, (int, float)) else time.time()
            compressed = runtime_event.get("messages_compressed")
            kept = runtime_event.get("messages_kept")
            if isinstance(compressed, int):
                metrics_payload["messages_compressed"] = compressed
            if isinstance(kept, int):
                metrics_payload["messages_kept"] = kept

        event = _to_activity_event(runtime, runtime_event)
        if event is None:
            continue
        events.append(event)

    metrics = context_metrics_update(metrics_payload) if metrics_payload else None
    return events, metrics


def _activity_payload(events: list[ActivityEvent], metrics: ContextMetricsState | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if events:
        for event in events:
            stream_activity_event(event)
        payload["activity_timeline"] = activity_timeline_update(events)
    if metrics:
        payload["context_metrics"] = metrics
    return payload


def _merge_activity_into_command(result: ToolMessage | Command, payload: dict[str, Any]) -> ToolMessage | Command:
    if not payload or not isinstance(result, Command):
        return result
    update = dict(result.update or {})
    if "activity_timeline" in payload:
        update["activity_timeline"] = payload["activity_timeline"]
    if "context_metrics" in payload:
        update["context_metrics"] = payload["context_metrics"]
    return Command(update=update)


class ActivityTimelineMiddleware(AgentMiddleware[ActivityTimelineMiddlewareState]):
    state_schema = ActivityTimelineMiddlewareState

    def _flush_runtime_activity(self, runtime: Runtime) -> dict[str, Any]:
        runtime_events = drain_runtime_events(runtime, consumer="activity_timeline")
        events, metrics = _build_updates(runtime, runtime_events)
        return _activity_payload(events, metrics)

    @override
    def before_agent(self, state: ActivityTimelineMiddlewareState, runtime: Runtime) -> dict | None:
        event = create_activity_event(
            runtime,
            actor="capyhome",
            kind="run_started",
            line="CapyHome is thinking...",
            payload={"message_count": len(state.get("messages", []) or [])},
        )
        stream_activity_event(event)
        return {"activity_timeline": activity_timeline_update([event])}

    @override
    def before_model(self, state: ActivityTimelineMiddlewareState, runtime: Runtime) -> dict | None:
        payload = self._flush_runtime_activity(runtime)
        if not payload:
            return None
        if "context_metrics" in payload:
            payload["context_metrics"] = merge_context_metrics(state.get("context_metrics"), payload["context_metrics"])
        return payload

    @override
    def after_model(self, state: ActivityTimelineMiddlewareState, runtime: Runtime) -> dict | None:
        updates: list[ActivityEvent] = []

        runtime_events = drain_runtime_events(runtime, consumer="activity_timeline")
        runtime_updates, metrics = _build_updates(runtime, runtime_events)
        updates.extend(runtime_updates)

        messages = state.get("messages", []) or []
        last_message = messages[-1] if messages else None
        if getattr(last_message, "type", None) == "ai":
            assistant_message_id = _as_str(getattr(last_message, "id", None))
            reasoning = extract_reasoning_from_message(last_message)
            if reasoning:
                updates.append(
                    create_activity_event(
                        runtime,
                        actor="capyhome",
                        kind="thinking",
                        line="CapyHome is thinking...",
                        assistant_message_id=assistant_message_id,
                        payload={"reasoning_preview": reasoning[:280]},
                    )
                )

            tool_calls = getattr(last_message, "tool_calls", None) or []
            if tool_calls:
                tool_names: list[str] = []
                for call in tool_calls:
                    if isinstance(call, dict):
                        name = _as_str(call.get("name"))
                        if name:
                            tool_names.append(name)
                updates.append(
                    create_activity_event(
                        runtime,
                        actor="capyhome",
                        kind="model_response",
                        line="CapyHome is working on choosing the next actions...",
                        assistant_message_id=assistant_message_id,
                        payload={"tool_names": tool_names, "tool_calls_count": len(tool_calls)},
                    )
                )
            else:
                updates.append(
                    create_activity_event(
                        runtime,
                        actor="capyhome",
                        kind="model_response",
                        line="CapyHome is working on finalizing the response...",
                        assistant_message_id=assistant_message_id,
                    )
                )

        payload = _activity_payload(updates, metrics)
        if not payload:
            return None
        if "context_metrics" in payload:
            payload["context_metrics"] = merge_context_metrics(state.get("context_metrics"), payload["context_metrics"])
        return payload

    @override
    def after_agent(self, state: ActivityTimelineMiddlewareState, runtime: Runtime) -> dict | None:
        payload = self._flush_runtime_activity(runtime)
        clear_run_store_key(runtime, _TOOL_INPUT_BY_TASK_ID_KEY)
        return payload or None

    @override
    def wrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        return handler(request)

    @override
    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        return await handler(request)

    def _wrap_tool_call_inner(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name")
        append_runtime_event(
            request.runtime,
            {
                "source": "activity_timeline_middleware",
                "event": "tool_call_start",
                "tool": tool_name,
                "task_id": request.tool_call.get("id"),
                "tool_input": _tool_input_preview(request.tool_call.get("args")),
            },
        )
        result = handler(request)
        append_runtime_event(
            request.runtime,
            {
                "source": "activity_timeline_middleware",
                "event": "tool_call_end",
                "tool": tool_name,
                "task_id": request.tool_call.get("id"),
                "tool_output_preview": _tool_output_preview(result),
            },
        )
        activity_payload = self._flush_runtime_activity(request.runtime)
        return _merge_activity_into_command(result, activity_payload)

    async def _awrap_tool_call_inner(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name")
        append_runtime_event(
            request.runtime,
            {
                "source": "activity_timeline_middleware",
                "event": "tool_call_start",
                "tool": tool_name,
                "task_id": request.tool_call.get("id"),
                "tool_input": _tool_input_preview(request.tool_call.get("args")),
            },
        )
        result = await handler(request)
        append_runtime_event(
            request.runtime,
            {
                "source": "activity_timeline_middleware",
                "event": "tool_call_end",
                "tool": tool_name,
                "task_id": request.tool_call.get("id"),
                "tool_output_preview": _tool_output_preview(result),
            },
        )
        activity_payload = self._flush_runtime_activity(request.runtime)
        return _merge_activity_into_command(result, activity_payload)

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        return self._wrap_tool_call_inner(request, handler)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        return await self._awrap_tool_call_inner(request, handler)
