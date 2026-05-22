"""Recursion-budget pivot middleware.

When the agent has consumed a configurable fraction of its ``recursion_limit``,
call an evaluator LLM to decide whether to inject a steering directive that
redirects the remaining budget. Designed for local-model long-running agents
where the cost of "pause and reflect" is negligible and hard ``GraphRecursionError``
crashes are the wrong shape.

Scope: lead agent only. Subagents keep their existing ``max_turns``-derived limit.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.recursion_pivot_config import RecursionPivotConfig, get_recursion_pivot_config
from src.models import ModelRouter, create_chat_model

logger = logging.getLogger(__name__)


class RecursionPivotState(AgentState):
    recursion_pivot: NotRequired[dict | None]


_EVALUATOR_SYSTEM_PROMPT = (
    "You are a course-correction evaluator for a long-running agent that is approaching its "
    "recursion budget. The agent will hit a hard step ceiling soon. Your job is to decide whether "
    "the agent should keep its current course or pivot to a different approach to finish in the "
    "remaining budget.\n\n"
    "Respond in exactly this format:\n"
    "DECISION: KEEP or PIVOT\n"
    "DIRECTIVE: <one short paragraph of guidance for the agent>\n"
    "REASON: <one sentence explaining the call>\n\n"
    "Rules:\n"
    "- Choose KEEP if the agent is making real progress and just needs more turns within its current strategy.\n"
    "- Choose PIVOT if the agent is stuck, off-task, or its current strategy cannot finish in the remaining steps.\n"
    "- The DIRECTIVE is read by the agent as authoritative guidance — be specific and actionable.\n"
)


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content) if content is not None else ""


def _summarize_recent_messages(messages: list[Any], *, tail: int = 6, per_message_chars: int = 600) -> str:
    if not messages:
        return "(no messages)"
    snippets: list[str] = []
    for msg in messages[-tail:]:
        msg_type = getattr(msg, "type", "?")
        name = getattr(msg, "name", None) or msg_type
        text = _extract_text(getattr(msg, "content", "")).strip()
        if not text and getattr(msg, "tool_calls", None):
            tool_call_names = [tc.get("name", "?") for tc in msg.tool_calls if isinstance(tc, dict)]
            text = f"(tool_calls: {', '.join(tool_call_names)})"
        if len(text) > per_message_chars:
            text = text[:per_message_chars] + "…"
        snippets.append(f"[{name}] {text}")
    return "\n".join(snippets)


def _parse_evaluator_response(raw: str) -> tuple[bool, str, str]:
    """Parse the evaluator LLM response.

    Returns (pivot, directive, reason). ``pivot`` is True iff DECISION is PIVOT.
    Falls back to ``pivot=False`` when the response is unparseable — keep course
    is the safe default.
    """
    decision: str | None = None
    directive_parts: list[str] = []
    reason_parts: list[str] = []
    current: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("DECISION:"):
            value = stripped.split(":", 1)[1].strip().split()[0].upper() if ":" in stripped else ""
            decision = value
            current = "decision"
        elif upper.startswith("DIRECTIVE:"):
            tail = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            if tail:
                directive_parts.append(tail)
            current = "directive"
        elif upper.startswith("REASON:"):
            tail = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            if tail:
                reason_parts.append(tail)
            current = "reason"
        elif current == "directive":
            directive_parts.append(stripped)
        elif current == "reason":
            reason_parts.append(stripped)
    pivot = decision == "PIVOT"
    directive = " ".join(directive_parts).strip()
    reason = " ".join(reason_parts).strip()
    return pivot, directive, reason


class RecursionBudgetPivotMiddleware(AgentMiddleware[RecursionPivotState]):
    """Inject evaluator-driven steering when the recursion budget is nearly consumed."""

    state_schema = RecursionPivotState

    def __init__(
        self,
        *,
        router: ModelRouter,
        requested_model: str | None = None,
        config: RecursionPivotConfig | None = None,
    ):
        super().__init__()
        self._router = router
        self._requested_model = requested_model
        self._config = config or get_recursion_pivot_config()

    def _step_count(self, state: RecursionPivotState) -> int:
        messages = state.get("messages", []) or []
        # One "step" = one model invocation. Each step typically produces 1 AI
        # message + 1 tool/human follow-up, so messages // 2 is a faithful proxy.
        return max(0, len(messages) // 2)

    def _recursion_limit(self, runtime: Runtime) -> int | None:
        config = getattr(runtime, "config", None)
        if not isinstance(config, dict):
            return None
        value = config.get("recursion_limit")
        if isinstance(value, int) and value > 0:
            return value
        return None

    def _next_threshold(self, *, step: int, recursion_limit: int, fired: set[int]) -> int | None:
        """Return the index of the next threshold to fire (or None).

        Thresholds are sorted ascending in the config validator. We fire each
        one at most once and only when the step count has actually crossed it.
        """
        for idx, fraction in enumerate(self._config.thresholds):
            if idx in fired:
                continue
            crossover = int(recursion_limit * fraction)
            if step >= crossover:
                return idx
        return None

    def _invoke_evaluator(self, prompt: str) -> str:
        model_name = self._config.evaluator_model or self._router.resolve(
            "evaluator", requested_model=self._requested_model
        )
        model = create_chat_model(name=model_name, thinking_enabled=False)
        # Thread-pool timeout so a hung local model doesn't lock the whole run.
        # The LLM call itself can't be cancelled mid-flight, but the run continues
        # without the directive and the daemon thread is abandoned.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: _extract_text(model.invoke(prompt).content))
            return future.result(timeout=self._config.evaluator_timeout_seconds)

    def _build_prompt(self, state: RecursionPivotState, runtime: Runtime, *, step: int, recursion_limit: int, pivot_number: int) -> str:
        runtime_context = getattr(runtime, "context", None) or {}
        original_request = (
            runtime_context.get("original_user_request")
            or runtime_context.get("current_turn_text")
            or "(not provided)"
        )
        messages = state.get("messages", []) or []
        recent = _summarize_recent_messages(messages)
        plan = state.get("plan") or {}
        todos = state.get("todos") or []
        todo_summary = (
            ", ".join(f"{t.get('id', '?')}={t.get('status', '?')}" for t in todos[:20] if isinstance(t, dict))
            if todos
            else "(none)"
        )
        remaining = max(0, recursion_limit - step)

        return (
            f"{_EVALUATOR_SYSTEM_PROMPT}\n\n"
            f"=== RUN STATE ===\n"
            f"Step: {step} / {recursion_limit} (remaining: {remaining})\n"
            f"Pivot number: {pivot_number} of {len(self._config.thresholds)}\n"
            f"Plan title: {plan.get('title', 'N/A')}\n"
            f"Todos: {todo_summary}\n\n"
            f"=== ORIGINAL USER REQUEST ===\n{original_request}\n\n"
            f"=== RECENT MESSAGES ===\n{recent}\n"
        )

    @override
    def before_model(self, state: RecursionPivotState, runtime: Runtime) -> dict | None:
        cfg = self._config
        if not cfg.enabled:
            return None

        recursion_limit = self._recursion_limit(runtime)
        if recursion_limit is None or recursion_limit < cfg.min_recursion_limit:
            return None

        step = self._step_count(state)
        pivot_state = dict(state.get("recursion_pivot") or {})
        fired_indices = set(pivot_state.get("fired_thresholds") or [])

        threshold_idx = self._next_threshold(step=step, recursion_limit=recursion_limit, fired=fired_indices)
        if threshold_idx is None:
            return None

        fraction = cfg.thresholds[threshold_idx]
        pivot_number = threshold_idx + 1
        fired_indices.add(threshold_idx)
        pivot_state["fired_thresholds"] = sorted(fired_indices)
        pivot_state["last_pivot_step"] = step
        pivot_state["last_pivot_fraction"] = fraction

        prompt = self._build_prompt(
            state, runtime,
            step=step, recursion_limit=recursion_limit, pivot_number=pivot_number,
        )

        try:
            raw_response = self._invoke_evaluator(prompt)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "recursion_pivot evaluator timed out after %ss at step %s/%s (pivot %s)",
                cfg.evaluator_timeout_seconds, step, recursion_limit, pivot_number,
            )
            append_runtime_event(
                runtime,
                {"source": "recursion_pivot", "signal": "evaluator_timeout", "step": step, "pivot": pivot_number},
            )
            return self._handle_evaluator_failure(pivot_state, step, pivot_number, recursion_limit)
        except Exception as exc:  # noqa: BLE001 — evaluator can fail in many ways; we must never break the run
            logger.warning("recursion_pivot evaluator failed: %s", exc)
            append_runtime_event(
                runtime,
                {"source": "recursion_pivot", "signal": "evaluator_error", "step": step, "pivot": pivot_number, "error": str(exc)},
            )
            return self._handle_evaluator_failure(pivot_state, step, pivot_number, recursion_limit)

        pivot, directive, reason = _parse_evaluator_response(raw_response)
        pivot_state["last_decision"] = "PIVOT" if pivot else "KEEP"
        pivot_state["last_reason"] = reason

        append_runtime_event(
            runtime,
            {
                "source": "recursion_pivot",
                "signal": "evaluator_decision",
                "step": step,
                "recursion_limit": recursion_limit,
                "pivot_number": pivot_number,
                "decision": pivot_state["last_decision"],
                "reason": reason,
            },
        )

        if not pivot or not directive:
            # KEEP course or empty directive — record threshold consumption and return.
            return {"recursion_pivot": pivot_state}

        remaining = max(0, recursion_limit - step)
        message = HumanMessage(
            name="recursion_pivot_steering",
            content=(
                f"<system_reminder source='recursion_pivot' "
                f"pivot='{pivot_number}_of_{len(cfg.thresholds)}' "
                f"step='{step}' recursion_limit='{recursion_limit}' remaining_steps='{remaining}'>\n"
                f"You have used {step} of {recursion_limit} steps. An evaluator reviewed your progress and "
                f"recommends a course change to finish in the remaining {remaining} steps:\n\n"
                f"{directive}\n\n"
                f"Adopt this guidance for your next actions.\n"
                f"</system_reminder>"
            ),
        )
        return {"recursion_pivot": pivot_state, "messages": [message]}

    def _handle_evaluator_failure(self, pivot_state: dict, step: int, pivot_number: int, recursion_limit: int) -> dict:
        pivot_state["last_decision"] = "FAILED"
        if self._config.on_evaluator_failure == "terminate":
            warning = HumanMessage(
                name="recursion_pivot_warning",
                content=(
                    f"<system_warning source='recursion_pivot' pivot='{pivot_number}'>\n"
                    f"Evaluator failed at step {step}/{recursion_limit}. Terminating run as configured.\n"
                    f"</system_warning>"
                ),
            )
            return {"recursion_pivot": pivot_state, "messages": [warning], "jump_to": "end"}
        return {"recursion_pivot": pivot_state}

    @override
    async def abefore_model(self, state: RecursionPivotState, runtime: Runtime) -> dict | None:
        return self.before_model(state, runtime)


# LangChain reads __can_jump_to__ to wire conditional edges; declare so the
# `on_evaluator_failure='terminate'` branch can actually end the run.
RecursionBudgetPivotMiddleware.before_model.__can_jump_to__ = ["end"]  # type: ignore[attr-defined]
RecursionBudgetPivotMiddleware.abefore_model.__can_jump_to__ = ["end"]  # type: ignore[attr-defined]
