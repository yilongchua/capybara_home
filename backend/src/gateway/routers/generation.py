from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.generation.models import GenerationJob
from src.generation.service import get_generation_service

router = APIRouter(prefix="/api", tags=["generation"])


class GenerationSubmitRequest(BaseModel):
    kind: Literal["image", "video"]
    prompt: str = Field(..., min_length=1, description="Prompt text to inject into workflow")
    output_name: str = Field(..., min_length=1, description="Output basename used for capybara/{output_name} prefix")
    aspect_ratio: str = Field(default="16:9", description="Aspect ratio for image generation")


class GenerationSubmitResponse(BaseModel):
    job: GenerationJob


class GenerationJobListResponse(BaseModel):
    items: list[GenerationJob]


class GenerationCompletionsResponse(BaseModel):
    items: list[GenerationJob]
    next_since_seq: int


@router.post("/threads/{thread_id}/generation/jobs", response_model=GenerationSubmitResponse, status_code=201)
async def submit_generation_job(thread_id: str, request: GenerationSubmitRequest) -> GenerationSubmitResponse:
    service = get_generation_service()
    try:
        job = service.submit_job(
            thread_id=thread_id,
            kind=request.kind,
            prompt_text=request.prompt,
            output_name=request.output_name,
            aspect_ratio=request.aspect_ratio,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to submit generation job: {exc}")
    return GenerationSubmitResponse(job=job)


@router.get("/generation/jobs/{job_id}", response_model=GenerationJob)
async def get_generation_job(job_id: str) -> GenerationJob:
    service = get_generation_service()
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Generation job '{job_id}' not found")
    return job


@router.get("/threads/{thread_id}/generation/jobs", response_model=GenerationJobListResponse)
async def list_generation_jobs(
    thread_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> GenerationJobListResponse:
    service = get_generation_service()
    return GenerationJobListResponse(items=service.list_jobs(thread_id=thread_id, limit=limit))


@router.get("/threads/{thread_id}/generation/completions", response_model=GenerationCompletionsResponse)
async def list_generation_completions(
    thread_id: str,
    since_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> GenerationCompletionsResponse:
    service = get_generation_service()
    items = service.list_completions(thread_id=thread_id, since_seq=since_seq, limit=limit)
    next_since_seq = since_seq
    if items:
        next_since_seq = max(next_since_seq, *(item.completion_seq or 0 for item in items))
    return GenerationCompletionsResponse(items=items, next_since_seq=next_since_seq)
