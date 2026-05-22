"""Tests for run resume gateway router."""


import asyncio

import pytest
from fastapi import HTTPException

from src.config.resume_config import ResumeConfig, set_resume_config
from src.gateway.routers.runs import ResumeRunRequest, resume_run, resume_run_status


class _RunsClient:
    def __init__(self, get_response=None):
        self.get_response = get_response or {"assistant_id": "lead-agent"}

    async def get(self, thread_id: str, run_id: str):  # noqa: ARG002
        if isinstance(self.get_response, Exception):
            raise self.get_response
        return self.get_response

    async def create(self, thread_id: str, assistant_id: str, **kwargs):  # noqa: ARG002
        return {"run_id": "new-run-1", "assistant_id": assistant_id, "kwargs": kwargs}


class _Client:
    def __init__(self, get_response=None):
        self.runs = _RunsClient(get_response=get_response)


def test_resume_run_router_success(monkeypatch):
    set_resume_config(ResumeConfig(enabled=True, require_checkpoint=True, max_resume_depth=3))
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client())

    response = asyncio.run(
        resume_run(
            "thread-1",
            "run-1",
            ResumeRunRequest(resume_payload={"resume_depth": 1}),
        )
    )
    assert response.accepted is True
    assert response.thread_id == "thread-1"
    assert response.assistant_id == "lead-agent"
    assert response.run_id == "new-run-1"


def test_resume_run_router_rejects_when_disabled():
    set_resume_config(ResumeConfig(enabled=False, require_checkpoint=True, max_resume_depth=3))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resume_run("thread-1", "run-1", ResumeRunRequest()))
    assert exc.value.status_code == 409


def test_resume_run_status_reads_langgraph_status(monkeypatch):
    monkeypatch.setattr(
        "langgraph_sdk.get_client",
        lambda url: _Client({"assistant_id": "lead-agent", "status": "completed"}),
    )

    response = asyncio.run(resume_run_status("thread-1", "new-run-1"))
    assert response.thread_id == "thread-1"
    assert response.run_id == "new-run-1"
    assert response.assistant_id == "lead-agent"
    assert response.status == "completed"


def test_resume_run_status_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr("langgraph_sdk.get_client", lambda url: _Client(RuntimeError("missing")))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(resume_run_status("thread-1", "missing-run"))
    assert exc.value.status_code == 404
