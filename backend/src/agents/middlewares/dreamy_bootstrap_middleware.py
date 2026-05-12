from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.memory.dreamy_state_preservation_hook import load_dreamy_resumption
from src.agents.middlewares.dreamy_intent_middleware import DreamyIntent
from src.agents.middlewares.runtime_events import append_runtime_event
from src.agents.thread_state import merge_artifacts
from src.config.dreamy_timeout_config import get_dreamy_timeout_config
from src.config.paths import get_paths


class DreamyBootstrapState(AgentState):
    dreamy_mode: NotRequired[bool]
    dreamy_intent: NotRequired[DreamyIntent]
    artifacts: NotRequired[list[str]]
    uploaded_files: NotRequired[list[dict]]


class _DetectedData(TypedDict):
    fields: list[str]
    sample_rows: list[dict]
    total_rows: int
    filename: str
    virtual_path: str
    data_source_type: str  # "inline" | "file" | "mounted_file"


class DreamyBootstrapMiddleware(AgentMiddleware[DreamyBootstrapState]):
    """Bootstrap a v2 workflow.json when the user explicitly invokes /workflow."""

    state_schema = DreamyBootstrapState

    _CSV_SPLIT_RE = re.compile(r"\s*,\s*")
    _UUID_RE = re.compile(r"^[a-f0-9]{8,}-?[a-f0-9-]*$", re.IGNORECASE)

    def __init__(self):
        super().__init__()
        self._config = get_dreamy_timeout_config()
    _AT_REF_RE = re.compile(r"@([\w\-. ]+\.(?:csv|xlsx|tsv|txt))", re.IGNORECASE)
    _TABULAR_EXTS = {".csv", ".xlsx", ".tsv", ".txt"}

    @staticmethod
    def _is_dreamy_mode(runtime: Runtime) -> bool:
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return False
        return bool(context.get("dreamy_mode", False))

    @staticmethod
    def _extract_human_text(state: DreamyBootstrapState) -> str:
        messages = state.get("messages", []) or []
        for msg in reversed(messages):
            if getattr(msg, "type", None) != "human":
                continue
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                return "\n".join(parts)
            return str(content)
        return ""

    def _detect_inline_tasks(self, text: str) -> tuple[list[str], list[dict]]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return [], []

        # Pipe-delimited markdown table
        pipe_lines = [ln for ln in lines if "|" in ln]
        if len(pipe_lines) >= 2:
            rows = [ln.strip("|").strip() for ln in pipe_lines]
            cells = [[c.strip() for c in row.split("|")] for row in rows if row]
            if len(cells) >= 2 and len(cells[0]) >= 2:
                header = cells[0]
                sample_rows: list[dict[str, str]] = []
                for row in cells[1:]:
                    if all(set(cell) <= {"-", ":"} for cell in row):
                        continue
                    if len(row) != len(header):
                        continue
                    sample_rows.append({header[i]: row[i] for i in range(len(header))})
                if sample_rows:
                    return header, sample_rows

        # CSV lines
        comma_lines = [ln for ln in lines if ln.count(",") >= 1]
        if len(comma_lines) >= 2:
            header = [c for c in self._CSV_SPLIT_RE.split(comma_lines[0]) if c]
            if len(header) >= 2:
                sample_rows = []
                for ln in comma_lines[1:]:
                    row = [c for c in self._CSV_SPLIT_RE.split(ln) if c or c == ""]
                    if len(row) != len(header):
                        continue
                    sample_rows.append({header[i]: row[i] for i in range(len(header))})
                if sample_rows:
                    return header, sample_rows

        # Bullet / numbered list
        bullets = [ln for ln in lines if ln.startswith("- ") or re.match(r"^\d+[.)]\s+", ln)]
        if len(bullets) >= 2:
            tasks = []
            for idx, b in enumerate(bullets, start=1):
                item = b[2:].strip() if b.startswith("- ") else re.sub(r"^\d+[.)]\s+", "", b).strip()
                if item:
                    tasks.append({"task": item, "id": str(idx)})
            if tasks:
                return ["task", "id"], tasks

        return [], []

    def _parse_tabular_file(self, file_path: Path) -> tuple[list[str], list[dict], int]:
        """Parse a tabular file. Returns (fields, sample_rows, total_rows)."""
        try:
            result = subprocess.run(
                ["python", "/mnt/skills/batch-workflow/scripts/load_tasks.py", "--input", str(file_path)],
                capture_output=True,
                text=True,
                timeout=self._config.bootstrap_loader_timeout_seconds,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                fields = data.get("fields", [])
                samples = data.get("samples", [])
                total = data.get("total", len(samples))  # use actual count from script
                if fields and samples:
                    return fields, samples, total
        except Exception:
            pass

        # Fallback: read directly — count ALL rows for accurate total
        try:
            import csv
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    return list(rows[0].keys()), rows[:3], len(rows)
        except Exception:
            pass

        return [], [], 0

    def _detect_uploaded_csv(
        self, state: DreamyBootstrapState, thread_id: str
    ) -> tuple[list[str], list[dict], int, str, str]:
        """Scan uploads/ then outputs/ for tabular files.
        Returns (fields, sample_rows, total_rows, filename, virtual_path).
        """
        paths = get_paths()
        uploaded = state.get("uploaded_files") or []

        # Check state-tracked uploaded files first (uploads/ dir)
        tabular_exts = self._TABULAR_EXTS
        for uf in uploaded:
            filename = uf.get("filename", "") if isinstance(uf, dict) else ""
            if not any(filename.lower().endswith(ext) for ext in tabular_exts):
                continue
            file_path = paths.sandbox_uploads_dir(thread_id) / filename
            if not file_path.exists():
                continue
            fields, samples, total = self._parse_tabular_file(file_path)
            if fields and samples:
                virtual = f"/mnt/user-data/uploads/{filename}"
                return fields, samples, total, filename, virtual

        # Also scan uploads/ dir directly (catches files not yet in state)
        uploads_dir = paths.sandbox_uploads_dir(thread_id)
        if uploads_dir.exists():
            for fp in sorted(uploads_dir.iterdir()):
                if fp.is_file() and fp.suffix.lower() in tabular_exts:
                    fields, samples, total = self._parse_tabular_file(fp)
                    if fields and samples:
                        virtual = f"/mnt/user-data/uploads/{fp.name}"
                        return fields, samples, total, fp.name, virtual

        # Fallback: scan outputs/ — handles manually placed / previously written files
        outputs_dir = paths.sandbox_outputs_dir(thread_id)
        if outputs_dir.exists():
            for fp in sorted(outputs_dir.iterdir()):
                if fp.is_file() and fp.suffix.lower() in tabular_exts and fp.name != "workflow.json":
                    fields, samples, total = self._parse_tabular_file(fp)
                    if fields and samples:
                        virtual = f"/mnt/user-data/outputs/{fp.name}"
                        return fields, samples, total, fp.name, virtual

        return [], [], 0, "", ""

    def _detect_mounted_folder_csv(
        self, thread_id: str, user_instruction: str
    ) -> tuple[list[str], list[dict], int, str, str]:
        """Detect a tabular file in the mounted folder.
        Checks for explicit @filename reference first, then auto-detects single file.
        Returns (fields, sample_rows, total_rows, filename, virtual_path).
        """
        paths = get_paths()
        mount_config = paths.sandbox_user_data_dir(thread_id) / "dreamy_mount.json"
        if not mount_config.exists():
            return [], [], 0, "", ""

        try:
            data = json.loads(mount_config.read_text(encoding="utf-8"))
            mounted_path_str = data.get("path")
        except Exception:
            return [], [], 0, "", ""

        if not mounted_path_str:
            return [], [], 0, "", ""

        folder = Path(mounted_path_str)
        if not folder.exists() or not folder.is_dir():
            return [], [], 0, "", ""

        # Explicit @filename reference takes priority
        at_match = self._AT_REF_RE.search(user_instruction)
        if at_match:
            ref_name = at_match.group(1).strip()
            candidate = folder / ref_name
            if candidate.exists() and candidate.is_file():
                fields, samples, total = self._parse_tabular_file(candidate)
                if fields and samples:
                    virtual = f"/mnt/user-data/mounted/{ref_name}"
                    return fields, samples, total, ref_name, virtual

        # Auto-detect: find tabular files in the folder
        tabular_files = sorted(
            [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in self._TABULAR_EXTS]
        )
        if not tabular_files:
            return [], [], 0, "", ""

        # Single file → use automatically
        if len(tabular_files) == 1:
            candidate = tabular_files[0]
            fields, samples, total = self._parse_tabular_file(candidate)
            if fields and samples:
                virtual = f"/mnt/user-data/mounted/{candidate.name}"
                return fields, samples, total, candidate.name, virtual

        # Multiple files → prefer single CSV if present, otherwise most recently modified
        csv_files = [f for f in tabular_files if f.suffix.lower() == ".csv"]
        if len(csv_files) == 1:
            candidate = csv_files[0]
            fields, samples, total = self._parse_tabular_file(candidate)
            if fields and samples:
                virtual = f"/mnt/user-data/mounted/{candidate.name}"
                return fields, samples, total, candidate.name, virtual

        # Multiple CSVs — pick most recently modified
        candidates = csv_files if csv_files else tabular_files
        candidate = max(candidates, key=lambda f: f.stat().st_mtime)
        fields, samples, total = self._parse_tabular_file(candidate)
        if fields and samples:
            virtual = f"/mnt/user-data/mounted/{candidate.name}"
            return fields, samples, total, candidate.name, virtual

        return [], [], 0, "", ""

    def _validate_data_source(
        self,
        fields: list[str],
        sample_rows: list[dict],
        total_rows: int,
        filename: str,
        data_source_type: str,
        user_text: str,
        thread_id: str,
    ) -> tuple[list[str], list[dict], int, str, str, str] | None:
        """Validate that the detected data source makes sense.

        Returns a possibly-revised (fields, sample_rows, total_rows, filename,
        virtual_path, data_source_type) tuple, or None if the current detection
        is acceptable.

        Heuristics:
        1. Single-column UUID-like data with few rows is likely not the
           intended workflow source (e.g. github-recovery-codes.txt).
        2. If the user asked to generate a large file, prefer outputs/ dir.
        3. .txt files with single column and <200 rows are suspicious.
        """
        paths = get_paths()

        # Heuristic: single-column data with UUID-like values and few rows
        # is unlikely to be the intended workflow data.
        if len(fields) == 1 and total_rows <= 100:
            sample_val = sample_rows[0].get(fields[0], "") if sample_rows else ""
            if self._UUID_RE.match(str(sample_val)):
                # Look for better candidates in outputs/ dir
                outputs_dir = paths.sandbox_outputs_dir(thread_id)
                if outputs_dir.exists():
                    best_candidate = None
                    best_score = 0
                    for fp in sorted(outputs_dir.iterdir()):
                        if not fp.is_file() or fp.suffix.lower() not in self._TABULAR_EXTS:
                            continue
                        if fp.name == "workflow.json":
                            continue
                        # Score: CSV > other tabular, more columns > fewer, more rows > fewer
                        score = 0
                        if fp.suffix.lower() == ".csv":
                            score += 10
                        try:
                            import csv
                            with open(fp, newline="", encoding="utf-8-sig") as f:
                                reader = csv.DictReader(f)
                                rows = list(reader)
                                if rows:
                                    score += len(rows[0]) * 3  # more columns = better
                                    score += min(len(rows), 50)  # more rows = better
                                    if score > best_score:
                                        best_score = score
                                        best_candidate = (fp, rows, len(rows))
                        except Exception:
                            continue

                    if best_candidate:
                        fp, samples, count = best_candidate
                        return (
                            list(samples[0].keys()),
                            samples[:3],
                            count,
                            fp.name,
                            f"/mnt/user-data/outputs/{fp.name}",
                            "file",
                        )

        return None

    @staticmethod
    def _fallback_steps(fields: list[str]) -> list[dict]:
        return [
            {
                "id": "step-1",
                "action": "tool_call",
                "tool": "",
                "description": "Process each row (configure the tool and fields below)",
                "input_fields": fields,
                "output_fields": [],
                "on_no_result": "skip",
            },
            {
                "id": "step-2",
                "action": "write_row",
                "description": "Write results to output file",
                "input_fields": [],
                "output_fields": [],
            },
        ]

    def _infer_steps_from_schema(
        self,
        *,
        fields: list[str],
        sample_rows: list[dict],
        user_instruction: str,
        model_name: str,
    ) -> list[dict]:
        from langchain_core.messages import HumanMessage as LcHumanMessage
        from langchain_core.messages import SystemMessage

        from src.models import create_chat_model

        system = (
            "You are a workflow designer for batch data processing. "
            "Given a table schema and sample rows, output a JSON array of steps to perform per row. "
            "Each step must have these exact fields: "
            "id (string, e.g. 'step-1'), "
            "action (one of: tool_call, write_row, conditional), "
            "tool (string, only if action=tool_call — use 'bash' for computation/scripting, else omit), "
            "description (string, human-readable), "
            "input_fields (array of field names from the table), "
            "output_fields (array of new column names to populate), "
            "on_no_result (one of: skip, error — only for tool_call steps). "
            "Return ONLY a valid JSON array. No prose, no markdown fences."
        )
        user_prompt = (
            f"Table fields: {json.dumps(fields)}\n"
            f"Sample rows (first {len(sample_rows[:3])}):\n"
            f"{json.dumps(sample_rows[:3], indent=2)}\n"
            f"User instruction: {user_instruction or '(not specified)'}\n\n"
            "Return the steps array."
        )
        try:
            model = create_chat_model(name=model_name, thinking_enabled=False)
            response = model.invoke([
                SystemMessage(content=system),
                LcHumanMessage(content=user_prompt),
            ])
            raw = (getattr(response, "content", None) or "").strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
            steps = json.loads(raw)
            if isinstance(steps, list) and steps:
                return steps
        except Exception:
            pass

        return self._fallback_steps(fields)

    @staticmethod
    def _workflow_virtual_path() -> str:
        return "/mnt/user-data/outputs/workflow.json"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    def _build_workflow(
        self,
        *,
        thread_id: str,
        data_source_type: str,
        filename: str,
        virtual_path: str,
        fields: list[str],
        sample_rows: list[dict],
        steps: list[dict],
        total_rows: int,
    ) -> dict:
        data_source: dict = {
            "type": data_source_type,
            "filename": filename,
            "total_rows": total_rows,
            "fields": fields,
            "sample_rows": sample_rows[:3],
        }
        if virtual_path:
            data_source["virtual_path"] = virtual_path

        return {
            "version": "2",
            "thread_id": thread_id,
            "created_at": self._now_iso(),
            "data_source": data_source,
            "steps": steps,
            "execution_state": {
                "phase": "poc",
                "current_row_index": 0,
                "current_step_id": None,
                "total_rows": total_rows,
                "poc_results": [],
                "seconds_per_row_estimate": None,
                "estimated_completion_iso": None,
                "started_at": None,
            },
        }

    @override
    def before_agent(self, state: DreamyBootstrapState, runtime: Runtime) -> dict | None:
        if not self._is_dreamy_mode(runtime):
            return None

        rehydrated_updates: dict[str, object] = {}
        context = runtime.context if isinstance(runtime.context, dict) else {}
        thread_id = context.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            resumption = load_dreamy_resumption(thread_id)
            if isinstance(resumption, dict):
                if not state.get("dreamy_intent") and resumption.get("dreamy_intent"):
                    rehydrated_updates["dreamy_intent"] = resumption.get("dreamy_intent")
                if not state.get("task_memory") and resumption.get("task_memory"):
                    rehydrated_updates["task_memory"] = resumption.get("task_memory")
                if rehydrated_updates:
                    append_runtime_event(
                        runtime,
                        {
                            "source": "dreamy_bootstrap",
                            "event": "dreamy_resumption_rehydrated",
                            "thread_id": thread_id,
                        },
                    )

        intent = state.get("dreamy_intent") or {}
        workflow_requested = bool(intent.get("workflow_requested", False))
        if not workflow_requested:
            if rehydrated_updates:
                return {"dreamy_mode": True, **rehydrated_updates}
            return None

        context = runtime.context if isinstance(runtime.context, dict) else {}
        thread_id = context.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return {"dreamy_mode": True, **rehydrated_updates}

        paths = get_paths()
        paths.ensure_thread_dirs(thread_id)
        workflow_path = paths.sandbox_outputs_dir(thread_id) / "workflow.json"
        artifacts = list(state.get("artifacts") or [])
        workflow_virtual = self._workflow_virtual_path()

        # If workflow.json already exists, just re-surface it
        if workflow_path.exists():
            merged = merge_artifacts(artifacts, [workflow_virtual])
            return {"dreamy_mode": True, "artifacts": merged, **rehydrated_updates}

        append_runtime_event(
            runtime,
            {
                "source": "dreamy_bootstrap",
                "event": "dreamy_bootstrap_started",
                "phase": "dreamy_bootstrap_started",
                "thread_id": thread_id,
            },
        )

        user_text = self._extract_human_text(state)
        instruction = user_text.lstrip()
        if instruction.startswith("/workflow"):
            instruction = instruction[len("/workflow"):].strip()

        # --- Data source detection (priority order) ---
        # 1. Uploaded files + outputs/ dir
        fields, sample_rows, total_rows, filename, virtual_path = self._detect_uploaded_csv(state, thread_id)
        data_source_type = "file"

        # 2. Mounted folder (explicit @ref or auto-detect)
        if not fields or not sample_rows:
            fields, sample_rows, total_rows, filename, virtual_path = self._detect_mounted_folder_csv(
                thread_id, instruction
            )
            data_source_type = "mounted_file"

        # 3. Inline data pasted in message
        if not fields or not sample_rows:
            fields, sample_rows = self._detect_inline_tasks(user_text)
            total_rows = len(sample_rows)
            filename = "tasks.txt"
            virtual_path = "/mnt/user-data/uploads/tasks.txt"
            data_source_type = "inline"

        if not fields or not sample_rows:
            append_runtime_event(
                runtime,
                {
                    "source": "dreamy_bootstrap",
                    "event": "dreamy_no_structured_data",
                    "phase": "dreamy_no_structured_data",
                    "thread_id": thread_id,
                },
            )
            if rehydrated_updates:
                return {"dreamy_mode": True, **rehydrated_updates}
            return None

        # --- Data source validation (safety check) ---
        if self._config.bootstrap_validate_data_source:
            validation_result = self._validate_data_source(
                fields, sample_rows, total_rows, filename, data_source_type, user_text, thread_id
            )
            if validation_result is not None:
                fields, sample_rows, total_rows, filename, virtual_path, data_source_type = validation_result

        append_runtime_event(
            runtime,
            {
                "source": "dreamy_bootstrap",
                "event": "dreamy_tasklist_detected",
                "phase": "dreamy_tasklist_detected",
                "thread_id": thread_id,
                "fields": fields,
                "total_rows": total_rows,
                "data_source_type": data_source_type,
                "virtual_path": virtual_path,
            },
        )

        # For inline data — persist all rows to tasks.txt so agent can load them
        if data_source_type == "inline":
            uploads_dir = paths.sandbox_uploads_dir(thread_id)
            tasks_txt = uploads_dir / "tasks.txt"
            tasks_txt.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in sample_rows),
                encoding="utf-8",
            )

        # Single focused LLM call to infer per-row steps
        model_name = context.get("model_name") or "default"
        steps = self._infer_steps_from_schema(
            fields=fields,
            sample_rows=sample_rows,
            user_instruction=instruction,
            model_name=model_name,
        )

        # Always ensure there is a write_row step — LLM inference may omit it
        if not any(s.get("action") == "write_row" for s in steps):
            steps.append({
                "id": f"step-{len(steps) + 1}",
                "action": "write_row",
                "description": "Write results to output CSV",
                "input_fields": [],
                "output_fields": [],
            })

        workflow = self._build_workflow(
            thread_id=thread_id,
            data_source_type=data_source_type,
            filename=filename,
            virtual_path=virtual_path,
            fields=fields,
            sample_rows=sample_rows,
            steps=steps,
            total_rows=total_rows,
        )
        # Reset checkpoint so a new workflow starts from row 0 with no stale completions.
        checkpoint_path = workflow_path.parent / "checkpoint.json"
        if checkpoint_path.exists():
            try:
                checkpoint_path.unlink()
            except Exception:
                pass

        workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")

        append_runtime_event(
            runtime,
            {
                "source": "dreamy_bootstrap",
                "event": "dreamy_workflow_created",
                "phase": "dreamy_workflow_created",
                "thread_id": thread_id,
                "workflow_path": workflow_virtual,
                "data_source_type": data_source_type,
                "steps_count": len(steps),
                "total_rows": total_rows,
                "virtual_path": virtual_path,
            },
        )

        merged = merge_artifacts(artifacts, [workflow_virtual])

        append_runtime_event(
            runtime,
            {
                "source": "dreamy_bootstrap",
                "event": "dreamy_workflow_presented",
                "phase": "dreamy_workflow_presented",
                "thread_id": thread_id,
                "artifacts_count": len(merged),
            },
        )

        # Build data source hint for the agent
        if data_source_type == "mounted_file":
            data_hint = f"Data source is the mounted folder file at {virtual_path} — use this path with read_file and load_tasks.py."
        elif data_source_type == "file":
            data_hint = f"Data source is the uploaded file at {virtual_path} — use this path with read_file and load_tasks.py."
        else:
            data_hint = f"Data source is inline (stored at {virtual_path}) — use load_tasks.py to read all {total_rows} rows."

        # Output file: derive from source filename, never write back to source
        base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
        output_virtual = f"/mnt/user-data/outputs/{base_name}_results.csv"

        reminder = HumanMessage(
            name="dreamy_bootstrap",
            content=(
                "<system_reminder>\n"
                f"workflow.json v2 initialized at /mnt/user-data/outputs/workflow.json. "
                f"{data_hint} "
                f"Total rows: {total_rows}. "
                f"Write all results to {output_virtual} — do NOT modify or overwrite the source file. "
                "EXECUTION CONTRACT: process ONE ROW at a time following workflow.json steps in order. "
                "Each tool/bash call receives data for exactly ONE row — never write loops or scripts "
                "that iterate over multiple rows. Call write_result.py and checkpoint.py after EACH row "
                "before advancing to the next. "
                "Load the dreamy-workflow skill, present the steps to the user as a table, "
                "then run the POC (rows 1–3 only). "
                "Do NOT start row-by-row execution until the user approves via ask_clarification.\n"
                "</system_reminder>"
            ),
        )
        return {"dreamy_mode": True, "artifacts": merged, "messages": [reminder], **rehydrated_updates}
