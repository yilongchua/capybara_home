# 03 — Control Plane & Generation BaseModels

Scope: `src/control_plane/` + `src/control_plane/agents/` + `src/control_plane/autoresearch_loop/` + `src/generation/`.

The control plane is the **most-mature pydantic surface** in the backend. The autoresearch sub-package still uses `@dataclass` / `TypedDict` in several places — those are flagged for migration.

---

## 3.1 Existing BaseModels — domain core

| Model | File | Line | Persistence | Notes |
|-------|------|-----:|-------------|-------|
| `IntegrationSecretRef` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 18 | snapshot | `name`, `env_var`, `required`, `description`. |
| `CustomRedactionPattern` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 26 | snapshot | `name`, `pattern`, `replacement`. |
| `CSVProfile` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 33 | snapshot | `id`, `description`, `focus`, `row_limit`, `select_columns`, `redact_columns`, `sample_rows`, `summary_instructions`. |
| `FolderSyncTarget` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 45 | snapshot | `id`, `path`, `recursive`, `file_globs[]`, `enabled`. |
| `PipelineStepDefinition` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 54 | snapshot | `id`, `name`, `kind` (15-value Literal), `stop_on_error`, `config`. |
| `PipelineTemplate` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 80 | snapshot | `id`, `name`, `description`, `enabled`, `requires_approval`, `trigger_sources[]`, `default_inputs`, `steps[]`, `created_at`, `updated_at`. |
| `PipelineStepRun` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 94 | snapshot | `id`, `step_id`, `name`, `kind`, `status`, `logs[]`, `output`, `error`, `started_at`, `finished_at`. |
| `ApprovalRequest` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 108 | snapshot | `id`, `pipeline_run_id`, `title`, `description`, `options[]`, `status`, timestamps, `resolution_note`, `requested_by`, `metadata`. |
| `PipelineRun` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 123 | snapshot | `id`, `template_id`, `template_name`, `trigger_event_id`, `status` (8-value Literal), `summary`, `requires_approval`, `approval_request_id`, `inputs`, `masked_inputs`, `steps[]`, `alerts[]`, `artifacts[]`, `metadata`, timestamps. |
| `TriggerEvent` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 154 | snapshot | `id`, `source`, `channel_name`, `chat_id`, `user_id`, `classification`, `status`, `message`, `masked_message`, `pipeline_template_id`, `pipeline_run_id`, `metadata`, timestamps. |
| `FeedbackEvent` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 172 | snapshot | `id`, `target_type`, `target_id`, `value` (`up`/`down`), `comment`, `source`, `metadata`, `created_at`. |
| `AuditEvent` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 184 | snapshot | `id`, `kind`, `message`, `metadata`, `created_at`. |
| `SchedulerJob` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 193 | snapshot | `id`, `name`, `pipeline_template_id`, `interval_seconds`, `schedule_type` (`interval`/`daily_time`), `daily_time`, `enabled`, `inputs`, `requires_approval`. |
| `SchedulerJobState` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 206 | snapshot | `id`, `last_run_at`, `next_run_at`, `last_status`, `last_run_id`. |
| `ProposalReview` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 215 | snapshot | Self-improver proposal review state. |
| `AutoresearchObjective` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 227 | snapshot | Full objective record (id, topic, endpoint_goal, status, scheduler job id, iteration counter, novelty rate, reflection, cluster coverage, ledger paths). |
| `ControlPlaneSnapshot` | [src/control_plane/models.py](../../backend/src/control_plane/models.py) | 251 | snapshot root | Top-level JSON document for `backend/.capyhome/control-plane/`. |

---

## 3.2 Existing BaseModels — agents & vault learning

| Model | File | Line | Notes |
|-------|------|-----:|-------|
| `AgentExecutionReport` | [src/control_plane/agents/schemas.py](../../backend/src/control_plane/agents/schemas.py) | 20 | Step-level execution envelope returned by every control-plane agent (`Improver`, `KnowledgeVault`, `Redaction`, `Autoresearch`). |
| `KnowledgeVaultExecutionProfile` | [src/control_plane/agents/schemas.py](../../backend/src/control_plane/agents/schemas.py) | 52 | `mode`, `source`, `topic_input_key`, `stop_if_inactive`, `activity_window_hours`. |
| `VaultLoopGuardConfig` | [src/control_plane/vault_learning.py](../../backend/src/control_plane/vault_learning.py) | 84 | Vault loop guardrails. |
| `VaultManifest` | [src/control_plane/vault_learning.py](../../backend/src/control_plane/vault_learning.py) | 90 | On-disk vault manifest. |

---

## 3.3 Generation domain

| Model | File | Line | Notes |
|-------|------|-----:|-------|
| `GenerationJob` | [src/generation/models.py](../../backend/src/generation/models.py) | 22 | `id`, `thread_id`, `kind`, `status`, `prompt_id`, `filename_prefix`, `expected_virtual_path`, `output_virtual_path`, `source_output_path`, `prompt_excerpt`, `output_name`, `aspect_ratio`, `error`, `completion_seq`, timestamps. |
| `GenerationSnapshot` | [src/generation/models.py](../../backend/src/generation/models.py) | 43 | `jobs: dict[str, GenerationJob]`, `next_completion_seq`. |

---

## 3.4 PROPOSED migrations — autoresearch loop & helper dataclasses

These currently exist as `@dataclass` / `TypedDict` and SHOULD become `BaseModel` because they cross persistence (vault on-disk ledger) and JSON wire boundaries (frontend renders the question DAG).

### 3.4.1 Convert to BaseModel

| Target `BaseModel` | Replaces | Source File | Line | Required fields | Rationale |
|--------------------|----------|-------------|-----:|-----------------|-----------|
| `QuestionNode` | `TypedDict` `QuestionNode` | [src/control_plane/autoresearch_loop/ledger.py](../../backend/src/control_plane/autoresearch_loop/ledger.py) | 31 | `id`, `content`, `status: QuestionStatus`, `depends_on[]`, `cluster`, `level`, `asked_by: Literal["generator","reflector","user"]`, `novelty: float (ge=0,le=1)`, `loop_iteration`, `vault_entries[]`, `duplicate_of`, `researcher_summary`, `sources_used`, `error`, `created_at`, `updated_at` | Persisted to disk as `ledger.json`; mirrored to `ledger.md`. Frontend renders the DAG; needs validation to avoid orphan `depends_on` edges. |
| `AutoresearchQuestionGenResult` | (no current type, free-form `dict`) | [src/control_plane/autoresearch_loop/generator.py](../../backend/src/control_plane/autoresearch_loop/generator.py) | — | `objective_id`, `iteration`, `proposed[]: list[QuestionNode]`, `cluster_coverage`, `model_used`, `latency_ms` | Wraps the LLM call output so the loop driver doesn't pass raw dicts. |
| `AutoresearchReflectionResult` | (no current type) | [src/control_plane/autoresearch_loop/reflector.py](../../backend/src/control_plane/autoresearch_loop/reflector.py) | — | `objective_id`, `iteration`, `followups[]: list[QuestionNode]`, `summary`, `signals: dict[str, Any]` | Mirror of `AutoresearchQuestionGenResult` for the reflector LLM call. |
| `DeduplicationDecision` | `@dataclass` (line 40, unnamed in current grep) | [src/control_plane/autoresearch_loop/dedup.py](../../backend/src/control_plane/autoresearch_loop/dedup.py) | 40 | `candidate_id`, `is_duplicate: bool`, `matched_against_id`, `score: float`, `source: Literal["ledger","vault"]` | Currently a `@dataclass`; wire-format needs validation when reflector/researcher consume it. |
| `ResearcherDispatch` | `@dataclass` | [src/control_plane/autoresearch_loop/researcher.py](../../backend/src/control_plane/autoresearch_loop/researcher.py) | 24 | `question_id`, `subagent_type` (Literal), `prompt`, `tool_budget`, `target_endpoint`, `dispatched_at` | Used to push a question into the subagent executor; also surfaces in audit logs. |
| `TaxonomyCluster` | `@dataclass(frozen=True)` | [src/control_plane/autoresearch_loop/taxonomy.py](../../backend/src/control_plane/autoresearch_loop/taxonomy.py) | 18 | `id: int`, `slug: str`, `title: str`, `description: str`, `example_questions[]` | Loaded from `{vault_root}/00_schema/QUESTION_TAXONOMY.json`; should validate the JSON. |
| `AgentExecutionContext` | `@dataclass(frozen=True, slots=True)` | [src/control_plane/agents/schemas.py](../../backend/src/control_plane/agents/schemas.py) | 12 | `run_id`, `run: PipelineRun`, `step: PipelineStepRun`, `definition: PipelineStepDefinition` | Pure DTO passed between control-plane services; converting unifies serialization for audit logging. |
| `AgentExecutionResult` | `@dataclass(frozen=True, slots=True)` | [src/control_plane/agents/schemas.py](../../backend/src/control_plane/agents/schemas.py) | 40 | `output: dict[str, Any]`, `report: AgentExecutionReport` | Same rationale as above; also enables FastAPI return-type binding for `/api/pipelines/runs/{id}/step/{step_id}`. |
| `UnifiedVaultSearchHit` | `@dataclass(slots=True)` | [src/control_plane/services/unified_vault_search.py](../../backend/src/control_plane/services/unified_vault_search.py) | 67 | `kind: Literal["page","entity","concept"]`, `id`, `title`, `score`, `path`, `excerpt`, `metadata` | Returned to the gateway `/api/vault/search` endpoint — must validate scores to `[0,1]`. |

### 3.4.2 Keep as `@dataclass`

| Class | File | Line | Why keep |
|-------|------|-----:|----------|
| `AgentExecutionError(RuntimeError)` | [src/control_plane/agents/schemas.py](../../backend/src/control_plane/agents/schemas.py) | 46 | It's an `Exception` subclass, not a data record. Carries an `AgentExecutionReport` attribute. |

---

## 3.5 Audit findings — actionable

| # | Finding | Suggested fix |
|---|---------|---------------|
| CP-1 | `PipelineRun.status` is a `Literal` with 8 values; same set appears in `PipelineRunStatus` callers as a free string. | Promote to `enum.StrEnum` `PipelineRunStatus` in `src/control_plane/models.py` and reference everywhere. |
| CP-2 | `TriggerEvent.classification: str = "chat"` is unconstrained. | Promote to `Literal["chat","command","webhook"]`. |
| CP-3 | `ControlPlaneSnapshot` has 10 top-level mutable maps. | Add a `version: int` discriminator so future migrations can branch on schema version. |
| CP-4 | `AutoresearchObjective.cluster_coverage` is `dict[str, int]`. | Type the key with `TaxonomyCluster.slug` once the taxonomy model lands (CP-5 dependency). |
| CP-5 | `KnowledgeVaultExecutionProfile.mode: Literal["continuous","autoresearch"]` — but tests refer to `"discover"` mode. | Confirm full set; align with `PipelineStepDefinition.kind` taxonomy. |
| CP-6 | `AgentExecutionReport.details: dict[str, Any]` is the catch-all. | Introduce typed sub-models per step kind (e.g. `RedactionStepDetails`, `VaultIngestStepDetails`). |
