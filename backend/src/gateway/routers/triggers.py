from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.control_plane.models import TriggerEvent
from src.control_plane.service import get_control_plane_service

router = APIRouter(prefix="/api", tags=["triggers"])


class TriggerCreateRequest(BaseModel):
    source: str = Field(default="web")
    message: str
    channel_name: str | None = None
    chat_id: str | None = None
    user_id: str | None = None
    classification: str = Field(default="manual")
    metadata: dict = Field(default_factory=dict)


class TriggerListResponse(BaseModel):
    items: list[TriggerEvent]


@router.get("/triggers", response_model=TriggerListResponse)
async def list_triggers() -> TriggerListResponse:
    service = get_control_plane_service()
    return TriggerListResponse(items=service.list_triggers())


@router.post("/triggers", response_model=TriggerEvent, status_code=201)
async def create_trigger(request: TriggerCreateRequest) -> TriggerEvent:
    service = get_control_plane_service()
    return service.create_trigger_event(
        source=request.source,
        message=request.message,
        channel_name=request.channel_name,
        chat_id=request.chat_id,
        user_id=request.user_id,
        classification=request.classification,
        metadata=request.metadata,
    )

