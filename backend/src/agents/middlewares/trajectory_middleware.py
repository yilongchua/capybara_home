"""JSONL trajectory logging middleware."""

from __future__ import annotations

import atexit
import json
import logging
import os
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import IO, Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.agents.middlewares.model_timeout_middleware import TIMEOUT_MESSAGE_FINGERPRINT
from src.agents.middlewares.runtime_events import drain_runtime_events
from src.agents.thread_state import TrajectoryRuntimeState
from src.config.paths import get_paths
from src.config.trajectory_config import get_trajectory_config

logger = logging.getLogger(__name__)

# Per-run append-mode file handles so we pay one open() per run instead of one
# per event. Cleaned up on process exit.
_TRAJECTORY_HANDLES: dict[str, IO[str]] = {}
_TRAJECTORY_LOCK = Lock()


def _close_trajectory_handles() -> None:
    with _TRAJECTORY_LOCK:
        for handle in _TRAJECTORY_HANDLES.values():
            try:
                handle.close()
            except Exception:
                pass
        _TRAJECTORY_HANDLES.clear()


atexit.register(_close_trajectory_handles)


def _get_trajectory_handle(file_path: Path) -> IO[str]:
    key = str(file_path)
    with _TRAJECTORY_LOCK:
        handle = _TRAJECTORY_HANDLES.get(key)
        if handle is not None and not handle.closed:
            return handle
        handle = open(file_path, "a", encoding="utf-8")
        _TRAJECTORY_HANDLES[key] = handle
        return handle


class TrajectoryMiddlewareState(AgentState):
    """State schema subset for trajectory logging."""

    trajectory: NotRequired[TrajectoryRuntimeState | None]


class TrajectoryMiddleware(AgentMiddleware[TrajectoryMiddlewareState]):
    """Persist middleware/model/tool events into a per-run JSONL trajectory."""

    state_schema = TrajectoryMiddlewareState

    @staticmethod
    def _truncate(value: Any, max_chars: int) -> Any:
        if isinstance(value, str) and len(value) > max_chars:
            return value[: max_chars - 3] + "..."
        if isinstance(value, dict):
            return {k: TrajectoryMiddleware._truncate(v, max_chars) for k, v in value.items()}
        if isinstance(value, list):
            return [TrajectoryMiddleware._truncate(v, max_chars) for v in value]
        return value

    def _resolve_trace_file(self, state: TrajectoryMiddlewareState, runtime: Runtime) -> tuple[str, Path]:
        existing = state.get("trajectory") or {}
        run_id = existing.get("run_id")
        file_path = existing.get("file_path")
        if run_id and file_path:
            return run_id, Path(file_path)

        context = runtime.context if runtime.context else {}
        thread_id = context.get("thread_id") if isinstance(context, dict) else None
        thread_part = thread_id or "unknown-thread"
        # Prefer LangGraph's native run_id so trajectory files are cross-referenced
        # with Gateway `/runs/{run_id}/resume`. Fall back to a synthetic uuid when
        # the runtime does not expose one (e.g., embedded CapyHomeClient paths).
        native_run_id = context.get("run_id") if isinstance(context, dict) else None
        run_id = str(native_run_id) if isinstance(native_run_id, str) and native_run_id else f"run-{uuid.uuid4().hex[:10]}"
        base_dir = get_paths().base_dir / "threads" / thread_part / "logs" / "trajectory"
        base_dir.mkdir(parents=True, exist_ok=True)
        cfg = get_trajectory_config()
        file_name = f"{cfg.file_prefix}-{int(time.time())}-{run_id}.jsonl"
        return run_id, base_dir / file_name

    def _write_event(
        self,
        state: TrajectoryMiddlewareState,
        runtime: Runtime,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict | None:
        cfg = get_trajectory_config()
        if not cfg.enabled:
            return None

        # Trajectory is an advisory/observability middleware — disk-IO failures
        # (full disk, read-only FS, permission issue) must not break the run.
        # Log once per failure, then continue without raising.
        try:
            run_id, file_path = self._resolve_trace_file(state, runtime)
            payload = payload or {}
            record = {
                "ts": time.time(),
                "run_id": run_id,
                "thread_id": (getattr(runtime, "context", None) or {}).get("thread_id") if runtime else None,
                "event": event_type,
                "payload": self._truncate(payload, cfg.max_payload_chars),
            }
            handle = _get_trajectory_handle(file_path)
            with _TRAJECTORY_LOCK:
                handle.write(json.dumps(record, ensure_ascii=False) + os.linesep)
                handle.flush()
                if cfg.fsync:
                    os.fsync(handle.fileno())
        except Exception as exc:  # pragma: no cover - disk IO failure paths
            logger.warning("TrajectoryMiddleware failed to persist event %r: %s", event_type, exc)
            return None

        return {
            "trajectory": {
                "run_id": run_id,
                "file_path": str(file_path),
            }
        }

    @override
    def before_agent(self, state: TrajectoryMiddlewareState, runtime: Runtime) -> dict | None:
        return self._write_event(state, runtime, "before_agent", {})

    @override
    def after_agent(self, state: TrajectoryMiddlewareState, runtime: Runtime) -> dict | None:
        # Terminal event so audit tools can distinguish "run finished cleanly"
        # from "trajectory ends mid-step" (the run-c0425b71bd failure mode).
        return self._write_event(state, runtime, "after_agent", {})

    @override
    async def aafter_agent(self, state: TrajectoryMiddlewareState, runtime: Runtime) -> dict | None:
        return self._write_event(state, runtime, "after_agent", {})

    @override
    def before_model(self, state: TrajectoryMiddlewareState, runtime: Runtime) -> dict | None:
        updates = self._write_event(
            state,
            runtime,
            "before_model",
            {
                "message_count": len(state.get("messages", []) or []),
            },
        )
        runtime_events = drain_runtime_events(runtime, consumer="trajectory")
        if runtime_events:
            for event in runtime_events:
                self._write_event(state, runtime, "middleware_event", event)
        return updates

    @override
    def after_model(self, state: TrajectoryMiddlewareState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", []) or []
        last_msg = messages[-1] if messages else None
        tool_calls = getattr(last_msg, "tool_calls", None) or []
        updates = self._write_event(
            state,
            runtime,
            "after_model",
            {
                "tool_calls_count": len(tool_calls),
                "last_message_type": getattr(last_msg, "type", None),
            },
        )
        runtime_events = drain_runtime_events(runtime, consumer="trajectory")
        if runtime_events:
            for event in runtime_events:
                self._write_event(state, runtime, "middleware_event", event)
        return updates

    @override
    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        state = getattr(request, "state", {}) or {}
        runtime = request.runtime
        self._write_event(
            state,
            runtime,
            "model_call_start",
            {"message_count": len(request.messages or [])},
        )
        result = handler(request)
        response = getattr(result, "result", [])
        self._write_event(
            state,
            runtime,
            "model_call_end",
            {"result_count": len(response) if isinstance(response, list) else 0},
        )
        return result

    @override
    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        state = getattr(request, "state", {}) or {}
        runtime = request.runtime
        self._write_event(
            state,
            runtime,
            "model_call_start",
            {"message_count": len(request.messages or [])},
        )
        # try/finally so a raised handler still produces a terminal event in
        # the trajectory. Without this, a crash mid-call leaves the trajectory
        # ending at `model_call_start` (the same audit gap that hid the
        # run-c0425b71bd hang).
        result: ModelResponse | None = None
        error: BaseException | None = None
        try:
            result = await handler(request)
            return result
        except BaseException as exc:
            error = exc
            raise
        finally:
            response = getattr(result, "result", []) if result is not None else []
            timed_out = False
            if isinstance(response, list) and len(response) == 1:
                msg = response[0]
                content = getattr(msg, "content", "") or ""
                if isinstance(content, str) and TIMEOUT_MESSAGE_FINGERPRINT in content:
                    timed_out = True
            if timed_out:
                self._write_event(state, runtime, "model_call_timeout", {})
            self._write_event(
                state,
                runtime,
                "model_call_end",
                {
                    "result_count": len(response) if isinstance(response, list) else 0,
                    "timed_out": timed_out,
                    "error": str(error)[:400] if error is not None else None,
                },
            )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        state = request.state or {}
        runtime = request.runtime
        tool_name = request.tool_call.get("name")
        started_at = time.time()
        self._write_event(state, runtime, "tool_call_start", {"tool": tool_name, "tool_call_id": request.tool_call.get("id"), "tool_started_at": started_at})
        result: ToolMessage | Command | None = None
        completed_at: float | None = None
        try:
            result = handler(request)
            completed_at = time.time()
            return result
        finally:
            result_type = "command" if isinstance(result, Command) else "tool_message"
            self._write_event(
                state,
                runtime,
                "tool_call_end",
                {"tool": tool_name, "result_type": result_type, "tool_completed_at": completed_at, "duration_ms": round((completed_at - started_at) * 1000, 1) if completed_at else None},
            )

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        state = request.state or {}
        runtime = request.runtime
        tool_name = request.tool_call.get("name")
        started_at = time.time()
        self._write_event(state, runtime, "tool_call_start", {"tool": tool_name, "tool_call_id": request.tool_call.get("id"), "tool_started_at": started_at})
        # try/finally guarantees `tool_call_end` is recorded for every started
        # call. Was missing for write_todos in run-c0425b71bd.
        result: ToolMessage | Command | None = None
        error: BaseException | None = None
        completed_at: float | None = None
        try:
            result = await handler(request)
            # Record the actual tool completion timestamp BEFORE the SSE writer
            # serializes the event. Without this, parallel tools that finish
            # simultaneously appear staggered in the trajectory because event
            # emission is single-threaded — see thread-cd90decb finding #6.
            completed_at = time.time()
            return result
        except BaseException as exc:
            error = exc
            completed_at = time.time()
            raise
        finally:
            result_type = "command" if isinstance(result, Command) else "tool_message"
            timed_out = False
            if isinstance(result, ToolMessage):
                content = getattr(result, "content", "") or ""
                if isinstance(content, str) and TIMEOUT_MESSAGE_FINGERPRINT in content:
                    timed_out = True
            if timed_out:
                self._write_event(state, runtime, "tool_call_timeout", {"tool": tool_name, "tool_call_id": request.tool_call.get("id")})
            self._write_event(
                state,
                runtime,
                "tool_call_end",
                {
                    "tool": tool_name,
                    "result_type": result_type,
                    "timed_out": timed_out,
                    "error": str(error)[:400] if error is not None else None,
                    "tool_completed_at": completed_at,
                    "duration_ms": round((completed_at - started_at) * 1000, 1) if completed_at else None,
                },
            )
