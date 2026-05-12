"""Tests for DAG todo middleware."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from src.agents.middlewares.todo_dag_middleware import TodoDagMiddleware, normalize_todo_nodes


def _runtime(state: dict | None = None):
    return SimpleNamespace(context={"thread_id": "thread-1"}, state=state or {})


def test_normalize_todos_rejects_cycles():
    with pytest.raises(ValueError, match="cycle"):
        normalize_todo_nodes(
            [
                {"id": "a", "content": "A", "depends_on": ["b"]},
                {"id": "b", "content": "B", "depends_on": ["a"]},
            ]
        )


def test_write_todos_dual_writes_legacy_and_graph():
    middleware = TodoDagMiddleware()
    tool = middleware.tools[0]
    result = tool.func(
        runtime=_runtime(),
        todos=[
            {"id": "a", "content": "Plan", "status": "completed"},
            {"id": "b", "content": "Execute", "depends_on": ["a"]},
        ],
        tool_call_id="tc-1",
    )
    update = result.update
    assert "todo_graph" in update
    assert "todos" in update
    assert update["todos"][1]["content"] == "Execute"
    assert update["todo_graph"]["ready_ids"] == ["b"]


def test_write_todos_patches_by_id_and_preserves_untouched_nodes():
    middleware = TodoDagMiddleware()
    tool = middleware.tools[0]
    runtime = _runtime(
        {
            "todo_graph": {
                "nodes": [
                    {"id": "todo-1", "content": "Scope", "status": "completed", "depends_on": []},
                    {"id": "todo-2", "content": "Research", "status": "pending", "depends_on": ["todo-1"]},
                    {"id": "todo-3", "content": "Draft", "status": "pending", "depends_on": ["todo-2"]},
                    {"id": "todo-4", "content": "Review", "status": "pending", "depends_on": ["todo-3"]},
                ],
                "ready_ids": ["todo-2"],
            }
        }
    )
    result = tool.func(
        runtime=runtime,
        todos=[{"id": "todo-2", "status": "in_progress"}],
        tool_call_id="tc-1",
    )
    nodes = result.update["todo_graph"]["nodes"]
    assert len(nodes) == 4
    by_id = {node["id"]: node for node in nodes}
    assert by_id["todo-2"]["status"] == "in_progress"
    assert by_id["todo-3"]["status"] == "pending"
    assert by_id["todo-4"]["status"] == "pending"


def test_write_todos_syncs_plan_and_sprint_contract(tmp_path):
    middleware = TodoDagMiddleware()
    tool = middleware.tools[0]
    plan_path = tmp_path / ".handoffs" / "plan.md"
    sprint_path = tmp_path / ".handoffs" / "sprint_contract.md"
    runtime = _runtime(
        {
            "plan": {
                "title": "Plan Title",
                "summary": "Plan Summary",
                "plan_path": str(plan_path),
                "sprint_contract_path": str(sprint_path),
            }
        }
    )

    tool.func(
        runtime=runtime,
        todos=[
            {"id": "a", "content": "Plan", "status": "completed"},
            {"id": "b", "content": "Execute", "status": "in_progress", "depends_on": ["a"]},
        ],
        tool_call_id="tc-1",
    )

    plan_text = plan_path.read_text(encoding="utf-8")
    sprint_text = sprint_path.read_text(encoding="utf-8")
    assert "- [x] **a**: Plan" in plan_text
    assert "- [ ] **b**: Execute" in plan_text
    assert "## Todo Status" in sprint_text
    assert "- [completed] Plan" in sprint_text


def test_write_todos_sync_idempotent(tmp_path):
    middleware = TodoDagMiddleware()
    tool = middleware.tools[0]
    plan_path = tmp_path / ".handoffs" / "plan.md"
    runtime = _runtime(
        {
            "plan": {
                "title": "Plan Title",
                "summary": "Plan Summary",
                "plan_path": str(plan_path),
            }
        }
    )
    todos = [
        {"id": "a", "content": "Plan", "status": "completed"},
        {"id": "b", "content": "Execute", "status": "pending", "depends_on": ["a"]},
    ]
    tool.func(runtime=runtime, todos=todos, tool_call_id="tc-1")
    first_mtime = plan_path.stat().st_mtime_ns
    time.sleep(0.002)
    tool.func(runtime=runtime, todos=todos, tool_call_id="tc-2")
    second_mtime = plan_path.stat().st_mtime_ns
    assert second_mtime == first_mtime


def test_before_model_injects_reminder_when_write_todos_scrolled_out():
    middleware = TodoDagMiddleware()
    state = {
        "messages": [HumanMessage(content="hello")],
        "todo_graph": {
            "nodes": [{"id": "a", "content": "Task", "status": "pending", "depends_on": []}],
            "ready_ids": ["a"],
            "updated_at": "2026-01-01T00:00:00Z",
        },
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert "todo_reminder" == update["messages"][0].name


# ── P4 reminder-deduplication tests ──────────────────────────────────────────

def test_before_model_skips_reminder_when_recent_reminder_present():
    """Reminder must not be injected if one already sits in the last 6 messages."""
    from langchain_core.messages import AIMessage

    middleware = TodoDagMiddleware()
    state = {
        "messages": [
            HumanMessage(content="user question"),
            HumanMessage(name="todo_reminder", content="<system_reminder>...</system_reminder>"),
            AIMessage(content="model response"),
        ],
        "todo_graph": {
            "nodes": [{"id": "a", "content": "Task", "status": "pending", "depends_on": []}],
            "ready_ids": ["a"],
            "updated_at": "2026-01-01T00:00:00Z",
        },
    }
    update = middleware.before_model(state, _runtime())
    assert update is None, "Reminder should be suppressed when one is already in the last 6 messages"


def test_before_model_allows_reminder_when_no_recent_reminder():
    """Reminder IS injected when no reminder is within the last 6 messages."""
    from langchain_core.messages import AIMessage

    middleware = TodoDagMiddleware()
    # 7 messages; the reminder was injected earlier and is outside the 6-message window.
    state = {
        "messages": [
            HumanMessage(name="todo_reminder", content="<system_reminder>old</system_reminder>"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
        ],
        "todo_graph": {
            "nodes": [{"id": "a", "content": "Task", "status": "pending", "depends_on": []}],
            "ready_ids": ["a"],
            "updated_at": "2026-01-01T00:00:00Z",
        },
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None, "Reminder should be injected when none is within the last 6 messages"
    assert update["messages"][0].name == "todo_reminder"
