from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from src.control_plane.models import AutoresearchObjective, PipelineRun, SchedulerJobState, utcnow

if TYPE_CHECKING:
    from src.control_plane.service import ControlPlaneService

logger = logging.getLogger(__name__)


class AutoresearchOrchestratorAgent:
    """Lifecycle owner for autoresearch objectives.

    Each objective is backed by a single-step pipeline template
    (``knowledge-vault-autoresearch-loop``). One scheduled run = one
    iteration of the agentic loop (generate → dedup → research → reflect).
    Per-iteration results land in a question ledger inside the vault.
    """

    template_id = "knowledge-vault-autoresearch-loop"
    default_daily_time = "02:00"

    def __init__(self, service: ControlPlaneService) -> None:
        self._service = service

    # --------------------------------------------------------------- start

    def start_objective(
        self,
        *,
        topic: str,
        endpoint_goal: str,
        thread_id: str | None = None,
        objective_id: str | None = None,
        daily_time: str | None = None,
        bootstrap: bool = True,
        summary: str | None = None,
    ) -> dict[str, Any]:
        normalized_topic = (topic or "").strip()
        normalized_endpoint_goal = (endpoint_goal or "").strip()
        if not normalized_topic:
            raise ValueError("Autoresearch topic is required.")
        if not normalized_endpoint_goal:
            raise ValueError("Autoresearch endpoint goal is required.")

        template_ids = {item.id for item in self._service.list_templates()}
        if self.template_id not in template_ids:
            raise ValueError(
                "Autoresearch is unavailable because the knowledge vault templates are disabled. "
                "Set `knowledge_vault.enabled: true` in config and restart CapyHome."
            )

        effective_objective_id = (objective_id or self._objective_id(normalized_topic)).strip()
        effective_time = (daily_time or self.default_daily_time).strip()
        self._service._parse_daily_time(effective_time)

        existing = self._get_objective_internal(effective_objective_id)
        if existing is None:
            objective = AutoresearchObjective(
                objective_id=effective_objective_id,
                topic=normalized_topic,
                endpoint_goal=normalized_endpoint_goal,
                schedule_daily_time=effective_time,
                status="active",
                scheduler_job_id=None,
                source_thread_id=thread_id,
            )

            def mutate(snapshot):
                snapshot.autoresearch_objectives[objective.id] = objective

            self._service._store.mutate(mutate)
        else:
            objective = existing
            if objective.scheduler_job_id:
                self._service.set_runtime_scheduler_job_enabled(
                    objective.scheduler_job_id,
                    enabled=True,
                    reason="autoresearch_resumed_by_start",
                    update_inputs={
                        "autoresearch_topic": normalized_topic,
                        "objective_id": effective_objective_id,
                        "endpoint_goal": normalized_endpoint_goal,
                    },
                )

            def mutate(snapshot):
                current = snapshot.autoresearch_objectives[objective.id]
                current.topic = normalized_topic
                current.endpoint_goal = normalized_endpoint_goal
                current.schedule_daily_time = effective_time
                current.status = "active"
                current.pause_reason = None
                current.updated_at = utcnow()

            self._service._store.mutate(mutate)

        run = None
        if bootstrap:
            run = self._service.create_run(
                template_id=self.template_id,
                inputs={
                    "autoresearch_topic": normalized_topic,
                    "objective_id": effective_objective_id,
                    "endpoint_goal": normalized_endpoint_goal,
                },
                requires_approval=False,
                summary=summary or f"Autoresearch first iteration: {normalized_topic}",
                metadata={
                    "manual_trigger": True,
                    "source_thread_id": thread_id,
                    "objective_id": effective_objective_id,
                    "autoresearch_continuous": True,
                    "first_run_for_objective": True,
                },
            )
            if not run.requires_approval:
                # The loop iteration takes many minutes — never block the HTTP
                # caller (or the asyncio event loop) waiting for it. The run
                # status will progress in the background; the frontend polls.
                run = self._service.start_run_in_background(run.id)

        objective = self.get_objective(effective_objective_id)
        return {
            "objective": objective,
            "bootstrap_run": run,
            "scheduled_time": effective_time,
        }

    # ---------------------------------------------------------- pause/resume

    def pause_objective(self, *, objective_id: str, reason: str = "denied") -> AutoresearchObjective:
        objective = self.get_objective(objective_id)
        if objective.scheduler_job_id:
            self._service.set_runtime_scheduler_job_enabled(
                objective.scheduler_job_id,
                enabled=False,
                reason=reason,
            )

        def mutate(snapshot):
            current = snapshot.autoresearch_objectives[objective.id]
            current.status = "paused_denied"
            current.pause_reason = reason
            current.updated_at = utcnow()

        self._service._store.mutate(mutate)
        return self.get_objective(objective_id)

    def resume_objective(self, *, objective_id: str) -> AutoresearchObjective:
        objective = self.get_objective(objective_id)
        if objective.scheduler_job_id:
            self._service.set_runtime_scheduler_job_enabled(
                objective.scheduler_job_id,
                enabled=True,
                reason="manual_resume",
            )

        def mutate(snapshot):
            current = snapshot.autoresearch_objectives[objective.id]
            current.status = "active"
            current.pause_reason = None
            current.updated_at = utcnow()

        self._service._store.mutate(mutate)
        return self.get_objective(objective_id)

    # --------------------------------------------------------------- run now

    def run_objective_now(self, *, objective_id: str) -> dict[str, Any]:
        """Trigger an immediate iteration for an objective.

        Two paths:
        - If a daily scheduler job already exists, defer to ``run_scheduler_job_now``
          so the run is recorded against the job.
        - Otherwise (stranded objective: crashed before first run completed),
          queue a bootstrap run directly so the lifecycle can recover. The
          objective's status is forced back to ``active`` and ``pause_reason``
          is cleared, matching the resume contract.
        """
        objective = self.get_objective(objective_id)
        normalized_objective_id = objective.objective_id

        if objective.scheduler_job_id:
            run = self._service.run_scheduler_job_now(objective.scheduler_job_id)
            return {
                "objective": self.get_objective(normalized_objective_id),
                "bootstrap_run": run,
                "via": "scheduler_job",
            }

        run = self._service.create_run(
            template_id=self.template_id,
            inputs={
                "autoresearch_topic": objective.topic,
                "objective_id": normalized_objective_id,
                "endpoint_goal": objective.endpoint_goal,
            },
            requires_approval=False,
            summary=f"Autoresearch recovery iteration: {objective.topic}",
            metadata={
                "manual_trigger": True,
                "source_thread_id": objective.source_thread_id,
                "objective_id": normalized_objective_id,
                "autoresearch_continuous": True,
                "first_run_for_objective": True,
                "recovery_run": True,
            },
        )
        if not run.requires_approval:
            run = self._service.start_run_in_background(run.id)

        def mutate(snapshot):
            current = snapshot.autoresearch_objectives.get(objective.id)
            if current is None:
                return
            current.status = "active"
            current.pause_reason = None
            current.updated_at = utcnow()

        self._service._store.mutate(mutate)
        self._service._append_audit_event(
            "autoresearch_objective_run_now",
            f"Manual run triggered for stranded autoresearch objective {normalized_objective_id}.",
            metadata={
                "objective_id": normalized_objective_id,
                "run_id": run.id,
            },
        )
        return {
            "objective": self.get_objective(normalized_objective_id),
            "bootstrap_run": run,
            "via": "bootstrap_recovery",
        }

    # ---------------------------------------------------------------- stop

    def stop_objective(self, *, objective_id: str) -> AutoresearchObjective:
        """Request cooperative cancellation of the objective's running iteration.

        The loop polls a stop flag at phase boundaries; once it observes the
        flag it raises and the run finalises as ``cancelled``. We do not block
        on completion here — the request is fire-and-forget and the UI will
        observe the cleared ``running_run_id`` on the next poll.
        """
        objective = self.get_objective(objective_id)
        running_run_id = (objective.running_run_id or "").strip()
        if not running_run_id:
            raise ValueError(f"Autoresearch objective {objective_id} has no running run to stop.")
        self._service.request_run_stop(running_run_id)
        self._service._append_audit_event(
            "autoresearch_objective_stop_requested",
            f"Stop requested for autoresearch objective {objective.objective_id} (run {running_run_id}).",
            metadata={
                "objective_id": objective.objective_id,
                "run_id": running_run_id,
            },
        )

        def mutate(snapshot):
            current = snapshot.autoresearch_objectives.get(objective.id)
            if current is None:
                return
            current.current_activity = "Stopping…"
            current.current_activity_at = utcnow()
            current.updated_at = utcnow()

        self._service._store.mutate(mutate)
        return self.get_objective(objective_id)

    # ----------------------------------------------------------------- crud

    def delete_objective(self, *, objective_id: str) -> dict[str, Any]:
        objective = self.get_objective(objective_id)
        normalized_objective_id = objective.objective_id

        snapshot = self._service._store.read()
        runtime_jobs = snapshot.runtime_scheduler_jobs
        job_ids_to_remove: list[str] = []
        for job in runtime_jobs.values():
            job_objective_id = str((job.inputs or {}).get("objective_id") or "").strip()
            if job_objective_id == normalized_objective_id:
                job_ids_to_remove.append(job.id)
        if objective.scheduler_job_id and objective.scheduler_job_id not in job_ids_to_remove:
            job_ids_to_remove.append(objective.scheduler_job_id)

        removed_scheduler_jobs: list[str] = []
        for job_id in sorted(set(job_ids_to_remove)):
            try:
                self._service.delete_runtime_scheduler_job(job_id)
                removed_scheduler_jobs.append(job_id)
            except ValueError:
                continue

        manager = self._service._default_vault_manager()
        purge_result = manager.purge_objective(objective_id=normalized_objective_id)

        def mutate(snapshot):
            snapshot.autoresearch_objectives.pop(objective.id, None)

        self._service._store.mutate(mutate)
        self._service._append_audit_event(
            "autoresearch_objective_deleted",
            f"Deleted autoresearch objective {normalized_objective_id}.",
            metadata={
                "objective_id": normalized_objective_id,
                "objective_entry_id": objective.id,
                "removed_scheduler_jobs": removed_scheduler_jobs,
                "purge_result": purge_result,
            },
        )
        return {
            "deleted": True,
            "objective_id": normalized_objective_id,
            "removed_scheduler_jobs": removed_scheduler_jobs,
            "purge_result": purge_result,
        }

    def get_objective(self, objective_id: str) -> AutoresearchObjective:
        match = self._get_objective_internal(objective_id)
        if match is None:
            raise ValueError(f"Unknown autoresearch objective: {objective_id}")
        return match.model_copy(deep=True)

    def list_objectives(self) -> list[AutoresearchObjective]:
        snapshot = self._service._store.read()
        return sorted(
            [item.model_copy(deep=True) for item in snapshot.autoresearch_objectives.values()],
            key=lambda item: item.updated_at,
            reverse=True,
        )

    # -------------------------------------------------------- run lifecycle

    def update_after_run(self, *, run: PipelineRun) -> None:
        """Called by ControlPlaneService after each pipeline run finalises.

        Reads the loop-iteration summary from the step output and writes it
        into the objective. Also creates the daily scheduler job on the very
        first successful run.
        """
        objective_id = str(run.metadata.get("objective_id") or run.inputs.get("objective_id") or "").strip()
        if not objective_id:
            return
        match = self._get_objective_internal(objective_id)
        if match is None:
            return

        # Extract the loop summary from the (single) step output.
        iteration_summary: dict[str, Any] = {}
        for step in run.steps:
            output = step.output if isinstance(step.output, dict) else {}
            payload = output.get("iteration_summary")
            if isinstance(payload, dict):
                iteration_summary = payload
                break

        schedule_job_id = None
        if bool(run.metadata.get("first_run_for_objective")) and run.status == "completed":
            schedule_job_id = self._upsert_daily_schedule(
                objective=match,
                topic=str(run.inputs.get("autoresearch_topic") or match.topic),
                endpoint_goal=str(run.inputs.get("endpoint_goal") or match.endpoint_goal),
                daily_time=match.schedule_daily_time or self.default_daily_time,
            )

        stop_requested = bool(iteration_summary.get("stop"))
        stop_reason = str(iteration_summary.get("stop_reason") or "")

        def mutate(snapshot):
            current = snapshot.autoresearch_objectives.get(match.id)
            if current is None:
                return
            current.latest_run_id = run.id
            current.updated_at = utcnow()
            if iteration_summary:
                # Monotonic in iteration count — guard against any race in which
                # an older run's late-arriving summary would otherwise decrement it.
                summary_iteration = int(iteration_summary.get("iteration") or 0)
                current.loop_iteration = max(int(current.loop_iteration or 0), summary_iteration)
                current.last_novelty_rate = float(iteration_summary.get("novelty_rate") or 0.0)
                current.last_stop_reason = stop_reason or None
                current.last_reflection = str(iteration_summary.get("reflection") or "") or None
                coverage = iteration_summary.get("cluster_coverage")
                if isinstance(coverage, dict):
                    # Pydantic field is dict[str, int]; the loop already stringifies keys.
                    current.cluster_coverage = {str(k): int(v) for k, v in coverage.items()}
                ledger_path = iteration_summary.get("ledger_path")
                if ledger_path:
                    current.ledger_markdown_path = str(ledger_path)
                    current.ledger_json_path = str(ledger_path).replace("ledger.md", "ledger.json")
            if schedule_job_id:
                current.scheduler_job_id = schedule_job_id
            if stop_requested:
                current.status = "completed_endpoint"
                current.pause_reason = stop_reason or "novelty_decay"

        self._service._store.mutate(mutate)

        if stop_requested and match.scheduler_job_id:
            try:
                self._service.set_runtime_scheduler_job_enabled(
                    match.scheduler_job_id,
                    enabled=False,
                    reason=stop_reason or "novelty_decay",
                )
            except Exception:
                logger.exception("Failed to disable scheduler job after stop signal: %s", match.scheduler_job_id)

    # -------------------------------------------------------- scheduler ops

    def _upsert_daily_schedule(
        self,
        *,
        objective: AutoresearchObjective,
        topic: str,
        endpoint_goal: str,
        daily_time: str,
    ) -> str:
        effective_time = (daily_time or self.default_daily_time).strip()
        self._service._parse_daily_time(effective_time)
        normalized_topic = (topic or objective.topic).strip()
        normalized_endpoint_goal = (endpoint_goal or objective.endpoint_goal).strip()

        snapshot = self._service._store.read()
        matches = [
            job
            for job in snapshot.runtime_scheduler_jobs.values()
            if job.pipeline_template_id == self.template_id
            and str((job.inputs or {}).get("objective_id") or "").strip() == objective.objective_id
        ]

        if not matches:
            created = self._service.create_runtime_scheduler_job(
                name=f"Autoresearch Daily {effective_time} - {normalized_topic[:36]}",
                pipeline_template_id=self.template_id,
                daily_time=effective_time,
                enabled=True,
                requires_approval=False,
                inputs={
                    "autoresearch_topic": normalized_topic,
                    "objective_id": objective.objective_id,
                    "endpoint_goal": normalized_endpoint_goal,
                },
            )

            def mutate(snapshot):
                current = snapshot.autoresearch_objectives.get(objective.id)
                if current is None:
                    return
                current.scheduler_job_id = created.id
                current.schedule_daily_time = effective_time
                current.updated_at = utcnow()

            self._service._store.mutate(mutate)
            return created.id

        primary = sorted(matches, key=lambda item: item.id)[0]
        duplicates = [item for item in matches if item.id != primary.id]
        for duplicate in duplicates:
            self._service.set_runtime_scheduler_job_enabled(
                duplicate.id,
                enabled=False,
                reason=f"duplicate_schedule_for_{objective.objective_id}",
            )

        now = utcnow()

        def mutate(snapshot):
            job = snapshot.runtime_scheduler_jobs.get(primary.id)
            if job is None:
                return
            job.name = f"Autoresearch Daily {effective_time} - {normalized_topic[:36]}"
            job.daily_time = effective_time
            job.enabled = True
            job.inputs = {
                **(job.inputs or {}),
                "autoresearch_topic": normalized_topic,
                "objective_id": objective.objective_id,
                "endpoint_goal": normalized_endpoint_goal,
            }
            state = snapshot.scheduler_jobs.get(job.id)
            if state is None:
                state = SchedulerJobState(id=job.id)
                snapshot.scheduler_jobs[job.id] = state
            try:
                state.next_run_at = self._service._next_daily_run_at(now, effective_time)
                state.last_status = "resumed"
            except ValueError:
                state.last_status = "error: invalid daily_time"

            current = snapshot.autoresearch_objectives.get(objective.id)
            if current is None:
                return
            current.scheduler_job_id = job.id
            current.schedule_daily_time = effective_time
            current.updated_at = utcnow()

        self._service._store.mutate(mutate)
        return primary.id

    # ----------------------------------------------------------------- util

    def _get_objective_internal(self, objective_id: str) -> AutoresearchObjective | None:
        snapshot = self._service._store.read()
        return self._lookup(snapshot=snapshot, objective_id=objective_id)

    def _lookup(self, *, snapshot, objective_id: str) -> AutoresearchObjective | None:
        normalized = objective_id.strip()
        if not normalized:
            return None
        for entry in snapshot.autoresearch_objectives.values():
            if entry.objective_id == normalized or entry.id == normalized:
                return entry
        return None

    def _objective_id(self, topic: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", topic.strip().lower()).strip("-")
        return f"obj-{slug or 'general'}"
