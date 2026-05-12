from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.control_plane.models import FeedbackEvent
from src.control_plane.service import get_control_plane_service

router = APIRouter(prefix="/api", tags=["feedback"])


class FeedbackCreateRequest(BaseModel):
    target_type: str
    target_id: str
    value: str
    comment: str = ""
    source: str = "web"
    metadata: dict = Field(default_factory=dict)


class FeedbackListResponse(BaseModel):
    items: list[FeedbackEvent]


@router.get("/feedback", response_model=FeedbackListResponse)
async def list_feedback() -> FeedbackListResponse:
    service = get_control_plane_service()
    return FeedbackListResponse(items=service.list_feedback())


@router.post("/feedback", response_model=FeedbackEvent, status_code=201)
async def create_feedback(request: FeedbackCreateRequest) -> FeedbackEvent:
    service = get_control_plane_service()
    return service.add_feedback(
        target_type=request.target_type,
        target_id=request.target_id,
        value=request.value,
        comment=request.comment,
        source=request.source,
        metadata=request.metadata,
    )

