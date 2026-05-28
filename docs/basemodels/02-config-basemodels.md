# 02 — Configuration BaseModels (`src/config/`)

All configuration nodes are already implemented as `pydantic.BaseModel`. This file is an **audit catalogue** — every entry must remain a `BaseModel`. Use it to spot missing fields, duplicated semantics, or fields that should be promoted to a dedicated nested model.

> Convention reminder: all config models use `model_config = ConfigDict(extra="allow")` so that experimental YAML keys never break startup. Migration owners adding strict validation should switch to `extra="forbid"` *only* once the corresponding loader is also tightened.

---

## 2.1 Root + top-level

| Model | File | Line | Purpose / Anchor field set |
|-------|------|-----:|----------------------------|
| `AppConfig` | [src/config/app_config.py](../../backend/src/config/app_config.py) | 61 | Root — composes every sub-config below (`models[]`, `sandbox`, `tools[]`, `tool_groups[]`, `skills`, `prompt`, `permissions`, `trajectory`, `metrics`, `execution_trace`, `dreamy_timeout`, `subagents`, `recursion_pivot`, `quality_gate`, `loop_detection`, `todos`, `routing`, `planner`, `evaluator`, `sprint_contracts`, `handoffs`, `hooks`, `retry`, `resume`, `tool_disclosure`, `web_search_summary`, `scratchpad`, `task_memory`, `memory_versioning`, `skill_curation`, `benchmarks`, `extensions`, `pipelines`, `approvals`, `redaction`, `csv_profiles`, `tool_backends`, `scheduler`, `generation`, `knowledge_vault`, `checkpointer`). |
| `GatewayConfig` | [src/gateway/config.py](../../backend/src/gateway/config.py) | 6 | FastAPI Gateway runtime config (host/port/CORS/static-roots). |

---

## 2.2 Per-feature config nodes

| Model | File | Line | Owned settings |
|-------|------|-----:|----------------|
| `ModelConfig` | [src/config/model_config.py](../../backend/src/config/model_config.py) | 4 | `name`, `model`, `use`, `supports_thinking`, `supports_vision`, `when_thinking_enabled`, provider kwargs, `base_url`. |
| `SandboxConfig` | [src/config/sandbox_config.py](../../backend/src/config/sandbox_config.py) | 12 | `use`, `volume_mounts`. |
| `VolumeMountConfig` | [src/config/sandbox_config.py](../../backend/src/config/sandbox_config.py) | 4 | `host_path`, `container_path`, `read_only`. |
| `ToolConfig` | [src/config/tool_config.py](../../backend/src/config/tool_config.py) | 11 | `name`, `use`, `group`. |
| `ToolGroupConfig` | [src/config/tool_config.py](../../backend/src/config/tool_config.py) | 4 | `name`, `description`. |
| `SkillsConfig` | [src/config/skills_config.py](../../backend/src/config/skills_config.py) | 6 | `path`, `container_path`, `progressive_disclosure`, `active_body_token_budget`, `matcher_trigger_enabled`. |
| `PromptConfig` | [src/config/prompt_config.py](../../backend/src/config/prompt_config.py) | 6 | `componentized`. |
| `PermissionsConfig` | [src/config/permissions_config.py](../../backend/src/config/permissions_config.py) | 10 | `allow[]`, `deny[]`, `ask[]`, `default_mode`. |
| `TrajectoryConfig` | [src/config/trajectory_config.py](../../backend/src/config/trajectory_config.py) | 6 | `enabled`, `directory`, `format`. |
| `MetricsConfig` | [src/config/metrics_config.py](../../backend/src/config/metrics_config.py) | 6 | `enabled`. |
| `ExecutionTraceConfig` | [src/config/execution_trace_config.py](../../backend/src/config/execution_trace_config.py) | 6 | `enabled`, `max_payload_chars`, retention. |
| `DreamyTimeoutConfig` | [src/config/dreamy_timeout_config.py](../../backend/src/config/dreamy_timeout_config.py) | 6 | Dreamy workflow watchdog. |
| `SubagentsAppConfig` | [src/config/subagents_config.py](../../backend/src/config/subagents_config.py) | 20 | `enabled`, `max_concurrent_limit`, `max_primary_per_turn`, `overrides[]`. |
| `SubagentOverrideConfig` | [src/config/subagents_config.py](../../backend/src/config/subagents_config.py) | 10 | Per-subagent override of `model`, `max_turns`, `timeout_seconds`. |
| `RecursionPivotConfig` | [src/config/recursion_pivot_config.py](../../backend/src/config/recursion_pivot_config.py) | 8 | Evaluator pivot trigger at recursion-budget thresholds. |
| `QualityGateConfig` | [src/config/quality_gate_config.py](../../backend/src/config/quality_gate_config.py) | 6 | Report quality-check thresholds. |
| `LoopDetectionConfig` | [src/config/loop_detection_config.py](../../backend/src/config/loop_detection_config.py) | 6 | Repetitive tool-call detection thresholds. |
| `TodosConfig` | [src/config/todos_config.py](../../backend/src/config/todos_config.py) | 6 | `dag_enabled`. |
| `RoutingConfig` | [src/config/routing_config.py](../../backend/src/config/routing_config.py) | 102 | `stages` (map), `fallback`, `timeouts`. |
| `RoutingTimeoutsConfig` | [src/config/routing_config.py](../../backend/src/config/routing_config.py) | 6 | Per-stage model timeout overrides. |
| `PlannerConfig` | [src/config/planner_config.py](../../backend/src/config/planner_config.py) | 6 | Planner middleware switches & limits. |
| `EvaluatorConfig` | [src/config/evaluator_config.py](../../backend/src/config/evaluator_config.py) | 6 | Evaluator switches & limits. |
| `SprintContractsConfig` | [src/config/sprint_contracts_config.py](../../backend/src/config/sprint_contracts_config.py) | 6 | Sprint contract trigger words & limits. |
| `HandoffsConfig` | [src/config/handoffs_config.py](../../backend/src/config/handoffs_config.py) | 6 | Handoff artifact directory + alias paths. |
| `HooksConfig` | [src/config/hooks_config.py](../../backend/src/config/hooks_config.py) | 22 | Lifecycle hook list. |
| `HookCommandConfig` | [src/config/hooks_config.py](../../backend/src/config/hooks_config.py) | 6 | `event`, `command`, `cwd`, `timeout_seconds`. |
| `RetryConfig` | [src/config/retry_config.py](../../backend/src/config/retry_config.py) | 22 | `default_rule`, `rules[]`. |
| `RetryRuleConfig` | [src/config/retry_config.py](../../backend/src/config/retry_config.py) | 6 | `tool_pattern`, `max_attempts`, `backoff_seconds`. |
| `ResumeConfig` | [src/config/resume_config.py](../../backend/src/config/resume_config.py) | 6 | Resume continuity-marker controls. |
| `ToolDisclosureConfig` | [src/config/tool_disclosure_config.py](../../backend/src/config/tool_disclosure_config.py) | 8 | Phase-gated tool allow-lists. |
| `WebSearchSummaryConfig` | [src/config/web_search_summary_config.py](../../backend/src/config/web_search_summary_config.py) | 6 | Web-search summarisation. |
| `ScratchpadConfig` | [src/config/scratchpad_config.py](../../backend/src/config/scratchpad_config.py) | 6 | Scratchpad bound + retention. |
| `TaskMemoryConfig` | [src/config/task_memory_config.py](../../backend/src/config/task_memory_config.py) | 6 | Task-scoped fact retention. |
| `MemoryConfig` | [src/config/memory_config.py](../../backend/src/config/memory_config.py) | 6 | `enabled`, `injection_enabled`, `storage_path`, debounce, model, thresholds. |
| `MemoryVersioningConfig` | [src/config/memory_versioning_config.py](../../backend/src/config/memory_versioning_config.py) | 6 | Append-only memory versioning. |
| `SkillCurationConfig` | [src/config/skill_curation_config.py](../../backend/src/config/skill_curation_config.py) | 6 | Self-improver skill curation gates. |
| `BenchmarksConfig` | [src/config/benchmarks_config.py](../../backend/src/config/benchmarks_config.py) | 6 | External benchmark suite controls. |
| `SummarizationConfig` | [src/config/summarization_config.py](../../backend/src/config/summarization_config.py) | 21 | `enabled`, `trigger`, `keep`, `mode_overrides`. |
| `ContextSize` | [src/config/summarization_config.py](../../backend/src/config/summarization_config.py) | 10 | `tokens`, `messages`, `fraction`. |
| `SummarizationModeOverride` | [src/config/summarization_config.py](../../backend/src/config/summarization_config.py) | 62 | Per-mode override (eg. `dreamy`). |
| `TitleConfig` | [src/config/title_config.py](../../backend/src/config/title_config.py) | 6 | `enabled`, `max_words`, `max_chars`, `prompt_template`. |
| `QuestionGenerationConfig` | [src/config/question_generation_config.py](../../backend/src/config/question_generation_config.py) | 6 | Suggested-question middleware controls. |
| `HarnessConfig` | [src/config/harness_config.py](../../backend/src/config/harness_config.py) | 32 | Kill-switch flag set (`use_minimal`, etc.). |
| `TracingConfig` | [src/config/tracing_config.py](../../backend/src/config/tracing_config.py) | 11 | Langfuse / LangSmith tracing toggles. |
| `CheckpointerConfig` | [src/config/checkpointer_config.py](../../backend/src/config/checkpointer_config.py) | 10 | Checkpointer provider class + kwargs. |
| `AgentConfig` | [src/config/agents_config.py](../../backend/src/config/agents_config.py) | 18 | Per-agent prompt/tool/skill overrides (used by user-defined "agents tab"). |

---

## 2.3 Extensions config (MCP, skills state, user-LLM endpoints)

| Model | File | Line | Notes |
|-------|------|-----:|-------|
| `ExtensionsConfig` | [src/config/extensions_config.py](../../backend/src/config/extensions_config.py) | 76 | Root for `extensions_config.json`. |
| `McpServerConfig` | [src/config/extensions_config.py](../../backend/src/config/extensions_config.py) | 34 | `enabled`, `type` (stdio/sse/http), `command`, `args`, `env`, `url`, `headers`, `oauth`, `description`. |
| `McpOAuthConfig` | [src/config/extensions_config.py](../../backend/src/config/extensions_config.py) | 11 | OAuth token endpoint settings. |
| `SkillStateConfig` | [src/config/extensions_config.py](../../backend/src/config/extensions_config.py) | 50 | `enabled`. |
| `CommunityToolStateConfig` | [src/config/extensions_config.py](../../backend/src/config/extensions_config.py) | 56 | `enabled`. |
| `UserLlmEndpointConfig` | [src/config/extensions_config.py](../../backend/src/config/extensions_config.py) | 62 | `name`, `base_url`, `api_key`, `models[]`. |

---

## 2.4 Control-plane configs (subset of `AppConfig`)

| Model | File | Line | Notes |
|-------|------|-----:|-------|
| `PipelinesConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 15 | Pipeline auto-approval + run defaults. |
| `ApprovalsConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 27 | Approval expiry, default approver list. |
| `RedactionConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 34 | PII redaction toggles + custom patterns. |
| `ToolBackendsConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 55 | Map of `tool_name → ToolBackendEndpointConfig`. |
| `ToolBackendEndpointConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 45 | `url`, `model`, `api_key`, `timeout_seconds`. |
| `SchedulerConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 60 | Tick interval, max concurrent jobs. |
| `CSVProfilesConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 67 | CSV interpreter profile bundle. |
| `GenerationAsyncConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 73 | ComfyUI async job poller settings. |
| `KnowledgeVaultConfig` | [src/config/control_plane_config.py](../../backend/src/config/control_plane_config.py) | 94 | Vault root, ingestion globs, autoresearch loop budget. |

---

## 2.5 Audit findings — actionable

These were spotted during the inventory and should be addressed during the structural migration.

| # | Finding | Suggested fix |
|---|---------|---------------|
| C-1 | `RoutingConfig` (line 102) is unusually large; the `stages` dict has no inner typing. | Add `RoutingStageConfig` nested model (`model`, `temperature`, `max_tokens`, `timeout`) and type `stages: dict[str, RoutingStageConfig]`. |
| C-2 | `ModelConfig` carries provider-specific extras through `extra="allow"`. | Introduce explicit `provider_kwargs: dict[str, Any] = Field(default_factory=dict)` and constrain top-level to known names — provider classes already document this. |
| C-3 | `HookCommandConfig.event` is `str`. | Promote to `Literal[…]` of known hook event names (currently scattered across `hooks_middleware.py`). |
| C-4 | `AgentConfig` has no validator preventing two agents with the same `name`. | Add `model_validator` on the **list** in `AppConfig.from_file` (post-load step). |
| C-5 | `PermissionsConfig.default_mode` is a free-form string. | Already a `PermissionDefaultMode` enum at line 4 — confirm `Literal` constraint on the field itself. |
| C-6 | `VolumeMountConfig.host_path` and `container_path` are not validated against `..` traversal. | Add a shared `validators.safe_path` (proposed in §01 conventions). |
