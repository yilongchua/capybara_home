"""Tests for TodoMiddleware — context-loss detection and premature-exit enforcement."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.todo_middleware import (
    TodoMiddleware,
    _count_exit_reminders,
    _format_todos,
    _has_incomplete_todos,
    _reminder_in_messages,
    _todos_in_messages,
)


def _runtime():
    return SimpleNamespace(context={"thread_id": "t1"})


def _todo(content: str, status: str = "pending") -> dict:
    return {"content": content, "status": status}


def _write_todos_ai():
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": "write_todos", "args": {}, "id": "tc1"}]
    return msg


def _final_ai(content: str = "done") -> AIMessage:
    msg = AIMessage(content=content)
    msg.tool_calls = []
    return msg


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


def test_todos_in_messages_true():
    assert _todos_in_messages([_write_todos_ai()]) is True


def test_todos_in_messages_false():
    assert _todos_in_messages([HumanMessage(content="hi")]) is False


def test_reminder_in_messages():
    reminder = HumanMessage(name="todo_reminder", content="...")
    assert _reminder_in_messages([reminder]) is True
    assert _reminder_in_messages([HumanMessage(content="plain")]) is False


def test_count_exit_reminders():
    msgs = [
        HumanMessage(name="todo_incomplete_reminder", content="..."),
        HumanMessage(content="other"),
        HumanMessage(name="todo_incomplete_reminder", content="..."),
    ]
    assert _count_exit_reminders(msgs) == 2


def test_has_incomplete_todos():
    assert _has_incomplete_todos([_todo("a", "pending")]) is True
    assert _has_incomplete_todos([_todo("a", "in_progress")]) is True
    assert _has_incomplete_todos([_todo("a", "completed")]) is False
    assert _has_incomplete_todos([_todo("a", "completed"), _todo("b", "pending")]) is True


def test_format_todos():
    todos = [_todo("step 1", "completed"), _todo("step 2", "in_progress")]
    result = _format_todos(todos)
    assert "completed" in result
    assert "in_progress" in result
    assert "step 1" in result


# ---------------------------------------------------------------------------
# before_model — context-loss detection
# ---------------------------------------------------------------------------


class TestBeforeModel:
    def _mw(self):
        return TodoMiddleware(system_prompt="", tool_description="")

    def test_no_todos_no_injection(self):
        mw = self._mw()
        state: dict[str, Any] = {"todos": [], "messages": []}
        assert mw.before_model(state, _runtime()) is None

    def test_write_todos_visible_no_injection(self):
        mw = self._mw()
        state = {"todos": [_todo("a")], "messages": [_write_todos_ai()]}
        assert mw.before_model(state, _runtime()) is None

    def test_reminder_already_present_no_double_inject(self):
        mw = self._mw()
        reminder = HumanMessage(name="todo_reminder", content="...")
        state = {"todos": [_todo("a")], "messages": [reminder]}
        assert mw.before_model(state, _runtime()) is None

    def test_injects_reminder_when_write_todos_scrolled_out(self):
        mw = self._mw()
        state = {
            "todos": [_todo("step 1", "pending"), _todo("step 2", "in_progress")],
            "messages": [HumanMessage(content="hi")],  # no write_todos visible
        }
        result = mw.before_model(state, _runtime())
        assert result is not None
        injected = result["messages"]
        assert len(injected) == 1
        msg = injected[0]
        assert isinstance(msg, HumanMessage)
        assert msg.name == "todo_reminder"
        assert "step 1" in msg.content
        assert "step 2" in msg.content


# ---------------------------------------------------------------------------
# after_model — premature-exit enforcement
# ---------------------------------------------------------------------------


class TestAfterModel:
    def _mw(self):
        return TodoMiddleware(system_prompt="", tool_description="")

    def test_no_todos_no_enforcement(self):
        mw = self._mw()
        state = {"todos": [], "messages": [_final_ai()]}
        assert mw.after_model(state, _runtime()) is None

    def test_all_todos_completed_no_enforcement(self):
        mw = self._mw()
        state = {
            "todos": [_todo("a", "completed"), _todo("b", "completed")],
            "messages": [_final_ai()],
        }
        assert mw.after_model(state, _runtime()) is None

    def test_model_still_using_tools_no_enforcement(self):
        mw = self._mw()
        state = {
            "todos": [_todo("a", "pending")],
            "messages": [_write_todos_ai()],  # has tool_calls
        }
        assert mw.after_model(state, _runtime()) is None

    def test_injects_reminder_when_model_exits_early(self):
        mw = self._mw()
        state = {
            "todos": [_todo("step 1", "in_progress"), _todo("step 2", "pending")],
            "messages": [_final_ai("I'm done")],
        }
        result = mw.after_model(state, _runtime())
        assert result is not None
        assert result.get("jump_to") == "model"
        msgs = result["messages"]
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)
        assert msgs[0].name == "todo_incomplete_reminder"
        assert "step 1" in msgs[0].content

    def test_enforcement_caps_at_max_reminders(self):
        mw = self._mw()
        existing_reminders = [
            HumanMessage(name="todo_incomplete_reminder", content="reminder 1"),
            HumanMessage(name="todo_incomplete_reminder", content="reminder 2"),
        ]
        state = {
            "todos": [_todo("step 1", "pending")],
            "messages": [*existing_reminders, _final_ai()],
        }
        # Already at cap (2 reminders) — should not inject a third
        result = mw.after_model(state, _runtime())
        assert result is None

    def test_enforcement_fires_before_cap(self):
        mw = self._mw()
        existing = [HumanMessage(name="todo_incomplete_reminder", content="reminder")]
        state = {
            "todos": [_todo("step 1", "pending")],
            "messages": [*existing, _final_ai()],
        }
        # Only 1 reminder so far — should inject a second
        result = mw.after_model(state, _runtime())
        assert result is not None
        assert result.get("jump_to") == "model"

    def test_jump_to_annotation_set(self):
        assert hasattr(TodoMiddleware.after_model, "__can_jump_to__")
        assert "model" in TodoMiddleware.after_model.__can_jump_to__
