from typing import Annotated, NotRequired, TypedDict

from langchain.agents import AgentState

from src.agents.activity_timeline import (
    ActivityTimelineState,
    ContextMetricsState,
    merge_activity_timeline,
    merge_context_metrics,
)
from src.agents.execution_trace import ExecutionTraceState, merge_execution_trace


class SandboxState(TypedDict):
    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]
    mounted_path: NotRequired[str | None]
    mounted_prompt_injected_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    base64: str
    mime_type: str


class ProgressGuardRuntimeState(TypedDict, total=False):
    no_progress_turns: int
    inactivity_turns: int
    repeated_tool_result_turns: int
    last_snapshot_hash: str
    last_tool_result_sig: str
    emitted_signals: list[str]


class TrajectoryRuntimeState(TypedDict, total=False):
    run_id: str
    file_path: str


class SkillDisclosureState(TypedDict, total=False):
    active: dict[str, int]
    last_injected_hash: str
    turn: int


class PlanState(TypedDict, total=False):
    plan_id: str
    status: str
    title: str
    summary: str
    objective: str
    assumptions: list[str]
    constraints: list[str]
    risks: list[dict[str, str]]
    acceptance_criteria: list[str]
    todo_ids: list[str]
    plan_path: str
    latest_alias_path: str
    evaluation_status: str
    latest_evaluator_report: str
    latest_evaluator_verdict: str
    evaluator_report_path: str
    clarifications: list[dict]
    clarification_index: int
    clarification_answers: list[dict]
    clarification_resolved: bool
    clarification_pending: bool
    clarification_question: str
    clarification_answered_at: str
    awaiting_execution_approval: bool
    created_at: str
    approved_at: str
    execution_requested_at: str
    execution_handoff_started: bool
    execution_handoff_started_at: str
    execution_handoff_failed: bool
    execution_handoff_failed_at: str
    execution_handoff_error: str
    execution_started_at: str
    completed_at: str


class PlanHistoryItem(TypedDict, total=False):
    plan_id: str
    title: str
    path: str
    created_at: str
    status: str


class TodoGraphItem(TypedDict, total=False):
    id: str
    content: str
    status: str
    depends_on: list[str]
    owner: str
    subagent_type: str | None
    target_endpoint: str | None
    tool_budget: int | None


class TodoGraphState(TypedDict, total=False):
    nodes: list[TodoGraphItem]
    ready_ids: list[str]
    updated_at: str


class RetryRuntimeState(TypedDict, total=False):
    last_retry_turn_had_attempts: bool
    attempts_by_tool_call: dict[str, int]


class HandoffArtifactState(TypedDict, total=False):
    plan_path: str
    report_path: str


class HooksRuntimeState(TypedDict, total=False):
    observed_files: list[str]


class ResumeMetaState(TypedDict, total=False):
    last_checkpoint_id: str | None
    last_completed_todo_id: str | None
    pending_ready_ids: list[str]
    deferred_task_calls_count: int
    handoff_refs: list[str]
    # Fields added for interrupt-recovery: allow a fresh run to detect and fix stale
    # in-progress entries left over from an interrupted run.
    in_progress_todo_ids: list[str]   # todos marked in_progress at interrupt time
    retry_counts: dict[str, int]      # tool_call_id -> attempt count from retry_meta
    running_subagent_ids: list[str]   # task IDs of deferred subagent calls in flight


class ScratchpadEntry(TypedDict, total=False):
    ts: str
    source: str
    text: str


class TaskMemoryFact(TypedDict, total=False):
    ts: str
    fact: str


class MemoryVersionRefState(TypedDict, total=False):
    version_id: str
    sha: str
    storage_path: str


class DreamyIntentState(TypedDict):
    shape: str
    intent_class: str
    confidence: float
    extracted_fields: list[str]
    inferred_goal: str
    workflow_requested: bool


class BackgroundFollowupJob(TypedDict, total=False):
    id: str
    status: str
    kind: str
    summary: str
    created_at: str
    completed_at: str | None
    error: str | None


class ExecutionIntentState(TypedDict, total=False):
    mode: str
    plan_behavior: str
    allow_background_deepen: bool
    max_primary_subagents: int


class SteeringIntentState(TypedDict, total=False):
    intent_id: str
    message: str
    created_at: str


class WorkModeState(TypedDict, total=False):
    """Tracks work mode activation and current execution position."""

    active: bool
    plan_source: str  # "prior_run" | "inline_generation" | "escalated"
    current_phase_index: int
    total_phases: int
    phases_completed: int


class PhaseExecutionState(TypedDict, total=False):
    """Per-phase execution metadata — single source of truth for frontend progress.

    Frontend reads this via onUpdateEvent (LangGraph state delta). SSE events
    (phase_started, phase_completed) are animation triggers only.
    """

    current_phase: int
    total_phases: int
    phase_results: list[dict]  # [{phase_index, todo_id, content, status, subagent_type, completed_at}]
    plan_adapted: bool
    adaptation_notes: str
    adaptation_attempts: int  # how many times plan adaptation has been auto-triggered (capped at 2)


class QualityGateState(TypedDict, total=False):
    status: str  # passed | failed | skipped
    fail_reasons: list[str]
    repair_passes: int
    checked_path: str


class HandoffMetaState(TypedDict, total=False):
    source_thread_id: str
    handoff_root_virtual_path: str
    package_manifest_virtual_path: str | None
    created_at: str


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Reducer for artifacts list - merges and deduplicates artifacts."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    # Use dict.fromkeys to deduplicate while preserving order
    return list(dict.fromkeys(existing + new))


def merge_viewed_images(existing: dict[str, ViewedImageData] | None, new: dict[str, ViewedImageData] | None) -> dict[str, ViewedImageData]:
    """Reducer for viewed_images dict - merges image dictionaries.

    Special case: If new is an empty dict {}, it clears the existing images.
    This allows middlewares to clear the viewed_images state after processing.
    """
    if existing is None:
        return new or {}
    if new is None:
        return existing
    # Special case: empty dict means clear all viewed images
    if len(new) == 0:
        return {}
    # Merge dictionaries, new values override existing ones for same keys
    return {**existing, **new}


class ThreadState(AgentState):
    dreamy_mode: NotRequired[bool]
    dreamy_intent: NotRequired[DreamyIntentState]
    execution_intent: NotRequired[ExecutionIntentState | None]
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]
    todos: NotRequired[list | None]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # image_path -> {base64, mime_type}
    progress_guard: NotRequired[ProgressGuardRuntimeState | None]
    trajectory: NotRequired[TrajectoryRuntimeState | None]
    skill_disclosure: NotRequired[SkillDisclosureState | None]
    plan: NotRequired[PlanState | None]
    plan_history: NotRequired[list[PlanHistoryItem] | None]
    eval_attempts: NotRequired[int]
    todo_graph: NotRequired[TodoGraphState | None]
    deferred_task_calls: NotRequired[list[dict] | None]
    handoff_artifacts: Annotated[list[str], merge_artifacts]
    retry_meta: NotRequired[RetryRuntimeState | None]
    hooks_state: NotRequired[HooksRuntimeState | None]
    resume_meta: NotRequired[ResumeMetaState | None]
    scratchpad: NotRequired[list[ScratchpadEntry] | None]
    task_memory: NotRequired[dict[str, list[TaskMemoryFact]] | None]
    memory_version_ref: NotRequired[MemoryVersionRefState | None]
    execution_trace: Annotated[ExecutionTraceState, merge_execution_trace]
    activity_timeline: Annotated[ActivityTimelineState, merge_activity_timeline]
    context_metrics: Annotated[ContextMetricsState, merge_context_metrics]
    suggested_questions: NotRequired[list[str] | None]
    background_followups: NotRequired[list[BackgroundFollowupJob] | None]
    # Auto Mode / Planner phase fields (Phase A + B revamp)
    auto_mode: NotRequired[bool]
    complexity_tier: NotRequired[str | None]
    plan_evaluated: NotRequired[bool]
    steering_context: NotRequired[str | None]
    pending_steering_intents: NotRequired[list[SteeringIntentState] | None]
    # Work Mode execution tracking (set by WorkModeMiddleware)
    work_mode: NotRequired[WorkModeState | None]
    phase_execution: NotRequired[PhaseExecutionState | None]
    quality_gate: NotRequired[QualityGateState | None]
    handoff_meta: NotRequired[HandoffMetaState | None]
