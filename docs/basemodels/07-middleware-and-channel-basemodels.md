# 07 — Middleware & Channel BaseModels

Scope:
* `src/agents/middlewares/` — local `@dataclass` and `TypedDict` records used by the middleware chain (planner output, summarization event, registry spec, hook results, etc.).
* `src/channels/` — message bus DTOs that flow between Slack / Telegram channels and the LangGraph dispatcher.

These currently rely heavily on `@dataclass` because middleware authors valued speed of iteration over validation. They are now load-bearing for **steering**, **plan approval**, **work-mode handoff**, and **channel inbound/outbound replay** — so structural validation is required.

---

## 7.1 Middleware records — PROPOSED migrations

### 7.1.1 Planner output (`planner_middleware.py`)

Source file: [src/agents/middlewares/planner_middleware.py](../../backend/src/agents/middlewares/planner_middleware.py)

| Target `BaseModel` | Replaces (`@dataclass`) | Line | Required fields | Notes |
|--------------------|-------------------------|-----:|-----------------|-------|
| `PlannerClarificationOption` | `ClarificationOption` | 82 | `label: str` (min_length=1), `recommended: bool = False`, `description: str \| None = None` | Wire format — flows to gateway `/api/steering/clarify`. |
| `PlannerClarification` | `PlannerClarification` | 89 | `question: str` (min_length=1), `options: list[PlannerClarificationOption] = []` | At least one option in non-trivial paths — `model_validator` guard. |
| `PlannerOutput` | `PlannerOutput` | 95 | `trivial: bool = False`, `title: str = "Execution Plan"`, `summary: str = ""`, `objective: str = ""`, `assumptions: list[str] = []`, `constraints: list[str] = []`, `risks: list[PlanRisk] = []` (see §5.2.1), `acceptance_criteria: list[str] = []`, `domain: Literal["generic","data","engineering","research","writing","ops"] = "generic"`, `todos: list[TodoNodeInput] = []`, `clarifications: list[PlannerClarification] = []`, `parse_ok: bool = True` | This is the **LLM call output schema**; should be passed to `with_structured_output(PlannerOutput)`. Today the planner parses JSON manually. |

### 7.1.2 Summarization hook event

Source file: [src/agents/middlewares/summarization_middleware.py](../../backend/src/agents/middlewares/summarization_middleware.py)

| Target `BaseModel` | Replaces (`@dataclass(frozen=True)`) | Line | Fields | Notes |
|--------------------|--------------------------------------|-----:|--------|-------|
| `SummarizationEvent` | `SummarizationEvent` | 106 | `messages_to_summarize: tuple[BaseMessage, ...]`, `preserved_messages: tuple[BaseMessage, ...]`, `thread_id: str \| None`, `agent_name: str \| None`, `state: dict[str, Any] \| None` (do **not** type as `BaseModel`; pass-through) | `frozen=True`. **Note**: `runtime: Runtime` field must remain non-Pydantic — exclude with `Field(exclude=True)` and provide via constructor. |

### 7.1.3 Permission middleware

Source file: [src/agents/middlewares/permission_middleware.py](../../backend/src/agents/middlewares/permission_middleware.py)

| Target `BaseModel` | Replaces (`@dataclass(frozen=True)`) | Line | Fields | Notes |
|--------------------|--------------------------------------|-----:|--------|-------|
| `ParsedRule` | `ParsedRule` | 28 | `tool_pattern: str` (min_length=1), `arg_pattern: str \| None = None` | `frozen=True`. Used only internally; could stay `@dataclass` — but `BaseModel` enables `model_validate` of a serialized config snapshot. |

### 7.1.4 Lead agent registry

Source file: [src/agents/lead_agent/agent.py](../../backend/src/agents/lead_agent/agent.py)

| Target `BaseModel` | Replaces (`@dataclass`) | Line | Fields | Notes |
|--------------------|-------------------------|-----:|--------|-------|
| `MiddlewareSpec` | `MiddlewareSpec` | 296 | `name: str`, `factory: Callable` (excluded from validation), `after: set[str] = set()`, `before: set[str] = set()`, `priority: int = 0` | `Callable` field must be `Field(exclude=True)`; rest validates. Helps reject duplicate names and unknown dependencies at boot. |
| `RegistryContext` | `_RegistryContext` | 354 | `is_plan_mode: bool`, `is_work_mode: bool`, `subagent_enabled: bool`, `max_concurrent_subagents: int (ge=0)`, `max_primary_per_turn: int (ge=0)`, `model_name: str \| None`, `agent_name: str \| None`, … (continue at line 369+) | Promote from private `_` prefix to a public model. |
| `LeadAgentBuildSpec` | `@dataclass` at line 685 (specific name to be confirmed) | 685 | Likely the full build context for `make_lead_agent`. | Read the source to expand. |

### 7.1.5 Prompt cache record

Source file: [src/agents/lead_agent/prompt_cache.py](../../backend/src/agents/lead_agent/prompt_cache.py)

| Target `BaseModel` | Replaces (`@dataclass`) | Line | Fields | Notes |
|--------------------|-------------------------|-----:|--------|-------|
| `PromptCacheEntry` | unnamed `@dataclass` | 27 | `prompt_sha: str` (regex sha256), `rendered_at: datetime`, `model_name: str`, `token_count: int (ge=0)`, `source: Literal["lead","planner","evaluator","subagent","memory"]`, `payload: dict[str, Any] = {}` | Persisted (in-memory dict; consider on-disk LRU). |

### 7.1.6 Memory update queue record

Source file: [src/agents/memory/queue.py](../../backend/src/agents/memory/queue.py)

| Target `BaseModel` | Replaces (`@dataclass`) | Line | Fields | Notes |
|--------------------|-------------------------|-----:|--------|-------|
| `ConversationContext` | `ConversationContext` | 15 | `thread_id: str`, `messages: list[Any]` (LangChain messages — `Field(exclude=True)` from JSON), `timestamp: datetime`, `agent_name: str \| None = None`, `workspace_id: str \| None = None` | The `messages` field carries LangChain objects; use `arbitrary_types_allowed=True`. Replace `datetime.utcnow()` with `datetime.now(UTC)` (see [01 §7](01-conventions-and-standards.md)). |

### 7.1.7 Quality check report

Source file: [src/agents/report_quality.py](../../backend/src/agents/report_quality.py)

| Target `BaseModel` | Replaces (`@dataclass`) | Line | Fields | Notes |
|--------------------|-------------------------|-----:|--------|-------|
| `QualityCheckReport` | `QualityCheckResult` | 10 | `ok: bool`, `reasons: list[str] = []`, `checked_path: str`, `metrics: dict[str, float] = {}` | Surfaces in `QualityGateState` and the SSE `quality_gate_*` events; `BaseModel` enables JSON round-trip. |

### 7.1.8 Search guardrails config

Source file: [src/security/search_guardrails.py](../../backend/src/security/search_guardrails.py)

| Target `BaseModel` | Replaces (`@dataclass(frozen=True)`) | Line | Fields | Notes |
|--------------------|--------------------------------------|-----:|--------|-------|
| `CIDGuardrailConfig` | `CIDGuardrailConfig` | 11 | `enabled: bool = True`, `block_on_detection: bool = True`, `max_query_chars: int (ge=1) = 512`, `allow_personal_data_queries: bool = False`, `block_private_network_urls: bool = True`, `allowed_fetch_domains: tuple[str, ...] = ()` | `frozen=True`. Promote `tuple` to `list` for JSON round-trip (or document the custom serializer). Currently constructed only from code defaults; should be loaded from `config.yaml -> security` (proposed). |

---

## 7.2 PROPOSED — NEW middleware event/record models

These middlewares emit or persist values that today are **raw dicts** with no schema. They should be promoted to `BaseModel`:

| New `BaseModel` | Target file | Used by | Fields |
|-----------------|-------------|---------|--------|
| `EvaluatorReport` | `src/agents/middlewares/evaluator_middleware.py` | `EvaluatorMiddleware` | `verdict: Literal["pass","fail","needs_repair"]`, `score: float (ge=0, le=1)`, `report: str`, `fail_reasons: list[str] = []`, `repair_passes: int (ge=0)`, `evaluator_model: str`, `created_at: datetime` |
| `LoopDetectionSignal` | `src/agents/middlewares/loop_detection_middleware.py` | `LoopDetectionMiddleware` | `pattern: Literal["repeated_tool_call","repeated_tool_result","oscillating_plan"]`, `evidence: list[str]`, `turns_observed: int (ge=1)`, `action_taken: Literal["warn","interrupt","compact"]` |
| `RecursionPivotDecision` | `src/agents/middlewares/recursion_pivot_middleware.py` | `RecursionBudgetPivotMiddleware` | `triggered: bool`, `budget_used: int (ge=0)`, `budget_total: int (ge=0)`, `pivot_reason: str`, `evaluator_verdict: str \| None` |
| `RetryDecision` | `src/agents/middlewares/retry_policy_middleware.py` | `RetryPolicyMiddleware` | `tool_call_id: str`, `attempt_number: int (ge=1)`, `max_attempts: int (ge=1)`, `should_retry: bool`, `backoff_seconds: float (ge=0)`, `reason: str` |
| `ProgressGuardSignal` | `src/agents/middlewares/progress_guard_middleware.py` | `ProgressGuardMiddleware` | `kind: Literal["warn","terminate"]`, `no_progress_turns: int (ge=0)`, `last_snapshot_hash: str`, `message: str` |
| `PlanFollowupJob` | `src/agents/middlewares/pro_followup_middleware.py` | `PlanFollowupMiddleware` | (alias of `BackgroundFollowupJob` in §5 — collapse to single source). |
| `HandoffSyncReport` | `src/agents/middlewares/handoff_sync.py` | `handoff_sync.render_plan_md` / `sync_handoff_files_from_state` | `plan_path: str`, `report_path: str \| None`, `files_synced: list[str]`, `created_at: datetime` |
| `MountFolderRecord` | `src/agents/middlewares/mount_folder_middleware.py` | `MountFolderMiddleware` | `mount_id: str`, `host_path: str`, `virtual_path: str`, `created_at: datetime`, `released: bool = False` |
| `UploadsManifest` | `src/agents/middlewares/uploads_middleware.py` | `UploadsMiddleware` | `files: list[UploadedFile]`, `injected_at: datetime` |
| `UploadedFile` | same | same | `filename: str`, `virtual_path: str`, `mime_type: str`, `size_bytes: int (ge=0)`, `converted_from: str \| None = None` |
| `WebSearchCircuitBreakerState` | `src/agents/middlewares/web_search_circuit_breaker_middleware.py` | same | `consecutive_failures: int (ge=0)`, `tripped: bool`, `last_failure_at: datetime \| None`, `cool_down_until: datetime \| None` |

---

## 7.3 Channels — `src/channels/`

The channels package currently uses three `@dataclass` records and a `StrEnum`. Channels are **persisted** (the inbound message → CapyHome thread mapping is on disk) and **replayed** (a restarted Slack channel re-emits unprocessed inbound messages), so structural validation is essential.

### 7.3.1 PROPOSED migrations

Source file: [src/channels/message_bus.py](../../backend/src/channels/message_bus.py)

| Target `BaseModel` | Replaces (`@dataclass`) | Line | Required fields | Notes |
|--------------------|-------------------------|-----:|-----------------|-------|
| `InboundMessage` | `InboundMessage` | 29 | `channel_name: Literal["slack","telegram"]`, `chat_id: str`, `user_id: str`, `text: str`, `msg_type: InboundMessageType = InboundMessageType.CHAT`, `thread_ts: str \| None = None`, `topic_id: str \| None = None`, `files: list[InboundFileAttachment] = []` (NEW typed sub-model), `metadata: dict[str, Any] = {}`, `created_at: datetime = Field(default_factory=utcnow)` | `frozen=True`. Replace `time.time()` → `datetime` for cross-channel consistency. |
| `ResolvedAttachment` | `ResolvedAttachment` | 61 | `virtual_path: str`, `actual_path: Path`, `filename: str`, `mime_type: str`, `size: int (ge=0)`, `is_image: bool` | `arbitrary_types_allowed=True` for `Path`. Could replace with `str` for JSON round-trip. |
| `OutboundMessage` | `OutboundMessage` | 82 | `channel_name`, `chat_id`, `thread_id`, `text`, `artifacts: list[str] = []`, `attachments: list[ResolvedAttachment] = []`, `is_final: bool = True`, `thread_ts: str \| None = None`, `metadata: dict[str, Any] = {}`, `created_at: datetime` | `frozen=True`. |
| `InboundMessageType` | `StrEnum` | 22 | Keep as `StrEnum` — Pydantic accepts `StrEnum` field types directly. | No migration. |

### 7.3.2 PROPOSED — NEW channel models

| New `BaseModel` | Target file | Fields | Notes |
|-----------------|-------------|--------|-------|
| `InboundFileAttachment` | [src/channels/message_bus.py](../../backend/src/channels/message_bus.py) | `kind: Literal["url","blob","platform_ref"]`, `url: str \| None = None`, `filename: str`, `mime_type: str`, `size: int \| None = None`, `platform_metadata: dict[str, Any] = {}` | Replaces `files: list[dict[str, Any]]` on `InboundMessage`. |
| `ChannelThreadMapRecord` | [src/channels/store.py](../../backend/src/channels/store.py) | `key: str` (`channel:chat` or `channel:chat:topic`), `channel_name: str`, `chat_id: str`, `topic_id: str \| None`, `thread_id: str`, `created_at: datetime`, `last_seen_at: datetime` | Persisted in `backend/.capyhome/channels/{name}/store.json`. Today is a raw `dict[str,str]`. |
| `ChannelRuntimeStatus` | [src/channels/manager.py](../../backend/src/channels/manager.py) | `channel_name: str`, `status: Literal["starting","running","stopping","stopped","errored"]`, `last_inbound_at: datetime \| None`, `last_outbound_at: datetime \| None`, `error: str \| None = None`, `queue_size: int (ge=0) = 0` | Powers `/api/channels/status` (currently returns ad-hoc dict). |
| `ChannelCommandRequest` | [src/channels/manager.py](../../backend/src/channels/manager.py) | `command: Literal["new","status","models","memory","help"]`, `args: list[str] = []`, `user_id: str`, `chat_id: str` | Replaces ad-hoc parsing in `_dispatch_loop`. |
| `ChannelCommandResponse` | same | `command: str`, `text: str`, `artifacts: list[str] = []` | |

### 7.3.3 Channel service config — keep / extend

The per-channel config (`channels.slack.bot_token`, etc.) is currently a `dict` inside `AppConfig` (via `extra="allow"`). It should be promoted to:

| New `BaseModel` | Target file | Fields |
|-----------------|-------------|--------|
| `ChannelsConfig` | `src/config/channels_config.py` (NEW FILE) | `enabled: bool = False`, `langgraph_url: str = "http://localhost:2024"`, `gateway_url: str = "http://localhost:8001"`, `slack: SlackChannelConfig \| None = None`, `telegram: TelegramChannelConfig \| None = None` |
| `SlackChannelConfig` | same | `enabled: bool = True`, `bot_token: str`, `app_token: str`, `default_channel: str \| None = None` |
| `TelegramChannelConfig` | same | `enabled: bool = True`, `bot_token: str`, `polling_interval_seconds: int (ge=1) = 1` |

Then add `channels: ChannelsConfig = Field(default_factory=ChannelsConfig)` to `AppConfig`.

---

## 7.4 Audit findings — actionable

| # | Finding | Suggested fix |
|---|---------|---------------|
| MW-1 | `PlannerOutput` is constructed by manual JSON parsing in `planner_middleware._parse_planner_output`. | Use `model = model.with_structured_output(PlannerOutput)` once `PlannerOutput` is a `BaseModel` — eliminates the entire `_normalize_*` helper cluster. |
| MW-2 | `_RegistryContext` is currently a private `@dataclass`. | Promote to public `RegistryContext` and document the contract — middleware factories receive this as their sole input. |
| MW-3 | Multiple middlewares emit `runtime_events` with free-form `kind` strings — see RE-1 in §06. | Single `Literal` enum sourced from one file. |
| MW-4 | `ConversationContext` uses `datetime.utcnow()` (deprecated). | Switch to `datetime.now(UTC)`. |
| CH-1 | Channels mix `float` (`time.time()`) and `datetime` for timestamps. | Standardize on `datetime` (UTC-aware). |
| CH-2 | `OutboundMessage.attachments: list[ResolvedAttachment]` contains `Path` — un-serializable to JSON. | Add a `model_serializer` that emits `actual_path: str`. |
| CH-3 | `ChannelThreadMapRecord` on disk is a flat `{key: thread_id}` dict — no created_at, no audit. | Promote storage to typed records (allows GC and audit). |
| CH-4 | Slack and Telegram channels each have their own ad-hoc inbound/outbound parsing. | Centralize via `InboundMessage.model_validate(channel_dict)` once these are `BaseModel`. |
