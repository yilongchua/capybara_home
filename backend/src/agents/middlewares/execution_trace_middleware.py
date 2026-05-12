"""Execution trace middleware.

Persists and streams user-visible execution trace entries for lead-model turns,
harness middleware decisions, and subagent lifecycle updates.
"""

from __future__ import annotations

from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.agents.execution_trace import (
    TRACE_SCHEMA_VERSION,
    ExecutionTraceState,
    TraceThinking,
    create_trace_event,
    execution_trace_update,
    extract_reasoning_from_message,
    extract_token_usage_from_message,
    make_summary_fallback,
    mark_run_started,
    resolve_trace_run_id,
    run_started_emitted,
    stream_trace_event,
)
from src.agents.middlewares.runtime_events import append_runtime_event, drain_runtime_events


class ExecutionTraceMiddlewareState(AgentState):
    execution_trace: NotRequired[ExecutionTraceState | None]


_SOURCE_STAGE: dict[str, str] = {
    "planner_middleware": "planner",
    "evaluator_middleware": "evaluator",
    "plan_followup_middleware": "harness",
    "title_middleware": "lead",
    "task_tool": "subagent",
    "progress_guard": "harness",
    "retry_policy_middleware": "harness",
    "permission_middleware": "harness",
    "hooks_middleware": "harness",
    "subagent_limit_middleware": "harness",
    "tool_disclosure_middleware": "harness",
    "execution_trace_middleware": "harness",
}

_TRACEABLE_RUNTIME_EVENTS = {
    "plan_created",
    "skipped_trivial",
    "parse_failed_fallback",
    "rule_fail",
    "llm_verdict",
    "background_followup_started",
    "task_started",
    "task_running",
    "task_completed",
    "task_failed",
    "task_timed_out",
    "tool_call_start",
    "tool_call_end",
    "compaction",
    "context_tokens",
    "memory_flush_failed",
    "dreamy_state_preserved",
    "dreamy_resumption_rehydrated",
}

_TRACEABLE_TOOL_NAMES = {"web_search", "query_knowledge_vault", "query_lightrag", "task"}


def _truncate_preview(value: str, *, limit: int = 280) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _tool_input_preview(tool_call: dict[str, Any]) -> str | None:
    args = tool_call.get("args")
    if isinstance(args, dict):
        for key in ("query", "command", "prompt", "url", "path", "description"):
            candidate = args.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return _truncate_preview(candidate.strip())
        compact_pairs: list[str] = []
        for key in ("q", "location", "ticker", "team", "date_from", "date_to"):
            candidate = args.get(key)
            if isinstance(candidate, str) and candidate.strip():
                compact_pairs.append(f"{key}={candidate.strip()}")
        if compact_pairs:
            return _truncate_preview(", ".join(compact_pairs))
    if isinstance(args, str) and args.strip():
        return _truncate_preview(args.strip())
    return None


def _tool_output_preview(result: ToolMessage | Command) -> str | None:
    if not isinstance(result, ToolMessage):
        return None
    content = result.content
    if isinstance(content, str):
        text = content.strip()
        return _truncate_preview(text) if text else None
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        text = "\n".join(parts).strip()
        return _truncate_preview(text) if text else None
    text = str(content).strip()
    return _truncate_preview(text) if text else None


def _inline_trace_from_runtime_event(runtime: Runtime, runtime_event: dict[str, Any]) -> dict[str, Any] | None:
    inline_trace = runtime_event.get("trace_event")
    if not isinstance(inline_trace, dict):
        return None
    stage = inline_trace.get("stage")
    event_type = inline_trace.get("event_type")
    status = inline_trace.get("status")
    timestamp = inline_trace.get("timestamp")
    if (
        not isinstance(stage, str)
        or not isinstance(event_type, str)
        or not isinstance(status, str)
        or not isinstance(timestamp, (int, float))
    ):
        return None

    event = dict(inline_trace)
    run_id = event.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        event["run_id"] = resolve_trace_run_id(runtime)
    if not isinstance(event.get("schema"), str):
        event["schema"] = TRACE_SCHEMA_VERSION
    return event


def _runtime_event_to_trace(runtime: Runtime, runtime_event: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    inline_trace = _inline_trace_from_runtime_event(runtime, runtime_event)
    if inline_trace is not None:
        # task_tool streams first-class trace events directly; avoid streaming a
        # duplicate copy from middleware unless explicitly requested.
        should_stream = not bool(runtime_event.get("trace_already_streamed", True))
        return inline_trace, should_stream

    source = str(runtime_event.get("source") or "harness")
    stage = _SOURCE_STAGE.get(source, "harness")
    event_type = (
        str(runtime_event.get("event") or "")
        or str(runtime_event.get("decision") or "")
        or str(runtime_event.get("signal") or "")
        or str(runtime_event.get("phase") or "")
        or "runtime_event"
    )
    if event_type not in _TRACEABLE_RUNTIME_EVENTS:
        return {}, False
    payload = dict(runtime_event)
    payload.pop("source", None)
    status = "info"
    if stage == "subagent":
        status = str(runtime_event.get("status") or "running")
    elif "warning" in event_type or "fail" in event_type or "blocked" in event_type:
        status = "warning"
    elif event_type in {"allow", "plan_created", "llm_verdict", "tool_call_end", "model_call_end"}:
        status = "completed"

    thinking: TraceThinking = {
        "source": "summary",
        "content": make_summary_fallback(event_type=event_type, payload=payload),
    }

    return create_trace_event(
        runtime,
        stage=stage,  # type: ignore[arg-type]
        event_type=event_type,
        status=status,
        payload=payload,
        thinking=thinking,
        turn_id=str(runtime_event.get("turn_id")) if runtime_event.get("turn_id") is not None else None,
        assistant_message_id=str(runtime_event.get("assistant_message_id")) if runtime_event.get("assistant_message_id") is not None else None,
        task_id=str(runtime_event.get("task_id")) if runtime_event.get("task_id") is not None else None,
    ), True


def _build_trace_update(runtime: Runtime, runtime_events: list[dict[str, Any]]) -> dict | None:
    if not runtime_events:
        return None
    trace_records = [
        pair
        for pair in (_runtime_event_to_trace(runtime, runtime_event) for runtime_event in runtime_events)
        if pair[0]
    ]
    for trace_event, should_stream in trace_records:
        if should_stream:
            stream_trace_event(trace_event)
    return {"execution_trace": execution_trace_update([event for event, _ in trace_records])}


class ExecutionTraceMiddleware(AgentMiddleware[ExecutionTraceMiddlewareState]):
    """Persist + stream execution trace records."""

    state_schema = ExecutionTraceMiddlewareState

    @override
    def before_agent(self, state: ExecutionTraceMiddlewareState, runtime: Runtime) -> dict | None:
        if run_started_emitted(runtime):
            return None
        mark_run_started(runtime)
        event = create_trace_event(
            runtime,
            stage="harness",
            event_type="run_started",
            status="running",
            payload={"message_count": len(state.get("messages", []) or [])},
            thinking={
                "source": "summary",
                "content": "Execution trace started for this run.",
            },
        )
        stream_trace_event(event)
        return {"execution_trace": execution_trace_update([event])}

    @override
    def before_model(self, state: ExecutionTraceMiddlewareState, runtime: Runtime) -> dict | None:
        runtime_events = drain_runtime_events(runtime, consumer="execution_trace")
        return _build_trace_update(runtime, runtime_events)

    @override
    def after_model(self, state: ExecutionTraceMiddlewareState, runtime: Runtime) -> dict | None:
        updates: list[dict[str, Any]] = []
        runtime_trace_records: list[tuple[dict[str, Any], bool]] = []

        runtime_events = drain_runtime_events(runtime, consumer="execution_trace")
        if runtime_events:
            runtime_trace_records = [_runtime_event_to_trace(runtime, runtime_event) for runtime_event in runtime_events]
            updates.extend([event for event, _ in runtime_trace_records])

        messages = state.get("messages", []) or []
        last_message = messages[-1] if messages else None
        if getattr(last_message, "type", None) == "ai":
            assistant_message_id = getattr(last_message, "id", None)
            tool_calls = getattr(last_message, "tool_calls", None) or []
            tool_names = [
                str(call.get("name"))
                for call in tool_calls
                if isinstance(call, dict) and isinstance(call.get("name"), str)
            ]
            reasoning = extract_reasoning_from_message(last_message)
            thinking: TraceThinking
            if reasoning:
                thinking = {
                    "source": "raw",
                    "content": reasoning,
                }
            else:
                thinking = {
                    "source": "summary",
                    "content": make_summary_fallback(
                        event_type="model_response",
                        payload={"tool_calls_count": len(tool_calls)},
                    ),
                }

            token_usage = extract_token_usage_from_message(last_message)
            event = create_trace_event(
                runtime,
                stage="lead",
                event_type="model_response",
                status="running" if tool_calls else "completed",
                payload={
                    "tool_calls_count": len(tool_calls),
                    "tool_names": tool_names,
                    "has_text_content": bool(getattr(last_message, "content", "")),
                },
                token_usage=token_usage,
                thinking=thinking,
                turn_id=str(assistant_message_id) if assistant_message_id is not None else None,
                assistant_message_id=str(assistant_message_id) if assistant_message_id is not None else None,
            )
            updates.append(event)

        if not updates:
            return None
        streamed_event_ids = {
            event.get("id")
            for event, should_stream in runtime_trace_records
            if not should_stream and isinstance(event.get("id"), str)
        }
        for event in updates:
            event_id = event.get("id")
            if isinstance(event_id, str) and event_id in streamed_event_ids:
                continue
            stream_trace_event(event)
        return {"execution_trace": execution_trace_update(updates)}

    @override
    def wrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        result = handler(request)
        return result

    @override
    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        result = await handler(request)
        return result

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name")
        should_trace = tool_name in _TRACEABLE_TOOL_NAMES
        if should_trace:
            append_runtime_event(
                request.runtime,
                {
                    "source": "execution_trace_middleware",
                    "event": "tool_call_start",
                    "phase": "tool_call_start",
                    "tool": tool_name,
                    "task_id": request.tool_call.get("id"),
                    "tool_input": _tool_input_preview(request.tool_call),
                },
            )
        result = handler(request)
        if should_trace:
            append_runtime_event(
                request.runtime,
                {
                    "source": "execution_trace_middleware",
                    "event": "tool_call_end",
                    "phase": "tool_call_end",
                    "tool": tool_name,
                    "task_id": request.tool_call.get("id"),
                    "tool_output_preview": _tool_output_preview(result),
                },
            )
        return result

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name")
        should_trace = tool_name in _TRACEABLE_TOOL_NAMES
        if should_trace:
            append_runtime_event(
                request.runtime,
                {
                    "source": "execution_trace_middleware",
                    "event": "tool_call_start",
                    "phase": "tool_call_start",
                    "tool": tool_name,
                    "task_id": request.tool_call.get("id"),
                    "tool_input": _tool_input_preview(request.tool_call),
                },
            )
        result = await handler(request)
        if should_trace:
            append_runtime_event(
                request.runtime,
                {
                    "source": "execution_trace_middleware",
                    "event": "tool_call_end",
                    "phase": "tool_call_end",
                    "tool": tool_name,
                    "task_id": request.tool_call.get("id"),
                    "tool_output_preview": _tool_output_preview(result),
                },
            )
        return result
