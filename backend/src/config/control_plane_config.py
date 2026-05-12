from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.control_plane.models import (
    CSVProfile,
    CustomRedactionPattern,
    FolderSyncTarget,
    IntegrationSecretRef,
    PipelineTemplate,
    SchedulerJob,
)


class PipelinesConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether the Capybara Home pipeline control plane is enabled")
    storage_dir: str = Field(default="control-plane", description="Relative directory under CAPYBARA_HOME used for pipeline state")
    default_requires_approval: bool = Field(default=True, description="Whether ad-hoc pipeline runs require approval by default")
    audit_log_max_entries: int = Field(default=200, description="Maximum number of audit events to retain")
    templates: list[PipelineTemplate] = Field(default_factory=list, description="Pipeline templates available to the control plane")
    folder_sync_targets: list[FolderSyncTarget] = Field(default_factory=list, description="Approved local folders for sync and indexing preparation")
    folder_sync_max_files: int = Field(default=200, description="Maximum number of files to process per folder sync step")
    folder_sync_max_bytes: int = Field(default=10 * 1024 * 1024, description="Maximum file size to process (bytes)")
    model_config = ConfigDict(extra="allow")


class ApprovalsConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether approval workflows are enabled")
    auto_expire_minutes: int = Field(default=1440, ge=5, le=10080, description="Minutes before pending approvals expire")
    require_resolution_note_on_reject: bool = Field(default=False, description="Whether rejections must include a note")
    model_config = ConfigDict(extra="allow")


class RedactionConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether deterministic redaction is enabled")
    replace_with: str = Field(default="[REDACTED]", description="Default replacement token")
    hash_values: bool = Field(default=False, description="Hash sensitive values instead of using a fixed token")
    mask_emails: bool = Field(default=True, description="Redact email addresses")
    mask_phone_numbers: bool = Field(default=True, description="Redact phone numbers")
    mask_credit_cards: bool = Field(default=True, description="Redact likely card numbers")
    custom_patterns: list[CustomRedactionPattern] = Field(default_factory=list, description="Additional regex redaction rules")
    model_config = ConfigDict(extra="allow")


class ToolBackendEndpointConfig(BaseModel):
    enabled: bool = Field(default=False, description="Whether the backend is enabled")
    base_url: str | None = Field(default=None, description="Base URL for the backend")
    health_path: str = Field(default="/health", description="Relative health-check path")
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0, description="HTTP timeout for backend checks")
    secret_refs: list[IntegrationSecretRef] = Field(default_factory=list, description="Secrets needed to use this backend")
    headers: dict[str, str] = Field(default_factory=dict, description="Static headers sent to the backend")
    model_config = ConfigDict(extra="allow")


class ToolBackendsConfig(BaseModel):
    comfyui: ToolBackendEndpointConfig = Field(default_factory=ToolBackendEndpointConfig)
    model_config = ConfigDict(extra="allow")


class SchedulerConfig(BaseModel):
    enabled: bool = Field(default=False, description="Whether background scheduled jobs are enabled")
    poll_interval_seconds: int = Field(default=60, ge=10, le=3600, description="How often the scheduler checks for due jobs")
    jobs: list[SchedulerJob] = Field(default_factory=list, description="Scheduled jobs mapped to pipeline templates")
    model_config = ConfigDict(extra="allow")


class CSVProfilesConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether deterministic CSV profiles are enabled")
    profiles: list[CSVProfile] = Field(default_factory=list)
    model_config = ConfigDict(extra="allow")


class GenerationAsyncConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether async generation jobs are enabled")
    storage_dir: str = Field(default="generation-jobs", description="Relative directory under CAPYBARA_HOME used for generation job state")
    poll_interval_seconds: int = Field(default=3, ge=1, le=30, description="How often generation poller checks job completion")
    max_job_age_seconds: int = Field(default=14400, ge=300, le=172800, description="Maximum job runtime before marking timed out")
    comfy_base_url: str = Field(default="http://127.0.0.1:8188", description="ComfyUI base URL")
    comfy_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0, description="HTTP timeout for ComfyUI requests")
    workflow_api_dir: str = Field(
        default="/Users/ryan_chua/Desktop/comfyUI/user/default/workflows_api",
        description="Directory containing ComfyUI API workflow JSON files",
    )
    image_workflow_file: str = Field(default="text2image.json", description="Image workflow filename under workflow_api_dir")
    video_workflow_file: str = Field(default="text_to_video_wan.json", description="Video workflow filename under workflow_api_dir")
    comfy_output_dir: str = Field(
        default="/Users/ryan_chua/Desktop/comfyUI/output",
        description="ComfyUI output directory on host",
    )
    filename_prefix_root: str = Field(default="capybara", description="Required filename prefix root under ComfyUI output")
    model_config = ConfigDict(extra="allow")


class KnowledgeVaultConfig(BaseModel):
    class LightRAGConfig(BaseModel):
        enabled: bool = Field(default=False, description="Whether LightRAG graph query integration is enabled")
        base_url: str = Field(default="http://localhost:9621", description="LightRAG API base URL")
        timeout_seconds: float = Field(default=12.0, ge=1.0, le=120.0, description="HTTP timeout for LightRAG requests")
        default_mode: str = Field(default="hybrid", description="Default query mode for LightRAG")
        max_top_k: int = Field(default=20, ge=1, le=200, description="Maximum top_k per LightRAG query")
        model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Whether knowledge vault workflows are enabled")
    path: str = Field(default="", description="Path to Obsidian-compatible vault directory")
    allowed_domains: list[str] = Field(default_factory=list, description="Optional domain allowlist for vault ingestion")
    max_content_chars: int = Field(default=20000, ge=1000, le=200000, description="Maximum extracted characters per ingested source")
    min_trust_score: float = Field(default=0.55, ge=0.0, le=1.0, description="Minimum trust score required before appending knowledge to vault")
    query_retention_hours: int = Field(default=72, ge=1, le=720, description="How long query artifacts remain active before expiry/merge review")
    search_results_queue_enabled: bool = Field(default=True, description="Whether enriched web_search results can be enqueued for vault ingestion")
    search_results_queue_path: str = Field(
        default="knowledge_vault/03_ops/queues/search_results_ingestion_queue.json",
        description="Relative queue file path used to stage enriched search results for vault ingestion",
    )
    search_results_require_extracted_content: bool = Field(
        default=True,
        description="Only enqueue search results when full extracted_content is present",
    )
    search_results_dedupe_window_hours: int = Field(
        default=72,
        ge=1,
        le=720,
        description="How long to dedupe queued search results by url and content hash",
    )
    search_results_auto_classify: bool = Field(
        default=True,
        description="Run an LLM classification pass to assign topic_tags and concept_refs before queue append",
    )
    search_results_max_queue_items: int = Field(
        default=5000,
        ge=10,
        le=50000,
        description="Maximum queue entries retained before older terminal records are trimmed",
    )
    lightrag: LightRAGConfig = Field(default_factory=LightRAGConfig)
    model_config = ConfigDict(extra="allow")
