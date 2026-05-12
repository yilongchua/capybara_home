"""Plan evaluator middleware — fast quality check on planner output before execution starts.

Async path: `abefore_model` runs the evaluator LLM via `model.ainvoke` so the
asyncio loop is free while the local LLM produces tokens. The sync path keeps
the daemon-thread fallback for embedded callers.

Pre-Phase-1 implementation delegated `abefore_model` to `before_model` which
called `Thread.join(timeout)` from inside an async hook — that blocked the
event loop and was the root cause of `decision=timeout_skipped` firing
deterministically when the planner had already consumed the cycle's budget
(see thread-cd90decb finding #2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event
from src.agents.middlewares.todo_dag_middleware import _legacy_todos, _materialize_ready_ids, normalize_todo_nodes
from src.config.evaluator_config import get_evaluator_config
from src.models import ModelRouter, create_chat_model

logger = logging.getLogger(__name__)

_PLAN_EVAL_PROMPT = """\
You are a plan quality reviewer. Evaluate the following execution plan.

Return ONLY valid JSON — no prose, no markdown fences:
{
  "ok": true,
  "issues": [],
  "revised_todos": null
}

If the plan looks correct, return {"ok": true} and nothing else.
If there are genuine structural problems:
- List each issue briefly in "issues" (max 3 issues)
- If you can fix the plan, provide "revised_todos" in the EXACT same format as the input todos
- Otherwise leave "revised_todos" as null

Plan to evaluate:
Title: {title}
Domain: {domain}
Summary: {summary}
Todos:
{todos_formatted}

Check ONLY for hard problems:
1. Circular dependencies (A depends on B, B depends on A)
2. Missing obvious prerequisite steps (e.g., auth step before API calls)
3. Missing final delivery/synthesis step for multi-step plans

Be lenient — only flag genuine blockers, not stylistic preferences.
"""


class PlanEvaluatorState(AgentState):
    plan: NotRequired[dict | None]
    todo_graph: NotRequired[dict | None]
    plan_evaluated: NotRequired[bool]
    complexity_tier: NotRequired[str | None]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _format_todos_for_eval(nodes: list[dict[str, Any]]) -> str:
    lines = []
    for node in nodes:
        dep_str = f", depends_on={node.get('depends_on')}" if node.get("depends_on") else ""
        lines.append(f"  [{node.get('id')}] {node.get('content')}{dep_str}")
    return "\n".join(lines)


def _run_with_timeout(fn, timeout: float) -> Any:
    """Run fn() in a daemon thread with a hard timeout."""
    result_holder: list[Any] = [None]
    exc_holder: list[BaseException | None] = [None]

    def worker():
        try:
            result_holder[0] = fn()
        except Exception as e:  # noqa: BLE001
            exc_holder[0] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise TimeoutError(f"Plan evaluator timed out after {timeout}s")
    if exc_holder[0] is not None:
        raise exc_holder[0]
    return result_holder[0]


class PlanEvaluatorMiddleware(AgentMiddleware[PlanEvaluatorState]):
    """Fast LLM quality check on planner output before execution starts.

    Runs after PlannerMiddleware creates the plan. Uses the planner model
    with a configurable hard timeout. If it times out or the LLM approves the
    plan, execution proceeds unchanged. If issues are found and revised_todos
    provided, the todo_graph is updated in place.
    """

    state_schema = PlanEvaluatorState

    def __init__(self, *, router: ModelRouter, requested_model: str | None, timeout_seconds: float | None = None):
        super().__init__()
        self._router = router
        self._requested_model = requested_model
        self._timeout_seconds = float(timeout_seconds if timeout_seconds is not None else get_evaluator_config().plan_evaluator_timeout_seconds)

    def _should_evaluate(self, state: PlanEvaluatorState) -> bool:
        if state.get("plan_evaluated"):
            return False
        todo_graph = state.get("todo_graph")
        if not todo_graph:
            return False
        if state.get("complexity_tier") == "trivial":
            return False
        plan = state.get("plan")
        return bool(plan)

    def _build_prompt_and_model(self, state: PlanEvaluatorState) -> tuple[str, str, list[dict[str, Any]]] | None:
        plan = state["plan"]
        todo_graph = state["todo_graph"]
        nodes: list[dict[str, Any]] = todo_graph.get("nodes") or []  # type: ignore[assignment]

        if not nodes:
            return None

        title = plan.get("title", "Execution Plan")
        summary = plan.get("summary", "")
        domain = str(state.get("complexity_tier") or "generic")
        todos_formatted = _format_todos_for_eval(nodes)

        prompt = _PLAN_EVAL_PROMPT.replace("{title}", title).replace("{domain}", domain).replace("{summary}", summary).replace("{todos_formatted}", todos_formatted)
        model_name = self._router.resolve("planner", requested_model=self._requested_model)
        return prompt, model_name, nodes

    def _process_llm_output(self, raw: str, runtime: Runtime, model_name: str) -> dict | None:
        # Strip accidental markdown fences
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            payload = json.loads(raw)
        except Exception:
            logger.warning("Plan evaluator returned non-JSON; treating as ok")
            return {"plan_evaluated": True}

        ok = bool(payload.get("ok", True))
        issues = list(payload.get("issues") or [])

        if ok or not issues:
            append_runtime_event(runtime, {"source": "plan_evaluator", "decision": "ok", "model": model_name})
            return {"plan_evaluated": True}

        revised_todos = payload.get("revised_todos")
        if not revised_todos or not isinstance(revised_todos, list):
            append_runtime_event(
                runtime,
                {
                    "source": "plan_evaluator",
                    "decision": "issues_no_revision",
                    "issues": issues,
                    "model": model_name,
                },
            )
            return {"plan_evaluated": True}

        try:
            new_nodes = normalize_todo_nodes(revised_todos)
            ready_ids = _materialize_ready_ids(new_nodes)
        except Exception:
            logger.warning("Plan evaluator provided invalid revised_todos; ignoring revision")
            append_runtime_event(
                runtime,
                {
                    "source": "plan_evaluator",
                    "decision": "revision_invalid",
                    "issues": issues,
                    "model": model_name,
                },
            )
            return {"plan_evaluated": True}

        append_runtime_event(
            runtime,
            {
                "source": "plan_evaluator",
                "decision": "revised",
                "issues": issues,
                "new_todo_count": len(new_nodes),
                "model": model_name,
            },
        )

        return {
            "plan_evaluated": True,
            "todo_graph": {
                "nodes": new_nodes,
                "ready_ids": ready_ids,
                "updated_at": _utc_now_iso(),
            },
            "todos": _legacy_todos(new_nodes),
        }

    @override
    def before_model(self, state: PlanEvaluatorState, runtime: Runtime) -> dict | None:
        if not self._should_evaluate(state):
            return None

        prepared = self._build_prompt_and_model(state)
        if prepared is None:
            return {"plan_evaluated": True}
        prompt, model_name, _nodes = prepared

        def _call_llm() -> str:
            model = create_chat_model(name=model_name, thinking_enabled=False)
            response = model.invoke(prompt)
            raw = response.content if isinstance(response.content, str) else str(response.content)
            return raw.strip()

        try:
            raw = _run_with_timeout(_call_llm, timeout=self._timeout_seconds)
        except TimeoutError:
            logger.warning("Plan evaluator timed out; skipping")
            append_runtime_event(runtime, {"source": "plan_evaluator", "decision": "timeout_skipped"})
            return {"plan_evaluated": True}
        except Exception:
            logger.exception("Plan evaluator LLM call failed; skipping")
            return {"plan_evaluated": True}

        return self._process_llm_output(raw, runtime, model_name)

    @override
    async def abefore_model(self, state: PlanEvaluatorState, runtime: Runtime) -> dict | None:
        if not self._should_evaluate(state):
            return None

        prepared = self._build_prompt_and_model(state)
        if prepared is None:
            return {"plan_evaluated": True}
        prompt, model_name, _nodes = prepared

        async def _acall_llm() -> str:
            model = create_chat_model(name=model_name, thinking_enabled=False)
            response = await model.ainvoke(prompt)
            raw = response.content if isinstance(response.content, str) else str(response.content)
            return raw.strip()

        try:
            raw = await asyncio.wait_for(_acall_llm(), timeout=self._timeout_seconds)
        except TimeoutError:
            logger.warning("Plan evaluator timed out; skipping")
            append_runtime_event(runtime, {"source": "plan_evaluator", "decision": "timeout_skipped"})
            return {"plan_evaluated": True}
        except Exception:
            logger.exception("Plan evaluator LLM call failed; skipping")
            return {"plan_evaluated": True}

        return self._process_llm_output(raw, runtime, model_name)
