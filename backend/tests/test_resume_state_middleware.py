"""Tests for resume state middleware."""

from types import SimpleNamespace

from src.agents.middlewares.resume_state_middleware import ResumeStateMiddleware
from src.config.resume_config import ResumeConfig


def test_resume_state_tracks_continuity_markers():
    middleware = ResumeStateMiddleware(ResumeConfig(enabled=True, require_checkpoint=True, max_resume_depth=3))
    state = {
        "todo_graph": {
            "nodes": [
                {"id": "todo-1", "status": "completed"},
                {"id": "todo-2", "status": "pending"},
            ],
            "ready_ids": ["todo-2"],
        },
        "deferred_task_calls": [{"id": "tc-1"}],
        "handoff_artifacts": ["/tmp/.handoffs/plan.md", "/tmp/.handoffs/report.md"],
    }
    runtime = SimpleNamespace(context={"thread_id": "thread-1", "checkpoint_id": "ckpt-123"})
    update = middleware.after_model(state, runtime)
    assert update is not None
    resume_meta = update["resume_meta"]
    assert resume_meta["last_checkpoint_id"] == "ckpt-123"
    assert resume_meta["last_completed_todo_id"] == "todo-1"
    assert resume_meta["pending_ready_ids"] == ["todo-2"]
    assert resume_meta["deferred_task_calls_count"] == 1
    assert len(resume_meta["handoff_refs"]) == 2


# ── P9: missing ResumeMetaState fields ───────────────────────────────────────

def test_resume_state_tracks_in_progress_todo_ids():
    """in_progress_todo_ids must list todos with status == 'in_progress'."""
    middleware = ResumeStateMiddleware(ResumeConfig(enabled=True, require_checkpoint=True, max_resume_depth=3))
    state = {
        "todo_graph": {
            "nodes": [
                {"id": "todo-1", "status": "completed"},
                {"id": "todo-2", "status": "in_progress"},
                {"id": "todo-3", "status": "pending"},
            ],
            "ready_ids": ["todo-3"],
        },
    }
    runtime = SimpleNamespace(context={"thread_id": "t1", "checkpoint_id": None})
    update = middleware.after_model(state, runtime)
    assert update is not None
    assert update["resume_meta"]["in_progress_todo_ids"] == ["todo-2"]


def test_resume_state_tracks_retry_counts():
    """retry_counts must be copied from retry_meta.attempts_by_tool_call."""
    middleware = ResumeStateMiddleware(ResumeConfig(enabled=True, require_checkpoint=True, max_resume_depth=3))
    state = {
        "retry_meta": {
            "attempts_by_tool_call": {"call-abc": 2, "call-def": 1},
        },
    }
    runtime = SimpleNamespace(context={"thread_id": "t1", "checkpoint_id": None})
    update = middleware.after_model(state, runtime)
    assert update is not None
    assert update["resume_meta"]["retry_counts"] == {"call-abc": 2, "call-def": 1}


def test_resume_state_tracks_running_subagent_ids():
    """running_subagent_ids must include deferred tasks that are not yet terminal."""
    middleware = ResumeStateMiddleware(ResumeConfig(enabled=True, require_checkpoint=True, max_resume_depth=3))
    state = {
        "deferred_task_calls": [
            {"id": "sa-1", "status": "running"},
            {"id": "sa-2", "status": "completed"},
            {"id": "sa-3", "status": "pending"},
            {"id": "sa-4", "status": "failed"},
        ],
    }
    runtime = SimpleNamespace(context={"thread_id": "t1", "checkpoint_id": None})
    update = middleware.after_model(state, runtime)
    assert update is not None
    running = update["resume_meta"]["running_subagent_ids"]
    assert "sa-1" in running  # running → included
    assert "sa-3" in running  # pending → included (not yet terminal)
    assert "sa-2" not in running  # completed → excluded
    assert "sa-4" not in running  # failed → excluded


def test_resume_state_empty_when_no_in_progress_todos():
    """in_progress_todo_ids must be an empty list when nothing is in_progress."""
    middleware = ResumeStateMiddleware(ResumeConfig(enabled=True, require_checkpoint=True, max_resume_depth=3))
    state = {
        "todo_graph": {
            "nodes": [{"id": "todo-1", "status": "completed"}],
            "ready_ids": [],
        },
    }
    runtime = SimpleNamespace(context={"thread_id": "t1", "checkpoint_id": None})
    update = middleware.after_model(state, runtime)
    assert update is not None
    assert update["resume_meta"]["in_progress_todo_ids"] == []
