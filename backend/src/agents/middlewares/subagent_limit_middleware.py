"""Middleware to enforce maximum concurrent subagent tool calls per model response."""

import logging
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.subagents_config import get_subagents_app_config
from src.models import ModelRouter
from src.subagents.executor import MAX_CONCURRENT_SUBAGENTS

logger = logging.getLogger(__name__)

_HELPER_SUBAGENT_TYPES = {
    "bash",
    "source-researcher",
    "docs-explorer",
    "comparison-dimension-researcher",
    "synthesis-reviewer",
}


def _clamp_subagent_limit(value: int) -> int:
    """Clamp subagent limit to the configured ``[min, max]`` range.

    Bounds live in ``subagents.min_concurrent_limit`` / ``subagents.max_concurrent_limit``
    so deployments on tighter hardware can widen or narrow them without editing this file.
    """
    cfg = get_subagents_app_config()
    lo = max(1, int(cfg.min_concurrent_limit))
    hi = max(lo, int(cfg.max_concurrent_limit))
    return max(lo, min(hi, value))


class SubagentLimitMiddleware(AgentMiddleware[AgentState]):
    """Truncates excess 'task' tool calls from a single model response.

    When an LLM generates more than max_concurrent parallel task tool calls
    in one response, this middleware keeps only the first max_concurrent and
    discards the rest. This is more reliable than prompt-based limits.

    Args:
        max_concurrent: Maximum number of concurrent subagent calls allowed.
            Defaults to MAX_CONCURRENT_SUBAGENTS (3). Clamped to [2, 4].
    """

    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT_SUBAGENTS,
        *,
        router: ModelRouter | None = None,
        requested_model: str | None = None,
        max_primary_per_turn: int = 1,
    ):
        super().__init__()
        self.max_concurrent = _clamp_subagent_limit(max_concurrent)
        self._router = router
        self._requested_model = requested_model
        self._max_primary_per_turn = max(1, max_primary_per_turn)

    def _target_endpoint(self, tool_call: dict[str, Any]) -> str:
        if tool_call.get("name") != "task":
            return "primary"
        subagent_type = str((tool_call.get("args") or {}).get("subagent_type") or "general-purpose")
        stage = "subagent_triage" if subagent_type in _HELPER_SUBAGENT_TYPES else "subagent_code"
        if self._router is None:
            return "primary"
        return self._router.endpoint_label(stage, requested_model=self._requested_model)

    def _truncate_task_calls(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        deferred_existing = list(state.get("deferred_task_calls") or [])
        if not messages:
            if deferred_existing:
                return {"deferred_task_calls": deferred_existing}
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            if deferred_existing:
                reminder = HumanMessage(
                    name="task_deferred",
                    content=(
                        "<system_reminder>\n"
                        f"{len(deferred_existing)} deferred task(s) are queued and will be prioritized when task calls appear.\n"
                        "</system_reminder>"
                    ),
                )
                return {"messages": [reminder], "deferred_task_calls": deferred_existing}
            return None

        tool_calls = list(getattr(last_msg, "tool_calls", None) or [])
        if deferred_existing:
            # Prepend so previously-deferred calls get scheduling priority over any
            # freshly-emitted calls on this turn. Original IDs are preserved; they
            # are only valid on the rewritten AIMessage (the upstream message where
            # they originated was itself rewritten via model_copy to drop them).
            tool_calls = deferred_existing + tool_calls

        if not tool_calls:
            if deferred_existing:
                reminder = HumanMessage(
                    name="task_deferred",
                    content=(
                        "<system_reminder>\n"
                        f"{len(deferred_existing)} deferred task(s) are queued and will be prioritized when task calls appear.\n"
                        "</system_reminder>"
                    ),
                )
                return {"messages": [reminder], "deferred_task_calls": deferred_existing}
            return None

        # Count task tool calls
        task_indices = [i for i, tc in enumerate(tool_calls) if tc.get("name") == "task"]
        if len(task_indices) == 0 and not deferred_existing:
            return None

        primary_count = 0
        helper_count = 0
        total_task_kept = 0
        kept_tool_calls: list[dict[str, Any]] = []
        deferred_tool_calls: list[dict[str, Any]] = []
        deferred_reasons: list[str] = []
        for tool_call in tool_calls:
            if tool_call.get("name") != "task":
                kept_tool_calls.append(tool_call)
                continue
            if total_task_kept >= self.max_concurrent:
                deferred_tool_calls.append(tool_call)
                deferred_reasons.append("total concurrency limit")
                continue
            endpoint = self._target_endpoint(tool_call)
            if endpoint == "primary":
                if primary_count >= self._max_primary_per_turn:
                    deferred_tool_calls.append(tool_call)
                    deferred_reasons.append("primary endpoint limit")
                    continue
                primary_count += 1
            else:
                helper_count += 1
            total_task_kept += 1
            kept_tool_calls.append(tool_call)

        dropped_count = len(deferred_tool_calls)
        if dropped_count == 0:
            if deferred_existing:
                return {"deferred_task_calls": []}
            return None
        logger.warning(
            "Deferred %s task tool call(s) due to endpoint-aware scheduling (primary_per_turn=%s).",
            dropped_count,
            self._max_primary_per_turn,
        )
        if len(deferred_existing) and dropped_count >= len(deferred_existing):
            logger.warning(
                "Subagent deferral queue is not draining (existing=%s, dropped=%s) — "
                "consider raising max_primary_per_turn or splitting the run.",
                len(deferred_existing),
                dropped_count,
            )

        # Append a visible note to the AIMessage content so the LLM knows on the
        # next turn that some of its task calls were not executed and must be
        # re-submitted. Without this, the model silently loses work.
        dropped_descriptions = [tc.get("args", {}).get("description") or tc.get("name", "task") for tc in deferred_tool_calls]
        reason_text = ", ".join(sorted(set(deferred_reasons)))
        drop_note = (
            f"\n\n[System: {dropped_count} task call(s) were dropped because the "
            f"{reason_text} was exceeded. "
            f"Deferred tasks queued for next turns: "
            + ", ".join(f'"{d}"' for d in dropped_descriptions)
            + "]"
        )
        existing_content = last_msg.content or ""
        updated_msg = last_msg.model_copy(update={
            "tool_calls": kept_tool_calls,
            "content": existing_content + drop_note,
        })
        append_runtime_event(
            runtime,
            {
                "source": "subagent_limit_middleware",
                "decision": "task_deferred",
                "deferred_count": dropped_count,
                "total_deferred": dropped_count,
                "total_kept": total_task_kept,
                "fanout_executed_count": total_task_kept,
                "primary_executed": primary_count,
                "helper_executed": helper_count,
            },
        )
        return {"messages": [updated_msg], "deferred_task_calls": deferred_tool_calls}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._truncate_task_calls(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._truncate_task_calls(state, runtime)
