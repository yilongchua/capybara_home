"""Middleware that hands off bulk execution to the Python DreamyExecutor.

Activates when workflow.json transitions to phase="bulk" and total_rows
exceeds EXECUTOR_THRESHOLD. Starts a background DreamyExecutor thread;
on subsequent turns detects completion and injects a system_reminder so
the main agent can present results to the user.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.dreamy_executor import EXECUTOR_THRESHOLD, DreamyExecutor
from src.config.dreamy_timeout_config import get_dreamy_timeout_config
from src.config.paths import get_paths

logger = logging.getLogger(__name__)


class DreamyExecutionMiddlewareState(AgentState):
    dreamy_mode: NotRequired[bool]


class DreamyExecutionMiddleware(AgentMiddleware[DreamyExecutionMiddlewareState]):
    """Starts the Python DreamyExecutor when bulk phase begins for large runs.

    Small runs (total_rows <= EXECUTOR_THRESHOLD) are unaffected — the LLM
    continues to drive the loop as before.
    """

    state_schema = DreamyExecutionMiddlewareState

    @staticmethod
    def _is_dreamy_mode(runtime: Runtime) -> bool:
        ctx = getattr(runtime, "context", None)
        return bool(isinstance(ctx, dict) and ctx.get("dreamy_mode"))

    @override
    def after_agent(self, state: DreamyExecutionMiddlewareState, runtime: Runtime) -> dict | None:
        if not self._is_dreamy_mode(runtime):
            return None

        context = runtime.context if isinstance(runtime.context, dict) else {}
        thread_id = context.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None

        paths = get_paths()
        workflow_path = paths.sandbox_outputs_dir(thread_id) / "workflow.json"
        if not workflow_path.exists():
            return None

        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        if workflow.get("version") != "2":
            return None

        es = workflow.get("execution_state") or {}
        phase = es.get("phase", "design")
        total_rows = int(es.get("total_rows") or 0)

        # Determine effective threshold: poc-phase executor can handle small runs
        # if total_rows is within executor_poc_max_rows.
        timeout_cfg = get_dreamy_timeout_config()
        poc_max = timeout_cfg.executor_poc_max_rows
        poc_threshold = timeout_cfg.executor_poc_threshold

        # Check if poc phase with small row count should use executor
        if phase == "poc" and total_rows <= poc_max and total_rows >= poc_threshold:
            progress_path = paths.sandbox_outputs_dir(thread_id) / "progress.json"
            executor_state = self._read_progress_state(progress_path)

            # If executor hasn't started and poc is in progress, launch it
            if executor_state not in ("running", "completed", "stopped", "failed"):
                logger.info(
                    "[dreamy-execution-mw] thread=%s starting poc executor total_rows=%d",
                    thread_id,
                    total_rows,
                )
                self._start_executor(thread_id, workflow, context, runtime)
                anchor = HumanMessage(
                    name="dreamy_execution",
                    content=(
                        "<system_reminder>\n"
                        f"POC execution started by the Dreamy Executor for {total_rows} rows. "
                        "The Python executor is now processing rows in the background. "
                        "You do NOT need to call any tools or process rows yourself. "
                        "Tell the user the POC is running and they can monitor progress "
                        "in the Directory tab (progress.json, run_status.md).\n"
                        "</system_reminder>"
                    ),
                )
                return {"messages": [anchor]}
            return None

        # Only handle large runs (bulk phase)
        if total_rows <= EXECUTOR_THRESHOLD:
            return None

        progress_path = paths.sandbox_outputs_dir(thread_id) / "progress.json"
        executor_state = self._read_progress_state(progress_path)

        # Inject completion reminder when executor finishes
        if executor_state == "completed":
            run_status_path = paths.sandbox_outputs_dir(thread_id) / "run_status.md"
            summary = ""
            if run_status_path.exists():
                try:
                    summary = run_status_path.read_text(encoding="utf-8")[:500]
                except Exception:
                    pass
            ds = workflow.get("data_source") or {}
            source_fn = ds.get("filename") or "tasks.txt"
            base = source_fn.rsplit(".", 1)[0] if "." in source_fn else source_fn
            output_virtual = f"/mnt/user-data/outputs/{base}_results.csv"
            done = self._read_progress_done(progress_path)
            reminder = HumanMessage(
                name="dreamy_executor",
                content=(
                    "<system_reminder>\n"
                    f"Batch execution complete. {done}/{total_rows} rows processed.\n"
                    f"Output file: {output_virtual}\n"
                    f"{summary}\n"
                    "Call present_files with the output file path to show the user the results.\n"
                    "</system_reminder>"
                ),
            )
            return {"messages": [reminder]}

        # Resume after pause: user sent a new message
        if executor_state == "paused" and phase == "bulk":
            logger.info("[dreamy-execution-mw] thread=%s resuming from pause", thread_id)
            self._start_executor(thread_id, workflow, context, runtime)
            return None

        # Start executor when bulk phase begins for the first time
        if phase == "bulk" and executor_state not in ("running", "completed", "stopped", "failed"):
            logger.info("[dreamy-execution-mw] thread=%s starting executor total_rows=%d", thread_id, total_rows)
            self._start_executor(thread_id, workflow, context, runtime)
            anchor = HumanMessage(
                name="dreamy_execution",
                content=(
                    "<system_reminder>\n"
                    f"Bulk execution started by the Dreamy Executor for {total_rows:,} rows. "
                    "The Python executor is now processing rows in the background. "
                    "You do NOT need to call any tools or process rows yourself. "
                    "Tell the user the batch is running and they can monitor progress in the Directory tab "
                    "(progress.json, run_status.md). "
                    "When the executor completes, you will receive another system_reminder.\n"
                    "</system_reminder>"
                ),
            )
            return {"messages": [anchor]}

        return None

    def _start_executor(
        self,
        thread_id: str,
        workflow: dict,
        context: dict,
        runtime: Runtime,
    ) -> None:
        """Launch DreamyExecutor in a daemon background thread."""
        self._clear_signal(thread_id)
        runtime_state = getattr(runtime, "state", None)
        state = runtime_state if isinstance(runtime_state, dict) else {}
        executor = DreamyExecutor(
            thread_id=thread_id,
            workflow=workflow,
            model_name=context.get("model_name"),
            sandbox_state=state.get("sandbox"),
            thread_data=state.get("thread_data"),
        )
        t = threading.Thread(target=executor.run, daemon=True, name=f"dreamy-exec-{thread_id[:8]}")
        t.start()

    @staticmethod
    def _clear_signal(thread_id: str) -> None:
        path = get_paths().sandbox_outputs_dir(thread_id) / "pause_signal.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps({"signal": None}), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _read_progress_state(progress_path: Path) -> str:
        if not progress_path.exists():
            return "not_started"
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
            return str(data.get("state") or "not_started")
        except Exception:
            return "not_started"

    @staticmethod
    def _read_progress_done(progress_path: Path) -> int:
        if not progress_path.exists():
            return 0
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
            return int(data.get("done") or 0)
        except Exception:
            return 0
