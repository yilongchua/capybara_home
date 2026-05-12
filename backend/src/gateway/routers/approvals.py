from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.control_plane.models import ApprovalRequest, PipelineRun
from src.control_plane.service import get_control_plane_service

router = APIRouter(prefix="/api", tags=["approvals"])


class ApprovalListResponse(BaseModel):
    items: list[ApprovalRequest]


class ApprovalResolveRequest(BaseModel):
    approve: bool
    note: str | None = None
    auto_start: bool = Field(default=True)


class ProposalApprovalListResponse(BaseModel):
    items: list[dict[str, Any]]


class ProposalResolveRequest(BaseModel):
    approve: bool
    note: str | None = None


@router.get("/approvals", response_model=ApprovalListResponse)
async def list_approvals() -> ApprovalListResponse:
    service = get_control_plane_service()
    return ApprovalListResponse(items=service.list_approvals())


@router.post("/approvals/{approval_id}/resolve", response_model=PipelineRun)
async def resolve_approval(approval_id: str, request: ApprovalResolveRequest) -> PipelineRun:
    service = get_control_plane_service()
    try:
        return service.resolve_approval(
            approval_id,
            approve=request.approve,
            note=request.note,
            auto_start=request.auto_start,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/approvals/proposals", response_model=ProposalApprovalListResponse)
async def list_proposal_approvals() -> ProposalApprovalListResponse:
    service = get_control_plane_service()
    return ProposalApprovalListResponse(items=service.list_self_improver_proposals())


@router.post("/approvals/proposals/{run_id}/{proposal_id}/resolve")
async def resolve_proposal_approval(
    run_id: str,
    proposal_id: str,
    request: ProposalResolveRequest,
) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        return service.resolve_self_improver_proposal(
            run_id=run_id,
            proposal_id=proposal_id,
            approve=request.approve,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
