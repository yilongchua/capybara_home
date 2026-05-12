from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from src.control_plane.service import get_control_plane_service

router = APIRouter(prefix="/api/vault", tags=["vault"])


class VaultSearchItem(BaseModel):
    rank: int
    score: float
    id: str | None = None
    kind: str | None = None
    title: str | None = None
    path: str | None = None
    snippet: str | None = None
    updated_at: str | None = None


class VaultSearchResponse(BaseModel):
    query: str
    total: int
    items: list[VaultSearchItem] = Field(default_factory=list)


class VaultStatusResponse(BaseModel):
    summary: dict[str, Any] = Field(default_factory=dict)
    counts: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    sufficiency: dict[str, Any] = Field(default_factory=dict)
    action_items: dict[str, Any] = Field(default_factory=dict)
    objectives: dict[str, Any] = Field(default_factory=dict)


class VaultActionItem(BaseModel):
    kind: str
    priority: str
    title: str
    detail: str
    created_at: str
    status: str
    objective_id: str | None = None


class VaultActionItemsResponse(BaseModel):
    generated_at: str
    counts: dict[str, Any] = Field(default_factory=dict)
    items: list[VaultActionItem] = Field(default_factory=list)


class VaultSufficiencyRequest(BaseModel):
    objective_id: str = Field(..., min_length=1)
    topic: str = ""
    min_score: float = Field(default=78.0, ge=0.0, le=100.0)


class VaultSufficiencyResponse(BaseModel):
    generated_at: str
    objective_id: str
    topic: str
    score: float
    decision: str
    blocking_checks: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    min_score: float
    auto_pause_recommended: bool = False
    sufficient_streak: int = 0
    progress: dict[str, Any] = Field(default_factory=dict)


@router.get("/status", response_model=VaultStatusResponse)
async def get_vault_status() -> VaultStatusResponse:
    service = get_control_plane_service()
    payload = service.get_vault_status()
    return VaultStatusResponse.model_validate(payload)


@router.get("/search", response_model=VaultSearchResponse)
async def search_vault(
    q: str = Query("", description="Search query"),
    limit: int = Query(10, ge=1, le=100),
) -> VaultSearchResponse:
    service = get_control_plane_service()
    payload = service.search_vault(query=q, limit=limit)
    return VaultSearchResponse.model_validate(payload)


@router.get("/sources/{source_id}")
async def get_vault_source(source_id: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        return service.get_vault_source(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/action-items", response_model=VaultActionItemsResponse)
async def list_vault_action_items(
    limit: int = Query(100, ge=1, le=500),
) -> VaultActionItemsResponse:
    service = get_control_plane_service()
    payload = service.list_vault_action_items(limit=limit)
    return VaultActionItemsResponse.model_validate(payload)


@router.post("/sufficiency/evaluate", response_model=VaultSufficiencyResponse)
async def evaluate_vault_sufficiency(
    request: VaultSufficiencyRequest,
) -> VaultSufficiencyResponse:
    service = get_control_plane_service()
    payload = service.evaluate_vault_sufficiency(
        objective_id=request.objective_id,
        topic=request.topic,
        min_score=request.min_score,
    )
    return VaultSufficiencyResponse.model_validate(payload)


@router.get("/objectives/{objective_id}/progress.md", response_class=PlainTextResponse)
async def get_autoresearch_progress_markdown(objective_id: str) -> PlainTextResponse:
    service = get_control_plane_service()
    try:
        name, content = service.get_autoresearch_progress_markdown(objective_id)
        return PlainTextResponse(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'inline; filename="{name}"'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
