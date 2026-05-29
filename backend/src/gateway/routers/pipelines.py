from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.control_plane.models import (
    AutoresearchObjective,
    PipelineRun,
    PipelineStepDefinition,
    PipelineTemplate,
)
from src.control_plane.service import get_control_plane_service

router = APIRouter(prefix="/api", tags=["pipelines"])


class PipelineTemplateListResponse(BaseModel):
    items: list[PipelineTemplate]


class PipelineTemplateUpsertRequest(BaseModel):
    template: PipelineTemplate


class PipelineRunCreateRequest(BaseModel):
    template_id: str | None = None
    steps: list[PipelineStepDefinition] = Field(default_factory=list)
    inputs: dict = Field(default_factory=dict)
    trigger_event_id: str | None = None
    summary: str = ""
    requires_approval: bool | None = None
    metadata: dict = Field(default_factory=dict)
    auto_start: bool = False


class PipelineRunListResponse(BaseModel):
    items: list[PipelineRun]


class AutoresearchObjectiveListResponse(BaseModel):
    items: list[AutoresearchObjective]


class AutoresearchStartRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    endpoint_goal: str = Field(..., min_length=1)
    thread_id: str | None = None
    objective_id: str | None = None
    daily_time: str | None = None
    bootstrap: bool = True
    summary: str | None = None


class AutoresearchPauseRequest(BaseModel):
    reason: str = "denied"


class AutoresearchStartResponse(BaseModel):
    objective: AutoresearchObjective
    bootstrap_run: PipelineRun | None = None
    scheduled_time: str


class AutoresearchRunNowResponse(BaseModel):
    objective: AutoresearchObjective
    bootstrap_run: PipelineRun | None = None
    via: str


class AutoresearchDeleteResponse(BaseModel):
    deleted: bool
    objective_id: str
    removed_scheduler_jobs: list[str] = Field(default_factory=list)
    purge_result: dict[str, Any] = Field(default_factory=dict)


class PipelineRunsCleanupRequest(BaseModel):
    older_than_days: int = Field(default=14, ge=1, le=3650)
    statuses: list[str] | None = None


class PipelineRunsCleanupResponse(BaseModel):
    deleted: int
    deleted_run_ids: list[str] = Field(default_factory=list)
    missing_run_ids: list[str] = Field(default_factory=list)


class AutoresearchCleanupRequest(BaseModel):
    include_runs: bool = True


class AutoresearchCleanupResponse(BaseModel):
    deleted_objectives: int
    objective_ids: list[str] = Field(default_factory=list)
    run_cleanup: dict[str, Any] = Field(default_factory=dict)


@router.get("/pipelines", response_model=PipelineTemplateListResponse)
async def list_pipelines() -> PipelineTemplateListResponse:
    service = get_control_plane_service()
    return PipelineTemplateListResponse(items=service.list_templates())


@router.put("/pipelines/{template_id}", response_model=PipelineTemplate)
async def upsert_pipeline(template_id: str, request: PipelineTemplateUpsertRequest) -> PipelineTemplate:
    service = get_control_plane_service()
    template = request.template
    template.id = template_id
    return service.upsert_template(template)


@router.get("/pipelines/runs", response_model=PipelineRunListResponse)
async def list_pipeline_runs(
    thread_id: str | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
) -> PipelineRunListResponse:
    service = get_control_plane_service()
    status_values: set[str] = set()
    for value in status or []:
        for item in value.split(","):
            normalized = item.strip()
            if normalized:
                status_values.add(normalized)
    return PipelineRunListResponse(
        items=service.list_runs(
            thread_id=thread_id,
            statuses=status_values or None,
            limit=limit,
        ),
    )


@router.get("/pipelines/runs/{run_id}", response_model=PipelineRun)
async def get_pipeline_run(run_id: str) -> PipelineRun:
    service = get_control_plane_service()
    try:
        return service.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/pipelines/runs", response_model=PipelineRun, status_code=201)
async def create_pipeline_run(request: PipelineRunCreateRequest) -> PipelineRun:
    service = get_control_plane_service()
    try:
        run = service.create_run(
            template_id=request.template_id,
            steps=request.steps,
            inputs=request.inputs,
            trigger_event_id=request.trigger_event_id,
            summary=request.summary,
            requires_approval=request.requires_approval,
            metadata=request.metadata,
        )
        if request.auto_start and not run.requires_approval:
            return service.start_run(run.id)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipelines/runs/{run_id}/start", response_model=PipelineRun)
async def start_pipeline_run(run_id: str) -> PipelineRun:
    service = get_control_plane_service()
    try:
        return service.start_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipelines/runs/cleanup", response_model=PipelineRunsCleanupResponse)
async def cleanup_pipeline_runs(request: PipelineRunsCleanupRequest) -> PipelineRunsCleanupResponse:
    service = get_control_plane_service()
    statuses = {str(item).strip() for item in (request.statuses or []) if str(item).strip()}
    result = service.cleanup_old_scheduled_runs(
        older_than_days=request.older_than_days,
        statuses=statuses or None,
    )
    return PipelineRunsCleanupResponse.model_validate(result)


@router.get("/pipelines/runs/{run_id}/artifacts/{artifact_name}")
async def get_pipeline_run_artifact(run_id: str, artifact_name: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        artifact_path = service.get_run_artifact_path(run_id, artifact_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if artifact_path.suffix.lower() != ".json":
        raise HTTPException(status_code=400, detail="Only JSON pipeline artifacts are supported by this endpoint.")

    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON artifact: {exc}")
    return payload


@router.get("/pipelines/runs/{run_id}/artifacts/{artifact_name}/content")
async def get_pipeline_run_artifact_content(run_id: str, artifact_name: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        artifact_path = service.get_run_artifact_path(run_id, artifact_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    suffix = artifact_path.suffix.lower()
    if suffix in {".md", ".txt", ".log"}:
        return {
            "name": artifact_path.name,
            "content_type": "text/markdown" if suffix == ".md" else "text/plain",
            "content": artifact_path.read_text(encoding="utf-8"),
        }
    if suffix == ".json":
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"Invalid JSON artifact: {exc}")
        return {
            "name": artifact_path.name,
            "content_type": "application/json",
            "content": json.dumps(payload, indent=2, ensure_ascii=False),
        }
    raise HTTPException(status_code=400, detail=f"Unsupported artifact type: {suffix}")


@router.get("/pipelines/autoresearch", response_model=AutoresearchObjectiveListResponse)
async def list_autoresearch_objectives() -> AutoresearchObjectiveListResponse:
    service = get_control_plane_service()
    return AutoresearchObjectiveListResponse(items=service.list_autoresearch_objectives())


@router.get("/pipelines/autoresearch/{objective_id}", response_model=AutoresearchObjective)
async def get_autoresearch_objective(objective_id: str) -> AutoresearchObjective:
    service = get_control_plane_service()
    try:
        return service.get_autoresearch_objective(objective_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/pipelines/autoresearch/start", response_model=AutoresearchStartResponse)
async def start_autoresearch(request: AutoresearchStartRequest) -> AutoresearchStartResponse:
    service = get_control_plane_service()
    try:
        result = service.start_autoresearch_objective(
            topic=request.topic,
            endpoint_goal=request.endpoint_goal,
            thread_id=request.thread_id,
            objective_id=request.objective_id,
            daily_time=request.daily_time,
            bootstrap=request.bootstrap,
            summary=request.summary,
        )
        return AutoresearchStartResponse(
            objective=result["objective"],
            bootstrap_run=result["bootstrap_run"],
            scheduled_time=result["scheduled_time"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipelines/autoresearch/{objective_id}/pause", response_model=AutoresearchObjective)
async def pause_autoresearch(objective_id: str, request: AutoresearchPauseRequest) -> AutoresearchObjective:
    service = get_control_plane_service()
    try:
        return service.pause_autoresearch_objective(objective_id, reason=request.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipelines/autoresearch/{objective_id}/resume", response_model=AutoresearchObjective)
async def resume_autoresearch(objective_id: str) -> AutoresearchObjective:
    service = get_control_plane_service()
    try:
        return service.resume_autoresearch_objective(objective_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipelines/autoresearch/{objective_id}/run", response_model=AutoresearchRunNowResponse)
async def run_autoresearch_now(objective_id: str) -> AutoresearchRunNowResponse:
    service = get_control_plane_service()
    try:
        result = service.run_autoresearch_objective_now(objective_id)
        return AutoresearchRunNowResponse(
            objective=result["objective"],
            bootstrap_run=result.get("bootstrap_run"),
            via=str(result.get("via") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipelines/autoresearch/{objective_id}/stop", response_model=AutoresearchObjective)
async def stop_autoresearch(objective_id: str) -> AutoresearchObjective:
    service = get_control_plane_service()
    try:
        return service.stop_autoresearch_objective(objective_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/pipelines/autoresearch/{objective_id}", response_model=AutoresearchDeleteResponse)
async def delete_autoresearch(objective_id: str) -> AutoresearchDeleteResponse:
    service = get_control_plane_service()
    try:
        payload = service.delete_autoresearch_objective(objective_id)
        return AutoresearchDeleteResponse.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipelines/autoresearch/cleanup", response_model=AutoresearchCleanupResponse)
async def cleanup_autoresearch(request: AutoresearchCleanupRequest) -> AutoresearchCleanupResponse:
    service = get_control_plane_service()
    payload = service.cleanup_autoresearch(include_runs=request.include_runs)
    return AutoresearchCleanupResponse.model_validate(payload)
