"""Tests for steering and explicit execute-plan gateway routes."""

import asyncio

import pytest
from fastapi import HTTPException

from src.gateway.routers.steering import (
    ExecutePlanRequest,
    SteerRequest,
    compact_thread,
    execute_plan,
    steer_thread,
)


class _ThreadsClient:
    def __init__(self, values: dict | None = None):
        self.calls = []
        self._values = values or {}

    async def get_state(self, thread_id: str):  # noqa: ARG002
        return {"values": self._values}

    async def update_state(self, thread_id: str, values: dict):
        self.calls.append((thread_id, values))
        self._values = {**self._values, **values}


class _Client:
    def __init__(self, threads: _ThreadsClient):
        self.threads = threads


def _messages(count: int) -> list[dict]:
    rows: list[dict] = []
    for i in range(count):
        msg_type = "human" if i % 2 == 0 else "ai"
        rows.append({"id": f"m{i}", "type": msg_type, "content": f"message {i}"})
    return rows


def test_steer_thread_router_success(monkeypatch):
    threads = _ThreadsClient()
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))
    monkeypatch.setattr(
        "src.gateway.routers.steering.enqueue_steering_intent",
        lambda **kwargs: {
            "status": "accepted",
            "intent": {
                "intent_id": kwargs["intent_id"],
                "message": kwargs["message"],
                "created_at": "2026-05-08T00:00:00Z",
            },
        },
    )

    response = asyncio.run(
        steer_thread(
            "thread-1",
            SteerRequest(message="Please avoid broad refactors."),
        )
    )

    assert response.acknowledged is True
    assert response.thread_id == "thread-1"
    assert response.status == "accepted"
    assert isinstance(response.intent_id, str)


def test_steer_thread_router_idempotent_on_existing_intent(monkeypatch):
    threads = _ThreadsClient()
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))
    monkeypatch.setattr(
        "src.gateway.routers.steering.enqueue_steering_intent",
        lambda **kwargs: {
            "status": "duplicate",
            "intent": {
                "intent_id": kwargs["intent_id"],
                "message": kwargs["message"],
                "created_at": "2026-05-08T00:00:00Z",
            },
        },
    )

    response = asyncio.run(
        steer_thread(
            "thread-1",
            SteerRequest(message="existing message", intent_id="intent-1"),
        )
    )

    assert response.acknowledged is True
    assert response.intent_id == "intent-1"
    assert response.status == "duplicate"


def test_steer_thread_router_conflict_on_same_intent_different_message(monkeypatch):
    threads = _ThreadsClient()
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))
    monkeypatch.setattr(
        "src.gateway.routers.steering.enqueue_steering_intent",
        lambda **kwargs: {
            "status": "conflict",
            "intent": {
                "intent_id": kwargs["intent_id"],
                "message": "existing message",
                "created_at": "2026-05-08T00:00:00Z",
            },
        },
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            steer_thread(
                "thread-1",
                SteerRequest(message="different message", intent_id="intent-1"),
            )
        )
    assert exc.value.status_code == 409


def test_steer_thread_router_rejects_blank_message():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(steer_thread("thread-1", SteerRequest(message="   ")))
    assert exc.value.status_code == 422


def test_steer_thread_router_maps_not_found(monkeypatch):
    class _NotFoundError(Exception):
        status_code = 404

    class _FailingThreadsClient:
        async def get_state(self, thread_id: str):  # noqa: ARG002
            raise _NotFoundError("missing")

        async def update_state(self, thread_id: str, values: dict):  # noqa: ARG002
            raise _NotFoundError("missing")

    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(_FailingThreadsClient()))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(steer_thread("missing-thread", SteerRequest(message="Steer me")))
    assert exc.value.status_code == 404


def test_execute_plan_conflict_when_clarification_pending(monkeypatch):
    threads = _ThreadsClient(values={"plan": {"plan_id": "plan-1", "status": "draft", "clarification_pending": True}})
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))

    response = asyncio.run(execute_plan("thread-1", ExecutePlanRequest(plan_id="plan-1")))
    assert response.acknowledged is False
    assert response.status == "conflict"


def test_execute_plan_resolves_answered_clarification(monkeypatch):
    threads = _ThreadsClient(
        values={
            "messages": [
                {
                    "type": "human",
                    "name": "planner_clarification_required",
                    "content": "<planner_clarification>Question: What timeframe should the research cover?</planner_clarification>",
                },
                {
                    "type": "human",
                    "content": [{"type": "text", "text": "Last 12 months (Recommended)"}],
                },
            ],
            "plan": {
                "plan_id": "plan-1",
                "status": "draft",
                "title": "Plan",
                "clarification_pending": True,
                "clarification_index": 0,
                "clarification_answers": [],
                "clarifications": [
                    {
                        "question": "What timeframe should the research cover?",
                        "options": [
                            {"label": "Last 12 months", "recommended": True},
                            {"label": "Last 3 years", "recommended": False},
                        ],
                    }
                ],
                "clarification_question": "What timeframe should the research cover?",
            },
            "plan_history": [{"plan_id": "plan-1", "title": "Plan", "status": "draft"}],
        }
    )
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))
    monkeypatch.setattr("src.gateway.routers.steering.spawn_work_mode_handoff", lambda **kwargs: None)

    response = asyncio.run(execute_plan("thread-1", ExecutePlanRequest(plan_id="plan-1")))

    assert response.acknowledged is True
    assert response.status == "accepted"
    assert response.plan_status == "approved"
    updated_plan = threads.calls[-1][1]["plan"]
    assert updated_plan["clarification_pending"] is False
    assert isinstance(updated_plan["clarification_answered_at"], str)


def test_execute_plan_accepts_draft_plan(monkeypatch):
    threads = _ThreadsClient(
        values={
            "plan": {"plan_id": "plan-1", "status": "draft", "title": "Plan"},
            "plan_history": [{"plan_id": "plan-1", "title": "Plan", "status": "draft"}],
        }
    )
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))

    response = asyncio.run(execute_plan("thread-1", ExecutePlanRequest(plan_id="plan-1")))
    assert response.acknowledged is True
    assert response.status == "accepted"
    assert response.plan_status == "approved"
    assert threads.calls, "execute endpoint should persist approved plan state"


def test_execute_plan_duplicate_for_already_approved(monkeypatch):
    threads = _ThreadsClient(
        values={
            "plan": {
                "plan_id": "plan-1",
                "status": "approved",
                "execution_handoff_started": True,
            }
        }
    )
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))
    spawn_calls: list[dict] = []
    monkeypatch.setattr(
        "src.gateway.routers.steering.spawn_work_mode_handoff",
        lambda **kwargs: spawn_calls.append(kwargs),
    )

    response = asyncio.run(execute_plan("thread-1", ExecutePlanRequest(plan_id="plan-1")))
    assert response.status == "duplicate"
    assert response.plan_status == "approved"
    assert spawn_calls == []


def test_execute_plan_recovers_approved_plan_without_handoff(monkeypatch):
    threads = _ThreadsClient(values={"plan": {"plan_id": "plan-1", "status": "approved"}})
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))
    spawn_calls: list[dict] = []
    monkeypatch.setattr(
        "src.gateway.routers.steering.spawn_work_mode_handoff",
        lambda **kwargs: spawn_calls.append(kwargs),
    )

    response = asyncio.run(execute_plan("thread-1", ExecutePlanRequest(plan_id="plan-1")))

    assert response.status == "accepted"
    assert response.plan_status == "approved"
    assert len(spawn_calls) == 1
    assert threads.calls[-1][1]["plan"]["execution_handoff_started"] is True


def test_execute_plan_conflict_when_plan_missing(monkeypatch):
    threads = _ThreadsClient(values={})
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))

    response = asyncio.run(execute_plan("thread-1", ExecutePlanRequest()))
    assert response.acknowledged is False
    assert response.status == "conflict"


def test_compact_thread_router_success(monkeypatch):
    threads = _ThreadsClient(values={"messages": _messages(20)})
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))

    response = asyncio.run(compact_thread("thread-1"))
    assert response.status == "accepted"
    assert response.compressed_messages > 0
    assert response.kept_messages > 0
    assert threads.calls


def test_compact_thread_keeps_tool_call_pair_when_cutoff_splits_pair(monkeypatch):
    messages = _messages(20)
    messages[7] = {
        "id": "m7",
        "type": "ai",
        "content": "",
        "tool_calls": [{"id": "tc-1", "name": "read_file", "args": {"path": "/tmp/a"}}],
    }
    messages[8] = {
        "id": "m8",
        "type": "tool",
        "tool_call_id": "tc-1",
        "content": "file contents",
    }
    threads = _ThreadsClient(values={"messages": messages})
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))

    response = asyncio.run(compact_thread("thread-1"))

    assert response.status == "accepted"
    updated_messages = threads.calls[0][1]["messages"]
    preserved_ids = [message["id"] for message in updated_messages[1:]]
    assert preserved_ids[0:2] == ["m7", "m8"]
    assert response.compressed_messages == 7


def test_compact_thread_router_noop_for_short_history(monkeypatch):
    threads = _ThreadsClient(values={"messages": _messages(8)})
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(threads))

    response = asyncio.run(compact_thread("thread-1"))
    assert response.status == "no_op"
    assert threads.calls == []


def test_compact_thread_router_maps_not_found(monkeypatch):
    class _NotFoundError(Exception):
        status_code = 404

    class _FailingThreadsClient:
        async def get_state(self, thread_id: str):  # noqa: ARG002
            raise _NotFoundError("missing")

        async def update_state(self, thread_id: str, values: dict):  # noqa: ARG002
            raise _NotFoundError("missing")

    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(_FailingThreadsClient()))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(compact_thread("missing-thread"))
    assert exc.value.status_code == 404
