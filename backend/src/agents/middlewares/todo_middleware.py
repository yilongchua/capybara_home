"""Middleware that extends TodoListMiddleware with context-loss detection and exit enforcement.

Two behaviours added on top of TodoListMiddleware:

1. **Context-loss detection** (before_model):
   When SummarizationMiddleware truncates the history, the original ``write_todos``
   tool call scrolls out of the active window.  We detect this gap and inject a
   reminder so the model still knows about the outstanding todo list.

2. **Premature-exit enforcement** (after_model):
   If the model produces a final response (no tool calls) while todos remain
   incomplete, we re-engage it with an explicit reminder — up to ``todos.max_exit_reminders``
   times per run — so it finishes what it started rather than silently stopping early.
"""

from __future__ import annotations

from typing import Any, override

from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.todo import PlanningState, Todo
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.handoff_sync import sync_handoff_files_from_state
from src.config.todos_config import get_todos_config


def _todos_in_messages(messages: list[Any]) -> bool:
    """Return True if any AIMessage in *messages* contains a write_todos tool call."""
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("name") == "write_todos":
                    return True
    return False


def _reminder_in_messages(messages: list[Any]) -> bool:
    """Return True if a todo_reminder HumanMessage is already present in *messages*."""
    for msg in messages:
        if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == "todo_reminder":
            return True
    return False


def _count_exit_reminders(messages: list[Any]) -> int:
    """Count how many todo_incomplete_reminder messages have been injected so far."""
    return sum(
        1
        for msg in messages
        if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == "todo_incomplete_reminder"
    )


def _format_todos(todos: list[Todo]) -> str:
    """Format a list of Todo items into a human-readable string."""
    lines: list[str] = []
    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        lines.append(f"- [{status}] {content}")
    return "\n".join(lines)


def _has_incomplete_todos(todos: list[Todo]) -> bool:
    return any(t.get("status") not in ("completed",) for t in todos)


class TodoMiddleware(TodoListMiddleware):
    """Extends TodoListMiddleware with context-loss detection and premature-exit enforcement.

    ``before_model``:
        Injects a reminder when the original ``write_todos`` call has scrolled
        out of the context window due to summarization.

    ``after_model``:
        If the model tries to exit (no tool calls) while todos remain incomplete,
        forces a re-run via ``jump_to: "agent"`` with an explicit reminder,
        capped at ``todos.max_exit_reminders`` retries to prevent infinite loops.
    """

    @override
    def before_model(
        self,
        state: PlanningState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Inject a todo-list reminder when write_todos has left the context window."""
        sync_handoff_files_from_state(state)
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        if not todos:
            return None

        messages = state.get("messages") or []
        if _todos_in_messages(messages):
            return None

        if _reminder_in_messages(messages):
            return None

        formatted = _format_todos(todos)
        reminder = HumanMessage(
            name="todo_reminder",
            content=(
                "<system_reminder>\n"
                "Your todo list from earlier is no longer visible in the current context window, "
                "but it is still active. Here is the current state:\n\n"
                f"{formatted}\n\n"
                "Continue tracking and updating this todo list as you work. "
                "Call `write_todos` whenever the status of any item changes.\n"
                "</system_reminder>"
            ),
        )
        return {"messages": [reminder]}

    @override
    def after_model(
        self,
        state: PlanningState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Re-engage the model when it exits prematurely with incomplete todos.

        If the last AI message has no tool calls (the model is about to finish the run)
        but there are still pending or in-progress todos, inject a reminder and jump
        back to the agent node.  This is capped at todos.max_exit_reminders injections to
        prevent an infinite loop when the model genuinely cannot proceed.
        """
        sync_handoff_files_from_state(state)
        todos: list[Todo] = state.get("todos") or []  # type: ignore[assignment]
        if not todos or not _has_incomplete_todos(todos):
            return None

        messages = state.get("messages") or []
        if not messages:
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None
        if getattr(last_msg, "tool_calls", None):
            # Model is still using tools — normal flow, nothing to enforce.
            return None

        # Model produced a final response while todos are incomplete.
        # Check the retry cap before injecting another reminder.
        if _count_exit_reminders(messages) >= get_todos_config().max_exit_reminders:
            return None

        formatted = _format_todos(todos)
        reminder = HumanMessage(
            name="todo_incomplete_reminder",
            content=(
                "<system_reminder>\n"
                "You have stopped working but your todo list is not fully completed. "
                "The following items still need attention:\n\n"
                f"{formatted}\n\n"
                "Please continue working through the remaining tasks. "
                "Mark each item as completed with `write_todos` when done. "
                "Only stop when all items are marked `completed`.\n"
                "</system_reminder>"
            ),
        )
        return {"messages": [reminder], "jump_to": "model"}

    @override
    async def abefore_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        return self.before_model(state, runtime)

    @override
    async def aafter_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        return self.after_model(state, runtime)


# Wire the jump target so create_agent builds the conditional edge from
# after_model → model.  Without this annotation the framework treats
# ``jump_to: "model"`` as an unknown field and never re-routes.
TodoMiddleware.after_model.__can_jump_to__ = ["model"]  # type: ignore[attr-defined]
TodoMiddleware.aafter_model.__can_jump_to__ = ["model"]  # type: ignore[attr-defined]
