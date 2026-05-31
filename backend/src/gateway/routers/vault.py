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


class VaultIngestStartRequest(BaseModel):
    force_reanalyze: bool = False
    workers: int = Field(default=1, ge=1, le=3)


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
    cancel_requested: bool = False
    workers_requested: int = 0
    workers_active: int = 0
    accepted: bool | None = None
    message: str | None = None


class VaultLintRequest(BaseModel):
    dry_run: bool = True
    use_llm: bool = False
    entity_slugs: list[str] | None = None
    concept_slugs: list[str] | None = None


class VaultLintFinding(BaseModel):
    slug: str
    label: str
    reasons: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    live_source_refs: list[str] = Field(default_factory=list)


class VaultLintCategoryReport(BaseModel):
    total_before: int = 0
    flagged: list[VaultLintFinding] = Field(default_factory=list)
    removed: int = 0


class VaultLintResponse(BaseModel):
    generated_at: str = ""
    dry_run: bool = True
    entities: VaultLintCategoryReport = Field(default_factory=VaultLintCategoryReport)
    concepts: VaultLintCategoryReport = Field(default_factory=VaultLintCategoryReport)


class VaultFileNode(BaseModel):
    name: str
    path: str
    kind: str
    size: int | None = None
    has_children: bool = False
    child_count: int | None = None
    children: list[dict[str, Any]] = Field(default_factory=list)


class VaultExplorerChildrenResponse(BaseModel):
    path: str
    children: list[VaultFileNode] = Field(default_factory=list)


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


class VaultKnowledgeGraphDeleteResponse(BaseModel):
    status: str
    removed: dict[str, Any] = Field(default_factory=dict)


class VaultEntitySourceItem(BaseModel):
    source_id: str
    title: str = ""
    url: str = ""


class VaultEntityConceptItem(BaseModel):
    slug: str
    label: str = ""


class VaultEntityBrowserItem(BaseModel):
    slug: str
    label: str
    degree: int = 0
    sources: list[VaultEntitySourceItem] = Field(default_factory=list)
    concepts: list[VaultEntityConceptItem] = Field(default_factory=list)


class VaultEntityBrowserResponse(BaseModel):
    generated_at: str
    counts: dict[str, Any] = Field(default_factory=dict)
    top: list[VaultEntityBrowserItem] = Field(default_factory=list)
    critical_gaps: list[VaultEntityBrowserItem] = Field(default_factory=list)
    less_covered: list[VaultEntityBrowserItem] = Field(default_factory=list)


class VaultEntityDismissalItem(BaseModel):
    slug: str
    label: str = ""
    reason: str = ""
    alias_for: str | None = None
    dismissed_at: str = ""


class VaultEntityDismissalsResponse(BaseModel):
    items: list[VaultEntityDismissalItem] = Field(default_factory=list)


class VaultEntityDismissRequest(BaseModel):
    reason: str = ""
    alias_for: str | None = None


class VaultEntityDismissResponse(BaseModel):
    slug: str
    alias_for: str | None = None
    affected_sources: list[str] = Field(default_factory=list)
    compiled_deleted: bool = False


class VaultEntityRestoreResponse(BaseModel):
    slug: str
    restored: bool


class VaultEntityAutoresearchRequest(BaseModel):
    label: str = ""
    endpoint_goal: str = ""


class VaultEntityAutoresearchResponse(BaseModel):
    objective_id: str | None = None
    run_id: str | None = None
    accepted: bool | None = None
    message: str | None = None


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


@router.get("/explorer/children", response_model=VaultExplorerChildrenResponse)
async def get_vault_explorer_children(
    path: str = Query(..., min_length=1, description="Directory path relative to the vault root."),
) -> VaultExplorerChildrenResponse:
    service = get_control_plane_service()
    try:
        payload = service.get_vault_explorer_children(relative_path=path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return VaultExplorerChildrenResponse.model_validate(payload)


@router.post("/ingest/start", response_model=VaultIngestStatusResponse)
async def start_vault_ingest(request: VaultIngestStartRequest | None = None) -> VaultIngestStatusResponse:
    service = get_control_plane_service()
    force = bool(request.force_reanalyze) if request is not None else False
    workers = int(request.workers) if request is not None else 1
    payload = service.start_vault_ingest_job(force_reanalyze=force, workers=workers)
    return VaultIngestStatusResponse.model_validate(payload)


@router.get("/ingest/status", response_model=VaultIngestStatusResponse)
async def get_vault_ingest_status() -> VaultIngestStatusResponse:
    service = get_control_plane_service()
    payload = service.get_vault_ingest_status()
    return VaultIngestStatusResponse.model_validate(payload)


@router.post("/ingest/cancel", response_model=VaultIngestStatusResponse)
async def cancel_vault_ingest() -> VaultIngestStatusResponse:
    service = get_control_plane_service()
    payload = service.cancel_vault_ingest_job()
    return VaultIngestStatusResponse.model_validate(payload)


@router.post("/lint", response_model=VaultLintResponse)
async def lint_vault(request: VaultLintRequest | None = None) -> VaultLintResponse:
    service = get_control_plane_service()
    req = request or VaultLintRequest()
    try:
        payload = service.lint_vault_pages(
            dry_run=bool(req.dry_run),
            use_llm=bool(req.use_llm),
            entity_slugs=req.entity_slugs,
            concept_slugs=req.concept_slugs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return VaultLintResponse.model_validate(payload)


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


@router.delete("/knowledge-graph", response_model=VaultKnowledgeGraphDeleteResponse)
async def delete_vault_knowledge_graph() -> VaultKnowledgeGraphDeleteResponse:
    service = get_control_plane_service()
    try:
        payload = service.delete_vault_knowledge_graph()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return VaultKnowledgeGraphDeleteResponse.model_validate(payload)


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


@router.get("/entity-browser", response_model=VaultEntityBrowserResponse)
async def get_vault_entity_browser(
    top: int = Query(15, ge=1, le=100),
    bottom: int = Query(10, ge=0, le=50),
    critical_max_degree: int = Query(2, ge=0, le=20),
) -> VaultEntityBrowserResponse:
    service = get_control_plane_service()
    payload = service.get_vault_entity_browser(
        top_n=top,
        bottom_n=bottom,
        critical_max_degree=critical_max_degree,
    )
    return VaultEntityBrowserResponse.model_validate(payload)


@router.get("/entity-dismissals", response_model=VaultEntityDismissalsResponse)
async def list_vault_entity_dismissals() -> VaultEntityDismissalsResponse:
    service = get_control_plane_service()
    items = service.list_vault_entity_dismissals()
    return VaultEntityDismissalsResponse.model_validate({"items": items})


@router.post("/entities/{slug}/dismiss", response_model=VaultEntityDismissResponse)
async def dismiss_vault_entity(
    slug: str,
    request: VaultEntityDismissRequest | None = None,
) -> VaultEntityDismissResponse:
    service = get_control_plane_service()
    body = request or VaultEntityDismissRequest()
    try:
        payload = service.dismiss_vault_entity(
            slug=slug,
            reason=body.reason,
            alias_for=body.alias_for,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return VaultEntityDismissResponse.model_validate(payload)


@router.post("/entity-dismissals/{slug}/restore", response_model=VaultEntityRestoreResponse)
async def restore_vault_entity_dismissal(slug: str) -> VaultEntityRestoreResponse:
    service = get_control_plane_service()
    try:
        payload = service.restore_vault_entity_dismissal(slug=slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return VaultEntityRestoreResponse.model_validate(payload)


@router.post("/entities/{slug}/autoresearch", response_model=VaultEntityAutoresearchResponse)
async def start_vault_entity_autoresearch(
    slug: str,
    request: VaultEntityAutoresearchRequest | None = None,
) -> VaultEntityAutoresearchResponse:
    service = get_control_plane_service()
    body = request or VaultEntityAutoresearchRequest()
    try:
        payload = service.start_vault_entity_autoresearch(
            slug=slug,
            label=body.label,
            endpoint_goal=body.endpoint_goal,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    objective = payload.get("objective")
    bootstrap_run = payload.get("bootstrap_run")
    objective_id = getattr(objective, "objective_id", None) or getattr(objective, "id", None)
    run_id = getattr(bootstrap_run, "id", None) if bootstrap_run is not None else None
    return VaultEntityAutoresearchResponse.model_validate(
        {
            "objective_id": objective_id,
            "run_id": run_id,
            "accepted": True,
            "message": None,
        }
    )


@router.get("/objectives/{objective_id}/ledger.md", response_class=PlainTextResponse)
async def get_autoresearch_ledger_markdown(objective_id: str) -> PlainTextResponse:
    service = get_control_plane_service()
    try:
        name, content = service.get_autoresearch_ledger_markdown(objective_id)
        return PlainTextResponse(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'inline; filename="{name}"'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/objectives/{objective_id}/ledger.json")
async def get_autoresearch_ledger_json(objective_id: str) -> dict[str, Any]:
    service = get_control_plane_service()
    try:
        return service.get_autoresearch_ledger_json(objective_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
