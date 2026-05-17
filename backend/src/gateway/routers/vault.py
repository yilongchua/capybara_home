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


class VaultClipRequest(BaseModel):
    url: str = Field(..., min_length=1)
    title: str = ""
    markdown: str = Field(..., min_length=1)
    topic: str = ""
    topic_tags: list[str] = Field(default_factory=list)


class VaultSaveRequest(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    topic: str = ""
    topic_tags: list[str] = Field(default_factory=list)
    source_url: str = ""
    source_thread_id: str = ""


class VaultWriteResponse(BaseModel):
    status: str
    source_id: str | None = None
    queue_path: str | None = None
    appended_count: int | None = None
    compiled_path: str | None = None
    raw_path: str | None = None


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


class VaultGraphNode(BaseModel):
    id: str
    label: str
    kind: str
    path: str
    tags: list[str] = Field(default_factory=list)
    degree: int = 0


class VaultGraphEdge(BaseModel):
    source: str
    target: str
    type: str


class VaultGraphResponse(BaseModel):
    generated_at: str
    counts: dict[str, Any] = Field(default_factory=dict)
    nodes: list[VaultGraphNode] = Field(default_factory=list)
    edges: list[VaultGraphEdge] = Field(default_factory=list)
    highlights: dict[str, Any] = Field(default_factory=dict)


class VaultIngestStartRequest(BaseModel):
    force_reanalyze: bool = False


class VaultIngestStatusResponse(BaseModel):
    job_id: str = ""
    status: str = "idle"
    total: int = 0
    processed: int = 0
    updated: int = 0
    skipped_no_raw: int = 0
    failed: int = 0
    current_index: int = 0
    current_source_id: str = ""
    current_title: str = ""
    last_status: str = ""
    last_error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
    log_path: str = ""
    accepted: bool | None = None
    message: str | None = None


class VaultFileNode(BaseModel):
    name: str
    path: str
    kind: str
    size: int | None = None
    children: list[dict[str, Any]] = Field(default_factory=list)


class VaultExplorerSourceItem(BaseModel):
    source_id: str
    title: str
    url: str = ""
    ingested_at: str = ""
    raw_path: str = ""
    compiled_path: str = ""


class VaultExplorerKnowledgeResponse(BaseModel):
    entities: list[VaultFileNode] = Field(default_factory=list)
    concepts: list[VaultFileNode] = Field(default_factory=list)
    sources: list[VaultFileNode] = Field(default_factory=list)
    others: list[VaultFileNode] = Field(default_factory=list)


class VaultExplorerResponse(BaseModel):
    generated_at: str
    cache_ttl_seconds: int
    raw_sources: list[VaultExplorerSourceItem] = Field(default_factory=list)
    knowledge: VaultExplorerKnowledgeResponse = Field(default_factory=VaultExplorerKnowledgeResponse)
    files: list[VaultFileNode] = Field(default_factory=list)
    graph: dict[str, Any] = Field(default_factory=dict)


class VaultFileResponse(BaseModel):
    path: str
    editable: bool
    content: str


class VaultFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str = ""


class VaultFileWriteResponse(BaseModel):
    status: str
    path: str
    bytes: int

class VaultFileDeleteResponse(BaseModel):
    status: str
    path: str


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


@router.post("/clip", response_model=VaultWriteResponse)
async def clip_to_vault(request: VaultClipRequest) -> VaultWriteResponse:
    service = get_control_plane_service()
    payload = service.clip_to_vault(
        url=request.url,
        title=request.title,
        markdown=request.markdown,
        topic=request.topic,
        topic_tags=request.topic_tags,
    )
    return VaultWriteResponse.model_validate(
        {
            "status": "queued",
            "queue_path": payload.get("queue_path"),
            "appended_count": payload.get("appended_count"),
        }
    )


@router.post("/save", response_model=VaultWriteResponse)
async def save_to_vault(request: VaultSaveRequest) -> VaultWriteResponse:
    service = get_control_plane_service()
    payload = service.save_to_vault(
        title=request.title,
        content=request.content,
        topic=request.topic,
        topic_tags=request.topic_tags,
        source_url=request.source_url,
        source_thread_id=request.source_thread_id,
    )
    return VaultWriteResponse.model_validate(payload)


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


@router.get("/graph", response_model=VaultGraphResponse)
async def get_vault_graph(limit: int | None = Query(None, ge=1, le=5000)) -> VaultGraphResponse:
    service = get_control_plane_service()
    payload = service.get_vault_graph(limit=limit)
    return VaultGraphResponse.model_validate(payload)


@router.get("/explorer", response_model=VaultExplorerResponse)
async def get_vault_explorer() -> VaultExplorerResponse:
    service = get_control_plane_service()
    payload = service.get_vault_explorer(force_refresh=False)
    return VaultExplorerResponse.model_validate(payload)


@router.post("/explorer/refresh", response_model=VaultExplorerResponse)
async def refresh_vault_explorer() -> VaultExplorerResponse:
    service = get_control_plane_service()
    payload = service.get_vault_explorer(force_refresh=True)
    return VaultExplorerResponse.model_validate(payload)


@router.post("/ingest/start", response_model=VaultIngestStatusResponse)
async def start_vault_ingest(request: VaultIngestStartRequest | None = None) -> VaultIngestStatusResponse:
    service = get_control_plane_service()
    force = bool(request.force_reanalyze) if request is not None else False
    payload = service.start_vault_ingest_job(force_reanalyze=force)
    return VaultIngestStatusResponse.model_validate(payload)


@router.get("/ingest/status", response_model=VaultIngestStatusResponse)
async def get_vault_ingest_status() -> VaultIngestStatusResponse:
    service = get_control_plane_service()
    payload = service.get_vault_ingest_status()
    return VaultIngestStatusResponse.model_validate(payload)


@router.get("/file", response_model=VaultFileResponse)
async def get_vault_file(path: str = Query(..., min_length=1)) -> VaultFileResponse:
    service = get_control_plane_service()
    try:
        payload = service.get_vault_file(relative_path=path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return VaultFileResponse.model_validate(payload)


@router.post("/file", response_model=VaultFileWriteResponse)
async def write_vault_file(request: VaultFileWriteRequest) -> VaultFileWriteResponse:
    service = get_control_plane_service()
    try:
        payload = service.save_vault_file(relative_path=request.path, content=request.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return VaultFileWriteResponse.model_validate(payload)

@router.delete("/file", response_model=VaultFileDeleteResponse)
async def delete_vault_file(path: str = Query(..., min_length=1)) -> VaultFileDeleteResponse:
    service = get_control_plane_service()
    try:
        payload = service.delete_vault_file(relative_path=path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return VaultFileDeleteResponse.model_validate(payload)


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
