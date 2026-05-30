"""Background sync for living plan files."""

from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.common.runtime_context import get_runtime_context
from src.agents.middlewares.handoff_sync import ensure_plan_state, sync_handoff_files_from_state
from src.agents.middlewares.runtime_events import append_runtime_event

logger = logging.getLogger(__name__)

# Per-thread lock to serialize concurrent plan.md writes. Two background workers
# for the same thread can otherwise race (e.g. when a quick second turn fires
# before the first 1s settle delay elapses).
_THREAD_SYNC_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_REGISTRY_LOCK = threading.Lock()


def _get_thread_lock(thread_id: str) -> threading.Lock:
    with _LOCKS_REGISTRY_LOCK:
        lock = _THREAD_SYNC_LOCKS.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _THREAD_SYNC_LOCKS[thread_id] = lock
        return lock


# Fields that the handoff sync helpers actually read. Snapshotting these
# narrowly skips heavy unused state (viewed_images, uploaded_files, scratchpad,
# etc.). `messages` and `todos` are needed because handoff_sync uses them for
# title fallback and execution-notes rendering; we shallow-copy messages since
# BaseMessage instances are effectively immutable for our purposes.
_DEEP_COPY_FIELDS = (
    "plan",
    "todo_graph",
    "artifacts",
    "handoff_artifacts",
    "thread_data",
    "todos",
)
_SHALLOW_COPY_FIELDS = ("messages",)


class PlanFileSyncState(AgentState):
    plan: NotRequired[dict | None]
    todo_graph: NotRequired[dict | None]
    artifacts: NotRequired[list[str] | None]
    handoff_artifacts: NotRequired[list[str] | None]
    thread_data: NotRequired[dict | None]


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content)


def _run_background_plan_sync(snapshot: dict[str, Any], thread_id: str) -> None:
    # Brief settle delay so the foreground turn's state has propagated.
    time.sleep(1.0)
    lock = _get_thread_lock(thread_id) if thread_id else None
    try:
        if lock is not None:
            with lock:
                ensure_plan_state(snapshot)
                sync_handoff_files_from_state(snapshot)
        else:
            ensure_plan_state(snapshot)
            sync_handoff_files_from_state(snapshot)
    except Exception:
        logger.exception("Background plan file sync failed")


class PlanFileSyncMiddleware(AgentMiddleware[PlanFileSyncState]):
    """Keeps plan.md and its latest backup copy fresh without blocking the foreground turn."""

    state_schema = PlanFileSyncState

    def _is_terminal_ai_response(self, state: PlanFileSyncState) -> bool:
        messages = state.get("messages", []) or []
        if not messages:
            return False
        last = messages[-1]
        if getattr(last, "type", None) != "ai":
            return False
        if getattr(last, "tool_calls", None):
            return False
        return bool(_extract_text(getattr(last, "content", "")).strip())

    @override
    def after_model(self, state: PlanFileSyncState, runtime: Runtime) -> dict | None:
        runtime_context = get_runtime_context(runtime)
        if bool(runtime_context.get("background_followup")):
            return None
        if not state.get("todo_graph") and not state.get("plan"):
            return None

        ensured_plan = ensure_plan_state(dict(state))
        if ensured_plan is None:
            return None
        if not self._is_terminal_ai_response(state):
            return {"plan": ensured_plan} if not state.get("plan") else None

        snapshot: dict[str, Any] = {}
        for field in _DEEP_COPY_FIELDS:
            value = state.get(field)
            if value is not None:
                snapshot[field] = copy.deepcopy(value)
        for field in _SHALLOW_COPY_FIELDS:
            value = state.get(field)
            if value is not None:
                snapshot[field] = list(value) if isinstance(value, list) else value
        snapshot["plan"] = ensured_plan
        thread_id = str(runtime_context.get("thread_id") or "")
        worker = threading.Thread(
            target=_run_background_plan_sync,
            kwargs={"snapshot": snapshot, "thread_id": thread_id},
            name=f"plan-file-sync-{thread_id[:8] if thread_id else 'anon'}",
            daemon=True,
        )
        worker.start()
        append_runtime_event(
            runtime,
            {
                "source": "plan_file_sync_middleware",
                "event": "background_plan_sync_started",
                "summary": "Refreshing living plan files in background",
            },
        )
        if not state.get("plan"):
            return {"plan": ensured_plan}
        return None

    @override
    async def aafter_model(self, state: PlanFileSyncState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)
