"""Evaluator middleware for terminal verification in Plan mode."""

from __future__ import annotations

import asyncio
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

_EVALUATOR_PROMPT_TEMPLATE = (
    "You are a strict evaluator for Plan mode. Respond with:\n"
    "VERDICT: PASS or FAIL\n"
    "CRITIQUE: <one concise paragraph>\n\n"
    "Enforcement rules:\n"
    "- A planning turn is only valid when both artifacts exist:\n"
    "  1) /mnt/user-data/workspace/plan.md\n"
    "  2) /mnt/user-data/workspace/plans/plan-*.md (timestamped trace artifact)\n"
    "- If artifacts are missing or stale, return FAIL and instruct the agent to continue and create fresh plan artifacts now.\n"
    "- Do not suggest recovering from previous plans; require creating a fresh plan turn artifact pair.\n\n"
    "Plan title: {plan_title}\n"
    "Plan summary: {plan_summary}\n\n"
    "Candidate response:\n{candidate_response}\n"
)


class EvaluatorState(AgentState):
    plan: NotRequired[dict | None]
    eval_attempts: NotRequired[int]
    todo_graph: NotRequired[dict | None]
    handoff_artifacts: NotRequired[list[str] | None]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _message_type(message: Any) -> str:
    raw = getattr(message, "type", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        val = message.get("type")
        if isinstance(val, str):
            return val
    return ""


def _message_name(message: Any) -> str:
    raw = getattr(message, "name", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        val = message.get("name")
        if isinstance(val, str):
            return val
    return ""


def _latest_real_ai_answer(messages: list[Any]) -> str:
    """Walk backwards to the most recent genuine AI response, skipping synthetic
    HumanMessages injected by the evaluator/planner pipeline.

    ``messages[-1]`` is unreliable: on retry turns it's typically a
    ``HumanMessage(name="evaluator_feedback", ...)`` from the prior cycle, and
    using that content as the "latest answer" lets evaluator critique trigger
    on its own echo (e.g. the 400-char draft-mode guard at line ~165).
    """
    for message in reversed(messages):
        if _message_type(message) != "ai":
            continue
        text = _extract_text(getattr(message, "content", ""))
        if text.strip():
            return text
    return ""


def _has_successful_research_tool_use(messages: list[Any]) -> bool:
    for message in messages:
        if _message_type(message) != "tool":
            continue
        name = _message_name(message)
        if name not in {"web_search", "task"}:
            continue
        body = _extract_text(getattr(message, "content", ""))
        if not body or "[plan_gate]" in body:
            continue
        if len(body.strip()) > 80:
            return True
    return False


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

    def _has_incomplete_todos(self, state: EvaluatorState) -> bool:
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if not isinstance(nodes, list) or not nodes:
            return False
        return any(node.get("status") != "completed" for node in nodes if isinstance(node, dict))

    def _pre_verify(self, state: EvaluatorState) -> list[str]:
        failures: list[str] = []
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if isinstance(nodes, list) and nodes:
            incomplete = [node["id"] for node in nodes if node.get("status") != "completed"]
            if incomplete:
                failures.append(
                    f"Plan has unfinished todos: {', '.join(incomplete)}. "
                    "Use mode-aware todo reconciliation: in work mode set done items to `status: completed`; "
                    "in plan draft mode keep items as `pending`/`in_progress`/`blocked` and refine structure. "
                    "Call `write_todos` with explicit ids and statuses "
                    "before producing a final answer. If `write_todos` is unavailable, explicitly report that "
                    "and list the intended status updates in plain text."
                )
        plan = state.get("plan") or {}
        plan_status = str(plan.get("status") or "draft").strip().lower()
        messages = state.get("messages", []) or []
        latest_ai = _latest_real_ai_answer(messages)

        if plan_status == "draft" and len(latest_ai.strip()) > 400:
            failures.append(
                "Plan is still draft but a substantive final answer was produced. "
                "Stop and wait for Execute Plan approval, then run research tools before answering."
            )

        domain = str(plan.get("domain") or "").strip().lower()
        if domain == "research" and plan_status in {"approved", "executing", "completed"}:
            if not _has_successful_research_tool_use(messages):
                failures.append(
                    "Research plan requires evidence from successful `web_search` or `task` tool results. "
                    "Run research tools after plan approval before producing the final synthesis."
                )

        plan_path = plan.get("plan_path")
        latest_alias_path = plan.get("latest_alias_path")
        thread_data = state.get("thread_data") or {}
        if self._handoffs_config.enabled:
            if not plan_path or not latest_alias_path:
                failures.append(
                    "Plan artifacts are incomplete: expected both versioned `plans/plan-*.md` and latest alias `plan.md` paths in plan state. Continue planning and create both now."
                )
            else:
                resolved_plan_path = replace_virtual_path(str(plan_path), thread_data)
                resolved_alias_path = replace_virtual_path(str(latest_alias_path), thread_data)
                versioned_exists = Path(resolved_plan_path).exists()
                alias_exists = Path(resolved_alias_path).exists()
                plan_path_text = str(plan_path).strip()
                alias_path_text = str(latest_alias_path).strip()
                if "/workspace/plans/plan-" not in plan_path_text:
                    failures.append(
                        "Versioned plan trace artifact path is invalid. Continue planning and write a fresh timestamped plan file under `/mnt/user-data/workspace/plans/`."
                    )
                if not alias_path_text.endswith("/workspace/plan.md"):
                    failures.append(
                        "Latest plan alias path is invalid. Continue planning and update `/mnt/user-data/workspace/plan.md` for this turn."
                    )
                if not versioned_exists or not alias_exists:
                    failures.append(
                        "Required plan artifacts are missing on disk (`plan.md` + timestamped `plans/plan-*.md`). Continue planning and create both for this turn."
                    )

        if domain == "research" and isinstance(nodes, list):
            synthesis_todos = [
                str(node.get("id") or "")
                for node in nodes
                if node.get("status") == "completed"
                and any(token in str(node.get("content") or "").lower() for token in ("synth", "report", "write", "deliver"))
            ]
            if synthesis_todos and not _has_successful_research_tool_use(messages):
                failures.append(
                    "Synthesis/report todos are marked complete without ingested research tool output."
                )
        return failures

    def _evaluate_llm(self, state: EvaluatorState) -> tuple[bool, str]:
        messages = state.get("messages", []) or []
        plan = state.get("plan") or {}
        latest_ai = _latest_real_ai_answer(messages)
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
                tail = upper.split(":", 1)[1].strip().split() if ":" in upper else []
                verdict = tail[0] if tail else None
                break
        # Treat empty `VERDICT:` (no value after the colon) the same as missing —
        # otherwise `passed = "" == "PASS"` silently downgrades to FAIL.
        if not verdict:
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
        # Evaluator must not block todo DAG completion. Let todo recovery and
        # execution middlewares drive todos to terminal state first.
        if self._has_incomplete_todos(state):
            append_runtime_event(runtime, {"source": "evaluator_middleware", "decision": "evaluation_skipped_incomplete_todos"})
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
            plan_update = {
                **plan,
                "evaluation_status": "failed",
                "latest_evaluator_report": critique,
                "latest_evaluator_verdict": "FAIL",
            }
            if self._handoffs_config.enabled:
                report_path = _write_report(workspace_path, self._handoffs_config.dir, report)
                if report_path:
                    # Convert physical path to virtual so frontend artifact URL builder
                    # produces /mnt/user-data/... and the artifact router serves it.
                    virtual_report_path = to_virtual_path(report_path, thread_data) or report_path
                    artifacts.append(virtual_report_path)
                    plan_update["evaluator_report_path"] = virtual_report_path
            append_runtime_event(runtime, {"source": "evaluator_middleware", "decision": "rule_fail", "failures": failures})
            return {
                "eval_attempts": attempts + 1,
                "plan": plan_update,
                "messages": [HumanMessage(name="evaluator_feedback", content=f"<evaluator_feedback>\n{critique}\n</evaluator_feedback>")],
                "handoff_artifacts": artifacts,
            }

        passed, critique = self._evaluate_llm(state)
        verdict = "PASS" if passed else "FAIL"
        report = f"# Evaluator Report\n\n- Timestamp: {_utc_now_iso()}\n- Verdict: {verdict}\n\n## Critique\n{critique}\n"
        plan_update = {
            **plan,
            "evaluation_status": "passed" if passed else "failed",
            "latest_evaluator_report": critique,
            "latest_evaluator_verdict": verdict,
        }
        if self._handoffs_config.enabled:
            report_path = _write_report(workspace_path, self._handoffs_config.dir, report)
            if report_path:
                virtual_report_path = to_virtual_path(report_path, thread_data) or report_path
                artifacts.append(virtual_report_path)
                plan_update["evaluator_report_path"] = virtual_report_path
        append_runtime_event(runtime, {"source": "evaluator_middleware", "decision": "llm_verdict", "verdict": verdict})

        if passed:
            return {
                "eval_attempts": attempts + 1,
                "plan": plan_update,
                "handoff_artifacts": artifacts,
            }

        next_attempt = attempts + 1
        if next_attempt >= self._max_attempts:
            return {
                "eval_attempts": next_attempt,
                "plan": {**plan_update, "evaluation_status": "max_attempts_reached"},
                "handoff_artifacts": artifacts,
            }
        return {
            "eval_attempts": next_attempt,
            "plan": plan_update,
            "messages": [HumanMessage(name="evaluator_feedback", content=f"<evaluator_feedback>\n{critique}\n</evaluator_feedback>")],
            "handoff_artifacts": artifacts,
        }

    @override
    async def aafter_model(self, state: EvaluatorState, runtime: Runtime) -> dict | None:
        return await asyncio.to_thread(self.after_model, state, runtime)
