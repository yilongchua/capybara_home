from __future__ import annotations

import json
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.paths import get_paths


class DreamyPocState(AgentState):
    dreamy_mode: NotRequired[bool]


class DreamyPocMiddleware(AgentMiddleware[DreamyPocState]):
    """
    Manages dreamy execution phases:
    - before_model: injects a per-row executor anchor during poc/bulk to survive context compression
    - after_agent: transitions poc→awaiting_approval and enforces the approval gate
    """

    state_schema = DreamyPocState

    @staticmethod
    def _is_dreamy_mode(runtime: Runtime) -> bool:
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return False
        return bool(context.get("dreamy_mode", False))

    @override
    def before_model(self, state: DreamyPocState, runtime: Runtime) -> dict | None:
        """Inject a short executor anchor once per row during poc/bulk phases.

        Reads workflow.json fresh from disk so the anchor is always current even after
        context summarization compresses the original skill injection messages.
        """
        if not self._is_dreamy_mode(runtime):
            return None

        context = runtime.context if isinstance(runtime.context, dict) else {}
        thread_id = context.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None

        workflow_path = get_paths().sandbox_outputs_dir(thread_id) / "workflow.json"
        if not workflow_path.exists():
            return None

        try:
            data = json.loads(workflow_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        if data.get("version") != "2":
            return None

        es = data.get("execution_state", {})
        phase = es.get("phase", "design")

        if phase not in ("poc", "bulk"):
            return None

        current_row = es.get("current_row_index", 0)
        total_rows = es.get("total_rows", 0)
        current_step = es.get("current_step_id") or (data["steps"][0]["id"] if data.get("steps") else "step-1")
        src_filename = (data.get("data_source") or {}).get("filename", "")
        base_name = src_filename.rsplit(".", 1)[0] if "." in src_filename else src_filename
        output_virtual = f"/mnt/user-data/outputs/{base_name}_results.csv"
        row_marker = f"row {current_row + 1} of {total_rows}"

        # Inject once per row — skip if the last dreamy_anchor already covers this row
        messages = state.get("messages") or []
        for msg in reversed(messages[-15:]):
            if getattr(msg, "name", None) == "dreamy_anchor":
                if row_marker in (getattr(msg, "content", "") or ""):
                    return None  # Already anchored for this row
                break  # Anchor exists for a previous row — fall through to inject new one

        anchor = HumanMessage(
            name="dreamy_anchor",
            content=(
                "<system_reminder>\n"
                f"DREAMY EXECUTOR — phase={phase}, {row_marker}\n"
                f"current_step_id: {current_step}\n"
                f"Output file: {output_virtual} (do NOT modify the source file)\n"
                "RULES: (1) One tool/bash call = exactly ONE row's data — never loop or batch "
                "multiple rows in a single tool call. "
                "(2) After every row: write_result.py → checkpoint.py --mark-done → "
                "update execution_state.current_row_index in workflow.json. "
                "(3) Follow workflow.steps in order.\n"
                "</system_reminder>"
            ),
        )
        return {"messages": [anchor]}

    @override
    def after_agent(self, state: DreamyPocState, runtime: Runtime) -> dict | None:
        if not self._is_dreamy_mode(runtime):
            return None

        context = runtime.context if isinstance(runtime.context, dict) else {}
        thread_id = context.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None

        workflow_path = get_paths().sandbox_outputs_dir(thread_id) / "workflow.json"
        if not workflow_path.exists():
            return None

        try:
            data = json.loads(workflow_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        if data.get("version") != "2":
            return None

        es = data.get("execution_state", {})
        phase = es.get("phase", "design")
        total_rows = es.get("total_rows", 0)
        poc_results = es.get("poc_results", [])

        # Sync current_row_index from checkpoint.json (source of truth for row progress)
        checkpoint_path = workflow_path.parent / "checkpoint.json"
        if checkpoint_path.exists():
            try:
                cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                completed_count = len(cp.get("completed", []))
                if completed_count > es.get("current_row_index", 0):
                    es["current_row_index"] = completed_count
                    data["execution_state"] = es
                    try:
                        workflow_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
            except Exception:
                pass

        current_row = es.get("current_row_index", 0)
        poc_target = min(3, total_rows)

        if phase == "poc" and current_row >= poc_target:
            seconds_list = [r.get("seconds", 30) for r in poc_results if isinstance(r.get("seconds"), (int, float))]
            avg_seconds = round(sum(seconds_list) / len(seconds_list)) if seconds_list else 30
            es["phase"] = "awaiting_approval"
            es["seconds_per_row_estimate"] = avg_seconds
            data["execution_state"] = es
            try:
                workflow_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            append_runtime_event(
                runtime,
                {
                    "source": "dreamy_poc",
                    "event": "dreamy_poc_complete",
                    "phase": "dreamy_poc_complete",
                    "poc_rows": current_row,
                    "seconds_per_row_estimate": avg_seconds,
                },
            )
            return None

        if phase == "awaiting_approval":
            messages = state.get("messages") or []
            last_ai = next(
                (m for m in reversed(messages) if getattr(m, "type", None) == "ai"),
                None,
            )
            asked = False
            if last_ai:
                for tc in getattr(last_ai, "tool_calls", []) or []:
                    if (tc.get("name") or "") == "ask_clarification":
                        asked = True
                        break
            if not asked:
                gate_msg = HumanMessage(
                    name="dreamy_poc",
                    content=(
                        "<system_reminder>\n"
                        f"WORKFLOW GATE: execution_state.phase is 'awaiting_approval'. "
                        f"You MUST call ask_clarification (clarification_type='risk_confirmation') "
                        f"before processing row {current_row + 1} or any subsequent rows. "
                        f"Show the POC results table and the estimated time to completion.\n"
                        "</system_reminder>"
                    ),
                )
                return {"messages": [gate_msg]}

        return None
