"""Run control APIs (resume helpers) — non-blocking task pattern."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.config.resume_config import get_resume_config

router = APIRouter(prefix="/api", tags=["runs"])


def _langgraph_url() -> str:
    return os.getenv("CAPYBARA_LANGGRAPH_URL") or os.getenv("LANGGRAPH_URL") or "http://localhost:2024"


class ResumeRunRequest(BaseModel):
    """Request body for resuming a run."""

    resume_payload: Any | None = Field(default=None, description="Optional command.resume payload.")
    assistant_id: str | None = Field(default=None, description="Optional assistant id override.")
    config: dict[str, Any] | None = Field(default=None, description="Optional run config overrides.")
    context: dict[str, Any] | None = Field(default=None, description="Optional run context overrides.")
    metadata: dict[str, Any] | None = Field(default=None, description="Optional metadata for the resumed run.")


class ResumeRunAcceptedResponse(BaseModel):
    """Accepted response for a non-blocking resumed run."""

    accepted: bool = True
    thread_id: str
    run_id: str
    assistant_id: str


class ResumeRunStatusResponse(BaseModel):
    """Status of an in-flight resumed run."""

    thread_id: str
    run_id: str
    status: str
    assistant_id: str | None = None


@router.post(
    "/threads/{thread_id}/runs/{run_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResumeRunAcceptedResponse,
    summary="Resume Run (non-blocking)",
    description="Resume a paused/interrupted run asynchronously. Returns immediately with the run_id; "
    "the client can poll for status or connect via LangGraph SSE for real-time updates.",
)
async def resume_run(
    thread_id: str,
    run_id: str,
    request: ResumeRunRequest,
) -> ResumeRunAcceptedResponse:
    """Resume a LangGraph run without blocking the Gateway thread."""
    cfg = get_resume_config()
    if not cfg.enabled:
        raise HTTPException(status_code=409, detail="Resume is disabled by configuration.")

    try:
        from langgraph_sdk import get_client

        client = get_client(url=_langgraph_url())
        run = await client.runs.get(thread_id, run_id)
        assistant_id = request.assistant_id or run["assistant_id"]
        if not assistant_id:
            raise HTTPException(status_code=400, detail="assistant_id is required to resume the run.")
        command = {"resume": request.resume_payload if request.resume_payload is not None else {"run_id": run_id}}
        metadata = dict(request.metadata or {})
        metadata.setdefault("resumed_from_run_id", run_id)

        created = await client.runs.create(
            thread_id,
            assistant_id,
            command=command,
            config=request.config,
            context=request.context,
            metadata=metadata,
        )
        new_run_id = created["run_id"] if isinstance(created, dict) else str(created)

        return ResumeRunAcceptedResponse(
            thread_id=thread_id,
            run_id=new_run_id,
            assistant_id=assistant_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to resume run: {exc}") from exc


@router.get(
    "/threads/{thread_id}/runs/{run_id}/resume-status",
    response_model=ResumeRunStatusResponse,
    summary="Check Resume Run Status",
    description="Check the status of a non-blocking resumed run.",
)
async def resume_run_status(
    thread_id: str,
    run_id: str,
) -> ResumeRunStatusResponse:
    """Return the current status of an in-flight resumed run."""
    try:
        from langgraph_sdk import get_client

        client = get_client(url=_langgraph_url())
        run = await client.runs.get(thread_id, run_id)
        return ResumeRunStatusResponse(
            thread_id=thread_id,
            run_id=run_id,
            status=run.get("status", "unknown"),
            assistant_id=run.get("assistant_id"),
        )
    except Exception:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
