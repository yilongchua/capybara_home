"""Tests for DAG todo middleware."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from src.agents.middlewares.todo_dag_middleware import TodoDagMiddleware, _is_acyclic, find_dangling_deps, merge_todo_nodes, normalize_todo_nodes
from src.tools.builtins.write_todos_tool import write_todos_tool


def _runtime(state: dict | None = None, *, mode: str | None = None):
    context: dict[str, str] = {"thread_id": "thread-1"}
    if mode is not None:
        context["mode"] = mode
    return SimpleNamespace(context=context, state=state or {})


def test_normalize_todos_rejects_cycles():
    with pytest.raises(ValueError, match="cycle"):
        normalize_todo_nodes(
            [
                {"id": "a", "content": "A", "depends_on": ["b"]},
                {"id": "b", "content": "B", "depends_on": ["a"]},
            ]
        )


def test_merge_todo_nodes_does_not_alias_steps_from_source():
    """#20: merged nodes must not share their `steps` dicts with the input payload."""
    source_step = {"description": "original", "completion_requirement": "done"}
    existing = [
        {
            "id": "a",
            "content": "A",
            "status": "pending",
            "depends_on": [],
            "steps": [source_step],
        }
    ]
    merged = merge_todo_nodes(existing, [])

    # Mutating the source must not bleed into the merged copy.
    source_step["description"] = "mutated"
    assert merged[0]["steps"][0]["description"] == "original"

    # Replacing steps via merge must also detach from the raw payload.
    new_step = {"description": "patched", "completion_requirement": "done"}
    patched = merge_todo_nodes(existing, [{"id": "a", "steps": [new_step]}])
    new_step["description"] = "mutated-again"
    assert patched[0]["steps"][0]["description"] == "patched"


def test_merge_todo_nodes_appended_new_node_detaches_steps():
    """#20: the new-node branch of merge_todo_nodes must also detach `steps`."""
    new_step = {"description": "original", "completion_requirement": "done"}
    merged = merge_todo_nodes([], [{"id": "fresh", "content": "Fresh", "steps": [new_step]}])
    new_step["description"] = "mutated"
    assert merged[0]["steps"][0]["description"] == "original"


def test_normalize_todo_nodes_detaches_steps_from_source():
    """#20: normalize_todo_nodes is the planner entry point — must not alias steps."""
    source_step = {"description": "original", "completion_requirement": "done"}
    normalized = normalize_todo_nodes(
        [{"id": "a", "content": "A", "steps": [source_step]}]
    )
    source_step["description"] = "mutated"
    assert normalized[0]["steps"][0]["description"] == "original"


def test_write_todos_tool_merge_passes_through_steps_without_aliasing():
    """#20: the write_todos_tool's local merge_todo_nodes also defends against aliasing.

    The tool itself never writes `steps`, but planner-set values pass through it
    when the LLM patches other fields on the same todo.
    """
    from src.tools.builtins.write_todos_tool import merge_todo_nodes as tool_merge

    planner_step = {"description": "original", "completion_requirement": "done"}
    existing = [
        {
            "id": "a",
            "content": "A",
            "status": "pending",
            "depends_on": [],
            "steps": [planner_step],
        }
    ]
    merged = tool_merge(existing, [{"id": "a", "status": "in_progress"}])
    planner_step["description"] = "mutated"
    assert merged[0]["steps"][0]["description"] == "original"


def test_cycle_check_is_separate_from_dangling_dependency_detection():
    nodes = [
        {"id": "a", "content": "A", "depends_on": ["missing"]},
        {"id": "b", "content": "B", "depends_on": ["a"]},
    ]

    assert _is_acyclic(nodes) is True
    assert find_dangling_deps(nodes) == {"a": ["missing"]}


def test_write_todos_dual_writes_legacy_and_graph():
    result = write_todos_tool.func(
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
    result = write_todos_tool.func(
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


def test_write_todos_blocks_completed_while_plan_draft_in_plan_mode():
    runtime = _runtime(
        {
            "plan": {
                "title": "Plan Title",
                "summary": "Plan Summary",
                "status": "draft",
            },
            "todo_graph": {
                "nodes": [{"id": "a", "content": "Research", "status": "pending", "depends_on": []}],
            },
        },
        mode="plan",
    )
    result = write_todos_tool.func(
        runtime=runtime,
        todos=[{"id": "a", "content": "Research", "status": "completed"}],
        tool_call_id="tc-draft",
    )
    message = result.update["messages"][0]
    assert "[todo_update_rejected:draft_completion_blocked]" in message.content


def test_write_todos_allows_completed_while_plan_draft_in_work_mode():
    runtime = _runtime(
        {
            "plan": {
                "title": "Plan Title",
                "summary": "Plan Summary",
                "status": "draft",
            },
            "todo_graph": {
                "nodes": [{"id": "a", "content": "Research", "status": "pending", "depends_on": []}],
            },
        },
        mode="work",
    )
    result = write_todos_tool.func(
        runtime=runtime,
        todos=[{"id": "a", "content": "Research", "status": "completed"}],
        tool_call_id="tc-draft-work",
    )
    nodes = result.update["todo_graph"]["nodes"]
    assert nodes[0]["status"] == "completed"


def test_write_todos_allows_completed_while_plan_executing():
    runtime = _runtime(
        {
            "plan": {
                "title": "Plan Title",
                "summary": "Plan Summary",
                "status": "executing",
            },
            "todo_graph": {
                "nodes": [{"id": "a", "content": "Research", "status": "in_progress", "depends_on": []}],
            },
        }
    )
    result = write_todos_tool.func(
        runtime=runtime,
        todos=[{"id": "a", "status": "completed"}],
        tool_call_id="tc-exec",
    )
    nodes = result.update["todo_graph"]["nodes"]
    assert nodes[0]["status"] == "completed"


def test_write_todos_blocks_mutation_when_plan_completed():
    runtime = _runtime(
        {
            "plan": {
                "title": "Plan Title",
                "summary": "Plan Summary",
                "status": "completed",
            },
            "todo_graph": {
                "nodes": [{"id": "a", "content": "Research", "status": "completed", "depends_on": []}],
            },
        }
    )
    result = write_todos_tool.func(
        runtime=runtime,
        todos=[{"id": "a", "status": "pending"}],
        tool_call_id="tc-completed",
    )
    message = result.update["messages"][0]
    assert "[todo_update_rejected:completed_plan_frozen]" in message.content
    assert result.update["todo_last_error_code"] == "completed_plan_frozen"


def test_write_todos_validation_failure_returns_guidance():
    runtime = _runtime(
        {
            "todo_graph": {
                "nodes": [
                    {"id": "a", "content": "A", "status": "pending", "depends_on": ["b"]},
                    {"id": "b", "content": "B", "status": "pending", "depends_on": []},
                ]
            }
        }
    )
    result = write_todos_tool.func(
        runtime=runtime,
        todos=[{"id": "b", "depends_on": ["a"]}],
        tool_call_id="tc-invalid",
    )
    message = result.update["messages"][0]
    assert "[todo_update_validation_failed:validation_failed]" in message.content
    assert "Double check write_todos schema" in message.content


def test_write_todos_syncs_plan(tmp_path):
    plan_path = tmp_path / ".runtime" / "plan.md"
    runtime = _runtime(
        {
            "plan": {
                "title": "Plan Title",
                "summary": "Plan Summary",
                "plan_path": str(plan_path),
            }
        }
    )

    write_todos_tool.func(
        runtime=runtime,
        todos=[
            {"id": "a", "content": "Plan", "status": "completed"},
            {"id": "b", "content": "Execute", "status": "in_progress", "depends_on": ["a"]},
        ],
        tool_call_id="tc-1",
    )

    plan_text = plan_path.read_text(encoding="utf-8")
    assert "- [x] **a**: Plan" in plan_text
    assert "- [ ] **b**: Execute" in plan_text
    assert "## Todo Status Snapshot" in plan_text
    assert "- [completed] a: Plan" in plan_text


def test_write_todos_sync_idempotent(tmp_path):
    plan_path = tmp_path / ".runtime" / "plan.md"
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
    write_todos_tool.func(runtime=runtime, todos=todos, tool_call_id="tc-1")
    first_mtime = plan_path.stat().st_mtime_ns
    time.sleep(0.002)
    write_todos_tool.func(runtime=runtime, todos=todos, tool_call_id="tc-2")
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
    assert "todo_dag_reminder" == update["messages"][0].name


# ── P4 reminder-deduplication tests ──────────────────────────────────────────

def test_before_model_skips_reminder_when_recent_reminder_present():
    """Reminder must not be injected if one already sits in the last 6 messages."""
    from langchain_core.messages import AIMessage

    middleware = TodoDagMiddleware()
    state = {
        "messages": [
            HumanMessage(content="user question"),
            HumanMessage(name="todo_dag_reminder", content="<system_reminder>...</system_reminder>"),
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
            HumanMessage(name="todo_dag_reminder", content="<system_reminder>old</system_reminder>"),
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
    assert update["messages"][0].name == "todo_dag_reminder"


def test_dag_reminder_skipped_when_list_mode_reminder_recently_injected():
    """#17: DAG guard recognizes a legacy `todo_reminder` so a config-flip
    from list mode to DAG mode mid-thread doesn't stack reminders."""
    from langchain_core.messages import AIMessage

    middleware = TodoDagMiddleware()
    state = {
        "messages": [
            HumanMessage(content="q"),
            HumanMessage(name="todo_reminder", content="<system_reminder>legacy</system_reminder>"),
            AIMessage(content="a"),
        ],
        "todo_graph": {
            "nodes": [{"id": "a", "content": "Task", "status": "pending", "depends_on": []}],
            "ready_ids": ["a"],
            "updated_at": "2026-01-01T00:00:00Z",
        },
    }
    update = middleware.before_model(state, _runtime())
    assert update is None
