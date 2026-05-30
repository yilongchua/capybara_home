import logging
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.runnables import RunnableConfig

from src.agents.common.middleware_registry import MiddlewareSpec, topological_sort_middleware_specs
from src.agents.common.mode import normalize_runtime_mode, resolve_current_mode
from src.agents.memory.summarization_hook import memory_flush_hook
from src.agents.middlewares.activity_timeline_middleware import ActivityTimelineMiddleware
from src.agents.middlewares.autoresearch_middleware import AutoresearchMiddleware
from src.agents.middlewares.clarification_middleware import ClarificationMiddleware
from src.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from src.agents.middlewares.evaluator_middleware import EvaluatorMiddleware
from src.agents.middlewares.execution_trace_middleware import ExecutionTraceMiddleware
from src.agents.middlewares.hooks_middleware import HooksMiddleware
from src.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from src.agents.middlewares.memory_middleware import MemoryMiddleware
from src.agents.middlewares.metrics_middleware import MetricsMiddleware
from src.agents.middlewares.model_timeout_middleware import ModelTimeoutMiddleware
from src.agents.middlewares.mount_folder_middleware import MountFolderMiddleware
from src.agents.middlewares.permission_middleware import PermissionMiddleware

# DEPRECATED: PhaseToolFilter and PlanExecutionGate middlewares are no longer
# registered. web_search is now exposed in Plan Mode directly. Imports are kept
# commented for reference; the middleware source files remain on disk.
# from src.agents.middlewares.phase_tool_filter_middleware import PhaseToolFilterMiddleware
from src.agents.middlewares.plan_evaluator_middleware import PlanEvaluatorMiddleware

# from src.agents.middlewares.plan_execution_gate_middleware import PlanExecutionGateMiddleware
from src.agents.middlewares.plan_file_sync_middleware import PlanFileSyncMiddleware
from src.agents.middlewares.planner_middleware import PlannerMiddleware
from src.agents.middlewares.pro_followup_middleware import PlanFollowupMiddleware
from src.agents.middlewares.question_generation_middleware import QuestionGenerationMiddleware
from src.agents.middlewares.recursion_pivot_middleware import RecursionBudgetPivotMiddleware
from src.agents.middlewares.resume_state_middleware import ResumeStateMiddleware
from src.agents.middlewares.retry_policy_middleware import RetryPolicyMiddleware
from src.agents.middlewares.scratchpad_task_memory_middleware import ScratchpadTaskMemoryMiddleware
from src.agents.middlewares.skill_disclosure_middleware import SkillDisclosureMiddleware
from src.agents.middlewares.steering_middleware import SteeringMiddleware
from src.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from src.agents.middlewares.summarization_middleware import CapyHomeSummarizationMiddleware
from src.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
from src.agents.middlewares.title_middleware import TitleMiddleware
from src.agents.middlewares.todo_dag_middleware import TodoDagMiddleware
from src.agents.middlewares.todo_failure_retry_middleware import TodoFailureRetryMiddleware
from src.agents.middlewares.todo_middleware import TodoMiddleware
from src.agents.middlewares.tool_disclosure_middleware import ToolDisclosureMiddleware
from src.agents.middlewares.tool_result_truncation_middleware import ToolResultTruncationMiddleware
from src.agents.middlewares.trajectory_middleware import TrajectoryMiddleware
from src.agents.middlewares.uploads_middleware import UploadsMiddleware
from src.agents.middlewares.view_image_middleware import ViewImageMiddleware
from src.agents.middlewares.web_search_circuit_breaker_middleware import WebSearchCircuitBreakerMiddleware
from src.agents.middlewares.web_search_summary_middleware import WebSearchSummaryMiddleware
from src.agents.middlewares.work_mode_middleware import _create_work_mode
from src.agents.middlewares.write_file_artifact_middleware import WriteFileArtifactMiddleware
from src.agents.thread_state import ThreadState
from src.agents.work_agent.prompt import apply_prompt_template
from src.agents.work_agent.todo_prompts import TODO_LIST_SYSTEM_PROMPT, TODO_LIST_TOOL_DESCRIPTION
from src.config.agents_config import load_agent_config
from src.config.app_config import get_app_config
from src.config.evaluator_config import get_evaluator_config
from src.config.execution_trace_config import get_execution_trace_config
from src.config.handoffs_config import get_handoffs_config
from src.config.harness_config import get_harness_config
from src.config.hooks_config import get_hooks_config
from src.config.loop_detection_config import get_loop_detection_config
from src.config.memory_config import get_memory_config
from src.config.model_config import ModelConfig
from src.config.planner_config import get_planner_config
from src.config.recursion_pivot_config import get_recursion_pivot_config
from src.config.resume_config import get_resume_config
from src.config.retry_config import get_retry_config
from src.config.scratchpad_config import get_scratchpad_config
from src.config.sprint_contracts_config import get_sprint_contracts_config
from src.config.subagents_config import get_subagents_app_config
from src.config.summarization_config import get_summarization_config
from src.config.task_memory_config import get_task_memory_config
from src.config.todos_config import get_todos_config
from src.config.tool_disclosure_config import get_tool_disclosure_config
from src.config.web_search_summary_config import get_web_search_summary_config
from src.models import ModelRouter, create_chat_model, resolve_model_name
from src.sandbox.middleware import SandboxMiddleware

logger = logging.getLogger(__name__)

_DEFAULT_COMPACTION_CONTEXT_TOKENS = 128_000
_DEFAULT_COMPACTION_TRIGGER_FRACTION = 0.8
_DEFAULT_COMPACTION_KEEP_TOKENS = 32_000


# Backwards-compat aliases — tests and external callers still reference these
# under the old private names. The implementations live in ``src.agents.common``.
_normalize_runtime_mode = normalize_runtime_mode
_resolve_current_mode = resolve_current_mode


def _resolve_model_name(requested_model_name: str | None = None) -> str:
    """Resolve a runtime model name safely, falling back to default if invalid.

    Thin wrapper around ``resolve_model_name``; kept for backwards compatibility
    with call sites inside this module.
    """
    return resolve_model_name(requested_model_name)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _profile_context_tokens(model: object) -> int | None:
    profile = getattr(model, "profile", None)
    if profile is None:
        return None
    if isinstance(profile, dict):
        return _positive_int(profile.get("max_input_tokens")) or _positive_int(profile.get("context_window"))
    return _positive_int(getattr(profile, "max_input_tokens", None)) or _positive_int(getattr(profile, "context_window", None))


def _model_config_context_tokens(model_name: str) -> int | None:
    model_config = get_app_config().get_model_config(model_name)
    if model_config is None or not model_config.model_extra:
        return None
    return _positive_int(model_config.model_extra.get("context_window")) or _positive_int(model_config.model_extra.get("max_input_tokens"))


_COMPACTION_FALLBACK_WARNED: set[str] = set()


def _resolve_compaction_context_tokens(
    *,
    model: object,
    model_name: str,
    configured_max_context_tokens: int | None,
) -> int:
    profile_tokens = _profile_context_tokens(model)
    if profile_tokens is not None:
        return profile_tokens

    configured_tokens = _positive_int(configured_max_context_tokens)
    if configured_tokens is not None:
        return configured_tokens

    model_config_tokens = _model_config_context_tokens(model_name)
    if model_config_tokens is not None:
        return model_config_tokens

    # Log the fallback once per model name to keep production logs quiet on
    # cold-start of agents whose model has no resolvable context size.
    if model_name not in _COMPACTION_FALLBACK_WARNED:
        _COMPACTION_FALLBACK_WARNED.add(model_name)
        logger.warning(
            "Summarization token-pressure trigger could not resolve context size for model %r; falling back to %s tokens.",
            model_name,
            _DEFAULT_COMPACTION_CONTEXT_TOKENS,
        )
    return _DEFAULT_COMPACTION_CONTEXT_TOKENS


def _resolve_fraction_to_tokens(value: int | float, context_tokens: int) -> tuple[str, int]:
    threshold = int(context_tokens * float(value))
    return ("tokens", max(1, threshold))


def _normalize_token_only_trigger(trigger: tuple | list[tuple] | None, context_tokens: int) -> tuple | list[tuple] | None:
    if trigger is None:
        return _resolve_fraction_to_tokens(_DEFAULT_COMPACTION_TRIGGER_FRACTION, context_tokens)

    raw_triggers = [trigger] if isinstance(trigger, tuple) else list(trigger)
    resolved: list[tuple] = []
    for item in raw_triggers:
        if not item or len(item) != 2:
            continue
        kind, value = item
        if kind == "fraction":
            resolved.append(_resolve_fraction_to_tokens(value, context_tokens))
        elif kind == "tokens":
            tokens = _positive_int(int(value))
            if tokens is not None:
                resolved.append(("tokens", tokens))
        elif kind == "messages":
            logger.warning(
                "Ignoring deprecated summarization message-count trigger %r; compaction is now token-pressure only.",
                item,
            )

    if not resolved:
        logger.warning(
            "Summarization trigger had no token-pressure threshold after normalization; using %.0f%% of %s tokens.",
            _DEFAULT_COMPACTION_TRIGGER_FRACTION * 100,
            context_tokens,
        )
        return _resolve_fraction_to_tokens(_DEFAULT_COMPACTION_TRIGGER_FRACTION, context_tokens)
    return resolved[0] if len(resolved) == 1 else resolved


def _normalize_token_only_keep(keep: tuple, context_tokens: int) -> tuple:
    if not keep or len(keep) != 2:
        return ("tokens", _DEFAULT_COMPACTION_KEEP_TOKENS)
    kind, value = keep
    if kind == "fraction":
        return _resolve_fraction_to_tokens(value, context_tokens)
    if kind == "tokens":
        tokens = _positive_int(int(value))
        return ("tokens", tokens or _DEFAULT_COMPACTION_KEEP_TOKENS)
    if kind == "messages":
        logger.warning(
            "Replacing deprecated summarization message-count keep policy %r with keep=('tokens', %s).",
            keep,
            _DEFAULT_COMPACTION_KEEP_TOKENS,
        )
    else:
        logger.warning(
            "Unknown summarization keep policy kind %r in %r; falling back to keep=('tokens', %s).",
            kind,
            keep,
            _DEFAULT_COMPACTION_KEEP_TOKENS,
        )
    return ("tokens", _DEFAULT_COMPACTION_KEEP_TOKENS)


def _create_summarization_middleware(*, mode: str = "") -> CapyHomeSummarizationMiddleware | None:
    """Create and configure the summarization middleware from config."""
    config = get_summarization_config()

    if not config.enabled:
        return None
    if config.trim_tokens_to_summarize is None:
        logger.warning("Summarization is enabled with trim_tokens_to_summarize unset; large contexts may be summarized without pre-trimming.")

    legacy_mode_aliases = {"work": "fast", "plan": "pro"}
    mode_override = config.modes.get(mode) or config.modes.get(legacy_mode_aliases.get(mode, mode)) or config.modes.get("default")

    # Prepare model parameter
    summary_model_name = _resolve_model_name(config.model_name)
    model = create_chat_model(name=summary_model_name, thinking_enabled=False)

    max_context_tokens = mode_override.max_context_tokens if mode_override and mode_override.max_context_tokens is not None else config.max_context_tokens
    context_tokens = _resolve_compaction_context_tokens(
        model=model,
        model_name=summary_model_name,
        configured_max_context_tokens=max_context_tokens,
    )

    # Prepare token-only trigger parameter.
    trigger = None
    mode_trigger = mode_override.trigger if mode_override and mode_override.trigger is not None else config.trigger
    if mode_trigger is not None:
        if isinstance(mode_trigger, list):
            trigger = [t.to_tuple() for t in mode_trigger]
        else:
            trigger = mode_trigger.to_tuple()
    trigger = _normalize_token_only_trigger(trigger, context_tokens)

    # Prepare token-only keep parameter.
    mode_keep = mode_override.keep if mode_override and mode_override.keep is not None else config.keep
    keep = _normalize_token_only_keep(mode_keep.to_tuple(), context_tokens)

    # Prepare kwargs
    kwargs = {
        "model": model,
        "trigger": trigger,
        "keep": keep,
    }

    trim_tokens_to_summarize = mode_override.trim_tokens_to_summarize if mode_override and mode_override.trim_tokens_to_summarize is not None else config.trim_tokens_to_summarize
    if trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = trim_tokens_to_summarize

    summary_prompt = mode_override.summary_prompt if mode_override and mode_override.summary_prompt is not None else config.summary_prompt
    if summary_prompt is not None:
        kwargs["summary_prompt"] = summary_prompt

    hooks = [memory_flush_hook] if get_memory_config().enabled else []

    return CapyHomeSummarizationMiddleware(
        **kwargs,
        before_summarization=hooks,
    )


def _create_todo_list_middleware(is_plan_mode: bool) -> TodoMiddleware | None:
    """Create the legacy flat-list TodoMiddleware when plan mode is active."""
    if not is_plan_mode:
        return None
    return TodoMiddleware(
        system_prompt=TODO_LIST_SYSTEM_PROMPT,
        tool_description=TODO_LIST_TOOL_DESCRIPTION,
    )


# Alias removed — call ``topological_sort_middleware_specs`` from
# ``src.agents.common.middleware_registry`` directly. The leading-underscore
# alias used to ease an in-progress rename of the public helper; tests have
# been migrated to the public name.


@dataclass
class _RegistryContext:
    """Dependencies shared across middleware factory functions.

    Bundling them into one dataclass keeps the factory signatures uniform and
    makes it obvious which inputs each factory actually reads — replacing the
    previous pattern of closure capture over 6+ local variables.
    """

    is_plan_mode: bool
    is_work_mode: bool
    subagent_enabled: bool
    max_concurrent_subagents: int
    max_primary_per_turn: int
    model_name: str | None
    agent_name: str | None
    model_config: ModelConfig | None
    router: ModelRouter


def _create_todo(ctx: _RegistryContext) -> AgentMiddleware | None:
    if not ctx.is_plan_mode:
        return None
    if get_todos_config().dag_enabled:
        return TodoDagMiddleware()
    return _create_todo_list_middleware(ctx.is_plan_mode)


def _create_planner(ctx: _RegistryContext) -> AgentMiddleware | None:
    planner_cfg = get_planner_config()
    if not ctx.is_plan_mode or not planner_cfg.enabled:
        return None
    return PlannerMiddleware(
        requested_model=ctx.model_name,
        max_plan_steps=planner_cfg.max_plan_steps,
        max_clarifications=planner_cfg.max_clarifications,
        dag_enabled=get_todos_config().dag_enabled,
        handoffs_config=get_handoffs_config(),
        sprint_contracts_config=get_sprint_contracts_config(),
        research_fanout=planner_cfg.research_fanout,
        research_fanout_min_todos=planner_cfg.research_fanout_min_todos,
        timeout_seconds=planner_cfg.timeout_seconds,
    )


def _create_evaluator(ctx: _RegistryContext) -> AgentMiddleware | None:
    evaluator_cfg = get_evaluator_config()
    if not ctx.is_plan_mode or not evaluator_cfg.enabled:
        return None
    return EvaluatorMiddleware(
        router=ctx.router,
        requested_model=ctx.model_name,
        max_attempts=evaluator_cfg.max_attempts,
        handoffs_config=get_handoffs_config(),
    )


def _create_plan_evaluator(ctx: _RegistryContext) -> AgentMiddleware | None:
    planner_cfg = get_planner_config()
    evaluator_cfg = get_evaluator_config()
    if not ctx.is_plan_mode or not planner_cfg.enabled:
        return None
    return PlanEvaluatorMiddleware(
        requested_model=ctx.model_name,
        timeout_seconds=evaluator_cfg.plan_evaluator_timeout_seconds,
    )


def _create_web_search_summary(ctx: _RegistryContext) -> AgentMiddleware | None:
    if not get_web_search_summary_config().enabled:
        return None
    return WebSearchSummaryMiddleware(requested_model=ctx.model_name)


def _create_view_image(ctx: _RegistryContext) -> AgentMiddleware | None:
    if ctx.model_config is not None and getattr(ctx.model_config, "supports_vision", False):
        return ViewImageMiddleware()
    return None


def _create_subagent_limit(ctx: _RegistryContext) -> AgentMiddleware | None:
    if not ctx.subagent_enabled:
        return None
    return SubagentLimitMiddleware(
        max_concurrent=ctx.max_concurrent_subagents,
        router=ctx.router,
        requested_model=ctx.model_name,
        max_primary_per_turn=ctx.max_primary_per_turn,
    )


def _create_hooks(_ctx: _RegistryContext) -> AgentMiddleware | None:
    hooks_cfg = get_hooks_config()
    if not any((hooks_cfg.SessionStart, hooks_cfg.PreToolUse, hooks_cfg.PostToolUse, hooks_cfg.FileChanged)):
        return None
    return HooksMiddleware(hooks_cfg)


def _create_retry(_ctx: _RegistryContext) -> AgentMiddleware | None:
    retry_cfg = get_retry_config()
    if not retry_cfg.enabled:
        return None
    return RetryPolicyMiddleware(retry_cfg)


def _create_recursion_pivot(ctx: _RegistryContext) -> AgentMiddleware | None:
    cfg = get_recursion_pivot_config()
    if not cfg.enabled:
        return None
    return RecursionBudgetPivotMiddleware(
        router=ctx.router,
        requested_model=ctx.model_name,
        config=cfg,
    )


def _create_loop_detection(_ctx: _RegistryContext) -> AgentMiddleware | None:
    cfg = get_loop_detection_config()
    if not cfg.enabled:
        return None
    return LoopDetectionMiddleware(
        warn_threshold=cfg.warn_threshold,
        hard_limit=cfg.hard_limit,
        window_size=cfg.window_size,
        max_tracked_threads=cfg.max_tracked_threads,
        tool_freq_warn=cfg.tool_freq_warn,
        tool_freq_hard_limit=cfg.tool_freq_hard_limit,
    )


def _create_tool_disclosure(_ctx: _RegistryContext) -> AgentMiddleware | None:
    cfg = get_tool_disclosure_config()
    if not cfg.enabled:
        return None
    return ToolDisclosureMiddleware(cfg)


# DEPRECATED: phase_tool_filter is no longer registered. Kept here (commented)
# so the wiring can be re-enabled without re-deriving the factory shape.
# def _create_phase_tool_filter(_ctx: _RegistryContext) -> AgentMiddleware | None:
#     # Always-on. Hides execution tools from the LLM while plan is draft so the
#     # LLM literally cannot call them. See phase_tool_filter_middleware.py.
#     return PhaseToolFilterMiddleware()


def _create_scratchpad_task_memory(_ctx: _RegistryContext) -> AgentMiddleware | None:
    scratchpad_cfg = get_scratchpad_config()
    task_memory_cfg = get_task_memory_config()
    if not scratchpad_cfg.enabled and not task_memory_cfg.enabled:
        return None
    return ScratchpadTaskMemoryMiddleware(scratchpad_cfg, task_memory_cfg)


def _create_resume_state(_ctx: _RegistryContext) -> AgentMiddleware | None:
    resume_cfg = get_resume_config()
    if not resume_cfg.enabled:
        return None
    return ResumeStateMiddleware(resume_cfg)


def _create_todo_failure_retry(ctx: _RegistryContext) -> AgentMiddleware | None:
    if not ctx.is_work_mode:
        return None
    return TodoFailureRetryMiddleware()


def _create_plan_followup(ctx: _RegistryContext) -> AgentMiddleware | None:
    if not ctx.is_plan_mode:
        return None
    return PlanFollowupMiddleware()


def _create_title(ctx: _RegistryContext) -> AgentMiddleware | None:
    # Single-model invariant: title generation runs on the chat-selected model.
    return TitleMiddleware(model_name=resolve_model_name(ctx.model_name))


def _create_memory(ctx: _RegistryContext) -> AgentMiddleware | None:
    return MemoryMiddleware(agent_name=ctx.agent_name)


def _create_execution_trace(ctx: _RegistryContext) -> AgentMiddleware | None:
    if not get_execution_trace_config().enabled:
        return None
    return ExecutionTraceMiddleware()


#: Plumbing middlewares kept when ``harness.enabled=false``. These four are the
#: minimum set that the frontend, sandbox, and tool executor hard-depend on.
#: Everything else (permissions, hooks, planner/evaluator, metrics, etc.) is
#: dropped as part of the kill-switch.
_HARNESS_MINIMAL_MIDDLEWARES: frozenset[str] = frozenset({"thread_data", "sandbox", "dangling_tool_call", "execution_trace", "activity_timeline", "clarification"})


def _build_middleware_registry(
    config: RunnableConfig,
    model_name: str | None,
    agent_name: str | None = None,
    model_router: ModelRouter | None = None,
) -> list[MiddlewareSpec]:
    cfg = config.get("configurable") or {}
    app_config = get_app_config()
    subagents_cfg = get_subagents_app_config()
    mode = _resolve_current_mode(cfg)
    ctx = _RegistryContext(
        is_plan_mode=mode == "plan",
        is_work_mode=(mode == "work"),
        subagent_enabled=cfg.get("subagent_enabled", False),
        max_concurrent_subagents=cfg.get("max_concurrent_subagents", 3),
        max_primary_per_turn=int(getattr(subagents_cfg, "max_primary_per_turn", 2)),
        model_name=model_name,
        agent_name=agent_name,
        model_config=app_config.get_model_config(model_name) if model_name else None,
        router=model_router or ModelRouter(app_config=app_config),
    )

    def bind(fn):
        return lambda: fn(ctx)

    specs = [
        MiddlewareSpec("thread_data", lambda: ThreadDataMiddleware()),
        MiddlewareSpec("steering", lambda: SteeringMiddleware(), after={"thread_data"}, before={"uploads"}),
        MiddlewareSpec("uploads", lambda: UploadsMiddleware(), after={"thread_data"}),
        MiddlewareSpec("mount_folder", lambda: MountFolderMiddleware(), after={"uploads", "thread_data"}),
        MiddlewareSpec("sandbox", lambda: SandboxMiddleware(), after={"thread_data"}),
        MiddlewareSpec("autoresearch", lambda: AutoresearchMiddleware(), after={"sandbox"}),
        MiddlewareSpec("write_file_artifact", lambda: WriteFileArtifactMiddleware(), after={"sandbox"}),
        MiddlewareSpec("dangling_tool_call", lambda: DanglingToolCallMiddleware(), after={"sandbox"}),
        MiddlewareSpec("work_mode", bind(_create_work_mode), after={"dangling_tool_call"}),
        # DEPRECATED: plan_execution_gate is no longer registered. web_search and
        # other execution tools are allowed in Plan Mode directly.
        # # Planner must run before plan_execution_gate so the gate has a plan to
        # # consult on turn 1. Otherwise the model's first-turn tool calls bypass
        # # the gate entirely. See thread-fa33b3bb investigation.
        # MiddlewareSpec("plan_execution_gate", lambda: PlanExecutionGateMiddleware(requested_model=ctx.model_name), after={"planner"}, before={"permissions"}),
        MiddlewareSpec("permissions", lambda: PermissionMiddleware(), after={"dangling_tool_call"}),
        MiddlewareSpec("tool_disclosure", bind(_create_tool_disclosure), after={"permissions"}),
        MiddlewareSpec("hooks", bind(_create_hooks), after={"tool_disclosure"}),
        MiddlewareSpec("summarization", lambda: _create_summarization_middleware(mode=mode), after={"dangling_tool_call"}),
        MiddlewareSpec("skill_disclosure", lambda: SkillDisclosureMiddleware(), after={"summarization"}),
        MiddlewareSpec("planner", bind(_create_planner), after={"skill_disclosure"}),
        # DEPRECATED: phase_tool_filter is no longer registered. web_search is
        # visible to the LLM in Plan Mode now.
        # MiddlewareSpec("phase_tool_filter", bind(_create_phase_tool_filter), after={"planner"}),
        MiddlewareSpec("plan_evaluator", bind(_create_plan_evaluator), after={"planner"}),
        MiddlewareSpec("web_search_summary", bind(_create_web_search_summary), after={"tool_result_truncation"}),
        MiddlewareSpec("todo", bind(_create_todo), after={"plan_evaluator"}),
        MiddlewareSpec("title", bind(_create_title), after={"todo"}),
        MiddlewareSpec("question_generation", lambda: QuestionGenerationMiddleware(), after={"title"}),
        MiddlewareSpec("memory", bind(_create_memory), after={"question_generation"}),
        MiddlewareSpec("view_image", bind(_create_view_image), after={"memory"}),
        MiddlewareSpec("retry", bind(_create_retry), after={"view_image"}),
        # Bound LLM call duration. Sits between retry (so retried calls are
        # also bounded) and subagent_limit. See routing.timeouts in config.yaml.
        MiddlewareSpec("model_timeout", lambda: ModelTimeoutMiddleware(), after={"retry"}),
        MiddlewareSpec("web_search_circuit_breaker", lambda: WebSearchCircuitBreakerMiddleware(), after={"model_timeout"}),
        # Cap tool-result size so context can't balloon round over round.
        MiddlewareSpec("tool_result_truncation", lambda: ToolResultTruncationMiddleware(), after={"web_search_circuit_breaker"}),
        MiddlewareSpec("subagent_limit", bind(_create_subagent_limit), after={"retry", "model_timeout", "tool_result_truncation"}),
        MiddlewareSpec("evaluator", bind(_create_evaluator), after={"subagent_limit"}),
        MiddlewareSpec("todo_failure_retry", bind(_create_todo_failure_retry), after={"evaluator"}),
        MiddlewareSpec("scratchpad_task_memory", bind(_create_scratchpad_task_memory), after={"todo_failure_retry"}),
        MiddlewareSpec("plan_file_sync", lambda: PlanFileSyncMiddleware(), after={"scratchpad_task_memory"}),
        MiddlewareSpec("resume_state", bind(_create_resume_state), after={"plan_file_sync"}),
        MiddlewareSpec("plan_followup", bind(_create_plan_followup), after={"resume_state", "evaluator"}),
        # LoopDetectionMiddleware detects repetitive inputs (identical call-pattern hashes
        # and per-tool-type frequency saturation).
        MiddlewareSpec("loop_detection", bind(_create_loop_detection), after={"plan_followup"}),
        # RecursionBudgetPivotMiddleware: at configured budget thresholds, calls an evaluator LLM
        # in before_model to inject steering. Runs after the output-focused guards so its decision
        # sees any warnings they emitted in the prior turn. Lead-agent only — subagents are out
        # of scope for v1 (they have their own max_turns-derived ceiling).
        MiddlewareSpec("recursion_pivot", bind(_create_recursion_pivot), after={"loop_detection"}),
        # TrajectoryMiddleware must be the OUTERMOST wrap_*_call wrapper so it observes
        # the synthetic timeout/error responses produced by ModelTimeoutMiddleware and
        # other inner middlewares (otherwise it sees CancelledError propagating from
        # asyncio.wait_for and reports `result_count=0, timed_out=False` for genuine
        # timeouts — see audit thread-cd90decb). Spec order = wrap order: first = outer.
        # The trade-off is that runtime events emitted in `before_model` of inner
        # middlewares (planner, summarization, etc.) are drained at the end of the
        # cycle (`after_model`, which runs in reversed spec order) instead of at the
        # next `before_model`. Events still appear in the trajectory, just later.
        MiddlewareSpec("trajectory", lambda: TrajectoryMiddleware(), after={"thread_data"}),
        MiddlewareSpec("execution_trace", bind(_create_execution_trace), after={"trajectory", "loop_detection"}),
        MiddlewareSpec("activity_timeline", lambda: ActivityTimelineMiddleware(), after={"execution_trace"}),
        MiddlewareSpec("metrics", lambda: MetricsMiddleware(), after={"activity_timeline"}),
        MiddlewareSpec(
            "clarification",
            lambda: ClarificationMiddleware(),
            after={"metrics", "permissions", "memory", "subagent_limit", "loop_detection", "recursion_pivot", "evaluator", "execution_trace", "activity_timeline"},
        ),
    ]

    # Harness-level kill switch. When disabled, strip the spec list to the
    # plumbing subset and re-point clarification's dependencies so the
    # topological sort still places it last with no dangling edges.
    if not get_harness_config().enabled:
        logger.warning("Harness kill-switch active: running with minimal middleware subset %s.", sorted(_HARNESS_MINIMAL_MIDDLEWARES))
        kept = [spec for spec in specs if spec.name in _HARNESS_MINIMAL_MIDDLEWARES]
        minimal_names = {spec.name for spec in kept}
        for spec in kept:
            spec.after = spec.after & minimal_names
            spec.before = spec.before & minimal_names
        return kept

    return specs


def _build_middlewares(
    config: RunnableConfig,
    model_name: str | None,
    agent_name: str | None = None,
    model_router: ModelRouter | None = None,
):
    """Build middleware chain based on runtime configuration.

    Args:
        config: Runtime configuration containing configurable options like is_plan_mode.
        agent_name: If provided, MemoryMiddleware will use per-agent memory storage.

    Returns:
        List of middleware instances.
    """
    specs = _build_middleware_registry(config, model_name=model_name, agent_name=agent_name, model_router=model_router)
    ordered_specs = topological_sort_middleware_specs(specs)

    middlewares: list[AgentMiddleware] = []
    for spec in ordered_specs:
        middleware = spec.factory()
        if middleware is None:
            continue
        middlewares.append(middleware)
    return middlewares


@dataclass
class _RuntimeParams:
    """Unpacked ``configurable`` fields + resolved agent metadata."""

    thinking_enabled: bool
    reasoning_effort: str | None
    requested_model_name: str | None
    mode: str
    plan_behavior: str
    background_followup: bool
    is_plan_mode: bool
    subagent_enabled: bool
    max_concurrent_subagents: int
    max_primary_per_turn: int
    is_bootstrap: bool
    agent_name: str | None
    agent_config: object | None  # AgentConfig | None — avoid circular import


def _extract_runtime_params(config: RunnableConfig) -> _RuntimeParams:
    cfg = config.get("configurable") or {}
    is_bootstrap = cfg.get("is_bootstrap", False)
    agent_name = cfg.get("agent_name")
    agent_config = load_agent_config(agent_name) if not is_bootstrap else None
    mode = _resolve_current_mode(cfg)
    plan_behavior = str(cfg.get("plan_behavior", "") or "").strip().lower()
    subagents_cfg = get_subagents_app_config()
    return _RuntimeParams(
        thinking_enabled=cfg.get("thinking_enabled", True),
        reasoning_effort=cfg.get("reasoning_effort", None),
        requested_model_name=cfg.get("model_name") or cfg.get("model"),
        mode=mode,
        plan_behavior=plan_behavior or ("plan_foreground" if mode == "plan" else "work_interactive"),
        background_followup=bool(cfg.get("background_followup", False)),
        is_plan_mode=mode == "plan",
        subagent_enabled=cfg.get("subagent_enabled", False),
        max_concurrent_subagents=cfg.get("max_concurrent_subagents", 3),
        max_primary_per_turn=int(getattr(subagents_cfg, "max_primary_per_turn", 2)),
        is_bootstrap=is_bootstrap,
        agent_name=agent_name,
        agent_config=agent_config,
    )


def _resolve_generator_model(params: _RuntimeParams, router: ModelRouter) -> str:
    """Resolve the generator model name with fallback semantics."""
    agent_config = params.agent_config
    agent_model_name = agent_config.model if agent_config and getattr(agent_config, "model", None) else _resolve_model_name()
    requested_or_agent = params.requested_model_name or agent_model_name
    return router.resolve("generator", requested_model=requested_or_agent)


def _reconcile_thinking_flags(params: _RuntimeParams, model_name: str, model_config) -> tuple[bool, str | None]:
    """Downgrade ``thinking_enabled`` to False if the resolved model lacks support.

    When thinking is disabled we also clear ``reasoning_effort`` — it is only
    meaningful while thinking is active, and some providers reject it otherwise.
    """
    thinking_enabled = params.thinking_enabled
    reasoning_effort = params.reasoning_effort
    if thinking_enabled and not model_config.supports_thinking:
        logger.debug(f"Thinking mode is enabled but model '{model_name}' does not support it; fallback to non-thinking mode.")
        thinking_enabled = False
        reasoning_effort = None
    return thinking_enabled, reasoning_effort


def _inject_trace_metadata(
    config: RunnableConfig,
    *,
    params: _RuntimeParams,
    model_name: str,
    thinking_enabled: bool,
    reasoning_effort: str | None,
) -> None:
    """Attach LangSmith trace tags to the RunnableConfig in place."""
    if "metadata" not in config:
        config["metadata"] = {}
    config["metadata"].update(
        {
            "agent_name": params.agent_name or "default",
            "model_name": model_name or "default",
            "generator_model_name": model_name or "default",
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort,
            "mode": params.mode or "default",
            "plan_behavior": params.plan_behavior,
            "background_followup": params.background_followup,
            "is_plan_mode": params.is_plan_mode,
            "subagent_enabled": params.subagent_enabled,
        }
    )


def make_work_agent(config: RunnableConfig):
    """Graph entry point for the ``work_agent`` LangGraph node.

    LangGraph's factory loader requires the registered callable's parameters
    to be ``ServerRuntime`` and/or ``RunnableConfig`` only — any extra kwarg
    (even with a default) causes graph load to fail. This function is the
    thin wrapper that satisfies that contract; the real builder is
    :func:`_build_work_agent`, which ``make_plan_agent`` calls directly when
    it needs to inject the plan-mode prompt template.
    """
    return _build_work_agent(config)


def _build_work_agent(config: RunnableConfig, *, prompt_template_fn=None):
    """Build a mode-aware agent.

    Backs both the ``work_agent`` and ``plan_agent`` LangGraph entry points.
    Selects the prompt template based on ``current_mode`` (or accepts an
    explicit ``prompt_template_fn`` override from :func:`make_plan_agent`).
    Middleware activation is driven by the same ``current_mode`` field via
    ``_RegistryContext.is_plan_mode``.

    ``prompt_template_fn`` precedence:
    1. Explicit kwarg (from ``make_plan_agent``).
    2. Auto-selected based on ``current_mode``: plan_agent's template for
       ``"plan"``, work_agent's template otherwise. This preserves plan-mode
       behavior when the frontend addresses the ``work_agent`` graph with
       ``mode="plan"`` in configurable, which is the current default routing.
    """
    # Lazy import to avoid circular dependency
    from src.tools import get_available_tools
    from src.tools.builtins import setup_agent

    params = _extract_runtime_params(config)

    if prompt_template_fn is None:
        if params.mode == "plan":
            # Lazy import keeps work_agent free of a hard dep on plan_agent
            # at module load (plan_agent imports work_agent's prompt module).
            from src.agents.plan_agent.prompt import apply_prompt_template as _plan_template
            prompt_template_fn = _plan_template
        else:
            prompt_template_fn = apply_prompt_template
    runtime_cfg = config.get("configurable") or {}
    current_turn_text = str(runtime_cfg.get("current_turn_text") or runtime_cfg.get("original_user_request") or runtime_cfg.get("user_prompt") or "")

    app_config = get_app_config()
    router = ModelRouter(app_config=app_config)
    model_name = _resolve_generator_model(params, router)
    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is None:
        raise ValueError("No chat model could be resolved. Please configure at least one model in config.yaml or provide a valid 'model_name'/'model' in the request.")
    thinking_enabled, reasoning_effort = _reconcile_thinking_flags(params, model_name, model_config)

    logger.info(
        "Create Agent(%s) -> thinking_enabled: %s, reasoning_effort: %s, model_name: %s, is_plan_mode: %s, subagent_enabled: %s, max_concurrent_subagents: %s",
        params.agent_name or "default",
        thinking_enabled,
        reasoning_effort,
        model_name,
        params.is_plan_mode,
        params.subagent_enabled,
        params.max_concurrent_subagents,
    )

    _inject_trace_metadata(
        config,
        params=params,
        model_name=model_name,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )

    chat_model = create_chat_model(
        name=model_name,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )

    if params.is_bootstrap:
        # Bootstrap mode is the initial custom-agent-creation flow. We deliberately
        # scope the prompt to a single "bootstrap" skill entry (rather than the full
        # enabled catalogue) so the model focuses on constructing the new agent's
        # SOUL.md / tool_groups without getting distracted by the broader skill
        # surface. The `setup_agent` tool handles persistence; once the user's
        # custom agent is saved, regular runs drop this branch and see the full
        # skill catalogue via apply_prompt_template's default path.
        system_prompt = prompt_template_fn(
            subagent_enabled=params.subagent_enabled,
            max_concurrent_subagents=params.max_concurrent_subagents,
            available_skills=set(["bootstrap"]),
            background_followup=params.background_followup,
            current_turn_text=current_turn_text,
        )
        return create_agent(
            model=chat_model,
            tools=get_available_tools(model_name=model_name, subagent_enabled=params.subagent_enabled, mode=params.mode) + [setup_agent],
            middleware=_build_middlewares(config, model_name=model_name, model_router=router),
            system_prompt=system_prompt,
            state_schema=ThreadState,
        )

    # Default lead agent (unchanged behavior)
    agent_config = params.agent_config
    return create_agent(
        model=chat_model,
        tools=get_available_tools(
            model_name=model_name,
            groups=agent_config.tool_groups if agent_config else None,
            subagent_enabled=params.subagent_enabled,
            mode=params.mode,
        ),
        middleware=_build_middlewares(
            config,
            model_name=model_name,
            agent_name=params.agent_name,
            model_router=router,
        ),
        system_prompt=prompt_template_fn(
            subagent_enabled=params.subagent_enabled,
            max_concurrent_subagents=params.max_concurrent_subagents,
            agent_name=params.agent_name,
            background_followup=params.background_followup,
            current_turn_text=current_turn_text,
        ),
        state_schema=ThreadState,
    )
