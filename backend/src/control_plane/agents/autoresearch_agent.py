from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.control_plane.models import AutoresearchObjective, PipelineRun, SchedulerJobState, utcnow

if TYPE_CHECKING:
    from src.control_plane.service import ControlPlaneService


class AutoresearchOrchestratorAgent:
    """Owns autoresearch objective lifecycle and continuous scheduling orchestration."""

    template_id = "knowledge-vault-autoresearch"
    default_daily_time = "02:00"

    def __init__(self, service: ControlPlaneService) -> None:
        self._service = service

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
                "Set `knowledge_vault.enabled: true` in config and restart Capybara Home."
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
                milestones=[
                    {
                        "at": utcnow(),
                        "event": "objective_started",
                        "detail": "Objective created and first Pro run queued.",
                    }
                ],
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
                current.milestones.append(
                    {
                        "at": utcnow(),
                        "event": "objective_restarted",
                        "detail": "Objective resumed via start trigger.",
                    }
                )

            self._service._store.mutate(mutate)

        self._write_progress_ledger(self.get_objective(effective_objective_id))

        run = None
        if bootstrap:
            run = self._service.create_run(
                template_id=self.template_id,
                inputs={
                    "autoresearch_topic": normalized_topic,
                    "urls": [],
                    "objective_id": effective_objective_id,
                    "endpoint_goal": normalized_endpoint_goal,
                },
                requires_approval=False,
                summary=summary or f"Autoresearch first run: {normalized_topic}",
                metadata={
                    "manual_trigger": True,
                    "source_thread_id": thread_id,
                    "objective_id": effective_objective_id,
                    "autoresearch_continuous": True,
                    "first_run_for_objective": True,
                    "forced_plan_mode": True,
                    "runtime_mode": "plan",
                    "subagents_enabled": True,
                },
            )
            if not run.requires_approval:
                run = self._service.start_run(run.id)

        objective = self.get_objective(effective_objective_id)
        self._write_progress_ledger(objective)
        return {
            "objective": objective,
            "bootstrap_run": run,
            "scheduled_time": effective_time,
        }

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
            current.milestones.append(
                {
                    "at": utcnow(),
                    "event": "objective_paused",
                    "detail": reason,
                }
            )

        self._service._store.mutate(mutate)
        updated = self.get_objective(objective_id)
        self._write_progress_ledger(updated)
        return updated

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
            current.milestones.append(
                {
                    "at": utcnow(),
                    "event": "objective_resumed",
                    "detail": "Resumed by user.",
                }
            )

        self._service._store.mutate(mutate)
        updated = self.get_objective(objective_id)
        self._write_progress_ledger(updated)
        return updated

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

    def update_after_run(self, *, run: PipelineRun) -> None:
        objective_id = str(run.metadata.get("objective_id") or run.inputs.get("objective_id") or "").strip()
        if not objective_id:
            return
        match = self._get_objective_internal(objective_id)
        if match is None:
            return

        recommended_tasks, recommended_queries = self._derive_recommendations(run=run, objective=match)
        schedule_job_id = None
        if bool(run.metadata.get("first_run_for_objective")) and run.status == "completed":
            schedule_job_id = self._upsert_daily_schedule(
                objective=match,
                topic=str(run.inputs.get("autoresearch_topic") or match.topic),
                endpoint_goal=str(run.inputs.get("endpoint_goal") or match.endpoint_goal),
                daily_time=match.schedule_daily_time or self.default_daily_time,
            )

        self._update_objective_from_run(
            objective_id,
            run=run,
            recommended_tasks=recommended_tasks,
            recommended_queries=recommended_queries,
            scheduler_job_id=schedule_job_id,
        )
        self._write_progress_ledger(self.get_objective(objective_id))

    def update_after_sufficiency(self, *, run: PipelineRun, report: dict[str, Any]) -> None:
        objective_id = str(
            report.get("objective_id")
            or run.metadata.get("objective_id")
            or run.inputs.get("objective_id")
            or ""
        ).strip()
        if not objective_id:
            return
        objective = self._get_objective_internal(objective_id)
        if objective is None:
            return

        decision = str(report.get("decision") or "").strip()
        score_raw = report.get("score")
        score = float(score_raw) if isinstance(score_raw, (int, float, str)) and str(score_raw).strip() else None
        blocking = [str(item) for item in report.get("blocking_checks") or [] if str(item).strip()]
        next_actions = [str(item) for item in report.get("recommended_actions") or [] if str(item).strip()]

        should_complete = bool(decision.lower() == "sufficient" and not blocking)

        def mutate(snapshot):
            current = snapshot.autoresearch_objectives[objective.id]
            current.latest_sufficiency_decision = decision or None
            current.latest_sufficiency_score = score
            current.latest_blocking_checks = blocking
            current.latest_next_actions = next_actions
            current.updated_at = utcnow()
            if should_complete:
                current.status = "completed_endpoint"
                current.pause_reason = "endpoint_reached"
                current.milestones.append(
                    {
                        "at": utcnow(),
                        "event": "objective_completed_endpoint",
                        "detail": f"Sufficiency reached with decision={decision} and no blockers.",
                    }
                )

        self._service._store.mutate(mutate)

        if should_complete and objective.scheduler_job_id:
            self._service.set_runtime_scheduler_job_enabled(
                objective.scheduler_job_id,
                enabled=False,
                reason="endpoint_reached",
            )

        self._write_progress_ledger(self.get_objective(objective_id))

    def _derive_recommendations(
        self,
        *,
        run: PipelineRun,
        objective: AutoresearchObjective,
    ) -> tuple[list[str], list[str]]:
        tasks: list[str] = []
        queries: list[str] = []
        for step in run.steps:
            output = step.output if isinstance(step.output, dict) else {}
            report = output.get("report")
            if not isinstance(report, dict):
                continue
            for candidate in report.get("recommended_actions") or []:
                text = str(candidate).strip()
                if text and text not in tasks:
                    tasks.append(text)
            for candidate in report.get("next_queries") or []:
                text = str(candidate).strip()
                if text and text not in queries:
                    queries.append(text)

        if not tasks:
            tasks.extend(
                [
                    "Review newly ingested sources and extract unanswered sub-questions.",
                    "Refine graph entities/relations tied to the endpoint goal.",
                ]
            )
        if not queries:
            topic = objective.topic.strip()
            endpoint = objective.endpoint_goal.strip()
            queries.extend(
                [
                    f"{topic} latest updates relevant to: {endpoint}",
                    f"{topic} official guidance and primary-source evidence",
                    f"{topic} risks, blockers, and unresolved questions",
                ]
            )
        return tasks[:10], queries[:10]

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
                name=f"Autoresearch Daily 02:00 - {normalized_topic[:36]}",
                pipeline_template_id=self.template_id,
                daily_time=effective_time,
                enabled=True,
                requires_approval=False,
                inputs={
                    "autoresearch_topic": normalized_topic,
                    "objective_id": objective.objective_id,
                    "endpoint_goal": normalized_endpoint_goal,
                    "urls": [],
                },
            )

            def mutate(snapshot):
                current = snapshot.autoresearch_objectives.get(objective.id)
                if current is None:
                    return
                current.scheduler_job_id = created.id
                current.schedule_daily_time = effective_time
                current.updated_at = utcnow()
                current.milestones.append(
                    {
                        "at": utcnow(),
                        "event": "schedule_created",
                        "detail": f"Created daily schedule {created.id} at {effective_time}.",
                    }
                )

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
            job.name = f"Autoresearch Daily 02:00 - {normalized_topic[:36]}"
            job.daily_time = effective_time
            job.enabled = True
            job.inputs = {
                **(job.inputs or {}),
                "autoresearch_topic": normalized_topic,
                "objective_id": objective.objective_id,
                "endpoint_goal": normalized_endpoint_goal,
                "urls": [],
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

    def _update_objective_from_run(
        self,
        objective_id: str,
        *,
        run: PipelineRun,
        recommended_tasks: list[str] | None = None,
        recommended_queries: list[str] | None = None,
        scheduler_job_id: str | None = None,
    ) -> None:
        def mutate(snapshot):
            objective = self._lookup(snapshot=snapshot, objective_id=objective_id)
            if objective is None:
                return
            objective.latest_run_id = run.id
            objective.updated_at = utcnow()
            if recommended_tasks is not None:
                objective.recommended_tasks = recommended_tasks
                objective.latest_next_actions = recommended_tasks
            if recommended_queries is not None:
                objective.recommended_queries = recommended_queries
            if scheduler_job_id:
                objective.scheduler_job_id = scheduler_job_id
            objective.milestones.append(
                {
                    "at": utcnow(),
                    "event": "run_executed",
                    "detail": f"Run {run.id} finished with status={run.status}",
                }
            )

        self._service._store.mutate(mutate)

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

    def _progress_paths(self, objective: AutoresearchObjective) -> tuple[Path, Path]:
        manager = self._service._default_vault_manager()
        root = manager.ops_dir / "autoresearch" / "objectives"
        topic_slug = re.sub(r"[^a-zA-Z0-9]+", "-", objective.objective_id.strip().lower()).strip("-") or "objective"
        objective_dir = root / topic_slug
        objective_dir.mkdir(parents=True, exist_ok=True)
        return (objective_dir / "progress.md", objective_dir / "progress.json")

    def _write_progress_ledger(self, objective: AutoresearchObjective) -> None:
        manager = self._service._default_vault_manager()
        root = manager.ops_dir / "autoresearch" / "objectives"
        topic_slug = re.sub(r"[^a-zA-Z0-9]+", "-", objective.objective_id.strip().lower()).strip("-") or "objective"
        objective_dir = root / topic_slug
        objective_dir.mkdir(parents=True, exist_ok=True)
        md_path = objective_dir / "progress.md"
        json_path = objective_dir / "progress.json"
        coverage = manager.get_coverage_progress(objective_id=objective.objective_id)
        progress_percent = round(float(coverage.get("percent") or 0.0), 1)
        payload = {
            "id": objective.id,
            "objective_id": objective.objective_id,
            "topic": objective.topic,
            "endpoint_goal": objective.endpoint_goal,
            "status": objective.status,
            "progress_percent": progress_percent,
            "endpoint_policy": "manual_stop_or_progress_or_no_more_action_items",
            "scheduler_job_id": objective.scheduler_job_id,
            "schedule_daily_time": objective.schedule_daily_time,
            "template_id": objective.template_id,
            "source_thread_id": objective.source_thread_id,
            "latest_run_id": objective.latest_run_id,
            "latest_sufficiency_score": objective.latest_sufficiency_score,
            "latest_sufficiency_decision": objective.latest_sufficiency_decision,
            "latest_blocking_checks": objective.latest_blocking_checks,
            "latest_next_actions": objective.latest_next_actions,
            "recommended_tasks": objective.recommended_tasks,
            "recommended_queries": objective.recommended_queries,
            "pause_reason": objective.pause_reason,
            "created_at": objective.created_at.isoformat(),
            "updated_at": objective.updated_at.isoformat(),
            "milestones": objective.milestones,
        }
        json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        lines = [
            f"# Autoresearch Objective: {objective.topic}",
            "",
            "## Detailed Objective",
            f"- Objective ID: `{objective.objective_id}`",
            f"- Topic: `{objective.topic}`",
            f"- Endpoint Goal: `{objective.endpoint_goal}`",
            f"- Tracking Status: `{objective.status}`",
            "",
            "## Endpoint",
            f"- Completion target: `{objective.endpoint_goal}`",
            "- Stop only when one of the following is true:",
            "  - manual user stop",
            "  - progress completed",
            "  - no more action items",
            "",
            "## Progress",
            f"- Percent: `{progress_percent:.1f}%`",
            f"- Last Updated: `{objective.updated_at.isoformat()}`",
            "",
            "## Structure",
            f"- Objective folder: `{md_path.parent}`",
            f"- Markdown tracker: `{md_path}`",
            f"- JSON tracker: `{json_path}`",
            f"- Suggested raw memory folder: `knowledge_vault/01_raw/{objective.objective_id}/`",
            "",
            "## UI Tracking",
            "- Primary control surface: `Knowledge Vault` objective card (`knowledge_vault card`).",
            "- Card freshness tag format: `Updated <relative-time>` (example: `Updated 15 minutes ago`).",
            "",
            "## Schedule Metadata",
            f"- Daily schedule time: `{objective.schedule_daily_time}`",
            f"- Scheduler job: `{objective.scheduler_job_id or '-'}`",
            "",
            "## Runtime Metadata",
            f"- Latest run: `{objective.latest_run_id or '-'}`",
            f"- Pause reason: `{objective.pause_reason or '-'}`",
            "",
            "## Next Steps",
        ]
        if objective.recommended_tasks:
            lines.extend(f"- {item}" for item in objective.recommended_tasks)
        else:
            lines.append("- Continue scheduled research cycles.")

        lines.extend(["", "## Next Queries"])
        if objective.recommended_queries:
            lines.extend(f"- {item}" for item in objective.recommended_queries)
        else:
            lines.append("- No next queries captured yet.")

        lines.extend(["", "## Milestones"])
        if objective.milestones:
            for milestone in objective.milestones[-20:]:
                at = str(milestone.get("at") or "-")
                event = str(milestone.get("event") or "event")
                detail = str(milestone.get("detail") or "")
                lines.append(f"- {at}: `{event}` {detail}".rstrip())
        else:
            lines.append("- No milestones recorded yet.")

        md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

        def mutate(snapshot):
            current = snapshot.autoresearch_objectives.get(objective.id)
            if current is None:
                return
            current.progress_markdown_path = str(md_path)
            current.progress_json_path = str(json_path)
            current.updated_at = utcnow()

        self._service._store.mutate(mutate)

    def _objective_id(self, topic: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", topic.strip().lower()).strip("-")
        return f"obj-{slug or 'general'}"
