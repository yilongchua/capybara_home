"""Retry middleware for todo failures in work mode.

When the model attempts to finish while todos are still incomplete, this
middleware injects a focused recovery instruction that tells the model to
reconcile todo state via ``write_todos`` and continue only with remaining work.
"""

from __future__ import annotations

from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

_MAX_TODO_RECOVERY_ATTEMPTS = 2

_TODO_RECOVERY_PROMPT = """You are in work mode. Do not create a new plan.
1) Read current todo_graph/plan.
2) Call write_todos to reconcile invalid statuses/dependencies:
   - mark completed items as completed
   - keep only truly active items as in_progress
   - mark blocked items with reason
3) Then continue execution for remaining todos only.
4) Return a short status summary with todo IDs changed."""


class TodoFailureRetryState(AgentState):
    """State needed for todo-failure recovery."""

    todo_graph: NotRequired[dict | None]
    todo_recovery_attempts: NotRequired[int]


def _has_incomplete_todos(state: TodoFailureRetryState) -> bool:
    graph = state.get("todo_graph") or {}
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return False
    return any(node.get("status") != "completed" for node in nodes if isinstance(node, dict))


class TodoFailureRetryMiddleware(AgentMiddleware[TodoFailureRetryState]):
    """Injects a recovery instruction when work-mode todos fail to converge."""

    state_schema = TodoFailureRetryState

    @override
    def after_model(self, state: TodoFailureRetryState, runtime: Runtime) -> dict[str, Any] | None:
        runtime_context = getattr(runtime, "context", None) or {}
        if str(runtime_context.get("mode") or "work").strip().lower() != "work":
            return None

        if not _has_incomplete_todos(state):
            return None

        messages = state.get("messages") or []
        if not messages:
            return None

        last = messages[-1]
        if getattr(last, "type", None) != "ai":
            return None
        if getattr(last, "tool_calls", None):
            return None

        attempts = int(state.get("todo_recovery_attempts", 0))
        if attempts >= _MAX_TODO_RECOVERY_ATTEMPTS:
            return None

        reminder = HumanMessage(
            name="todo_failure_recovery",
            content=f"<system_reminder>\n{_TODO_RECOVERY_PROMPT}\n</system_reminder>",
        )
        return {
            "messages": [reminder],
            "todo_recovery_attempts": attempts + 1,
            "jump_to": "model",
        }

    @override
    async def aafter_model(self, state: TodoFailureRetryState, runtime: Runtime) -> dict[str, Any] | None:
        return self.after_model(state, runtime)


TodoFailureRetryMiddleware.after_model.__can_jump_to__ = ["model"]  # type: ignore[attr-defined]
TodoFailureRetryMiddleware.aafter_model.__can_jump_to__ = ["model"]  # type: ignore[attr-defined]
