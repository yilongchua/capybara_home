"""Python-loop batch executor for Dreamy large-scale workflows.

Activates when total_rows > EXECUTOR_THRESHOLD. Runs as a daemon background
thread, processes one row at a time via SubagentExecutor, writes compact
file-based progress state (no growing JSON arrays), and handles failure
classification + pause/stop signals.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

EXECUTOR_THRESHOLD = 20

_active_executors: dict[str, DreamyExecutor] = {}
_active_executors_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _safe_write(path: Path, data: str) -> None:
    """Atomic write via temp file to avoid partial reads."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


class DreamyExecutor:
    """Runs the row-processing loop for a Dreamy batch workflow.

    Loop control is entirely Python — the LLM only executes per-row steps.
    """

    def __init__(
        self,
        thread_id: str,
        workflow: dict,
        model_name: str | None,
        sandbox_state: dict | None,
        thread_data: dict | None,
    ) -> None:
        self.thread_id = thread_id
        self.workflow = workflow
        self.model_name = model_name
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data

        from src.config.paths import get_paths
        self._paths = get_paths()
        self._outputs_dir = self._paths.sandbox_outputs_dir(thread_id)

        self._total = int((workflow.get("execution_state") or {}).get("total_rows") or 0)
        self._steps: list[dict] = workflow.get("steps") or []
        ds = workflow.get("data_source") or {}
        self._source_filename: str = ds.get("filename") or "tasks.txt"
        self._source_type: str = ds.get("type") or "file"
        self._source_virtual: str = ds.get("virtual_path") or f"/mnt/user-data/outputs/{self._source_filename}"
        base = self._source_filename.rsplit(".", 1)[0] if "." in self._source_filename else self._source_filename
        self._output_virtual = f"/mnt/user-data/outputs/{base}_results.csv"

        # Mutable counters
        self._done = 0
        self._failed = 0
        self._skipped = 0
        self._consecutive_failures = 0
        self._recent_failures: list[dict] = []  # last 20 failure records
        self._start_time: float = 0.0
        self._rate_sleep: float = 0.0  # injected delay for rate-limiting

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main loop. Runs in a daemon thread."""
        with _active_executors_lock:
            _active_executors[self.thread_id] = self

        self._start_time = time.monotonic()
        self._write_progress("running")
        logger.info("[dreamy-executor] thread=%s total=%d starting", self.thread_id, self._total)

        try:
            rows = self._load_rows()
            resume = self._get_resume_index()
            logger.info("[dreamy-executor] thread=%s resume_index=%d", self.thread_id, resume)

            for row_idx in range(resume, self._total):
                signal = self._check_signal()
                if signal == "stop":
                    logger.info("[dreamy-executor] thread=%s hard stop at row %d", self.thread_id, row_idx)
                    self._write_progress("stopped")
                    self._update_run_status(f"Stopped by user at row {row_idx}.")
                    return
                if signal == "pause":
                    logger.info("[dreamy-executor] thread=%s paused at row %d", self.thread_id, row_idx)
                    self._write_progress("paused")
                    self._update_run_status(f"Paused at row {row_idx}. Send a message to resume.")
                    return

                if self._rate_sleep > 0:
                    time.sleep(self._rate_sleep)

                row_data = rows[row_idx] if row_idx < len(rows) else {}
                try:
                    self._process_row(row_idx, row_data)
                    self._done += 1
                    self._consecutive_failures = 0
                    self._update_completion_ranges(row_idx, success=True)
                except Exception as exc:
                    failure_type = self._classify_failure(exc, row_idx)
                    self._record_failure(row_idx, failure_type, str(exc))
                    self._failed += 1
                    self._consecutive_failures += 1
                    self._update_completion_ranges(row_idx, success=False)

                    if failure_type == "critical":
                        msg = f"Critical failure at row {row_idx}: {exc}. Stopping."
                        self._update_run_status(msg)
                        self._write_progress("failed")
                        logger.error("[dreamy-executor] thread=%s %s", self.thread_id, msg)
                        return

                    rows_processed = self._done + self._failed + self._skipped
                    failure_rate = self._failed / max(rows_processed, 1)
                    if self._failed > 5 and failure_rate > 0.20:
                        msg = f"Failure rate {failure_rate:.1%} ({self._failed}/{rows_processed}) exceeded 20%. Stopping."
                        self._update_run_status(msg)
                        self._write_progress("failed")
                        logger.error("[dreamy-executor] thread=%s %s", self.thread_id, msg)
                        return

                    if self._consecutive_failures >= 5:
                        logger.warning("[dreamy-executor] thread=%s 5 consecutive failures — skipping ahead", self.thread_id)
                        self._consecutive_failures = 0

                self._write_progress("running")
                self._detect_pattern()

            # All rows done
            self._write_progress("completed")
            self._update_run_status(
                f"Batch complete. {self._done}/{self._total} rows processed. "
                f"Failed: {self._failed}. Skipped: {self._skipped}. "
                f"Output: {self._output_virtual}"
            )
            logger.info("[dreamy-executor] thread=%s completed done=%d failed=%d", self.thread_id, self._done, self._failed)

        except Exception as exc:
            logger.exception("[dreamy-executor] thread=%s unexpected error: %s", self.thread_id, exc)
            self._write_progress("failed")
            self._update_run_status(f"Executor error: {exc}")
        finally:
            with _active_executors_lock:
                _active_executors.pop(self.thread_id, None)

    # ------------------------------------------------------------------
    # Row processing
    # ------------------------------------------------------------------

    def _load_rows(self) -> list[dict]:
        """Load all rows from the data source via load_tasks.py."""
        source_path = self._resolve_virtual(self._source_virtual)
        if not source_path or not source_path.exists():
            logger.warning("[dreamy-executor] source not found: %s", self._source_virtual)
            return []

        try:
            result = subprocess.run(
                ["python", "/mnt/skills/batch-workflow/scripts/load_tasks.py", "--input", str(source_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                # load_tasks returns samples only; for full run we parse directly
                total = data.get("total", 0)
                if total == 0:
                    return []
        except Exception:
            pass

        # Direct parse for full row list
        return self._parse_all_rows(source_path)

    def _parse_all_rows(self, file_path: Path) -> list[dict]:
        """Return all rows as list of dicts."""
        suffix = file_path.suffix.lower()
        try:
            if suffix in (".xlsx", ".xls", ".xlsm"):
                import openpyxl
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    return []
                headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
                return [dict(zip(headers, row)) for row in rows[1:]]
            elif suffix in (".csv", ".tsv", ".txt"):
                import csv
                with open(file_path, newline="", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    return [dict(row) for row in reader]
            elif suffix == ".json":
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [r if isinstance(r, dict) else {"value": r} for r in data]
                if isinstance(data, dict) and "tasks" in data:
                    return data["tasks"]
            else:
                # Plain text: one item per line
                lines = [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                return [{"task": line, "id": str(i + 1)} for i, line in enumerate(lines)]
        except Exception as exc:
            logger.error("[dreamy-executor] failed to parse %s: %s", file_path, exc)
        return []

    def _process_row(self, row_idx: int, row_data: dict) -> None:
        """Execute all steps for a single row via SubagentExecutor."""
        from src.subagents.config import SubagentConfig
        from src.subagents.executor import SubagentExecutor, SubagentStatus
        from src.tools.tools import get_available_tools

        step = self._steps[0] if self._steps else {}
        step_tool = step.get("tool") or ""
        step_desc = step.get("description") or "process this row"
        output_fields = step.get("output_fields") or []

        allowed_tools = ["bash", "read_file", "write_file", "str_replace"]
        if step_tool and step_tool not in allowed_tools:
            allowed_tools.append(step_tool)

        row_prompt = (
            f"You are processing batch row {row_idx + 1} of {self._total}. Execute exactly ONE step:\n"
            f"Step: {step_desc}\n"
            f"Tool: {step_tool or '(bash)'}\n"
            f"Input data for this row: {json.dumps(row_data, ensure_ascii=False)}\n"
            f"Output fields to extract: {json.dumps(output_fields)}\n"
            f"Output file (1-based row index {row_idx + 1}): {self._output_virtual}\n\n"
            f"Instructions:\n"
            f"1. Execute the step for THIS row only. Do not process any other rows.\n"
            f"2. Call write_result.py with the extracted fields:\n"
            f"   python /mnt/skills/batch-workflow/scripts/write_result.py "
            f"--output {self._output_virtual} --task-id {row_idx + 1} "
            f"--data '{{...}}' --status found\n"
            f"3. Call: python /mnt/skills/batch-workflow/scripts/checkpoint.py "
            f"--file /mnt/user-data/outputs/checkpoint.json --mark-done {row_idx}\n"
            f"4. Stop immediately after — do not continue to the next row.\n"
        )

        row_config = SubagentConfig(
            name=f"dreamy-row-{row_idx}",
            description=f"Process row {row_idx + 1} of {self._total}",
            system_prompt=(
                "You are a strict batch executor. Process exactly ONE row. "
                "Always call write_result.py and checkpoint.py after completing the step. "
                "Never process more than one row per invocation."
            ),
            tools=allowed_tools,
            model="inherit",
            max_turns=6,
            timeout_seconds=120,
        )

        all_tools = get_available_tools(model_name=self.model_name, subagent_enabled=False)

        executor = SubagentExecutor(
            config=row_config,
            tools=all_tools,
            parent_model=self.model_name,
            sandbox_state=self.sandbox_state,
            thread_data=self.thread_data,
            thread_id=self.thread_id,
            trace_id=f"row-{row_idx}",
        )

        result = executor.execute(row_prompt)
        if result.status in (SubagentStatus.FAILED, SubagentStatus.TIMED_OUT):
            raise RuntimeError(result.error or f"Row {row_idx} failed: {result.status}")

    # ------------------------------------------------------------------
    # Checkpoint: range-based completion tracking
    # ------------------------------------------------------------------

    def _get_resume_index(self) -> int:
        """Find first uncompleted row from completion_ranges.json."""
        path = self._outputs_dir / "completion_ranges.json"
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ranges: list[list[int]] = data.get("ranges") or []
            gaps: list[int] = data.get("gaps") or []
            gap_set = set(gaps)

            # Find first row not covered by any range and not in gaps
            covered = set()
            for r in ranges:
                if len(r) == 2:
                    covered.update(range(r[0], r[1] + 1))

            for i in range(self._total):
                if i not in covered and i not in gap_set:
                    return i
            return self._total  # all done
        except Exception as exc:
            logger.warning("[dreamy-executor] could not read completion_ranges: %s", exc)
            return 0

    def _update_completion_ranges(self, row_idx: int, success: bool) -> None:
        """Extend ranges for successful rows; record failures in gaps."""
        path = self._outputs_dir / "completion_ranges.json"
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = {"ranges": [], "total": self._total, "done": 0, "gaps": []}

            if not success:
                gaps: list[int] = data.get("gaps") or []
                if row_idx not in gaps:
                    gaps.append(row_idx)
                data["gaps"] = gaps
            else:
                ranges: list[list[int]] = data.get("ranges") or []
                # Try to extend the last range or add a new one
                if ranges and ranges[-1][1] == row_idx - 1:
                    ranges[-1][1] = row_idx
                else:
                    ranges.append([row_idx, row_idx])
                data["ranges"] = ranges

            data["done"] = self._done
            data["total"] = self._total
            _safe_write(path, json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as exc:
            logger.warning("[dreamy-executor] completion_ranges update failed: %s", exc)

    # ------------------------------------------------------------------
    # Progress and status files
    # ------------------------------------------------------------------

    def _write_progress(self, state: str) -> None:
        rows_processed = self._done + self._failed + self._skipped
        elapsed = max(time.monotonic() - self._start_time, 0.001)
        rate = round(rows_processed / elapsed * 60, 1) if elapsed > 0 else 0.0

        eta_iso: str | None = None
        if rate > 0 and self._total > rows_processed:
            remaining_rows = self._total - rows_processed
            remaining_minutes = remaining_rows / rate
            eta_ts = time.time() + remaining_minutes * 60
            eta_iso = datetime.fromtimestamp(eta_ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        progress = {
            "total": self._total,
            "done": self._done,
            "failed": self._failed,
            "skipped": self._skipped,
            "rows_per_minute": rate,
            "eta_iso": eta_iso,
            "state": state,
            "started_at": self._started_at_iso,
            "updated_at": _now_iso(),
        }
        path = self._outputs_dir / "progress.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        _safe_write(path, json.dumps(progress, ensure_ascii=False, indent=2))

    @property
    def _started_at_iso(self) -> str:
        if self._start_time == 0.0:
            return _now_iso()
        ts = time.time() - (time.monotonic() - self._start_time)
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    def _update_run_status(self, note: str = "") -> None:
        rows_processed = self._done + self._failed + self._skipped
        pct = f"{rows_processed / max(self._total, 1) * 100:.1f}"
        path = self._outputs_dir / "run_status.md"
        content = (
            f"# Run Status\n\n"
            f"**Progress**: {rows_processed:,} / {self._total:,} rows ({pct}%)  \n"
            f"**Done**: {self._done:,} · **Failed**: {self._failed} · **Skipped**: {self._skipped}  \n"
            f"**Rate**: {round(self._done / max(time.monotonic() - self._start_time, 0.001) * 60, 1)} rows/min  \n"
            f"**Last updated**: {_now_iso()}  \n"
        )
        if note:
            content += f"\n**Note**: {note}\n"
        _safe_write(path, content)

    def _record_failure(self, row_idx: int, failure_type: str, error: str) -> None:
        record = {"row": row_idx, "type": failure_type, "error": error[:200], "ts": _now_iso()}
        self._recent_failures.append(record)
        if len(self._recent_failures) > 20:
            self._recent_failures = self._recent_failures[-20:]

        path = self._outputs_dir / "failures.md"
        step_id = self._steps[0].get("id", "step-1") if self._steps else "?"
        tool = self._steps[0].get("tool", "") if self._steps else ""
        row = f"| {row_idx} | {failure_type} | {step_id} | {tool} | {error[:80]} | {record['ts']} |\n"

        if not path.exists():
            header = (
                "# Failure Log\n\n"
                "| Row | Type | Step | Tool | Error | Timestamp |\n"
                "|-----|------|------|------|-------|----------|\n"
            )
            _safe_write(path, header + row)
        else:
            with open(path, "a", encoding="utf-8") as f:
                f.write(row)

    # ------------------------------------------------------------------
    # Signal and failure logic
    # ------------------------------------------------------------------

    def _check_signal(self) -> str | None:
        path = self._outputs_dir / "pause_signal.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("signal")
        except Exception:
            return None

    def _classify_failure(self, exc: Exception, row_idx: int) -> str:
        msg = str(exc).lower()
        if "tool not found" in msg or "input field missing" in msg or "no such tool" in msg:
            return "critical"
        if any(k in msg for k in ("timeout", "connection", "refused", "unavailable")):
            return "tool_error"
        return "workflow_error"

    def _detect_pattern(self) -> None:
        """Check recent failures for suspicious patterns; update failures.md."""
        if len(self._recent_failures) < 3:
            return

        recent = self._recent_failures[-10:]

        # Rate-limiting: multiple tool_errors within a short window
        tool_errors = [f for f in recent if f["type"] == "tool_error"]
        if len(tool_errors) >= 3:
            try:
                times = [datetime.fromisoformat(f["ts"].rstrip("Z")) for f in tool_errors[-3:]]
                span = (times[-1] - times[0]).total_seconds()
                if span < 15:
                    self._rate_sleep = max(self._rate_sleep, 3.0)
                    self._append_pattern_note("⚠️ RATE LIMITING DETECTED — added 3s delay between rows")
                    return
            except Exception:
                pass

        # Cluster: >5 failures in last 10 rows on same step
        step_failures = [f for f in recent if f.get("type") != "critical"]
        if len(step_failures) >= 5:
            self._append_pattern_note("⚠️ CLUSTER FAILURE — >5 failures in last 10 rows. Consider stopping.")

    def _append_pattern_note(self, note: str) -> None:
        path = self._outputs_dir / "failures.md"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n## Pattern Analysis\n- {note} ({_now_iso()})\n")
        logger.warning("[dreamy-executor] thread=%s pattern: %s", self.thread_id, note)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_virtual(self, virtual_path: str) -> Path | None:
        try:
            return self._paths.resolve_virtual_path(self.thread_id, virtual_path)
        except Exception:
            # Fallback: manual resolution
            prefix = "/mnt/user-data/"
            if virtual_path.startswith(prefix):
                rel = virtual_path[len(prefix):]
                parts = rel.split("/", 1)
                subdir = parts[0]
                rest = parts[1] if len(parts) > 1 else ""
                base = {
                    "outputs": self._paths.sandbox_outputs_dir(self.thread_id),
                    "uploads": self._paths.sandbox_uploads_dir(self.thread_id),
                    "workspace": self._paths.sandbox_work_dir(self.thread_id),
                }.get(subdir)
                if base:
                    return base / rest if rest else base
            return None


def get_active_executor(thread_id: str) -> DreamyExecutor | None:
    with _active_executors_lock:
        return _active_executors.get(thread_id)
