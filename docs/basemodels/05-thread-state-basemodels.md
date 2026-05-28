# 05 — Thread-State BaseModels (`src/agents/thread_state.py`)

This is **the highest-leverage migration target** in the entire backend. `ThreadState` is the persisted LangGraph state passed between every middleware and to the agent model on every turn. Today it is composed of **22 TypedDicts** with `total=False`, which means:

* No required-field validation — middlewares silently read `None` when they expect a structured payload.
* No JSON-schema export — frontend has to hand-maintain TypeScript mirrors.
* No `model_validator` — invariants like "if `awaiting_execution_approval=True` then `clarification_pending=False`" are checked ad-hoc.
* No defaults — every middleware reaches into the dict with `state.get("plan", {}) or {}`.

> ⚠️ **Caveat**: `class ThreadState(AgentState)` itself MUST remain a `TypedDict` because LangGraph's `Annotated[..., reducer]` machinery only accepts `TypedDict` field types. The migration target is the **nested** TypedDicts that appear as the *types of* those fields. They can be `BaseModel` subclasses; LangGraph stores them as `dict` after `.model_dump()` and reads them back via `.model_validate(state["plan"])`.
>
> Concretely: the `ThreadState` TypedDict stays, but every line `plan: NotRequired[PlanState | None]` changes to `plan: NotRequired[PlanState | None]` where `PlanState` is now a `BaseModel`. Reducers may need a thin `model_validate(dict_or_model)` wrapper.

---

## 5.1 PROPOSED — TypedDict → BaseModel migrations

All targets live in [src/agents/thread_state.py](../../backend/src/agents/thread_state.py).

| Target `BaseModel` | Replaces (current `TypedDict`) | File | Line | Fields to enforce | Validators / Invariants |
|--------------------|--------------------------------|------|-----:|-------------------|-------------------------|
| `SandboxState` | `class SandboxState(TypedDict)` | thread_state.py | 14 | `sandbox_id: str \| None = None` | None. |
| `ThreadDataState` | `ThreadDataState` | thread_state.py | 18 | `workspace_path`, `uploads_path`, `outputs_path`, `mounted_path`, `mounted_prompt_injected_path` — all `str \| None = None` | `model_validator`: if any of `*_path` are set they must be absolute. |
| `ViewedImageData` | `ViewedImageData` | thread_state.py | 26 | `base64: str` (non-empty), `mime_type: Literal["image/png","image/jpeg","image/gif","image/webp"]` | `Field(min_length=1)` on `base64`. |
| `TrajectoryRuntimeState` | `TrajectoryRuntimeState` | thread_state.py | 40 | `run_id: str`, `file_path: str` | Non-empty + path validator. |
| `SkillDisclosureState` | `SkillDisclosureState` | thread_state.py | 45 | `active: dict[str, int] = {}`, `last_injected_hash: str = ""`, `turn: int = 0` (ge=0) | Hash sha256 hex regex. |
| `PlanState` | `PlanState` (36 fields, `total=False`) | thread_state.py | 51 | (see §5.2 detailed schema below) | Cross-field validators detailed in §5.2. |
| `PlanHistoryItem` | `PlanHistoryItem` | thread_state.py | 88 | `plan_id`, `title`, `path`, `created_at: datetime`, `status: Literal["draft","approved","executing","completed","cancelled"]` | `created_at` must be `datetime` not `str`. |
| `TodoGraphItem` | `TodoGraphItem` | thread_state.py | 96 | `id: str`, `content: str`, `status: Literal["pending","in_progress","completed","blocked"]`, `depends_on: list[str]`, `owner: Literal["lead","subagent"]`, `subagent_type: str \| None`, `target_endpoint: Literal["primary","helper"] \| None`, `tool_budget: int \| None (ge=1)` | `id` matches `^[a-z0-9-]{1,48}$`. |
| `TodoGraphState` | `TodoGraphState` | thread_state.py | 107 | `nodes: list[TodoGraphItem] = []`, `ready_ids: list[str] = []`, `updated_at: datetime \| None = None` | `ready_ids` subset of `{n.id for n in nodes}`; `model_validator` rejects cycles in `depends_on`. |
| `RetryRuntimeState` | `RetryRuntimeState` | thread_state.py | 113 | `last_retry_turn_had_attempts: bool = False`, `attempts_by_tool_call: dict[str, int] = {}` | Counters non-negative. |
| `HandoffArtifactState` | `HandoffArtifactState` | thread_state.py | 118 | `plan_path: str \| None = None`, `report_path: str \| None = None` | Paths absolute when set. |
| `HooksRuntimeState` | `HooksRuntimeState` | thread_state.py | 123 | `observed_files: list[str] = []` | None. |
| `ResumeMetaState` | `ResumeMetaState` | thread_state.py | 127 | 8 fields — `last_checkpoint_id`, `last_completed_todo_id`, `pending_ready_ids[]`, `deferred_task_calls_count: int (ge=0)`, `handoff_refs[]`, `in_progress_todo_ids[]`, `retry_counts: dict[str,int]`, `running_subagent_ids[]` | Counters non-negative. |
| `ScratchpadEntry` | `ScratchpadEntry` | thread_state.py | 140 | `ts: datetime`, `source: Literal["lead","subagent","middleware","handoff"]`, `text: str` (min_length=1) | Source is closed-set. |
| `TaskMemoryFact` | `TaskMemoryFact` | thread_state.py | 146 | `ts: datetime`, `fact: str` (min_length=1) | Fact is non-empty. |
| `MemoryVersionRefState` | `MemoryVersionRefState` | thread_state.py | 151 | `version_id: str`, `sha: str` (regex `^[0-9a-f]{40,64}$`), `storage_path: str` | Hash regex. |
| `DreamyIntentState` | `DreamyIntentState` | thread_state.py | 157 | `shape: str`, `intent_class: Literal[...]`, `confidence: float (ge=0,le=1)`, `extracted_fields: list[str]`, `inferred_goal: str`, `workflow_requested: bool` | Confidence bounds; closed `intent_class` set. |
| `BackgroundFollowupJob` | `BackgroundFollowupJob` | thread_state.py | 166 | `id: str`, `status: Literal["queued","running","completed","failed"]`, `kind: str`, `summary: str`, `created_at: datetime`, `completed_at: datetime \| None`, `error: str \| None` | `completed_at` ≥ `created_at`. |
| `ExecutionIntentState` | `ExecutionIntentState` | thread_state.py | 176 | `mode: Literal["plan","work","auto"]`, `plan_behavior: Literal[...]`, `allow_background_deepen: bool`, `max_primary_subagents: int (ge=0)` | Bound the subagent counter to `≤ config.subagents.max_concurrent_limit`. |
| `SteeringIntentState` | `SteeringIntentState` | thread_state.py | 183 | `intent_id: str`, `message: str`, `created_at: datetime` | None. |
| `WorkModeState` | `WorkModeState` | thread_state.py | 189 | `active: bool`, `plan_source: Literal["prior_run","inline_generation","escalated"]`, `current_phase_index: int (ge=0)`, `total_phases: int (ge=0)`, `phases_completed: int (ge=0)` | `current_phase_index ≤ total_phases`, `phases_completed ≤ total_phases`. |
| `PhaseExecutionState` | `PhaseExecutionState` | thread_state.py | 199 | `current_phase: int`, `total_phases: int`, `phase_results: list[PhaseResultRecord]` (NEW), `plan_adapted: bool`, `adaptation_notes: str`, `adaptation_attempts: int (ge=0, le=2)` | `phase_results[*].phase_index < total_phases`. |
| `QualityGateState` | `QualityGateState` | thread_state.py | 214 | `status: Literal["passed","failed","skipped"]`, `fail_reasons: list[str]`, `repair_passes: int (ge=0)`, `checked_path: str` | None. |
| `HandoffMetaState` | `HandoffMetaState` | thread_state.py | 221 | `source_thread_id: str`, `handoff_root_virtual_path: str`, `package_manifest_virtual_path: str \| None`, `created_at: datetime` | Virtual paths must start with `/mnt/`. |

---

## 5.2 Detailed schema for `PlanState`

`PlanState` is currently 36 loose fields in a `total=False` TypedDict (lines 51–86). It should be decomposed into a structured `BaseModel` with sub-models for clarification, evaluator, and approval phases.

| Top-level field | Type | Required | Notes |
|-----------------|------|----------|-------|
| `plan_id` | `str` | yes | UUID-like. |
| `status` | `Literal["draft","awaiting_clarification","awaiting_approval","approved","executing","completed","cancelled"]` | yes | Closed set. |
| `title` | `str` | yes | min_length=1. |
| `summary` | `str` | default="" | |
| `objective` | `str` | default="" | |
| `assumptions` | `list[str]` | default=[] | |
| `constraints` | `list[str]` | default=[] | |
| `risks` | `list[PlanRisk]` | default=[] | NEW sub-model: `{title, severity: Literal["low","med","high"], mitigation: str \| None}` |
| `acceptance_criteria` | `list[str]` | default=[] | |
| `todo_ids` | `list[str]` | default=[] | Must be subset of `TodoGraphState.nodes[*].id` (cross-state validator at runtime). |
| `plan_path` | `str \| None` | default=None | Virtual path. |
| `latest_alias_path` | `str \| None` | default=None | Virtual path. |
| `evaluation` | `PlanEvaluationState` | default=`PlanEvaluationState()` | NEW sub-model — groups `evaluation_status`, `latest_evaluator_report`, `latest_evaluator_verdict`, `evaluator_report_path`. |
| `clarification` | `PlanClarificationState` | default=`PlanClarificationState()` | NEW sub-model — groups 8 clarification fields. |
| `approval` | `PlanApprovalState` | default=`PlanApprovalState()` | NEW sub-model — groups `awaiting_execution_approval`, `approved_at`, `execution_requested_at`, `execution_handoff_*`. |
| `created_at` | `datetime` | yes | |
| `completed_at` | `datetime \| None` | default=None | |

### 5.2.1 NEW sub-models (proposed)

| Sub-model | Fields |
|-----------|--------|
| `PlanRisk` | `title: str`, `severity: Literal["low","med","high"]`, `mitigation: str \| None = None` |
| `PlanEvaluationState` | `status: Literal["pending","in_review","passed","failed"] = "pending"`, `latest_report: str = ""`, `latest_verdict: str = ""`, `report_path: str \| None = None` |
| `PlanClarificationState` | `items: list[PlanClarificationItem] = []`, `index: int = 0`, `answers: list[PlanClarificationAnswer] = []`, `resolved: bool = False`, `pending: bool = False`, `pending_question: str = ""`, `answered_at: datetime \| None = None` |
| `PlanClarificationItem` | `question: str`, `options: list[PlanClarificationOption] = []` |
| `PlanClarificationOption` | `label: str`, `recommended: bool = False`, `description: str \| None = None` |
| `PlanClarificationAnswer` | `index: int`, `value: str`, `at: datetime` |
| `PlanApprovalState` | `awaiting: bool = False`, `approved_at: datetime \| None = None`, `requested_at: datetime \| None = None`, `handoff_started: bool = False`, `handoff_started_at: datetime \| None = None`, `handoff_failed: bool = False`, `handoff_failed_at: datetime \| None = None`, `handoff_error: str \| None = None`, `started_at: datetime \| None = None` |
| `PhaseResultRecord` | `phase_index: int`, `todo_id: str`, `content: str`, `status: Literal["pending","running","completed","failed"]`, `subagent_type: str \| None`, `completed_at: datetime \| None` |

---

## 5.3 Reducer compatibility note

Two reducers exist in [src/agents/thread_state.py](../../backend/src/agents/thread_state.py):

| Reducer | Line | Behaviour | Migration impact |
|---------|------|-----------|------------------|
| `merge_artifacts` | 228 | Dedup string list. | None — operates on `list[str]` regardless of nested types. |
| `merge_viewed_images` | 238 | Dict-merge with `{}` sentinel = clear. | The reducer receives `dict[str, ViewedImageData]`. With `BaseModel` migration, callers must either pass `BaseModel` instances (the reducer code does `new.values()` which works on both) or `.model_dump()` before passing. Recommended: add `_coerce_value(v) -> ViewedImageData = ViewedImageData.model_validate(v)` at the reducer's input. |

Two **proposed new reducers** for `BaseModel` fields:

| Reducer | Field | Behaviour |
|---------|-------|-----------|
| `merge_plan(prev, new) -> PlanState \| None` | `plan` | If `new` is `None`, keep `prev`; if `new.status == "cancelled"`, replace; else deep-merge by field with `new` winning. |
| `merge_phase_execution(prev, new) -> PhaseExecutionState \| None` | `phase_execution` | Append `phase_results` rather than replacing. |

These should be defined in `src/agents/state_reducers.py` (NEW FILE) and re-exported from `thread_state.py`.

---

## 5.4 ThreadState root — the unchanged TypedDict

`ThreadState` (lines 255–299) stays a `TypedDict` extending `AgentState`. The field **types** change to `BaseModel` references. Example diff:

```python
# BEFORE
class ThreadState(AgentState):
    plan: NotRequired[PlanState | None]                  # PlanState is TypedDict
    todo_graph: NotRequired[TodoGraphState | None]       # TypedDict

# AFTER
class ThreadState(AgentState):
    plan: NotRequired[PlanState | None]                  # PlanState is BaseModel
    todo_graph: NotRequired[TodoGraphState | None]       # BaseModel
```

Plus middlewares that currently do:

```python
plan = state.get("plan") or {}
plan["status"] = "approved"
state["plan"] = plan
```

Should switch to:

```python
plan = state.get("plan") or PlanState(plan_id=new_id("plan"), title="", status="draft", created_at=utcnow())
plan = plan.model_copy(update={"status": "approved"})
state["plan"] = plan  # LangGraph serializes via model_dump on checkpoint
```

---

## 5.5 Consumers — blast radius

Each migrated model has many readers. Migration owners must update the following sites. Counts are approximate (from grep `state.get("<field>")`).

| Field | Readers |
|-------|--------:|
| `plan` | ~38 sites (planner middleware, plan_evaluator, plan_execution_gate, plan_file_sync, plan_followup, work_run_handoff, handoff_sync, lead_agent prompt, gateway steering, write_todos_tool, clarification_resolution, clarification_middleware) |
| `todo_graph` | ~24 sites (todo_dag_middleware, todo_middleware, todo_failure_retry, write_todos_tool, work_mode_middleware) |
| `phase_execution` | ~14 sites |
| `work_mode` | ~10 sites |
| `viewed_images` | 6 sites (view_image_middleware, view_image_tool, lead_agent factory) |
| `scratchpad` | 8 sites |
| `task_memory` | 5 sites |
| `dreamy_intent` | 12 sites (dreamy_* middlewares) |
| `trajectory` | 3 sites |
| `resume_meta` | 6 sites |
| `handoff_artifacts` | 5 sites |
| `execution_trace` / `activity_timeline` / `context_metrics` | covered in §06 |

---

## 5.6 Acceptance criteria for this migration

1. Every type referenced by `ThreadState` (excluding `AgentState` itself) is a `BaseModel`.
2. Every middleware that reads/writes a thread-state field uses `model_validate` on read and `model_dump` on write — no raw dict access.
3. `merge_viewed_images`, `merge_artifacts`, and the two new reducers (`merge_plan`, `merge_phase_execution`) live in `src/agents/state_reducers.py` with unit tests.
4. The on-disk checkpoint format (sqlite blob from `extended_sqlite_saver.py`) is byte-compatible — verified by a round-trip test using a saved real checkpoint.
5. Frontend types (`frontend/src/typings/`) are regenerated from the new `/openapi.json` and `ThreadState` snapshot dump.
