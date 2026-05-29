export type PipelineRunStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "rejected";

export type PipelineStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export interface TriggerEvent {
  id: string;
  source: string;
  channel_name?: string | null;
  chat_id?: string | null;
  user_id?: string | null;
  classification: string;
  status: string;
  message: string;
  masked_message: string;
  pipeline_template_id?: string | null;
  pipeline_run_id?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PipelineStepDefinition {
  id: string;
  name: string;
  kind: string;
  stop_on_error: boolean;
  config: Record<string, unknown>;
}

export interface PipelineTemplate {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  requires_approval: boolean;
  trigger_sources: string[];
  default_inputs: Record<string, unknown>;
  steps: PipelineStepDefinition[];
  created_at: string;
  updated_at: string;
}

export interface PipelineStepRun {
  id: string;
  step_id: string;
  name: string;
  kind: string;
  status: PipelineStepStatus;
  logs: string[];
  output: Record<string, unknown>;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface PipelineRun {
  id: string;
  template_id?: string | null;
  template_name: string;
  trigger_event_id?: string | null;
  status: PipelineRunStatus;
  summary: string;
  requires_approval: boolean;
  approval_request_id?: string | null;
  inputs: Record<string, unknown>;
  masked_inputs: Record<string, unknown>;
  steps: PipelineStepRun[];
  alerts: string[];
  artifacts: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ApprovalRequest {
  id: string;
  pipeline_run_id: string;
  title: string;
  description: string;
  options: string[];
  status: "pending" | "approved" | "rejected" | "expired";
  requested_at: string;
  resolved_at?: string | null;
  resolution_note?: string | null;
  requested_by: string;
  metadata: Record<string, unknown>;
}

export interface FeedbackEvent {
  id: string;
  target_type: string;
  target_id: string;
  value: "up" | "down";
  comment: string;
  source: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  kind: string;
  message: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface CreatePipelineRunRequest {
  template_id?: string;
  steps?: PipelineStepDefinition[];
  inputs?: Record<string, unknown>;
  trigger_event_id?: string;
  summary?: string;
  requires_approval?: boolean;
  metadata?: Record<string, unknown>;
  auto_start?: boolean;
}

export interface ResolveApprovalRequest {
  approve: boolean;
  note?: string;
  auto_start?: boolean;
}

export interface CreateFeedbackRequest {
  target_type: string;
  target_id: string;
  value: "up" | "down";
  comment?: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

export interface IntegrationHealth {
  healthy: boolean;
  status_code?: number;
  url?: string;
  reason?: string;
  error?: string;
}

export interface ToolBackendStatus {
  enabled: boolean;
  base_url?: string | null;
  secrets_ready: boolean;
  health: IntegrationHealth;
}

export interface MCPServerStatus {
  enabled: boolean;
  type: string;
  url?: string | null;
  description: string;
  health: IntegrationHealth;
}

export interface FolderSyncTarget {
  id: string;
  path: string;
  recursive: boolean;
  file_globs: string[];
  upload_to_onyx: boolean;
  connector_prefix: string;
  enabled: boolean;
}

export interface FolderSyncManifest {
  target_id?: string | null;
  root: string;
  files: Array<{
    path: string;
    name: string;
    size_bytes: number;
    upload_to_onyx: boolean;
    connector_prefix: string;
  }>;
  file_count: number;
  skipped_files?: Array<{ path: string; reason: string }>;
  prepared_for_onyx: boolean;
  onyx_ingestion?: {
    enabled: boolean;
    base_url?: string;
    reason?: string;
    attempted: number;
    succeeded: number;
    failed: Array<{ path: string; reason: string }>;
  };
}

export interface LoginScraperStatus {
  id: string;
  enabled: boolean;
  mode: string;
  allowed_domains: string[];
  credentials_ready: boolean;
}

export interface SchedulerState {
  id: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_status: string;
  last_run_id?: string | null;
}

export interface SchedulerJobConfig {
  id: string;
  name: string;
  pipeline_template_id: string;
  interval_seconds: number;
  schedule_type?: "interval" | "daily_time";
  daily_time?: string | null;
  enabled: boolean;
  inputs?: Record<string, unknown>;
  requires_approval?: boolean | null;
  source?: "config" | "runtime" | string;
}

export interface AutoresearchObjective {
  id: string;
  objective_id: string;
  topic: string;
  endpoint_goal: string;
  status: "active" | "paused_denied" | "completed_endpoint";
  scheduler_job_id?: string | null;
  schedule_daily_time: string;
  template_id: string;
  source_thread_id?: string | null;
  latest_run_id?: string | null;
  loop_iteration: number;
  last_novelty_rate?: number | null;
  last_stop_reason?: string | null;
  last_reflection?: string | null;
  cluster_coverage: Record<string, number>;
  ledger_markdown_path?: string | null;
  ledger_json_path?: string | null;
  pause_reason?: string | null;
  running_run_id?: string | null;
  current_activity?: string | null;
  current_activity_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutoresearchQuestionNode {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "answered" | "duplicate" | "rejected" | "blocked";
  depends_on?: string[];
  cluster: number;
  level: number;
  asked_by: "generator" | "reflector" | "user";
  novelty: number;
  loop_iteration: number;
  vault_entries?: string[];
  duplicate_of?: string | null;
  researcher_summary?: string;
  sources_used?: number;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutoresearchLedger {
  objective_slug: string;
  loop_iteration: number;
  questions: AutoresearchQuestionNode[];
  iterations: Array<{
    iteration: number;
    at: string;
    generated: number;
    answered: number;
    duplicates: number;
    blocked: number;
    followups: number;
    novelty_rate: number;
    stop: boolean;
    stop_reason: string;
    reflection: string;
  }>;
  updated_at: string;
}

export interface StartAutoresearchObjectiveRequest {
  topic: string;
  endpoint_goal: string;
  thread_id?: string;
  objective_id?: string;
  daily_time?: string;
  bootstrap?: boolean;
  summary?: string;
}

export interface StartAutoresearchObjectiveResponse {
  objective: AutoresearchObjective;
  bootstrap_run?: PipelineRun | null;
  scheduled_time: string;
}

export interface RunAutoresearchObjectiveResponse {
  objective: AutoresearchObjective;
  bootstrap_run?: PipelineRun | null;
  via: string;
}

export interface DeleteAutoresearchObjectiveResponse {
  deleted: boolean;
  objective_id: string;
  removed_scheduler_jobs: string[];
  purge_result: Record<string, unknown>;
}

export interface CleanupPipelineRunsRequest {
  older_than_days: number;
  statuses?: string[];
}

export interface CleanupPipelineRunsResponse {
  deleted: number;
  deleted_run_ids: string[];
  missing_run_ids: string[];
}

export interface CleanupAutoresearchResponse {
  deleted_objectives: number;
  objective_ids: string[];
  run_cleanup: Record<string, unknown>;
}

export interface VaultStatusResponse {
  summary: Record<string, unknown>;
  counts: Record<string, unknown>;
  memory: Record<string, unknown>;
  progress: Record<string, unknown>;
  sufficiency: Record<string, unknown>;
  action_items: Record<string, unknown>;
  objectives: Record<string, unknown>;
}

export interface VaultSearchItem {
  rank: number;
  score: number;
  id?: string | null;
  kind?: string | null;
  title?: string | null;
  path?: string | null;
  snippet?: string | null;
  updated_at?: string | null;
}

export interface VaultSearchResponse {
  query: string;
  total: number;
  items: VaultSearchItem[];
}

export interface VaultWriteResponse {
  status: string;
  source_id?: string | null;
  queue_path?: string | null;
  appended_count?: number | null;
  compiled_path?: string | null;
  raw_path?: string | null;
}

export interface VaultExplorerFileNode {
  name: string;
  path: string;
  kind: "directory" | "file" | string;
  size?: number;
  children?: VaultExplorerFileNode[];
}

export interface VaultExplorerSourceItem {
  source_id: string;
  title: string;
  url: string;
  ingested_at: string;
  raw_path: string;
  compiled_path: string;
}

export interface VaultExplorerResponse {
  generated_at: string;
  cache_ttl_seconds: number;
  raw_sources: VaultExplorerSourceItem[];
  knowledge: {
    entities: VaultExplorerFileNode[];
    concepts: VaultExplorerFileNode[];
    sources: VaultExplorerFileNode[];
    others: VaultExplorerFileNode[];
  };
  files: VaultExplorerFileNode[];
}

export interface VaultFileResponse {
  path: string;
  editable: boolean;
  content: string;
}

export interface VaultFileWriteRequest {
  path: string;
  content: string;
}

export interface VaultSaveRequest {
  title: string;
  content: string;
  topic?: string;
  topic_tags?: string[];
  source_url?: string;
  source_thread_id?: string;
}

export interface VaultEntitySourceItem {
  source_id: string;
  title: string;
  url: string;
}

export interface VaultEntityConceptItem {
  slug: string;
  label: string;
}

export interface VaultEntityBrowserItem {
  slug: string;
  label: string;
  degree: number;
  sources: VaultEntitySourceItem[];
  concepts: VaultEntityConceptItem[];
}

export interface VaultEntityBrowserResponse {
  generated_at: string;
  counts: {
    total_entities?: number;
    dismissed?: number;
    critical_max_degree?: number;
  } & Record<string, unknown>;
  top: VaultEntityBrowserItem[];
  critical_gaps: VaultEntityBrowserItem[];
  less_covered: VaultEntityBrowserItem[];
}

export interface VaultEntityDismissalItem {
  slug: string;
  label: string;
  reason: string;
  alias_for: string | null;
  dismissed_at: string;
}

export interface VaultEntityDismissalsResponse {
  items: VaultEntityDismissalItem[];
}

export interface VaultEntityDismissRequest {
  reason?: string;
  alias_for?: string | null;
}

export interface VaultEntityDismissResponse {
  slug: string;
  alias_for: string | null;
  affected_sources: string[];
  compiled_deleted: boolean;
}

export interface VaultEntityRestoreResponse {
  slug: string;
  restored: boolean;
}

export interface VaultEntityAutoresearchRequest {
  label?: string;
  endpoint_goal?: string;
}

export interface VaultEntityAutoresearchResponse {
  objective_id: string | null;
  run_id: string | null;
  accepted: boolean | null;
  message: string | null;
}

export interface VaultIngestStatusResponse {
  job_id: string;
  status: "idle" | "running" | "success" | "failed" | string;
  total: number;
  processed: number;
  updated: number;
  skipped_no_raw: number;
  failed: number;
  current_index: number;
  current_source_id: string;
  current_title: string;
  last_status: string;
  last_error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  log_path: string;
  cancel_requested?: boolean;
  workers_requested?: number;
  workers_active?: number;
  accepted?: boolean | null;
  message?: string | null;
}

export interface VaultLintFinding {
  slug: string;
  label: string;
  reasons: string[];
  source_refs: string[];
  live_source_refs: string[];
}

export interface VaultLintCategoryReport {
  total_before: number;
  flagged: VaultLintFinding[];
  removed: number;
}

export interface VaultLintResponse {
  generated_at: string;
  dry_run: boolean;
  entities: VaultLintCategoryReport;
  concepts: VaultLintCategoryReport;
}

export interface VaultActionItem {
  kind: string;
  priority: string;
  title: string;
  detail: string;
  created_at: string;
  status: string;
  objective_id?: string | null;
}

export interface VaultActionItemsResponse {
  generated_at: string;
  counts: Record<string, unknown>;
  items: VaultActionItem[];
}

export interface VaultSufficiencyRequest {
  objective_id: string;
  topic?: string;
  min_score?: number;
}

export interface VaultSufficiencyResponse {
  generated_at: string;
  objective_id: string;
  topic: string;
  score: number;
  decision: string;
  blocking_checks: string[];
  reasons: string[];
  recommended_actions: string[];
  min_score: number;
  auto_pause_recommended: boolean;
  sufficient_streak: number;
  progress: Record<string, unknown>;
}

export interface PipelineArtifactContent {
  name: string;
  content_type: string;
  content: string;
}

export interface IntegrationStatusResponse {
  generated_at: string;
  channels: {
    service_running: boolean;
    channels: Record<string, { enabled: boolean; running: boolean }>;
  };
  tool_backends: Record<string, ToolBackendStatus>;
  mcp_servers: Record<string, MCPServerStatus>;
  folder_sync_targets: FolderSyncTarget[];
  audit_log: AuditEvent[];
  login_scrapers: LoginScraperStatus[];
  scheduler: {
    enabled: boolean;
    jobs: SchedulerJobConfig[];
    state: SchedulerState[];
    autoresearch_objectives?: AutoresearchObjective[];
  };
}

export interface SelfImproverDraftProposal {
  id: string;
  skill_name: string;
  category: string;
  skill_path: string;
  confidence: number;
  summary: string;
  recommended_addition: string;
  risk_flags: string[];
  evidence: Record<string, unknown>;
  validation: {
    frontmatter_ok: boolean;
    parse_ok: boolean;
    issues: string[];
  };
  diff_preview: string;
}

export interface SelfImproverDraftReport {
  version: string;
  generated_at: string;
  run_id: string;
  signal_window: {
    lookback_days: number;
    since: string;
    until: string;
  };
  limits: {
    max_proposals: number;
    max_diff_lines: number;
  };
  counts: {
    skills_total: number;
    skills_with_signals: number;
    proposals: number;
    skipped: number;
  };
  proposals: SelfImproverDraftProposal[];
  skipped: Array<Record<string, unknown>>;
}

export type ProposalApprovalStatus =
  | "pending"
  | "applied"
  | "rejected"
  | "apply_failed";

export interface ProposalApprovalItem {
  id: string;
  run_id: string;
  proposal_id: string;
  run_template_name: string;
  run_status: PipelineRunStatus;
  run_created_at: string;
  run_updated_at: string;
  status: ProposalApprovalStatus;
  note?: string | null;
  error?: string | null;
  resolved_at?: string | null;
  updated_at?: string | null;
  applied_path?: string | null;
  proposal: SelfImproverDraftProposal;
}

export interface ResolveProposalApprovalRequest {
  approve: boolean;
  note?: string;
}

export interface SchedulerRuntimeJobCreateRequest {
  name: string;
  pipeline_template_id: string;
  daily_time: string;
  enabled?: boolean;
  inputs?: Record<string, unknown>;
  requires_approval?: boolean | null;
}

export type IntegrationServiceId =
  | "llm"
  | "comfyui"
  | "websearch";

export interface IntegrationServiceStatus {
  id: IntegrationServiceId;
  label: string;
  base_url: string | null;
  host: string | null;
  port: number | null;
  healthy: boolean;
  status_code?: number;
  error?: string | null;
  can_start: boolean;
  can_stop?: boolean;
  docker_online?: boolean;
  phase?: "starting" | "running" | "healthy" | "degraded" | "failed";
  last_failure_reason?: string | null;
  last_transition_at?: string;
}

export interface IntegrationServicesStatusResponse {
  generated_at: string;
  docker_desktop_online?: boolean;
  docker_desktop_error?: string | null;
  docker_services?: Array<{
    name: string;
    status: string;
    online: boolean;
  }>;
  required_core_services?: string[];
  readiness_summary?: {
    all_ready: boolean;
    healthy_count: number;
    required_count: number;
    stability_target_seconds: number;
  };
  services: IntegrationServiceStatus[];
}

export interface IntegrationServiceStartResponse {
  job_id: string;
  status: "queued" | "running" | "success" | "failed";
  accepted: boolean;
  message: string;
}

export interface IntegrationServiceToggleResponse {
  service_id: string;
  accepted: boolean;
  action: "start" | "stop";
  status: string;
  message: string;
  job_id?: string;
}

export interface StartupStep {
  service_id: string;
  phase: "starting" | "running" | "healthy" | "degraded" | "failed";
  ok: boolean | null;
  detail: string;
  updated_at: string;
}

export interface StartupJob {
  id: string;
  target_service: string;
  command: string;
  status: "queued" | "running" | "success" | "failed";
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
  steps: StartupStep[];
  logs_tail: string[];
  error?: string | null;
}
