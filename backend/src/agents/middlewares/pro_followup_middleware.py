"""Background follow-up scheduler for Plan mode."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.config import get_config, get_stream_writer
from langgraph.runtime import Runtime

from src.agents.background import submit_background_task
from src.agents.middlewares.message_selection import latest_message_text, latest_real_ai_answer
from src.agents.middlewares.runtime_events import append_runtime_event
from src.agents.thread_state import BackgroundFollowupJob

logger = logging.getLogger(__name__)

# Thread-safe store for background job failures so they can be surfaced to the
# user on the next model turn (since SSE writers are only usable inside a run).
_failed_jobs: dict[str, tuple[str, str]] = {}  # thread_id -> (job_id, error_msg)
_failed_jobs_lock = threading.Lock()
_MAX_FAILED_JOBS = 256


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _record_failed_job(thread_id: str, job_id: str, error_msg: str) -> None:
    with _failed_jobs_lock:
        _failed_jobs[thread_id] = (job_id, error_msg)
        while len(_failed_jobs) > _MAX_FAILED_JOBS:
            oldest_thread_id = next(iter(_failed_jobs))
            _failed_jobs.pop(oldest_thread_id, None)


class PlanFollowupState(AgentState):
    background_followups: NotRequired[list[BackgroundFollowupJob] | None]

def _run_background_followup(
    *,
    thread_id: str,
    job_id: str,
    requested_model_name: str | None,
    summary_prompt: str,
) -> None:
    from src.agents.middlewares.daemon_agent_invoke import invoke_client_agent_async
    from src.client import CapyHomeClient

    time.sleep(2.0)
    client = None
    try:
        client = CapyHomeClient(
            model_name=requested_model_name,
            thinking_enabled=True,
            subagent_enabled=True,
            plan_mode=False,
            auto_mode=False,
        )
        config = client._get_runnable_config(  # noqa: SLF001
            thread_id,
            model_name=requested_model_name,
            thinking_enabled=True,
            subagent_enabled=True,
        )
        config["configurable"].update(
            {
                "mode": "work",
                "background_followup": True,
                "plan_behavior": "work_background_followup",
            }
        )
        invoke_client_agent_async(
            client,
            {"messages": [HumanMessage(name="plan_followup_prompt", content=summary_prompt)]},
            config=config,
            context={
                "thread_id": thread_id,
                "mode": "work",
                "background_followup": True,
                "plan_behavior": "work_background_followup",
                "model_name": requested_model_name,
            },
        )
    except Exception as exc:
        logger.exception("Background Plan follow-up failed for thread %s", thread_id)
        # Surface the failure on the next model turn for this thread.
        _record_failed_job(thread_id, job_id, str(exc))
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()


class PlanFollowupMiddleware(AgentMiddleware[PlanFollowupState]):
    state_schema = PlanFollowupState

    def _has_plan_context(self, state: PlanFollowupState) -> bool:
        return bool(state.get("plan") or state.get("todo_graph"))

    @override
    def before_model(self, state: PlanFollowupState, runtime: Runtime) -> dict | None:
        runtime_context = getattr(runtime, "context", None) or {}
        mode = str(runtime_context.get("mode") or "").strip().lower() or "work"

        # Emit any recorded background-job failure as an SSE event so the frontend
        # can show an error notice.  The failure was recorded by the daemon thread
        # and can only be pushed once we're back inside a LangGraph execution context.
        thread_id = runtime_context.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            with _failed_jobs_lock:
                failed = _failed_jobs.pop(thread_id, None)
            if failed:
                failed_job_id, error_msg = failed
                try:
                    writer = get_stream_writer()
                    writer({
                        "type": "background_followup_failed",
                        "source": "plan_followup_middleware",
                        "job_id": failed_job_id,
                        "error": error_msg,
                    })
                except Exception:
                    logger.debug("Failed to emit background_followup_failed SSE for job %s", failed_job_id)

        return {
            "execution_intent": {
                "mode": mode,
                "plan_behavior": str(runtime_context.get("plan_behavior") or ("plan_foreground" if mode == "plan" else "work_interactive")),
                "allow_background_deepen": (
                    mode == "work"
                    and not bool(runtime_context.get("background_followup"))
                    and self._has_plan_context(state)
                    and not self._has_incomplete_todos(state)
                ),
                "max_primary_subagents": 1,
            }
        }

    def _is_terminal_answer(self, state: PlanFollowupState) -> bool:
        messages = state.get("messages", []) or []
        if not messages:
            return False
        last = messages[-1]
        if getattr(last, "type", None) != "ai":
            return False
        if getattr(last, "tool_calls", None):
            return False
        return bool(latest_real_ai_answer([last]))

    def _has_incomplete_todos(self, state: PlanFollowupState) -> bool:
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if not isinstance(nodes, list) or not nodes:
            return False
        return any(
            isinstance(node, dict) and node.get("status") not in {"completed", "blocked"}
            for node in nodes
        )

    @override
    def after_model(self, state: PlanFollowupState, runtime: Runtime) -> dict | None:
        runtime_context = getattr(runtime, "context", None) or {}
        if str(runtime_context.get("mode") or "").strip().lower() != "work":
            return None
        if bool(runtime_context.get("background_followup")):
            return None
        if not self._has_plan_context(state):
            return None
        plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
        plan_status = str(plan.get("status") or "").strip().lower()
        if plan_status != "completed":
            return None
        if str(plan.get("evaluation_status") or "").strip().lower() in {"failed", "max_attempts_reached"}:
            return None
        if str(plan.get("latest_evaluator_verdict") or "").strip().upper() == "FAIL":
            return None
        if self._has_incomplete_todos(state):
            return None
        if not self._is_terminal_answer(state):
            return None

        existing = list(state.get("background_followups") or [])
        if existing:
            return None

        thread_id = runtime_context.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None

        messages = state.get("messages", []) or []
        user_text = latest_message_text(messages, msg_type="human", skip_synthetic_human=True)
        answer_text = latest_real_ai_answer(messages)
        if not user_text or not answer_text:
            return None

        requested_model_name = (get_config().get("metadata") or {}).get("model_name")
        job_id = f"plan-followup-{int(time.time())}"
        summary_prompt = (
            "Continue the previous Work Mode answer in the background.\n"
            "Do not repeat the original answer. Add only meaningful follow-up value.\n"
            "Focus on evaluator critique, alternative-source verification, expanded comparison details, "
            "or a secondary research pass when useful.\n\n"
            f"Original user request:\n{user_text}\n\n"
            f"Foreground answer already delivered:\n{answer_text}\n"
        )
        submitted = submit_background_task(
            f"plan-followup-{thread_id[:8]}",
            _run_background_followup,
            thread_id=thread_id,
            job_id=job_id,
            requested_model_name=requested_model_name if isinstance(requested_model_name, str) else None,
            summary_prompt=summary_prompt,
        )
        if not submitted:
            _record_failed_job(thread_id, job_id, "Background executor is full")
            return None

        append_runtime_event(
            runtime,
            {
                "source": "plan_followup_middleware",
                "event": "background_followup_started",
                "job_id": job_id,
                "summary": "Deepening in background",
            },
        )
        return {
            "background_followups": [
                {
                    "id": job_id,
                    "status": "running",
                    "kind": "plan_background_deepen",
                    "summary": "Deepening in background",
                    "created_at": _utc_now_iso(),
                    "completed_at": None,
                    "error": None,
                }
            ]
        }

    @override
    async def aafter_model(self, state: PlanFollowupState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)


# Backward-compat alias while module name remains unchanged.
ProFollowupMiddleware = PlanFollowupMiddleware
