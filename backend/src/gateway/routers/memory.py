"""Memory API router for retrieving and managing scoped memory data."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.agents.memory.compaction_archive import read_compaction_entries
from src.agents.memory.store import (
    MEMORY_SCOPE_GLOBAL,
    MEMORY_SCOPE_WORKSPACE,
    get_memory_version,
    list_memory_versions,
    redact_memory,
)
from src.agents.memory.updater import (
    add_behavior_rule,
    clear_memory,
    delete_behavior_rule,
    delete_fact,
    forget_thread_facts,
    get_memory_data,
    get_memory_version_reference,
    reload_memory_data,
    update_behavior_rule,
    upsert_fact,
)
from src.config.memory_config import get_memory_config

router = APIRouter(prefix="/api", tags=["memory"])

MemoryScope = Literal["global", "workspace"]


class ContextSection(BaseModel):
    summary: str = Field(default="", description="Summary content")
    updatedAt: str = Field(default="", description="Last update timestamp")


class UserContext(BaseModel):
    workContext: ContextSection = Field(default_factory=ContextSection)
    personalContext: ContextSection = Field(default_factory=ContextSection)
    topOfMind: ContextSection = Field(default_factory=ContextSection)


class HistoryContext(BaseModel):
    recentMonths: ContextSection = Field(default_factory=ContextSection)
    earlierContext: ContextSection = Field(default_factory=ContextSection)
    longTermBackground: ContextSection = Field(default_factory=ContextSection)


class Fact(BaseModel):
    id: str
    content: str
    category: str = "context"
    confidence: float = 0.5
    createdAt: str = ""
    source: str = "unknown"


class BehaviorRule(BaseModel):
    id: str
    instruction: str
    active: bool = True
    scope: str = "global"
    scopeId: str = "global"
    source: str = "api"
    createdAt: str = ""
    updatedAt: str = ""


class MemoryResponse(BaseModel):
    version: str = "2.0"
    scope: str = "global"
    scopeId: str = "global"
    lastUpdated: str = ""
    user: UserContext = Field(default_factory=UserContext)
    history: HistoryContext = Field(default_factory=HistoryContext)
    facts: list[Fact] = Field(default_factory=list)
    behaviorRules: list[BehaviorRule] = Field(default_factory=list)


class MemoryConfigResponse(BaseModel):
    enabled: bool
    storage_path: str
    debounce_seconds: int
    max_facts: int
    fact_confidence_threshold: float
    injection_enabled: bool
    max_injection_tokens: int
    global_scope_enabled: bool
    workspace_scope_enabled: bool
    behavior_rules_enabled: bool
    decay_enabled: bool
    decay_half_life_days: int
    decay_archive_threshold: float
    recall_top_k: int


class MemoryStatusResponse(BaseModel):
    config: MemoryConfigResponse
    data: MemoryResponse
    memory_version_ref: dict[str, Any] | None = None


class MemoryVersionSummary(BaseModel):
    version_id: str
    created_at: str | None = None
    sha: str | None = None
    parent_sha: str | None = None
    source_thread: str | None = None
    operation: str | None = None
    scope: str | None = None
    scope_id: str | None = None
    audit: dict[str, Any] = Field(default_factory=dict)


class MemoryVersionsResponse(BaseModel):
    items: list[MemoryVersionSummary] = Field(default_factory=list)


class MemoryVersionDetailResponse(BaseModel):
    version_id: str
    created_at: str | None = None
    sha: str | None = None
    parent_sha: str | None = None
    source_thread: str | None = None
    operation: str | None = None
    scope: str | None = None
    scope_id: str | None = None
    audit: dict[str, Any] = Field(default_factory=dict)
    memory: MemoryResponse


class MemoryRedactRequest(BaseModel):
    fact_ids: list[str] = Field(default_factory=list)
    pattern: str | None = None
    reason: str = Field(..., min_length=1)
    actor: str = "api"
    expected_sha: str | None = None


class MemoryRedactResponse(BaseModel):
    success: bool
    affected_fact_ids: list[str] = Field(default_factory=list)
    memory_version_ref: dict[str, Any] | None = None


class FactUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1)
    category: str = "context"
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    source: str = "manual"


class BehaviorRuleCreateRequest(BaseModel):
    instruction: str = Field(..., min_length=1)
    active: bool = True
    source: str = "api"


class BehaviorRuleUpdateRequest(BaseModel):
    instruction: str | None = None
    active: bool | None = None


class ForgetThreadRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)


class CompactionEntriesResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class MemoryClearResponse(BaseModel):
    success: bool = True
    scope: str
    scope_id: str
    memory: MemoryResponse


def _scope_args(scope: MemoryScope, workspace_id: str | None) -> tuple[str, str | None]:
    normalized = MEMORY_SCOPE_WORKSPACE if scope == "workspace" else MEMORY_SCOPE_GLOBAL
    if normalized == MEMORY_SCOPE_WORKSPACE and not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required for workspace scope")
    return normalized, workspace_id


@router.get("/memory", response_model=MemoryResponse, summary="Get Memory Data")
async def get_memory(
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> MemoryResponse:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    return MemoryResponse(**get_memory_data(scope=normalized_scope, workspace_id=wsid))


@router.post("/memory/reload", response_model=MemoryResponse, summary="Reload Memory Data")
async def reload_memory(
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> MemoryResponse:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    return MemoryResponse(**reload_memory_data(scope=normalized_scope, workspace_id=wsid))


@router.get("/memory/config", response_model=MemoryConfigResponse, summary="Get Memory Configuration")
async def get_memory_config_endpoint() -> MemoryConfigResponse:
    config = get_memory_config()
    return MemoryConfigResponse(
        enabled=config.enabled,
        storage_path=config.storage_path,
        debounce_seconds=config.debounce_seconds,
        max_facts=config.max_facts,
        fact_confidence_threshold=config.fact_confidence_threshold,
        injection_enabled=config.injection_enabled,
        max_injection_tokens=config.max_injection_tokens,
        global_scope_enabled=config.global_scope_enabled,
        workspace_scope_enabled=config.workspace_scope_enabled,
        behavior_rules_enabled=config.behavior_rules_enabled,
        decay_enabled=config.decay_enabled,
        decay_half_life_days=config.decay_half_life_days,
        decay_archive_threshold=config.decay_archive_threshold,
        recall_top_k=config.recall_top_k,
    )


@router.get("/memory/status", response_model=MemoryStatusResponse, summary="Get Memory Status")
async def get_memory_status(
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> MemoryStatusResponse:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    config = await get_memory_config_endpoint()
    data = MemoryResponse(**get_memory_data(scope=normalized_scope, workspace_id=wsid))
    return MemoryStatusResponse(
        config=config,
        data=data,
        memory_version_ref=get_memory_version_reference(scope=normalized_scope, workspace_id=wsid),
    )


@router.get("/memory/versions", response_model=MemoryVersionsResponse, summary="List Memory Versions")
async def list_memory_versions_endpoint(
    limit: int = 50,
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> MemoryVersionsResponse:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    records = list_memory_versions(limit=limit, scope=normalized_scope, workspace_id=wsid)
    return MemoryVersionsResponse(items=[MemoryVersionSummary(**record) for record in records if record.get("version_id")])


@router.get("/memory/versions/{version_id}", response_model=MemoryVersionDetailResponse, summary="Get Memory Version")
async def get_memory_version_endpoint(
    version_id: str,
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> MemoryVersionDetailResponse:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    record = get_memory_version(version_id, scope=normalized_scope, workspace_id=wsid)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Memory version '{version_id}' not found")
    memory_payload = record.get("memory") or {}
    return MemoryVersionDetailResponse(
        version_id=record.get("version_id", version_id),
        created_at=record.get("created_at"),
        sha=record.get("sha"),
        parent_sha=record.get("parent_sha"),
        source_thread=record.get("source_thread"),
        operation=record.get("operation"),
        scope=record.get("scope"),
        scope_id=record.get("scope_id"),
        audit=record.get("audit") or {},
        memory=MemoryResponse(**memory_payload),
    )


@router.post("/memory/redact", response_model=MemoryRedactResponse, summary="Redact Memory")
async def redact_memory_endpoint(
    request: MemoryRedactRequest,
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> MemoryRedactResponse:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    result = redact_memory(
        agent_name=None,
        fact_ids=request.fact_ids,
        pattern=request.pattern,
        reason=request.reason,
        actor=request.actor,
        expected_sha=request.expected_sha,
        scope=normalized_scope,
        workspace_id=wsid,
    )
    return MemoryRedactResponse(
        success=True,
        affected_fact_ids=result.get("affected_fact_ids", []),
        memory_version_ref=result.get("ref"),
    )


@router.post("/memory/facts/{fact_id}", response_model=Fact, summary="Create or update memory fact")
async def upsert_fact_endpoint(
    fact_id: str,
    request: FactUpdateRequest,
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> Fact:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    updated = upsert_fact(
        fact_id=fact_id,
        content=request.content,
        category=request.category,
        confidence=request.confidence,
        source=request.source,
        scope=normalized_scope,
        workspace_id=wsid,
    )
    return Fact(**updated)


@router.delete("/memory/facts/{fact_id}", summary="Delete memory fact")
async def delete_fact_endpoint(
    fact_id: str,
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> dict[str, Any]:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    removed = delete_fact(fact_id=fact_id, scope=normalized_scope, workspace_id=wsid)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")
    return {"success": True, "id": fact_id}


@router.post("/memory/forget-thread", summary="Forget all facts sourced from a thread")
async def forget_thread_endpoint(
    request: ForgetThreadRequest,
    scope: MemoryScope = Query(default="workspace"),
    workspace_id: str | None = Query(default=None),
) -> dict[str, Any]:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    removed = forget_thread_facts(request.thread_id, scope=normalized_scope, workspace_id=wsid)
    return {"success": True, "removed": removed}


@router.post("/memory/rules", response_model=BehaviorRule, summary="Create behavior rule")
async def create_behavior_rule_endpoint(
    request: BehaviorRuleCreateRequest,
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> BehaviorRule:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    rule = add_behavior_rule(
        instruction=request.instruction,
        active=request.active,
        source=request.source,
        scope=normalized_scope,
        workspace_id=wsid,
    )
    return BehaviorRule(**rule)


@router.patch("/memory/rules/{rule_id}", response_model=BehaviorRule, summary="Update behavior rule")
async def update_behavior_rule_endpoint(
    rule_id: str,
    request: BehaviorRuleUpdateRequest,
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> BehaviorRule:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    try:
        rule = update_behavior_rule(
            rule_id=rule_id,
            instruction=request.instruction,
            active=request.active,
            scope=normalized_scope,
            workspace_id=wsid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BehaviorRule(**rule)


@router.delete("/memory/rules/{rule_id}", summary="Delete behavior rule")
async def delete_behavior_rule_endpoint(
    rule_id: str,
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> dict[str, Any]:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    deleted = delete_behavior_rule(rule_id=rule_id, scope=normalized_scope, workspace_id=wsid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return {"success": True, "id": rule_id}


@router.get("/memory/compactions", response_model=CompactionEntriesResponse, summary="Get compaction history")
async def get_compactions_endpoint(
    workspace_id: str = Query(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=1000),
) -> CompactionEntriesResponse:
    return CompactionEntriesResponse(items=read_compaction_entries(workspace_id, limit=limit))


@router.post("/memory/clear", response_model=MemoryClearResponse, summary="Clear all memory in scope")
async def clear_memory_endpoint(
    scope: MemoryScope = Query(default="global"),
    workspace_id: str | None = Query(default=None),
) -> MemoryClearResponse:
    normalized_scope, wsid = _scope_args(scope, workspace_id)
    cleared = clear_memory(scope=normalized_scope, workspace_id=wsid)
    return MemoryClearResponse(
        scope=normalized_scope,
        scope_id=wsid or "global",
        memory=MemoryResponse(**cleared),
    )
