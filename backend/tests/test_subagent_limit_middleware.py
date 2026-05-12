"""Tests for endpoint-aware subagent scheduling middleware."""

from __future__ import annotations

from types import MethodType, SimpleNamespace

from langchain_core.messages import AIMessage

from src.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware


def _runtime():
    return SimpleNamespace(context={"thread_id": "thread-1"})


def _state_with_tasks():
    return {
        "messages": [
            AIMessage(
                content="run subagents",
                tool_calls=[
                    {"name": "task", "id": "t1", "args": {"description": "A", "subagent_type": "general-purpose"}},
                    {"name": "task", "id": "t2", "args": {"description": "B", "subagent_type": "general-purpose"}},
                    {"name": "task", "id": "t3", "args": {"description": "C", "subagent_type": "bash"}},
                ],
            )
        ]
    }


def test_primary_tasks_are_deferred_when_limit_exceeded():
    middleware = SubagentLimitMiddleware(max_concurrent=3, max_primary_per_turn=1)

    # Force all tasks to primary to test deferral.
    middleware._target_endpoint = MethodType(lambda self, tc: "primary", middleware)  # type: ignore[method-assign]

    update = middleware.after_model(_state_with_tasks(), _runtime())
    assert update is not None
    assert len(update["deferred_task_calls"]) == 2
    assert len(update["messages"][0].tool_calls) == 1


def test_helper_tasks_can_execute_without_primary_deferral():
    middleware = SubagentLimitMiddleware(max_concurrent=3, max_primary_per_turn=1)

    def _endpoint(self, tc):
        return "helper" if tc.get("id") == "t3" else "primary"

    middleware._target_endpoint = MethodType(_endpoint, middleware)  # type: ignore[method-assign]
    update = middleware.after_model(_state_with_tasks(), _runtime())
    assert update is not None
    # One primary kept + helper kept, second primary deferred
    assert len(update["messages"][0].tool_calls) == 2
    assert len(update["deferred_task_calls"]) == 1


def test_total_concurrency_cap_enforced():
    middleware = SubagentLimitMiddleware(max_concurrent=2, max_primary_per_turn=3)
    middleware._target_endpoint = MethodType(lambda self, tc: "helper", middleware)  # type: ignore[method-assign]

    update = middleware.after_model(_state_with_tasks(), _runtime())
    assert update is not None
    assert len(update["messages"][0].tool_calls) == 2
    assert len(update["deferred_task_calls"]) == 1


def test_deferred_tasks_drain_fifo_priority():
    middleware = SubagentLimitMiddleware(max_concurrent=2, max_primary_per_turn=2)
    middleware._target_endpoint = MethodType(lambda self, tc: "primary", middleware)  # type: ignore[method-assign]

    state = {
        "deferred_task_calls": [
            {"name": "task", "id": "old-1", "args": {"description": "old-1", "subagent_type": "general-purpose"}},
            {"name": "task", "id": "old-2", "args": {"description": "old-2", "subagent_type": "general-purpose"}},
        ],
        "messages": [
            AIMessage(
                content="new tasks",
                tool_calls=[
                    {"name": "task", "id": "new-1", "args": {"description": "new-1", "subagent_type": "general-purpose"}},
                    {"name": "task", "id": "new-2", "args": {"description": "new-2", "subagent_type": "general-purpose"}},
                ],
            )
        ],
    }
    update = middleware.after_model(state, _runtime())
    assert update is not None
    kept_ids = [call["id"] for call in update["messages"][0].tool_calls if call.get("name") == "task"]
    deferred_ids = [call["id"] for call in update["deferred_task_calls"]]
    assert kept_ids == ["old-1", "old-2"]
    assert deferred_ids == ["new-1", "new-2"]
