# 06 — Runtime Event BaseModels

Scope: every value that crosses the **SSE wire** to the frontend, or that the agent emits via `get_stream_writer()`. These are user-visible payloads and any drift causes a UI breakage — they must be `BaseModel` with `extra="forbid", frozen=True` (per [01-conventions-and-standards.md §1](01-conventions-and-standards.md#1-model_config--the-only-knob-that-varies-by-purpose)).

Affected modules:

* [src/agents/activity_timeline.py](../../backend/src/agents/activity_timeline.py)
* [src/agents/execution_trace.py](../../backend/src/agents/execution_trace.py)
* [src/agents/steering_queue_store.py](../../backend/src/agents/steering_queue_store.py)
* [src/agents/middlewares/runtime_events.py](../../backend/src/agents/middlewares/runtime_events.py)
* [src/agents/middlewares/dreamy_intent_middleware.py](../../backend/src/agents/middlewares/dreamy_intent_middleware.py)
* [src/agents/middlewares/steering_middleware.py](../../backend/src/agents/middlewares/steering_middleware.py)
* [src/agents/middlewares/todo_dag_middleware.py](../../backend/src/agents/middlewares/todo_dag_middleware.py)
* [src/agents/middlewares/dreamy_bootstrap_middleware.py](../../backend/src/agents/middlewares/dreamy_bootstrap_middleware.py)
* [src/agents/thinking_stream.py](../../backend/src/agents/thinking_stream.py)
* [src/control_plane/autoresearch_loop/ledger.py](../../backend/src/control_plane/autoresearch_loop/ledger.py)

---

## 6.1 PROPOSED — Activity Timeline

Source file: [src/agents/activity_timeline.py](../../backend/src/agents/activity_timeline.py)

| Target `BaseModel` | Replaces (TypedDict) | Line | Required fields | Notes |
|--------------------|----------------------|-----:|-----------------|-------|
| `ActivityEvent` | `ActivityEvent` | 24 | `id: str`, `schema: Literal["v1"]`, `run_id: str`, `seq: int (ge=1)`, `timestamp: float (ge=0)`, `actor: Literal["capyhome","baby_capy","system"]`, `kind: str`, `line: str`, `task_id: str \| None = None`, `group_id: str \| None = None`, `group_kind: str \| None = None`, `group_title: str \| None = None`, `group_role: str \| None = None`, `subagent_type: str \| None = None`, `description: str \| None = None`, `tool_summary: str \| None = None`, `assistant_message_id: str \| None = None`, `payload: dict[str, Any] = {}` | **Wire format**: `extra="forbid", frozen=True`. `timestamp` stays `float` for SSE compatibility (frontend parses milliseconds). `payload` should ideally be a discriminated union (see §6.5). |
| `ActivityTimelineState` | `ActivityTimelineState` | 45 | `version: Literal["v1"] = "v1"`, `events: list[ActivityEvent] = []` (bounded by `ACTIVITY_MAX_EVENTS_RETAINED = 1200`) | Persisted in `ThreadState`. |
| `ContextMetricsState` | `ContextMetricsState` | 50 | `token_count: int (ge=0)`, `message_count: int (ge=0)`, `context_updated_at: float (ge=0)`, `compaction_count: int (ge=0)`, `last_compaction_at: float (ge=0)`, `messages_compressed: int (ge=0)`, `messages_kept: int (ge=0)` | Persisted; reducer `merge_context_metrics` already exists. |

---

## 6.2 PROPOSED — Execution Trace

Source file: [src/agents/execution_trace.py](../../backend/src/agents/execution_trace.py)

| Target `BaseModel` | Replaces (TypedDict) | Line | Required fields | Notes |
|--------------------|----------------------|-----:|-----------------|-------|
| `TraceThinking` | `TraceThinking` | 26 | `source: Literal["raw","summary"]`, `content: str` | Wire format. |
| `TraceTokenUsage` | `TraceTokenUsage` | 31 | `input_tokens: int = 0`, `output_tokens: int = 0`, `total_tokens: int = 0` | Bounds `ge=0`. |
| `ExecutionTraceEvent` | `ExecutionTraceEvent` | 37 | `id: str`, `schema: Literal["v1"]`, `run_id: str`, `turn_id: str \| None`, `stage: Literal["lead","planner","evaluator","subagent","harness"]`, `event_type: str`, `timestamp: float`, `seq: int (ge=1)`, `status: str`, `payload: dict[str, Any] = {}`, `token_usage: TraceTokenUsage = TraceTokenUsage()`, `thinking: TraceThinking \| None = None`, `assistant_message_id: str \| None = None`, `task_id: str \| None = None`, `payload_truncated: bool = False`, `payload_original_chars: int (ge=0) = 0` | **Wire format**. |
| `ExecutionTraceRun` | `ExecutionTraceRun` | 56 | `run_id: str`, `started_at: float`, `updated_at: float`, `events: list[ExecutionTraceEvent] = []` (bounded by `TRACE_MAX_EVENTS_PER_RUN = 320`) | Persisted. |
| `ExecutionTraceState` | `ExecutionTraceState` | 63 | `version: Literal["v1"] = "v1"`, `runs: dict[str, ExecutionTraceRun] = {}` (bounded by `TRACE_MAX_RUNS_RETAINED = 24`) | Persisted. |

---

## 6.3 PROPOSED — Steering queue

Source file: [src/agents/steering_queue_store.py](../../backend/src/agents/steering_queue_store.py)

| Target `BaseModel` | Replaces (TypedDict) | Line | Required fields | Notes |
|--------------------|----------------------|-----:|-----------------|-------|
| `SteeringQueuedIntent` | `SteeringQueuedIntent` | 19 | `intent_id: str`, `message: str` (min_length=1), `created_at: datetime` | Persisted in sqlite; ISO-string in DB column. |
| `SteeringEnqueueResult` | `SteeringEnqueueResult` | 25 | `status: Literal["accepted","duplicate","conflict"]`, `intent: SteeringQueuedIntent` | Wire format (returned from gateway). |

---

## 6.4 PROPOSED — Middleware-local event TypedDicts

| Target `BaseModel` | Replaces | File | Line | Required fields |
|--------------------|----------|------|-----:|-----------------|
| `DreamyIntent` | TypedDict `DreamyIntent` | [src/agents/middlewares/dreamy_intent_middleware.py](../../backend/src/agents/middlewares/dreamy_intent_middleware.py) | 13 | `shape: str`, `intent_class: Literal[...]`, `confidence: float (ge=0, le=1)`, `extracted_fields: list[str]`, `inferred_goal: str`, `workflow_requested: bool` (mirrors `DreamyIntentState`). |
| `SteeringIntent` | TypedDict `SteeringIntent` | [src/agents/middlewares/steering_middleware.py](../../backend/src/agents/middlewares/steering_middleware.py) | 17 | `intent_id: str`, `message: str`, `created_at: datetime`, `consumed: bool = False`. |
| `TodoNodeInput` (middleware copy) | TypedDict `TodoNodeInput` | [src/agents/middlewares/todo_dag_middleware.py](../../backend/src/agents/middlewares/todo_dag_middleware.py) | 21 | Same as `TodoGraphItem` minus runtime fields — single source of truth in §5. |
| `TodoNodeInput` (tool copy) | TypedDict `TodoNodeInput` | [src/tools/builtins/write_todos_tool.py](../../backend/src/tools/builtins/write_todos_tool.py) | 18 | DUPLICATE of above — collapse to one shared model. |
| `_TodoToolState` | TypedDict `_TodoToolState` | [src/tools/builtins/write_todos_tool.py](../../backend/src/tools/builtins/write_todos_tool.py) | 29 | Slice of `ThreadState` used by the tool — replace by importing the actual state types. |
| `_DetectedData` | TypedDict `_DetectedData` | [src/agents/middlewares/dreamy_bootstrap_middleware.py](../../backend/src/agents/middlewares/dreamy_bootstrap_middleware.py) | 30 | `kind: Literal["repo","csv","markdown","notebook","other"]`, `confidence: float`, `signals: list[str]`. Currently private (`_`) — promote to `DetectedWorkspaceShape`. |

---

## 6.5 PROPOSED — Discriminated event union for SSE stream

The agent stream emits multiple event types over a single `text/event-stream` channel. Today, frontend has hand-coded TypeScript guards. Proposed Pydantic discriminated union:

```python
# src/agents/events.py (NEW FILE)

class _BaseStreamEvent(CapyEvent):
    event: str
    timestamp: float

class ActivityStreamEvent(_BaseStreamEvent):
    event: Literal["activity_event.v1"] = "activity_event.v1"
    data: ActivityEvent

class TraceStreamEvent(_BaseStreamEvent):
    event: Literal["trace_event.v1"] = "trace_event.v1"
    data: ExecutionTraceEvent

class TaskLifecycleStreamEvent(_BaseStreamEvent):
    event: Literal["task_started","task_running","task_completed","task_failed","task_timed_out"]
    data: TaskLifecyclePayload   # NEW — see §6.6

class ThinkingStreamEvent(_BaseStreamEvent):
    event: Literal["thinking.delta","thinking.flush"]
    data: ThinkingPayload  # NEW

class RuntimeStreamEvent(_BaseStreamEvent):
    event: Literal["runtime_event"]
    data: RuntimeEventPayload   # NEW

StreamEvent = Annotated[
    ActivityStreamEvent | TraceStreamEvent | TaskLifecycleStreamEvent | ThinkingStreamEvent | RuntimeStreamEvent,
    Field(discriminator="event"),
]
```

This gives the frontend (via `/openapi.json`) a complete grammar of the wire.

---

## 6.6 PROPOSED — Per-event payloads (new BaseModels)

| New `BaseModel` | Target file | Used by | Fields |
|-----------------|-------------|---------|--------|
| `TaskLifecyclePayload` | `src/agents/events.py` | `SubagentExecutor` (in [src/subagents/executor.py](../../backend/src/subagents/executor.py)) | `task_id: str`, `subagent_type: str`, `description: str`, `status: Literal["started","running","completed","failed","timed_out"]`, `started_at: datetime`, `completed_at: datetime \| None`, `error: str \| None`, `result_excerpt: str \| None`, `group_id: str \| None`, `group_title: str \| None` |
| `ThinkingPayload` | `src/agents/events.py` | [src/agents/thinking_stream.py](../../backend/src/agents/thinking_stream.py) | `kind: Literal["delta","flush"]`, `content: str`, `source: Literal["raw","summary"]`, `assistant_message_id: str \| None` |
| `RuntimeEventPayload` | `src/agents/events.py` | [src/agents/middlewares/runtime_events.py](../../backend/src/agents/middlewares/runtime_events.py) | `kind: str` (closed set, see audit RE-1), `seq: int (ge=1)`, `message: str`, `data: dict[str, Any] = {}` |
| `SkillDisclosureEventPayload` | `src/agents/events.py` | [src/agents/middlewares/skill_disclosure_middleware.py](../../backend/src/agents/middlewares/skill_disclosure_middleware.py) | `kind: Literal["activated","deactivated"]`, `skill_name: str`, `turn: int (ge=0)` |
| `CompactionEventPayload` | `src/agents/events.py` | [src/agents/middlewares/summarization_middleware.py](../../backend/src/agents/middlewares/summarization_middleware.py) | `messages_compressed: int (ge=0)`, `messages_kept: int (ge=0)`, `before_tokens: int (ge=0)`, `after_tokens: int (ge=0)`, `summary_excerpt: str` |
| `MemoryUpdateEventPayload` | `src/agents/events.py` | [src/agents/memory/updater.py](../../backend/src/agents/memory/updater.py) | `facts_added: int (ge=0)`, `facts_removed: int (ge=0)`, `version_id: str` |
| `TitleSetEventPayload` | `src/agents/events.py` | [src/agents/middlewares/title_middleware.py](../../backend/src/agents/middlewares/title_middleware.py) | `title: str` (max_length=200) |
| `QualityGateEventPayload` | `src/agents/events.py` | [src/agents/middlewares/evaluator_middleware.py](../../backend/src/agents/middlewares/evaluator_middleware.py) | `status: Literal["passed","failed","skipped"]`, `fail_reasons: list[str]`, `checked_path: str` |

---

## 6.7 PROPOSED — Autoresearch ledger event

| Target `BaseModel` | Replaces | File | Line | Notes |
|--------------------|----------|------|-----:|-------|
| `QuestionNode` | TypedDict `QuestionNode` | [src/control_plane/autoresearch_loop/ledger.py](../../backend/src/control_plane/autoresearch_loop/ledger.py) | 31 | Already detailed in [03-control-plane-basemodels.md §3.4.1](03-control-plane-basemodels.md). Listed here too because the **vault-source-researcher** subagent emits it as an SSE event. |

---

## 6.8 Audit findings — actionable

| # | Finding | Suggested fix |
|---|---------|---------------|
| RE-1 | `runtime_events.append_runtime_event` accepts an arbitrary `kind: str`. | Enumerate the closed set seen across middlewares: `plan_drafted`, `plan_approved`, `clarification_pending`, `clarification_answered`, `todo_graph_updated`, `phase_started`, `phase_completed`, `subagent_dispatched`, `subagent_completed`, `memory_updated`, `compaction_complete`, `title_set`, `quality_gate_pass`, `quality_gate_fail`, … → promote to `Literal`. |
| RE-2 | `ActivityEvent.timestamp` is `float` (epoch seconds); `ExecutionTraceEvent.timestamp` is also `float`. Channels/Control Plane use `datetime`. | Document this divergence in `01-conventions-and-standards.md` and stick with `float` here for backwards-compat. |
| RE-3 | `ExecutionTraceEvent.payload_original_chars` is only set when `payload_truncated=True`. | Add a `model_validator` enforcing the implication `payload_truncated ⇒ payload_original_chars > 0`. |
| RE-4 | `SteeringQueuedIntent.created_at` is stored as ISO string in SQLite. | Use a `Field(..., json_schema_extra={"format":"date-time"})` and a custom serializer to preserve the ISO format. |
| RE-5 | Two copies of `TodoNodeInput` (middleware + tool). | Single canonical definition in `src/agents/state_models.py`, imported in both sites. |
