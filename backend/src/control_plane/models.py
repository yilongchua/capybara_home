from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class IntegrationSecretRef(BaseModel):
    name: str = Field(..., description="Human-readable secret label")
    env_var: str = Field(..., description="Environment variable containing the secret")
    required: bool = Field(default=False, description="Whether the secret is required")
    description: str | None = Field(default=None, description="Optional usage guidance")
    model_config = ConfigDict(extra="allow")


class CustomRedactionPattern(BaseModel):
    name: str
    pattern: str
    replacement: str | None = None
    model_config = ConfigDict(extra="allow")


class CSVProfile(BaseModel):
    id: str
    description: str = ""
    focus: str = ""
    row_limit: int = 25
    select_columns: list[str] = Field(default_factory=list)
    redact_columns: list[str] = Field(default_factory=list)
    sample_rows: int = 5
    summary_instructions: str = ""
    model_config = ConfigDict(extra="allow")


class FolderSyncTarget(BaseModel):
    id: str
    path: str
    recursive: bool = True
    file_globs: list[str] = Field(default_factory=lambda: ["*.md", "*.txt", "*.pdf", "*.csv", "*.docx", "*.xlsx"])
    enabled: bool = True
    model_config = ConfigDict(extra="allow")


class PipelineStepDefinition(BaseModel):
    id: str = Field(default_factory=lambda: new_id("step"))
    name: str
    kind: Literal[
        "noop",
        "note",
        "redact_text",
        "csv_profile",
        "folder_sync",
        "local_llm",
        "http_request",
        "improver_scan",
        "self_improver_draft",
        "vault_discover",
        "vault_ingest",
        "vault_compile",
        "vault_lint",
        "synthesize_knowledge_graph",
        "vault_sufficiency_evaluate",
        "autoresearch_loop_iteration",
    ]
    stop_on_error: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="allow")


class PipelineTemplate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tmpl"))
    name: str
    description: str = ""
    enabled: bool = True
    requires_approval: bool = True
    trigger_sources: list[str] = Field(default_factory=lambda: ["manual"])
    default_inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[PipelineStepDefinition] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    model_config = ConfigDict(extra="allow")


class PipelineStepRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("steprun"))
    step_id: str
    name: str
    kind: str
    status: Literal["pending", "running", "completed", "failed", "skipped", "cancelled"] = "pending"
    logs: list[str] = Field(default_factory=list)
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    model_config = ConfigDict(extra="allow")


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("approval"))
    pipeline_run_id: str
    title: str
    description: str = ""
    options: list[str] = Field(default_factory=lambda: ["approve", "reject"])
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    requested_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    requested_by: str = "system"
    metadata: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="allow")


class PipelineRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    template_id: str | None = None
    template_name: str = ""
    trigger_event_id: str | None = None
    status: Literal[
        "draft",
        "pending_approval",
        "approved",
        "running",
        "completed",
        "failed",
        "cancelled",
        "rejected",
    ] = "draft"
    summary: str = ""
    requires_approval: bool = True
    approval_request_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    masked_inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[PipelineStepRun] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    model_config = ConfigDict(extra="allow")


class TriggerEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("trigger"))
    source: str
    channel_name: str | None = None
    chat_id: str | None = None
    user_id: str | None = None
    classification: str = "chat"
    status: Literal["received", "drafted", "processed", "ignored", "error"] = "received"
    message: str = ""
    masked_message: str = ""
    pipeline_template_id: str | None = None
    pipeline_run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    model_config = ConfigDict(extra="allow")


class FeedbackEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("feedback"))
    target_type: str
    target_id: str
    value: Literal["up", "down"]
    comment: str = ""
    source: str = "web"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    model_config = ConfigDict(extra="allow")


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("audit"))
    kind: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    model_config = ConfigDict(extra="allow")


class SchedulerJob(BaseModel):
    id: str
    name: str
    pipeline_template_id: str
    interval_seconds: int = 3600
    schedule_type: Literal["interval", "daily_time"] = "interval"
    daily_time: str | None = None
    enabled: bool = True
    inputs: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool | None = None
    model_config = ConfigDict(extra="allow")


class SchedulerJobState(BaseModel):
    id: str
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_status: str = "never_run"
    last_run_id: str | None = None
    model_config = ConfigDict(extra="allow")


class ProposalReview(BaseModel):
    run_id: str
    proposal_id: str
    status: Literal["pending", "applied", "rejected", "apply_failed"] = "pending"
    note: str | None = None
    error: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    applied_path: str | None = None
    model_config = ConfigDict(extra="allow")


class AutoresearchObjective(BaseModel):
    id: str = Field(default_factory=lambda: new_id("autoobj"))
    objective_id: str
    topic: str
    endpoint_goal: str = ""
    status: Literal["active", "paused_denied", "completed_endpoint"] = "active"
    scheduler_job_id: str | None = None
    schedule_daily_time: str = "02:00"
    template_id: str = "knowledge-vault-autoresearch-loop"
    source_thread_id: str | None = None
    latest_run_id: str | None = None
    loop_iteration: int = 0
    last_novelty_rate: float | None = None
    last_stop_reason: str | None = None
    last_reflection: str | None = None
    cluster_coverage: dict[str, int] = Field(default_factory=dict)
    ledger_markdown_path: str | None = None
    ledger_json_path: str | None = None
    pause_reason: str | None = None
    running_run_id: str | None = None
    current_activity: str | None = None
    current_activity_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    model_config = ConfigDict(extra="allow")


class ControlPlaneSnapshot(BaseModel):
    templates: dict[str, PipelineTemplate] = Field(default_factory=dict)
    runs: dict[str, PipelineRun] = Field(default_factory=dict)
    approvals: dict[str, ApprovalRequest] = Field(default_factory=dict)
    triggers: dict[str, TriggerEvent] = Field(default_factory=dict)
    feedback: dict[str, FeedbackEvent] = Field(default_factory=dict)
    scheduler_jobs: dict[str, SchedulerJobState] = Field(default_factory=dict)
    runtime_scheduler_jobs: dict[str, SchedulerJob] = Field(default_factory=dict)
    autoresearch_objectives: dict[str, AutoresearchObjective] = Field(default_factory=dict)
    proposal_reviews: dict[str, ProposalReview] = Field(default_factory=dict)
    audit_log: list[AuditEvent] = Field(default_factory=list)
    model_config = ConfigDict(extra="allow")
