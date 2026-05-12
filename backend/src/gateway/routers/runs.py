"""Run control APIs (resume helpers)."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
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


class ResumeRunResponse(BaseModel):
    """Response body for resumed run."""

    resumed: bool
    thread_id: str
    run_id: str
    assistant_id: str
    result: dict[str, Any] | list[dict[str, Any]] | list | dict


@router.post(
    "/threads/{thread_id}/runs/{run_id}/resume",
    response_model=ResumeRunResponse,
    summary="Resume Run",
    description="Resume a paused/interrupted run using LangGraph command.resume against existing checkpointed state.",
)
async def resume_run(
    thread_id: str,
    run_id: str,
    request: ResumeRunRequest,
) -> ResumeRunResponse:
    """Resume a LangGraph run for a thread."""
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
        result = await client.runs.wait(
            thread_id,
            assistant_id,
            command=command,
            config=request.config,
            context=request.context,
            metadata=metadata,
        )
        return ResumeRunResponse(
            resumed=True,
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            result=result,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to resume run: {exc}") from exc
