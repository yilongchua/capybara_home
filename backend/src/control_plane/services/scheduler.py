"""Scheduler sub-service.

Owns:
- Runtime scheduler job CRUD (``create``/``update``/``delete``/``enable``).
- Daily-time parsing and next-run computation.
- The scheduler tick (firing due jobs) and manual ``run_now`` path.

Cross-domain dependencies (``create_run``, ``start_run``, audit event logging)
are routed through the back-reference to :class:`ControlPlaneService` so
behaviour is byte-identical to the original monolith.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.config import get_app_config
from src.control_plane.models import (
    PipelineRun,
    SchedulerJob,
    SchedulerJobState,
    utcnow,
)
from src.control_plane.store import ControlPlaneStore

if TYPE_CHECKING:
    from src.control_plane.service import ControlPlaneService


_DAILY_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class SchedulerService:
    def __init__(self, store: ControlPlaneStore, control_plane: ControlPlaneService) -> None:
        self._store = store
        self._cps = control_plane

    @staticmethod
    def parse_daily_time(daily_time: str) -> tuple[int, int]:
        normalized = (daily_time or "").strip()
        match = _DAILY_TIME_RE.match(normalized)
        if not match:
            raise ValueError("Invalid daily_time; expected HH:MM (24-hour).")
        return int(match.group(1)), int(match.group(2))

    def next_daily_run_at(self, now: datetime, daily_time: str) -> datetime:
        hour, minute = self.parse_daily_time(daily_time)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    def jobs_from_config(self) -> dict[str, SchedulerJob]:
        config = get_app_config().scheduler
        return {job.id: job.model_copy(deep=True) for job in config.jobs}

    def jobs_from_runtime(self) -> dict[str, SchedulerJob]:
        snapshot = self._store.read()
        return {
            job_id: job.model_copy(deep=True)
            for job_id, job in snapshot.runtime_scheduler_jobs.items()
        }

    def merged_jobs(self) -> dict[str, SchedulerJob]:
        jobs = self.jobs_from_config()
        for job_id, job in self.jobs_from_runtime().items():
            if job_id not in jobs:
                jobs[job_id] = job
        return jobs

    def create_runtime_scheduler_job(
        self,
        *,
        name: str,
        pipeline_template_id: str,
        daily_time: str,
        enabled: bool = True,
        inputs: dict[str, Any] | None = None,
        requires_approval: bool | None = False,
    ) -> SchedulerJob:
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise ValueError("Scheduler job name is required.")
        normalized_time = daily_time.strip()
        self.parse_daily_time(normalized_time)

        snapshot = self._store.read()
        if pipeline_template_id not in snapshot.templates:
            raise ValueError(f"Unknown pipeline template: {pipeline_template_id}")

        objective_id = str((inputs or {}).get("objective_id") or "").strip()
        for job in self.merged_jobs().values():
            if getattr(job, "schedule_type", "interval") != "daily_time":
                continue
            if not job.daily_time:
                continue
            existing_objective_id = str((job.inputs or {}).get("objective_id") or "").strip()
            if (
                job.pipeline_template_id == pipeline_template_id
                and job.daily_time == normalized_time
                and (
                    (objective_id and existing_objective_id and existing_objective_id == objective_id)
                    or (not objective_id and not existing_objective_id)
                )
            ):
                raise ValueError(
                    "A daily schedule already exists for this template and time."
                )

        now = utcnow()
        job = SchedulerJob(
            id=f"runtime-sched-{uuid4().hex[:10]}",
            name=normalized_name,
            pipeline_template_id=pipeline_template_id,
            schedule_type="daily_time",
            daily_time=normalized_time,
            interval_seconds=24 * 60 * 60,
            enabled=enabled,
            inputs=inputs or {},
            requires_approval=requires_approval,
        )

        def mutate(snapshot):
            snapshot.runtime_scheduler_jobs[job.id] = job
            snapshot.scheduler_jobs[job.id] = SchedulerJobState(
                id=job.id,
                next_run_at=self.next_daily_run_at(now, normalized_time),
            )

        self._store.mutate(mutate)
        self._cps._append_audit_event(
            "scheduler_runtime_job_created",
            f"Created runtime scheduler job {job.id}.",
            metadata={
                "job_id": job.id,
                "template_id": job.pipeline_template_id,
                "daily_time": job.daily_time,
            },
        )
        return job

    def update_runtime_scheduler_job(
        self,
        job_id: str,
        *,
        daily_time: str | None = None,
        endpoint_goal: str | None = None,
    ) -> SchedulerJob:
        config_jobs = self.jobs_from_config()
        if job_id in config_jobs:
            raise ValueError("Cannot modify config-backed scheduler jobs.")

        normalized_time: str | None = None
        if daily_time is not None:
            normalized_time = daily_time.strip()
            self.parse_daily_time(normalized_time)

        now = utcnow()
        result: dict = {}

        def mutate(snapshot):
            job = snapshot.runtime_scheduler_jobs.get(job_id)
            if job is None:
                raise ValueError(f"Unknown runtime scheduler job: {job_id}")
            if normalized_time is not None:
                job.daily_time = normalized_time
                state = snapshot.scheduler_jobs.get(job_id)
                if state is not None and job.enabled:
                    try:
                        state.next_run_at = self.next_daily_run_at(now, normalized_time)
                    except ValueError:
                        pass
            if endpoint_goal is not None:
                job.inputs = {**(job.inputs or {}), "endpoint_goal": endpoint_goal.strip()}
            result["job"] = job

        self._store.mutate(mutate)
        metadata: dict[str, Any] = {"job_id": job_id}
        if normalized_time is not None:
            metadata["daily_time"] = normalized_time
        if endpoint_goal is not None:
            metadata["endpoint_goal"] = endpoint_goal.strip()
        self._cps._append_audit_event(
            "scheduler_runtime_job_updated",
            f"Updated runtime scheduler job {job_id}.",
            metadata=metadata,
        )
        return result["job"]

    def update_runtime_scheduler_job_time(self, job_id: str, *, daily_time: str) -> SchedulerJob:
        return self.update_runtime_scheduler_job(job_id, daily_time=daily_time)

    def delete_runtime_scheduler_job(self, job_id: str) -> None:
        config_jobs = self.jobs_from_config()
        if job_id in config_jobs:
            raise ValueError("Cannot delete config-backed scheduler jobs.")

        def mutate(snapshot):
            if job_id not in snapshot.runtime_scheduler_jobs:
                raise ValueError(f"Unknown runtime scheduler job: {job_id}")
            snapshot.runtime_scheduler_jobs.pop(job_id, None)
            snapshot.scheduler_jobs.pop(job_id, None)
            return True

        self._store.mutate(mutate)
        self._cps._append_audit_event(
            "scheduler_runtime_job_deleted",
            f"Deleted runtime scheduler job {job_id}.",
            metadata={"job_id": job_id},
        )

    def set_runtime_scheduler_job_enabled(
        self,
        job_id: str,
        *,
        enabled: bool,
        reason: str | None = None,
        update_inputs: dict[str, Any] | None = None,
    ) -> bool:
        if not job_id:
            return False
        changed = {"value": False}
        now = utcnow()

        def mutate(snapshot):
            job = snapshot.runtime_scheduler_jobs.get(job_id)
            if job is None:
                return
            if update_inputs:
                job.inputs = {**(job.inputs or {}), **update_inputs}
            if job.enabled == enabled and not update_inputs:
                return
            job.enabled = enabled
            state = snapshot.scheduler_jobs.get(job_id)
            if state is not None:
                if enabled:
                    state.last_status = "resumed"
                    if job.daily_time:
                        try:
                            state.next_run_at = self.next_daily_run_at(now, job.daily_time)
                        except ValueError:
                            state.last_status = "error: invalid daily_time"
                else:
                    state.last_status = f"paused: {reason}" if reason else "paused"
            changed["value"] = True

        self._store.mutate(mutate)
        if changed["value"]:
            event_kind = "scheduler_runtime_job_resumed" if enabled else "scheduler_runtime_job_paused"
            event_message = ("Resumed" if enabled else "Paused") + f" runtime scheduler job {job_id}."
            self._cps._append_audit_event(
                event_kind,
                event_message,
                metadata={"job_id": job_id, "reason": reason or "", "enabled": enabled},
            )
        return changed["value"]

    def pause_runtime_scheduler_job(self, job_id: str, *, reason: str | None = None) -> bool:
        return self.set_runtime_scheduler_job_enabled(job_id, enabled=False, reason=reason)

    def run_scheduler_tick(self) -> list[PipelineRun]:
        config = get_app_config().scheduler
        if not config.enabled:
            return []

        now = utcnow()
        jobs: dict[str, SchedulerJob] = {
            job.id: job for job in self.merged_jobs().values() if job.enabled
        }
        if not jobs:
            return []

        def initialize_states(snapshot):
            due_job_ids: list[str] = []
            for job_id, job in jobs.items():
                state = snapshot.scheduler_jobs.get(job_id)
                if state is None:
                    state = SchedulerJobState(id=job_id)
                    snapshot.scheduler_jobs[job_id] = state
                schedule_type = getattr(job, "schedule_type", "interval")
                if schedule_type == "daily_time":
                    if not job.daily_time:
                        state.last_status = "error: missing daily_time"
                        continue
                    try:
                        if state.next_run_at is None:
                            state.next_run_at = self.next_daily_run_at(now, job.daily_time)
                        if state.next_run_at <= now:
                            state.next_run_at = self.next_daily_run_at(now, job.daily_time)
                            state.last_status = "queued"
                            due_job_ids.append(job_id)
                    except ValueError:
                        state.last_status = "error: invalid daily_time"
                    continue

                interval_seconds = max(1, int(job.interval_seconds))
                if state.next_run_at is None:
                    state.next_run_at = now + timedelta(seconds=interval_seconds)
                if state.next_run_at <= now:
                    state.next_run_at = now + timedelta(seconds=interval_seconds)
                    state.last_status = "queued"
                    due_job_ids.append(job_id)
            return due_job_ids

        due_job_ids = self._store.mutate(initialize_states)
        runs: list[PipelineRun] = []

        for job_id in due_job_ids:
            job = jobs[job_id]
            self._cps._append_audit_event(
                "scheduler_job_due",
                f"Scheduler job due: {job.name}",
                metadata={"job_id": job.id, "template_id": job.pipeline_template_id},
            )
            run: PipelineRun | None = None
            status = "queued"
            try:
                run = self._cps.create_run(
                    template_id=job.pipeline_template_id,
                    inputs=job.inputs,
                    requires_approval=job.requires_approval,
                    summary=f"Scheduled run: {job.name}",
                    metadata={"scheduler_job_id": job.id},
                )
                if not run.requires_approval:
                    run = self._cps.start_run(run.id)
                status = run.status
            except Exception as exc:
                status = f"error: {exc}"
                self._cps._append_audit_event(
                    "scheduler_job_error",
                    f"Scheduler job failed: {job.name}",
                    metadata={"job_id": job.id, "error": str(exc)},
                )

            def update_state(snapshot):
                state = snapshot.scheduler_jobs.get(job_id) or SchedulerJobState(id=job_id)
                state.last_run_at = now
                state.last_status = status
                state.last_run_id = run.id if run is not None else None
                snapshot.scheduler_jobs[job_id] = state

            self._store.mutate(update_state)
            if run is not None:
                self._cps._append_audit_event(
                    "scheduler_job_run",
                    f"Scheduler run {run.id} created for {job.name} ({status}).",
                    metadata={"job_id": job.id, "run_id": run.id, "status": status},
                )
                runs.append(run)

        return runs

    def run_scheduler_job_now(self, job_id: str) -> PipelineRun:
        job = self.merged_jobs().get(job_id)
        if job is None:
            raise ValueError(f"Unknown scheduler job: {job_id}")
        if not job.enabled:
            runtime_job = self.jobs_from_runtime().get(job_id)
            if runtime_job is not None and runtime_job.pipeline_template_id == "knowledge-vault-autoresearch":
                self.set_runtime_scheduler_job_enabled(
                    job_id,
                    enabled=True,
                    reason="manual_run_override",
                )
                refreshed = self.merged_jobs().get(job_id)
                if refreshed is not None:
                    job = refreshed
            else:
                self._cps._append_audit_event(
                    "scheduler_job_manual_blocked",
                    f"Manual scheduler run blocked because job is disabled: {job_id}",
                    metadata={
                        "job_id": job_id,
                        "template_id": job.pipeline_template_id,
                        "reason": "job_disabled",
                    },
                )
                raise ValueError(f"Scheduler job is disabled: {job_id}")

        now = utcnow()
        run = self._cps.create_run(
            template_id=job.pipeline_template_id,
            inputs=job.inputs,
            requires_approval=job.requires_approval,
            summary=f"Manual scheduler run: {job.name}",
            metadata={"scheduler_job_id": job.id, "manual_trigger": True},
        )
        if not run.requires_approval:
            run = self._cps.start_run(run.id)

        def update_state(snapshot):
            state = snapshot.scheduler_jobs.get(job_id) or SchedulerJobState(id=job_id)
            state.last_run_at = now
            state.last_status = run.status
            state.last_run_id = run.id
            snapshot.scheduler_jobs[job_id] = state

        self._store.mutate(update_state)
        self._cps._append_audit_event(
            "scheduler_job_manual",
            f"Manual scheduler run {run.id} created for {job.name} ({run.status}).",
            metadata={"job_id": job.id, "run_id": run.id, "status": run.status},
        )
        return run
