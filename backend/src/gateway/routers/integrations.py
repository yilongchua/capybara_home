from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.control_plane.service import get_control_plane_service

router = APIRouter(prefix="/api", tags=["integrations"])


class IntegrationToggleRequest(BaseModel):
    enabled: bool


class SchedulerRuntimeJobCreateRequest(BaseModel):
    name: str
    pipeline_template_id: str
    daily_time: str = Field(..., description="HH:MM, 24-hour local time")
    enabled: bool = True
    inputs: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool | None = False


class SchedulerRuntimeJobUpdateRequest(BaseModel):
    daily_time: str | None = Field(None, description="HH:MM, 24-hour local time")
    endpoint_goal: str | None = Field(None, description="Updated endpoint goal text")


@router.get("/integrations/status")
async def get_integrations_status() -> dict[str, Any]:
    service = get_control_plane_service()
    return service.get_integrations_status()


@router.get("/integrations/services")
async def get_integration_services() -> dict[str, Any]:
    service = get_control_plane_service()
    return service.get_integration_services_status()


@router.post("/integrations/services/{service_id}/start")
async def start_integration_service(service_id: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        return service.start_integration_service(service_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/integrations/services/{service_id}/stop")
async def stop_integration_service(service_id: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        return service.stop_integration_service(service_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/integrations/services/{service_id}/set-enabled")
async def set_integration_service_enabled(service_id: str, request: IntegrationToggleRequest) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        return service.set_integration_service_enabled(service_id, request.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/integrations/services/start-all")
async def start_all_integration_services() -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        return service.start_all_integration_services()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/integrations/startup-jobs/{job_id}")
async def get_startup_job(job_id: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        return service.get_startup_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/integrations/scheduler/{job_id}/run")
async def run_scheduler_job(job_id: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        run = service.run_scheduler_job_now(job_id)
        return run.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/integrations/scheduler/jobs")
async def create_runtime_scheduler_job(
    request: SchedulerRuntimeJobCreateRequest,
) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        job = service.create_runtime_scheduler_job(
            name=request.name,
            pipeline_template_id=request.pipeline_template_id,
            daily_time=request.daily_time,
            enabled=request.enabled,
            inputs=request.inputs,
            requires_approval=request.requires_approval,
        )
        return job.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/integrations/scheduler/jobs/{job_id}")
async def update_runtime_scheduler_job(job_id: str, request: SchedulerRuntimeJobUpdateRequest) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        job = service.update_runtime_scheduler_job(
            job_id,
            daily_time=request.daily_time,
            endpoint_goal=request.endpoint_goal,
        )
        return job.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/integrations/scheduler/jobs/{job_id}")
async def delete_runtime_scheduler_job(job_id: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        service.delete_runtime_scheduler_job(job_id)
        return {"deleted": True, "job_id": job_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/integrations/folder-sync/{target_id}/ingest")
async def reingest_folder_sync(target_id: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        manifest = service.reingest_folder_sync_target(target_id)
        return manifest
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
