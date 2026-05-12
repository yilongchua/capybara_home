"""Dreamy watchdog middleware — enforces run-time limits and writes checkpoints.

This middleware addresses the class of failures where an agent run hangs
indefinitely. It provides two layers of protection that operate at hook
boundaries (where we have control):

1. **Wall-clock enforcement** — ``after_agent`` checks total elapsed time
   since ``before_agent`` and terminates via ``jump_to: "end"`` when
   ``max_run_wall_clock`` is exceeded.

2. **Checkpoint persistence** — on every ``after_agent``, writes
   ``checkpoint.json`` from the current ``workflow.json`` execution_state
   so row-progress is never lost between turns.

Stuck model-call detection (model_call_start with no model_call_end) is
handled by the background trajectory monitor registered in
``dreamy_trajectory_monitor`` — this middleware coordinates with it by
recording timestamps on runtime.context.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.dreamy_timeout_config import DreamyTimeoutConfig, get_dreamy_timeout_config
from src.config.paths import get_paths


class DreamyWatchdogState(AgentState):
    dreamy_mode: NotRequired[bool]
    dreamy_watchdog: NotRequired[dict | None]


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


def _write_checkpoint(thread_id: str, workflow_path) -> None:
    """Write checkpoint.json from workflow.json execution_state.

    This is a standalone function (not a method) so it can be called
    from both the middleware and the trajectory monitor.
    """
    try:
        data = json.loads(workflow_path.read_text(encoding="utf-8"))
        if data.get("version") != "2":
            return

        es = data.get("execution_state", {})
        current_row = es.get("current_row_index", 0)
        total_rows = es.get("total_rows", 0)
        phase = es.get("phase", "design")

        # Read existing checkpoint to preserve completed list
        checkpoint_path = workflow_path.parent / "checkpoint.json"
        completed: list[int] = []
        try:
            if checkpoint_path.exists():
                cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                completed = cp.get("completed", [])
        except Exception:
            pass

        # Update completed list based on current_row_index
        for row_idx in range(current_row):
            if row_idx not in completed:
                completed.append(row_idx)
        completed.sort()

        checkpoint = {
            "total": total_rows,
            "completed": completed,
            "last_done": completed[-1] if completed else None,
            "phase": phase,
            "updated_at": _now_iso(),
        }

        checkpoint_path.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


class DreamyWatchdogMiddleware(AgentMiddleware[DreamyWatchdogState]):
    """Detect stuck model calls and enforce run-time limits for dreamy threads."""

    state_schema = DreamyWatchdogState

    def __init__(self, config: DreamyTimeoutConfig | None = None):
        super().__init__()
        self._config = config or get_dreamy_timeout_config()
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop = threading.Event()

    def _is_dreamy_mode(self, runtime: Runtime) -> bool:
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return False
        return bool(context.get("dreamy_mode", False))

    def _get_thread_id(self, runtime: Runtime) -> str | None:
        context = runtime.context if isinstance(runtime.context, dict) else {}
        thread_id = context.get("thread_id")
        return thread_id if isinstance(thread_id, str) and thread_id else None

    # ------------------------------------------------------------------
    # before_agent — record start time, launch trajectory monitor
    # ------------------------------------------------------------------

    @override
    def before_agent(self, state: DreamyWatchdogState, runtime: Runtime) -> dict | None:
        if not self._is_dreamy_mode(runtime):
            return None

        thread_id = self._get_thread_id(runtime)
        if not thread_id:
            return None

        cfg = self._config
        if not cfg.enabled:
            return None

        context = getattr(runtime, "context", None) or {}
        if not isinstance(context, dict):
            context = {}
            runtime.context = context

        # Record run start time for wall-clock enforcement
        context["_dreamy_run_start"] = time.time()

        # Launch background trajectory monitor if not already running
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_stop.clear()
            paths = get_paths()
            traj_dir = paths.thread_dir(thread_id) / "logs" / "trajectory"
            if traj_dir.exists():
                self._monitor_thread = threading.Thread(
                    target=self._trajectory_monitor_loop,
                    args=(traj_dir, thread_id, runtime),
                    daemon=True,
                    name=f"watchdog-{thread_id[:8]}",
                )
                self._monitor_thread.start()

        return None

    # ------------------------------------------------------------------
    # after_agent — wall-clock check, checkpoint writing
    # ------------------------------------------------------------------

    @override
    def after_agent(self, state: DreamyWatchdogState, runtime: Runtime) -> dict | None:
        if not self._is_dreamy_mode(runtime):
            return None

        thread_id = self._get_thread_id(runtime)
        if not thread_id:
            return None

        cfg = self._config
        if not cfg.enabled:
            return None

        context = getattr(runtime, "context", None) or {}

        # Wall-clock check
        run_start = context.get("_dreamy_run_start")
        if run_start and isinstance(run_start, (int, float)):
            elapsed = time.time() - run_start
            if elapsed >= cfg.max_run_wall_clock:
                append_runtime_event(
                    runtime,
                    {
                        "source": "dreamy_watchdog",
                        "signal": "run_wall_clock_exceeded",
                        "elapsed": round(elapsed, 1),
                        "threshold": cfg.max_run_wall_clock,
                    },
                )
                return {
                    "messages": [
                        HumanMessage(
                            name="dreamy_watchdog_terminated",
                            content=(
                                "<system_warning>\n"
                                f"Watchdog terminated run: wall-clock exceeded "
                                f"{cfg.max_run_wall_clock}s ({elapsed:.0f}s elapsed).\n"
                                "The agent run was too long — execution stopped.\n"
                                "</system_warning>"
                            ),
                        )
                    ],
                    "jump_to": "end",
                }

        # Write checkpoint.json to preserve row-progress state
        if cfg.checkpoint_on_after_agent:
            paths = get_paths()
            workflow_path = paths.sandbox_outputs_dir(thread_id) / "workflow.json"
            if workflow_path.exists():
                _write_checkpoint(thread_id, workflow_path)

        return None

    # ------------------------------------------------------------------
    # Background trajectory monitor — detects stuck model calls
    # ------------------------------------------------------------------

    def _trajectory_monitor_loop(
        self, traj_dir, thread_id: str, runtime: Runtime
    ) -> None:
        """Periodically scan the trajectory file for in-flight model calls.

        Scans every 10 seconds. Detects a ``model_call_start`` event that
        has no matching ``model_call_end`` and has exceeded
        ``max_model_call_duration``.
        """
        cfg = self._config
        poll_interval = 10.0  # seconds between scans

        while not self._monitor_stop.wait(timeout=poll_interval):
            try:
                # Find the latest trajectory file
                traj_files = sorted(traj_dir.glob("trajectory-*.jsonl"))
                if not traj_files:
                    continue

                latest = traj_files[-1]
                self._check_stuck_model_calls(latest, cfg, runtime)
            except Exception:
                # Non-fatal — don't crash the monitor
                pass

    def _check_stuck_model_calls(
        self, traj_path, cfg: DreamyTimeoutConfig, runtime: Runtime
    ) -> None:
        """Read the trajectory file and detect stuck model calls."""
        try:
            lines = traj_path.read_text(encoding="utf-8").strip().splitlines()
        except Exception:
            return

        # Parse events in order, tracking in-flight model calls
        in_flight: dict[str, float] = {}  # call_index -> start_timestamp
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = event.get("ts", 0.0)
            if not isinstance(ts, (int, float)):
                continue
            etype = event.get("event", "")
            run_id = event.get("run_id", "")

            if etype == "model_call_start":
                call_key = f"{run_id}:mci:{len(in_flight)}"
                in_flight[call_key] = ts
            elif etype in ("model_call_end", "after_model", "after_agent"):
                # Close all in-flight calls for this run
                keys_to_remove = [k for k in in_flight if k.startswith(f"{run_id}:")]
                for k in keys_to_remove:
                    del in_flight[k]

        # Check for stuck calls
        now = time.time()
        context = getattr(runtime, "context", None) or {}
        warned = context.get("_dreamy_watchdog_warned", set()) or set()

        for call_key, start_ts in list(in_flight.items()):
            duration = now - start_ts
            if duration >= cfg.max_model_call_duration and call_key not in warned:
                warned.add(call_key)
                context["_dreamy_watchdog_warned"] = warned

                append_runtime_event(
                    runtime,
                    {
                        "source": "dreamy_watchdog",
                        "signal": "model_call_stuck",
                        "duration": round(duration, 1),
                        "threshold": cfg.max_model_call_duration,
                    },
                )

                # Terminate by injecting jump_to state
                # We store the termination signal on runtime.context so
                # after_agent can pick it up (since we can't return state
                # from the background thread).
                context["_dreamy_watchdog_terminate"] = {
                    "signal": "model_call_stuck",
                    "duration": round(duration, 1),
                    "threshold": cfg.max_model_call_duration,
                }

                # Stop the monitor — termination is imminent
                self._monitor_stop.set()

                return

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _stop_monitor(self) -> None:
        """Signal the background monitor to stop."""
        self._monitor_stop.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)


# LangChain's agent factory reads __can_jump_to__ off the overridden hook
# method to wire conditional edges from after_agent → END.
DreamyWatchdogMiddleware.after_agent.__can_jump_to__ = ["end"]  # type: ignore[attr-defined]
