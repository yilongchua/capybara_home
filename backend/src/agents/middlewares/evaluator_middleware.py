"""Evaluator middleware for terminal verification in Plan mode."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.handoffs_config import HandoffsConfig
from src.models import ModelRouter, create_chat_model
from src.sandbox.path_mapping import replace_virtual_path, to_virtual_path

_EVALUATOR_PROMPT_TEMPLATE = "You are a strict evaluator. Respond with:\nVERDICT: PASS or FAIL\nCRITIQUE: <one concise paragraph>\n\nPlan title: {plan_title}\nPlan summary: {plan_summary}\n\nCandidate response:\n{candidate_response}\n"


class EvaluatorState(AgentState):
    plan: NotRequired[dict | None]
    eval_attempts: NotRequired[int]
    todo_graph: NotRequired[dict | None]
    handoff_artifacts: NotRequired[list[str] | None]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
    return str(content)


def _write_report(workspace_path: str | None, handoff_dir: str, body: str) -> str | None:
    if not workspace_path:
        return None
    root = Path(workspace_path) / handoff_dir
    root.mkdir(parents=True, exist_ok=True)
    path = root / "report.md"
    path.write_text(body, encoding="utf-8")
    return str(path)


class EvaluatorMiddleware(AgentMiddleware[EvaluatorState]):
    """Runs deterministic pre-checks then optional LLM evaluator critique."""

    state_schema = EvaluatorState

    def __init__(
        self,
        *,
        router: ModelRouter,
        requested_model: str | None,
        max_attempts: int,
        handoffs_config: HandoffsConfig,
    ):
        super().__init__()
        self._router = router
        self._requested_model = requested_model
        self._max_attempts = max_attempts
        self._handoffs_config = handoffs_config

    def _is_terminal_ai_response(self, state: EvaluatorState) -> bool:
        messages = state.get("messages", []) or []
        if not messages:
            return False
        last = messages[-1]
        if getattr(last, "type", None) != "ai":
            return False
        if getattr(last, "tool_calls", None):
            return False
        return bool(_extract_text(getattr(last, "content", "")).strip())

    def _pre_verify(self, state: EvaluatorState) -> list[str]:
        failures: list[str] = []
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if isinstance(nodes, list) and nodes:
            incomplete = [node["id"] for node in nodes if node.get("status") != "completed"]
            if incomplete:
                failures.append(
                    f"Plan has unfinished todos: {', '.join(incomplete)}. "
                    "Call `write_todos` with these ids set to `status: completed` (or `blocked` with a reason) "
                    "before producing a final answer. If `write_todos` is unavailable, explicitly report that "
                    "and list the intended status updates in plain text."
                )
        plan = state.get("plan") or {}
        plan_path = plan.get("plan_path")
        thread_data = state.get("thread_data") or {}
        if self._handoffs_config.enabled and plan_path:
            resolved_plan_path = replace_virtual_path(str(plan_path), thread_data)
            if not Path(resolved_plan_path).exists():
                failures.append("Planner handoff artifact plan.md is missing.")
        return failures

    def _evaluate_llm(self, state: EvaluatorState) -> tuple[bool, str]:
        messages = state.get("messages", []) or []
        plan = state.get("plan") or {}
        latest_ai = _extract_text(getattr(messages[-1], "content", "")) if messages else ""
        model_name = self._router.resolve("evaluator", requested_model=self._requested_model)
        model = create_chat_model(name=model_name, thinking_enabled=False)
        prompt = _EVALUATOR_PROMPT_TEMPLATE.format(
            plan_title=plan.get("title", "N/A"),
            plan_summary=plan.get("summary", ""),
            candidate_response=latest_ai,
        )
        text = _extract_text(model.invoke(prompt).content).strip()
        # Parse the first VERDICT: line specifically so substrings elsewhere in the
        # critique cannot flip the decision (e.g., "... not VERDICT: PASS").
        verdict: str | None = None
        for line in text.splitlines():
            upper = line.strip().upper()
            if upper.startswith("VERDICT:"):
                verdict = upper.split(":", 1)[1].strip().split()[0] if ":" in upper else None
                break
        if verdict is None:
            first_line = text.splitlines()[0].strip().upper() if text else ""
            if first_line in {"PASS", "FAIL"}:
                verdict = first_line
        passed = verdict == "PASS"
        critique = text
        return passed, critique

    @override
    def after_model(self, state: EvaluatorState, runtime: Runtime) -> dict | None:
        plan = state.get("plan") or {}
        if not plan:
            return None
        if plan.get("evaluation_status") == "passed":
            return None
        if not self._is_terminal_ai_response(state):
            return None

        attempts = int(state.get("eval_attempts", 0))
        if attempts >= self._max_attempts:
            return None

        failures = self._pre_verify(state)
        thread_data = state.get("thread_data") or {}
        workspace_path = thread_data.get("workspace_path")
        artifacts: list[str] = []
        if failures:
            critique = "Evaluator pre-verifier found issues:\n" + "\n".join(f"- {item}" for item in failures)
            report = f"# Evaluator Report\n\n- Timestamp: {_utc_now_iso()}\n- Verdict: FAIL (rule-based pre-verifier)\n\n## Findings\n" + "\n".join(f"- {item}" for item in failures) + "\n"
            if self._handoffs_config.enabled:
                report_path = _write_report(workspace_path, self._handoffs_config.dir, report)
                if report_path:
                    # Convert physical path to virtual so frontend artifact URL builder
                    # produces /mnt/user-data/... and the artifact router serves it.
                    artifacts.append(to_virtual_path(report_path, thread_data) or report_path)
            append_runtime_event(runtime, {"source": "evaluator_middleware", "decision": "rule_fail", "failures": failures})
            return {
                "eval_attempts": attempts + 1,
                "messages": [HumanMessage(name="evaluator_feedback", content=f"<evaluator_feedback>\n{critique}\n</evaluator_feedback>")],
                "handoff_artifacts": artifacts,
            }

        passed, critique = self._evaluate_llm(state)
        verdict = "PASS" if passed else "FAIL"
        report = f"# Evaluator Report\n\n- Timestamp: {_utc_now_iso()}\n- Verdict: {verdict}\n\n## Critique\n{critique}\n"
        if self._handoffs_config.enabled:
            report_path = _write_report(workspace_path, self._handoffs_config.dir, report)
            if report_path:
                artifacts.append(to_virtual_path(report_path, thread_data) or report_path)
        append_runtime_event(runtime, {"source": "evaluator_middleware", "decision": "llm_verdict", "verdict": verdict})

        if passed:
            return {
                "eval_attempts": attempts + 1,
                "plan": {**plan, "evaluation_status": "passed"},
                "handoff_artifacts": artifacts,
            }

        next_attempt = attempts + 1
        if next_attempt >= self._max_attempts:
            return {
                "eval_attempts": next_attempt,
                "plan": {**plan, "evaluation_status": "max_attempts_reached"},
                "handoff_artifacts": artifacts,
            }
        return {
            "eval_attempts": next_attempt,
            "messages": [HumanMessage(name="evaluator_feedback", content=f"<evaluator_feedback>\n{critique}\n</evaluator_feedback>")],
            "handoff_artifacts": artifacts,
        }

    @override
    async def aafter_model(self, state: EvaluatorState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)
