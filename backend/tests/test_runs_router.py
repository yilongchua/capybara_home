"""Tests for run resume gateway router."""


import asyncio

import pytest
from fastapi import HTTPException

from src.config.resume_config import ResumeConfig, set_resume_config
from src.gateway.routers.runs import ResumeRunRequest, resume_run


class _RunsClient:
    async def get(self, thread_id: str, run_id: str):  # noqa: ARG002
        return {"assistant_id": "lead-agent"}

    async def wait(self, thread_id: str, assistant_id: str, **kwargs):  # noqa: ARG002
        return {"messages": [{"type": "ai", "content": "resumed"}], "assistant_id": assistant_id, "kwargs": kwargs}


class _Client:
    def __init__(self):
        self.runs = _RunsClient()


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
    assert response.resumed is True
    assert response.thread_id == "thread-1"
    assert response.assistant_id == "lead-agent"


def test_resume_run_router_rejects_when_disabled():
    set_resume_config(ResumeConfig(enabled=False, require_checkpoint=True, max_resume_depth=3))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resume_run("thread-1", "run-1", ResumeRunRequest()))
    assert exc.value.status_code == 409
