from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx

from src.channels.service import get_channel_service
from src.config import get_app_config, get_extensions_config, get_paths  # noqa: F401
from src.control_plane.agents import (
    AgentExecutionContext,
    AgentExecutionError,
    AutoresearchOrchestratorAgent,
    ImproverAgent,
    KnowledgeVaultAgent,
    RedactionAgent,
)
from src.control_plane.csv_profiles import CSVProfileService
from src.control_plane.models import (
    ApprovalRequest,
    AuditEvent,
    AutoresearchObjective,
    FeedbackEvent,
    FolderSyncTarget,
    PipelineRun,
    PipelineStepDefinition,
    PipelineStepRun,
    PipelineTemplate,
    SchedulerJob,
    SchedulerJobState,
    TriggerEvent,
    utcnow,
)
from src.control_plane.redaction import RedactionService
from src.control_plane.services import (
    ApprovalsService,
    ArtifactsService,
    FeedbackService,
    ProposalsService,
    SchedulerService,
    TemplatesService,
    TriggersService,
    UnifiedVaultSearchService,
)
from src.control_plane.store import ControlPlaneStore
from src.control_plane.vault_learning import VaultLearningManager

logger = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".log",
}
_CONVERTIBLE_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}
class ControlPlaneService:
    def __init__(self, store: ControlPlaneStore | None = None) -> None:
        self._store = store or ControlPlaneStore()
        self._redaction = RedactionService()
        self._csv_profiles = CSVProfileService()
        self._autoresearch_orchestrator = AutoresearchOrchestratorAgent(self)
        self._redaction_agent = RedactionAgent(self)
        self._improver_agent = ImproverAgent(self)
        self._knowledge_vault_agent = KnowledgeVaultAgent(self)
        self._agents_by_kind = self._build_agent_registry()
        self._startup_jobs: dict[str, dict[str, Any]] = {}
        self._startup_lock = threading.Lock()
        self._active_startup_job_id: str | None = None
        self._service_state: dict[str, dict[str, Any]] = {}
        self._triggers = TriggersService(self._store, self._redaction)
        self._feedback = FeedbackService(self._store)
        self._artifacts = ArtifactsService(self._store)
        self._approvals = ApprovalsService(self._store, self)
        self._templates = TemplatesService(self._store)
        self._proposals = ProposalsService(self._store, self)
        self._scheduler = SchedulerService(self._store, self)
        self._vault_explorer_cache: dict[str, Any] = {}
        self._vault_explorer_cache_ttl_seconds = 300
        self._vault_explorer_cache_lock = threading.Lock()
        self._vault_ingest_job: dict[str, Any] = self._new_vault_ingest_job_state()
        self._vault_ingest_lock = threading.Lock()
        self._vault_ingest_logger: logging.Logger | None = None
        self._seed_from_config()

    def _build_agent_registry(self) -> dict[str, Any]:
        registry: dict[str, Any] = {}
        for agent in (self._redaction_agent, self._improver_agent, self._knowledge_vault_agent):
            for kind in agent.supported_kinds():
                registry[kind] = agent
        return registry

    def _seed_from_config(self) -> None:
        config = get_app_config()
        builtin_templates = self._templates.builtin_templates()

        def seed(snapshot):
            # Builtin templates are code-defined; always overwrite so new steps propagate without manual state wipes.
            for template in builtin_templates:
                snapshot.templates[template.id] = template.model_copy(deep=True)
            for template in config.pipelines.templates:
                if template.id not in snapshot.templates:
                    snapshot.templates[template.id] = template.model_copy(deep=True)

            for job in config.scheduler.jobs:
                if job.id not in snapshot.scheduler_jobs:
                    snapshot.scheduler_jobs[job.id] = SchedulerJobState(id=job.id)

        self._store.mutate(seed)

    def _builtin_templates(self) -> list[PipelineTemplate]:
        return self._templates.builtin_templates()

    def _scheduler_jobs_from_config(self) -> dict[str, SchedulerJob]:
        return self._scheduler.jobs_from_config()

    def _scheduler_jobs_from_runtime(self) -> dict[str, SchedulerJob]:
        return self._scheduler.jobs_from_runtime()

    def _merged_scheduler_jobs(self) -> dict[str, SchedulerJob]:
        return self._scheduler.merged_jobs()

    def _parse_daily_time(self, daily_time: str) -> tuple[int, int]:
        return SchedulerService.parse_daily_time(daily_time)

    def _next_daily_run_at(self, now: datetime, daily_time: str) -> datetime:
        return self._scheduler.next_daily_run_at(now, daily_time)

    def _proposal_review_key(self, run_id: str, proposal_id: str) -> str:
        return ProposalsService.proposal_review_key(run_id, proposal_id)

    def _self_improver_proposals_for_run(self, run: PipelineRun) -> list[dict[str, Any]]:
        return ProposalsService.proposals_for_run(run)

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
        return self._scheduler.create_runtime_scheduler_job(
            name=name,
            pipeline_template_id=pipeline_template_id,
            daily_time=daily_time,
            enabled=enabled,
            inputs=inputs,
            requires_approval=requires_approval,
        )

    def update_runtime_scheduler_job(
        self,
        job_id: str,
        *,
        daily_time: str | None = None,
        endpoint_goal: str | None = None,
    ) -> SchedulerJob:
        return self._scheduler.update_runtime_scheduler_job(
            job_id,
            daily_time=daily_time,
            endpoint_goal=endpoint_goal,
        )

    def update_runtime_scheduler_job_time(self, job_id: str, *, daily_time: str) -> SchedulerJob:
        return self._scheduler.update_runtime_scheduler_job_time(job_id, daily_time=daily_time)

    def delete_runtime_scheduler_job(self, job_id: str) -> None:
        return self._scheduler.delete_runtime_scheduler_job(job_id)

    def set_runtime_scheduler_job_enabled(
        self,
        job_id: str,
        *,
        enabled: bool,
        reason: str | None = None,
        update_inputs: dict[str, Any] | None = None,
    ) -> bool:
        return self._scheduler.set_runtime_scheduler_job_enabled(
            job_id,
            enabled=enabled,
            reason=reason,
            update_inputs=update_inputs,
        )

    def start_autoresearch_objective(
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
        return self._autoresearch_orchestrator.start_objective(
            topic=topic,
            endpoint_goal=endpoint_goal,
            thread_id=thread_id,
            objective_id=objective_id,
            daily_time=daily_time,
            bootstrap=bootstrap,
            summary=summary,
        )

    def pause_autoresearch_objective(
        self,
        objective_id: str,
        *,
        reason: str = "denied",
    ) -> AutoresearchObjective:
        return self._autoresearch_orchestrator.pause_objective(objective_id=objective_id, reason=reason)

    def resume_autoresearch_objective(self, objective_id: str) -> AutoresearchObjective:
        return self._autoresearch_orchestrator.resume_objective(objective_id=objective_id)

    def delete_autoresearch_objective(self, objective_id: str) -> dict[str, Any]:
        return self._autoresearch_orchestrator.delete_objective(objective_id=objective_id)

    def get_autoresearch_objective(self, objective_id: str) -> AutoresearchObjective:
        return self._autoresearch_orchestrator.get_objective(objective_id)

    def list_autoresearch_objectives(self) -> list[AutoresearchObjective]:
        return self._autoresearch_orchestrator.list_objectives()

    def get_autoresearch_progress_markdown(self, objective_id: str) -> tuple[str, str]:
        objective = self.get_autoresearch_objective(objective_id)
        progress_path = str(objective.progress_markdown_path or "").strip()
        if not progress_path:
            raise ValueError(f"No markdown tracker found for objective: {objective_id}")
        path = Path(progress_path)
        if not path.exists() or not path.is_file():
            raise ValueError(f"Markdown tracker does not exist for objective: {objective_id}")
        return (path.name, path.read_text(encoding="utf-8"))

    def list_self_improver_proposals(self) -> list[dict[str, Any]]:
        return self._proposals.list_self_improver_proposals()

    def _find_self_improver_proposal(
        self,
        *,
        run: PipelineRun,
        proposal_id: str,
    ) -> dict[str, Any]:
        return self._proposals.find_proposal(run=run, proposal_id=proposal_id)

    def _resolve_skill_path_for_proposal(self, proposal: dict[str, Any]) -> Path:
        return self._proposals.resolve_skill_path(proposal)

    def _apply_self_improver_proposal(self, proposal: dict[str, Any]) -> str:
        return self._proposals.apply_proposal(proposal)

    def resolve_self_improver_proposal(
        self,
        *,
        run_id: str,
        proposal_id: str,
        approve: bool,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self._proposals.resolve_self_improver_proposal(
            run_id=run_id,
            proposal_id=proposal_id,
            approve=approve,
            note=note,
        )

    def _artifact_root(self) -> Path:
        return self._artifacts.artifact_root()

    def _run_dir(self, run_id: str) -> Path:
        return self._artifacts.run_dir(run_id)

    def _write_json_artifact(self, run_id: str, filename: str, data: Any) -> str:
        return self._artifacts.write_json_artifact(run_id, filename, data)

    def _write_text_artifact(self, run_id: str, filename: str, content: str) -> str:
        return self._artifacts.write_text_artifact(run_id, filename, content)

    def _append_audit_event(self, kind: str, message: str, metadata: dict[str, Any] | None = None) -> AuditEvent:
        event = AuditEvent(kind=kind, message=message, metadata=metadata or {})
        max_entries = max(10, get_app_config().pipelines.audit_log_max_entries)

        def mutate(snapshot):
            snapshot.audit_log.append(event)
            if len(snapshot.audit_log) > max_entries:
                snapshot.audit_log = snapshot.audit_log[-max_entries:]

        self._store.mutate(mutate)
        return event

    def _step_definitions_for_run(self, run: PipelineRun) -> dict[str, PipelineStepDefinition]:
        raw_definitions = run.metadata.get("step_definitions", {})
        if isinstance(raw_definitions, list):
            definitions = {}
            for item in raw_definitions:
                definition = PipelineStepDefinition.model_validate(item)
                definitions[definition.id] = definition
            return definitions
        if isinstance(raw_definitions, dict):
            return {
                step_id: PipelineStepDefinition.model_validate(item)
                for step_id, item in raw_definitions.items()
                if isinstance(item, dict)
            }
        return {}

    def _expire_approvals(self) -> None:
        self._approvals._expire_approvals()

    def list_triggers(self) -> list[TriggerEvent]:
        return self._triggers.list_triggers()

    def create_trigger_event(
        self,
        *,
        source: str,
        message: str,
        channel_name: str | None = None,
        chat_id: str | None = None,
        user_id: str | None = None,
        classification: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> TriggerEvent:
        return self._triggers.create_trigger_event(
            source=source,
            message=message,
            channel_name=channel_name,
            chat_id=chat_id,
            user_id=user_id,
            classification=classification,
            metadata=metadata,
        )

    def record_channel_message(self, msg: Any, *, thread_id: str | None = None) -> TriggerEvent:
        return self._triggers.record_channel_message(msg, thread_id=thread_id)

    def list_templates(self) -> list[PipelineTemplate]:
        self._seed_from_config()
        return self._templates.list_templates()

    def upsert_template(self, template: PipelineTemplate) -> PipelineTemplate:
        return self._templates.upsert_template(template)

    def _build_step_runs(self, definitions: list[PipelineStepDefinition]) -> list[PipelineStepRun]:
        return [
            PipelineStepRun(
                step_id=definition.id,
                name=definition.name,
                kind=definition.kind,
            )
            for definition in definitions
        ]

    def create_run(
        self,
        *,
        template_id: str | None = None,
        steps: list[PipelineStepDefinition] | None = None,
        inputs: dict[str, Any] | None = None,
        trigger_event_id: str | None = None,
        summary: str = "",
        requires_approval: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PipelineRun:
        config = get_app_config()
        snapshot = self._store.read()

        template: PipelineTemplate | None = None
        definitions: list[PipelineStepDefinition]

        if template_id:
            template = snapshot.templates.get(template_id)
            if template is None:
                raise ValueError(f"Unknown pipeline template: {template_id}")
            definitions = [step.model_copy(deep=True) for step in template.steps]
        elif steps:
            definitions = [step.model_copy(deep=True) for step in steps]
        else:
            definitions = [
                PipelineStepDefinition(
                    name="Review inputs",
                    kind="note",
                    config={"message": "No steps were provided; created as a placeholder run."},
                )
            ]

        raw_inputs = {}
        if template is not None:
            raw_inputs.update(template.default_inputs)
        if inputs:
            raw_inputs.update(inputs)

        effective_requires_approval = (
            requires_approval
            if requires_approval is not None
            else template.requires_approval
            if template is not None
            else config.pipelines.default_requires_approval
        )

        run = PipelineRun(
            template_id=template.id if template else None,
            template_name=template.name if template else "Ad-hoc pipeline",
            trigger_event_id=trigger_event_id,
            summary=summary or (template.description if template else "Ad-hoc local pipeline run"),
            requires_approval=effective_requires_approval,
            inputs=raw_inputs,
            masked_inputs=self._redaction.redact_value(raw_inputs),
            steps=self._build_step_runs(definitions),
            metadata={
                **(metadata or {}),
                "step_definitions": {
                    definition.id: definition.model_dump(mode="json") for definition in definitions
                },
            },
        )

        if effective_requires_approval and config.approvals.enabled:
            approval = ApprovalRequest(
                pipeline_run_id=run.id,
                title=f"Approve pipeline: {run.template_name}",
                description=run.summary,
                metadata={
                    "template_id": run.template_id,
                    "trigger_event_id": trigger_event_id,
                },
            )
            run.status = "pending_approval"
            run.approval_request_id = approval.id
        else:
            approval = None
            run.status = "approved"

        def mutate(snapshot):
            snapshot.runs[run.id] = run
            if approval is not None:
                snapshot.approvals[approval.id] = approval

            if trigger_event_id and trigger_event_id in snapshot.triggers:
                trigger = snapshot.triggers[trigger_event_id]
                trigger.status = "drafted"
                trigger.pipeline_template_id = run.template_id
                trigger.pipeline_run_id = run.id
                trigger.updated_at = utcnow()

        self._store.mutate(mutate)
        return self.get_run(run.id)

    def list_runs(
        self,
        *,
        thread_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int | None = None,
    ) -> list[PipelineRun]:
        snapshot = self._store.read()
        items = list(snapshot.runs.values())

        if thread_id:
            normalized_thread_id = thread_id.strip()
            items = [
                run
                for run in items
                if normalized_thread_id
                in {
                    str(run.metadata.get("source_thread_id", "")).strip(),
                    str(run.metadata.get("thread_id", "")).strip(),
                    str(run.inputs.get("source_thread_id", "")).strip(),
                    str(run.inputs.get("thread_id", "")).strip(),
                }
            ]

        if statuses:
            allowed = {status.strip() for status in statuses if status and status.strip()}
            if allowed:
                items = [run for run in items if run.status in allowed]

        items.sort(key=lambda item: item.created_at, reverse=True)
        if limit is not None:
            return items[: max(1, limit)]
        return items

    def get_run(self, run_id: str) -> PipelineRun:
        snapshot = self._store.read()
        run = snapshot.runs.get(run_id)
        if run is None:
            raise ValueError(f"Unknown pipeline run: {run_id}")
        return run

    def get_run_artifact_path(self, run_id: str, artifact_name: str) -> Path:
        if not artifact_name or "/" in artifact_name or "\\" in artifact_name:
            raise ValueError("Invalid artifact name.")

        run = self.get_run(run_id)
        run_dir = self._run_dir(run_id).resolve()

        for artifact in run.artifacts:
            raw = Path(str(artifact))
            candidate = (raw if raw.is_absolute() else run_dir / raw).resolve()
            if candidate.name != artifact_name:
                continue
            if run_dir not in candidate.parents:
                continue
            if not candidate.exists() or not candidate.is_file():
                continue
            return candidate

        raise ValueError(f"Artifact not found for run {run_id}: {artifact_name}")

    def _update_step_state(
        self,
        run_id: str,
        step_id: str,
        *,
        status: str | None = None,
        log_line: str | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        now = utcnow()

        def mutate(snapshot):
            run = snapshot.runs[run_id]
            run.updated_at = now
            for step in run.steps:
                if step.step_id != step_id:
                    continue
                if status:
                    step.status = status
                if started and step.started_at is None:
                    step.started_at = now
                if finished:
                    step.finished_at = now
                if log_line:
                    step.logs.append(log_line)
                if output:
                    step.output.update(output)
                if error:
                    step.error = error
                break

        self._store.mutate(mutate)

    def _finalize_run(
        self,
        run_id: str,
        *,
        status: str,
        alert: str | None = None,
    ) -> PipelineRun:
        now = utcnow()

        def mutate(snapshot):
            run = snapshot.runs[run_id]
            run.status = status
            run.updated_at = now
            run.finished_at = now
            if alert:
                run.alerts.append(alert)
            if run.trigger_event_id and run.trigger_event_id in snapshot.triggers:
                trigger = snapshot.triggers[run.trigger_event_id]
                trigger.status = "processed" if status == "completed" else "error"
                trigger.updated_at = now
            return run

        finalized = self._store.mutate(mutate)
        try:
            self._autoresearch_orchestrator.update_after_run(run=finalized)
        except Exception:
            logger.exception("Failed to update autoresearch objective after run finalization: %s", finalized.id)
        return finalized

    def start_run(self, run_id: str) -> PipelineRun:
        run = self.get_run(run_id)
        if run.status == "pending_approval":
            raise ValueError("Pipeline run is still pending approval.")
        if run.status == "running":
            return run
        if run.status in {"completed", "failed", "cancelled", "rejected"}:
            raise ValueError(f"Pipeline run cannot be started from status '{run.status}'.")

        now = utcnow()

        def mark_running(snapshot):
            current = snapshot.runs[run_id]
            current.status = "running"
            current.started_at = current.started_at or now
            current.updated_at = now
            return current

        run = self._store.mutate(mark_running)
        definitions = self._step_definitions_for_run(run)

        for step in run.steps:
            definition = definitions.get(step.step_id)
            if definition is None:
                self._update_step_state(
                    run_id,
                    step.step_id,
                    status="failed",
                    error="Step definition not found.",
                    finished=True,
                )
                return self._finalize_run(run_id, status="failed", alert=f"Missing step definition for {step.name}.")

            self._update_step_state(run_id, step.step_id, status="running", started=True, log_line="Step started.")
            try:
                output = self._execute_step(run_id=run_id, run=self.get_run(run_id), step=step, definition=definition)
                # Propagate agent-level skip signals (inactivity guard, loop guard) to the step status
                # so they are visible in the pipeline run log rather than silently appearing as "completed".
                step_status = "completed"
                log_line = "Step completed."
                if isinstance(output, dict):
                    report_status = str((output.get("report") or {}).get("status") or "")
                    if report_status in {"skipped_inactive", "skipped_loop_guard"}:
                        step_status = "skipped"
                        log_line = f"Step skipped: {report_status}."
                self._update_step_state(
                    run_id,
                    step.step_id,
                    status=step_status,
                    output=output,
                    finished=True,
                    log_line=log_line,
                )
            except Exception as exc:
                logger.exception("Pipeline step failed: run=%s step=%s", run_id, step.step_id)
                failed_output: dict[str, Any] | None = None
                if isinstance(exc, AgentExecutionError):
                    failed_output = {"agent_report": exc.report.model_dump(mode="json")}
                self._update_step_state(
                    run_id,
                    step.step_id,
                    status="failed",
                    output=failed_output,
                    error=str(exc),
                    finished=True,
                    log_line=f"Step failed: {exc}",
                )
                if definition.stop_on_error:
                    return self._finalize_run(run_id, status="failed", alert=str(exc))

        return self._finalize_run(run_id, status="completed")

    def _execute_step(
        self,
        *,
        run_id: str,
        run: PipelineRun,
        step: PipelineStepRun,
        definition: PipelineStepDefinition,
    ) -> dict[str, Any]:
        if definition.kind in {"noop", "note"}:
            message = str(definition.config.get("message", "No-op step completed."))
            artifact = self._write_text_artifact(run_id, f"{step.step_id}.txt", message)
            self._append_artifact(run_id, artifact)
            return {"message": message, "artifact_path": artifact}

        if definition.kind == "csv_profile":
            csv_path = definition.config.get("path") or run.inputs.get(definition.config.get("input_key", "csv_path"))
            if not csv_path:
                raise ValueError("CSV profile step requires a CSV path.")
            profile_id = definition.config.get("profile_id")
            analysis = self._csv_profiles.analyze(str(csv_path), profile_id=profile_id)
            artifact = self._write_json_artifact(run_id, f"{step.step_id}-csv-profile.json", analysis)
            self._append_artifact(run_id, artifact)
            return {"analysis": analysis, "artifact_path": artifact}

        if definition.kind == "folder_sync":
            target_id = definition.config.get("target_id") or run.inputs.get(definition.config.get("input_key", "target_id"))
            manifest = self._build_folder_sync_manifest(target_id=target_id, override_path=definition.config.get("path"))
            artifact = self._write_json_artifact(run_id, f"{step.step_id}-folder-sync.json", manifest)
            self._append_artifact(run_id, artifact)
            return {"manifest": manifest, "artifact_path": artifact}

        if definition.kind == "http_request":
            response = self._run_http_request(definition)
            artifact = self._write_json_artifact(run_id, f"{step.step_id}-http.json", response)
            self._append_artifact(run_id, artifact)
            return {"response": response, "artifact_path": artifact}
        agent_result = self._execute_step_with_agent(
            run_id=run_id,
            run=run,
            step=step,
            definition=definition,
        )
        if agent_result is not None:
            return agent_result

        raise ValueError(f"Unsupported step kind: {definition.kind}")

    def _execute_step_with_agent(
        self,
        *,
        run_id: str,
        run: PipelineRun,
        step: PipelineStepRun,
        definition: PipelineStepDefinition,
    ) -> dict[str, Any] | None:
        agent = self._agents_by_kind.get(definition.kind)
        if agent is None:
            return None
        context = AgentExecutionContext(run_id=run_id, run=run, step=step, definition=definition)
        try:
            result = agent.execute(context)
            return result.output
        except Exception as exc:
            if isinstance(exc, AgentExecutionError):
                raise
            report = agent.build_failure_report(
                context,
                error=str(exc),
                note=f"Agent execution failed for kind '{definition.kind}'.",
            )
            raise AgentExecutionError(str(exc), report=report) from exc

    def _append_artifact(self, run_id: str, artifact_path: str) -> None:
        self._artifacts.append_artifact(run_id, artifact_path)

    def _write_vault_step_artifacts(
        self,
        *,
        run_id: str,
        step_id: str,
        phase: str,
        report: dict[str, Any],
    ) -> dict[str, str]:
        json_name = f"{step_id}-vault-{phase}.json"
        md_name = f"{step_id}-vault-{phase}.md"
        json_path = self._write_json_artifact(run_id, json_name, report)
        md_path = self._write_text_artifact(
            run_id,
            md_name,
            self._render_vault_markdown_summary(phase=phase, report=report),
        )
        self._append_artifact(run_id, json_path)
        self._append_artifact(run_id, md_path)
        return {"json_path": json_path, "md_path": md_path}

    def _render_vault_markdown_summary(self, *, phase: str, report: dict[str, Any]) -> str:
        title = {
            "discover": "Vault Discover Summary",
            "ingest": "Vault Ingest Summary",
            "compile": "Vault Compile Summary",
            "lint": "Vault Lint Summary",
            "synthesis": "Knowledge Graph Synthesis Summary",
            "sufficiency": "Vault Sufficiency Summary",
        }.get(phase, "Vault Step Summary")

        lines = [f"# {title}", "", "## Highlights"]
        if phase == "discover":
            lines.extend(
                [
                    f"- Candidates: `{int(report.get('candidate_count') or 0)}`",
                    f"- Rejected: `{int(report.get('rejected_count') or 0)}`",
                    f"- Topic: `{str(report.get('topic') or '-')}`",
                ]
            )
            candidates = report.get("candidates") if isinstance(report.get("candidates"), list) else []
            if candidates:
                lines.extend(["", "## Top Candidate URLs"])
                for item in candidates[:10]:
                    if isinstance(item, dict):
                        lines.append(f"- {str(item.get('url') or '').strip()}")
        elif phase == "ingest":
            lines.extend(
                [
                    f"- Processed: `{int(report.get('processed_count') or 0)}`",
                    f"- Ingested: `{int(report.get('ingested_count') or 0)}`",
                    f"- Skipped Unchanged: `{int(report.get('skipped_unchanged_count') or 0)}`",
                    f"- Rejected (trust): `{int(report.get('rejected_for_trust_count') or 0)}`",
                    f"- Rejected (policy): `{int(report.get('rejected_for_policy_count') or 0)}`",
                ]
            )
            compile_report = report.get("compile")
            if isinstance(compile_report, dict):
                lines.extend(["", "## Compile Impact"])
                for page in compile_report.get("compiled_pages", [])[:20]:
                    lines.append(f"- {str(page)}")
        elif phase == "compile":
            lines.extend(
                [
                    f"- Status: `{str(report.get('status') or 'unknown')}`",
                    f"- Compiled Pages: `{int(report.get('compiled_count') or 0)}`",
                ]
            )
            pages = report.get("compiled_pages") if isinstance(report.get("compiled_pages"), list) else []
            if pages:
                lines.extend(["", "## Affected Pages"])
                for page in pages[:30]:
                    lines.append(f"- {str(page)}")
        elif phase == "synthesis":
            lines.extend(
                [
                    f"- Objective: `{str(report.get('objective_id') or '-')}`",
                    f"- Findings: `{len(report.get('findings') or [])}`",
                    f"- Gaps: `{len(report.get('gaps') or [])}`",
                    f"- Contradictions: `{len(report.get('contradictions') or [])}`",
                    f"- Next actions: `{len(report.get('next_actions') or [])}`",
                ]
            )
        elif phase == "sufficiency":
            lines.extend(
                [
                    f"- Objective: `{str(report.get('objective_id') or '-')}`",
                    f"- Score: `{report.get('score', '-')}`",
                    f"- Decision: `{str(report.get('decision') or '-')}`",
                    f"- Blocking checks: `{len(report.get('blocking_checks') or [])}`",
                    f"- Auto-pause recommended: `{bool(report.get('auto_pause_recommended', False))}`",
                ]
            )
        else:
            lines.extend(
                [
                    f"- Stale syntheses: `{int(report.get('stale_syntheses_count') or 0)}`",
                    f"- Orphan pages: `{int(report.get('orphan_pages_count') or 0)}`",
                    f"- Missing backlinks: `{int(report.get('missing_backlinks_count') or 0)}`",
                    f"- Contradictions: `{int(report.get('contradictions_count') or 0)}`",
                    f"- Expired queries: `{int(report.get('expired_queries_count') or 0)}`",
                    f"- Queue backlog: `{int(report.get('queue_backlog_count') or 0)}`",
                ]
            )

        lines.extend(["", "## Next Actions"])
        if phase == "discover":
            lines.append("- Run ingest to apply trust checks and append approved knowledge.")
        elif phase == "ingest":
            lines.append("- Review trust rejections and adjust allowlist/min_trust_score if needed.")
        elif phase == "compile":
            lines.append("- Open `02_compiled/index.md` to validate latest compiled output.")
        elif phase == "synthesis":
            lines.append("- Prioritize listed gaps and execute next actions.")
        elif phase == "sufficiency":
            lines.append("- Pause scheduler only when sufficiency is stable and blockers are clear.")
        else:
            lines.append("- Review lint findings and resolve stale syntheses, expired queries, or queue backlog.")
        return "\n".join(lines) + "\n"

    def _build_vault_manager(self, definition: PipelineStepDefinition) -> VaultLearningManager:
        config = get_app_config()
        vault_cfg = config.knowledge_vault
        default_root = VaultLearningManager.default_vault_root()
        configured_root = str(definition.config.get("vault_path") or vault_cfg.path or default_root)
        vault_root = Path(configured_root).expanduser().resolve()

        allowed_domains = definition.config.get("allowed_domains")
        if not isinstance(allowed_domains, list):
            allowed_domains = vault_cfg.allowed_domains

        max_chars = int(definition.config.get("max_content_chars") or vault_cfg.max_content_chars)
        min_trust_score = float(definition.config.get("min_trust_score") or vault_cfg.min_trust_score)
        return VaultLearningManager(
            vault_root=vault_root,
            allowed_domains=allowed_domains,
            max_content_chars=max_chars,
            min_trust_score=min_trust_score,
            query_retention_hours=int(definition.config.get("query_retention_hours") or vault_cfg.query_retention_hours),
            search_results_queue_path=str(
                definition.config.get("search_results_queue_path") or vault_cfg.search_results_queue_path
            ),
            search_results_dedupe_window_hours=int(
                definition.config.get("search_results_dedupe_window_hours") or vault_cfg.search_results_dedupe_window_hours
            ),
            search_results_max_queue_items=int(
                definition.config.get("search_results_max_queue_items") or vault_cfg.search_results_max_queue_items
            ),
        )

    def _default_vault_manager(self) -> VaultLearningManager:
        return self._build_vault_manager(
            PipelineStepDefinition(
                id="vault-status",
                name="Vault status",
                kind="vault_compile",
                config={},
            )
        )

    def _vault_queue_ingest_steps(self, *, queue_count: int) -> list[PipelineStepDefinition]:
        max_queue_items = max(1, int(queue_count))
        return [
            PipelineStepDefinition(
                id="queue-ingest",
                name="Ingest queued search results",
                kind="vault_ingest",
                config={
                    "source": "queue_approval",
                    "max_queue_items": max_queue_items,
                },
            ),
            PipelineStepDefinition(
                id="queue-compile",
                name="Compile vault indexes",
                kind="vault_compile",
                config={},
            ),
            PipelineStepDefinition(
                id="queue-lint",
                name="Lint vault maintenance",
                kind="vault_lint",
                config={"freshness_window_days": 30},
            ),
        ]

    def _render_vault_queue_approval_description(self, *, queue_count: int, sample_titles: list[str]) -> str:
        noun = "item" if queue_count == 1 else "items"
        lines = [
            f"Knowledge Vault has `{queue_count}` queued search result {noun} ready for ingestion.",
            "Approving this will start a long-running vault job that ingests queued results, refreshes compiled pages, and runs vault lint.",
        ]
        if sample_titles:
            lines.append("Pending examples:")
            lines.extend(f"- {title}" for title in sample_titles[:5])
        return "\n".join(lines)

    def ensure_vault_queue_ingest_approval(
        self,
        *,
        queue_count: int | None = None,
        sample_titles: list[str] | None = None,
    ) -> PipelineRun | None:
        config = get_app_config()
        if not (config.knowledge_vault.enabled and config.approvals.enabled):
            return None

        manager = self._default_vault_manager()
        effective_queue_count = int(
            queue_count
            if queue_count is not None
            else manager.get_run_summary().get("counts", {}).get("queued_search_results") or 0
        )
        if effective_queue_count <= 0:
            return None

        queue_items = [item for item in manager._load_queue() if str(item.get("status") or "") == "queued"]
        titles = [
            str(item.get("title") or item.get("url") or "").strip()
            for item in queue_items
            if str(item.get("title") or item.get("url") or "").strip()
        ]
        if sample_titles:
            titles = [*sample_titles, *titles]
        deduped_titles: list[str] = []
        seen_titles: set[str] = set()
        for title in titles:
            normalized = title.strip()
            if not normalized or normalized in seen_titles:
                continue
            seen_titles.add(normalized)
            deduped_titles.append(normalized)

        approval_title = f"Approve Knowledge Vault queue ingest ({effective_queue_count} items)"
        approval_description = self._render_vault_queue_approval_description(
            queue_count=effective_queue_count,
            sample_titles=deduped_titles,
        )
        approval_metadata = {
            "approval_kind": "knowledge_vault_queue_ingest",
            "queued_item_count": effective_queue_count,
            "sample_titles": deduped_titles[:5],
        }
        step_definitions = self._vault_queue_ingest_steps(queue_count=effective_queue_count)
        now = utcnow()

        def update_existing(snapshot):
            for approval in snapshot.approvals.values():
                if approval.status != "pending":
                    continue
                if str(approval.metadata.get("approval_kind") or "") != "knowledge_vault_queue_ingest":
                    continue
                run = snapshot.runs.get(approval.pipeline_run_id)
                if run is None or run.status != "pending_approval":
                    continue
                approval.title = approval_title
                approval.description = approval_description
                approval.requested_at = now
                approval.metadata = {
                    **approval.metadata,
                    **approval_metadata,
                }
                run.summary = approval_description
                run.inputs = {
                    **run.inputs,
                    "queued_item_count": effective_queue_count,
                }
                run.updated_at = now
                run.metadata = {
                    **run.metadata,
                    **approval_metadata,
                    "step_definitions": {
                        definition.id: definition.model_dump(mode="json")
                        for definition in step_definitions
                    },
                }
                return run.id
            return None

        existing_run_id = self._store.mutate(update_existing)
        if existing_run_id:
            self._append_audit_event(
                "vault_queue_approval_updated",
                f"Updated Knowledge Vault queue approval for {effective_queue_count} item(s).",
                metadata={"run_id": existing_run_id, "queued_item_count": effective_queue_count},
            )
            return self.get_run(existing_run_id)

        # If the same queue size was explicitly rejected, do not immediately
        # recreate another identical pending approval card.
        snapshot = self._store.read()
        for approval in snapshot.approvals.values():
            if approval.status != "rejected":
                continue
            if str(approval.metadata.get("approval_kind") or "") != "knowledge_vault_queue_ingest":
                continue
            rejected_count = approval.metadata.get("queued_item_count")
            if int(rejected_count or -1) == effective_queue_count:
                return None

        run = self.create_run(
            steps=step_definitions,
            inputs={"queued_item_count": effective_queue_count},
            summary=approval_description,
            requires_approval=True,
            metadata=approval_metadata,
        )

        def finalize_created(snapshot):
            created_run = snapshot.runs[run.id]
            approval_id = created_run.approval_request_id
            if approval_id and approval_id in snapshot.approvals:
                approval = snapshot.approvals[approval_id]
                approval.title = approval_title
                approval.description = approval_description
                approval.requested_by = "vault_queue_inspector"
                approval.metadata = {
                    **approval.metadata,
                    **approval_metadata,
                }
            created_run.summary = approval_description
            created_run.updated_at = now
            created_run.metadata = {
                **created_run.metadata,
                **approval_metadata,
            }

        self._store.mutate(finalize_created)
        self._append_audit_event(
            "vault_queue_approval_created",
            f"Created Knowledge Vault queue approval for {effective_queue_count} item(s).",
            metadata={"run_id": run.id, "queued_item_count": effective_queue_count},
        )
        return self.get_run(run.id)

    def get_vault_status(self) -> dict[str, Any]:
        manager = self._default_vault_manager()
        return manager.get_run_summary()

    def search_vault(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        manager = self._default_vault_manager()
        search_service = UnifiedVaultSearchService(manager.vault_root)
        return search_service.search_payload(query=query, limit=limit)

    def clip_to_vault(
        self,
        *,
        url: str,
        title: str,
        markdown: str,
        topic: str = "",
        topic_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        manager = self._default_vault_manager()
        return manager.enqueue_clip(url=url, title=title, markdown=markdown, topic=topic, topic_tags=topic_tags)

    def save_to_vault(
        self,
        *,
        title: str,
        content: str,
        topic: str = "",
        topic_tags: list[str] | None = None,
        source_url: str = "",
        source_thread_id: str = "",
    ) -> dict[str, Any]:
        manager = self._default_vault_manager()
        return manager.save_document(
            title=title,
            content=content,
            topic=topic,
            topic_tags=topic_tags,
            source_url=source_url,
            source_thread_id=source_thread_id,
        )

    def get_vault_graph(self, *, limit: int = 200) -> dict[str, Any]:
        manager = self._default_vault_manager()
        return manager.get_graph(limit=limit)

    def get_vault_source(self, source_id: str) -> dict[str, Any]:
        manager = self._default_vault_manager()
        return manager.get_source(source_id)

    def get_vault_explorer(self, *, force_refresh: bool = False) -> dict[str, Any]:
        manager = self._default_vault_manager()
        now = time.time()
        with self._vault_explorer_cache_lock:
            cached_generated_at = float(self._vault_explorer_cache.get("generated_at_unix") or 0.0)
            is_fresh = (now - cached_generated_at) < self._vault_explorer_cache_ttl_seconds
            if self._vault_explorer_cache and is_fresh and not force_refresh:
                return dict(self._vault_explorer_cache.get("payload") or {})

        payload = self._build_vault_explorer_payload(manager)
        with self._vault_explorer_cache_lock:
            self._vault_explorer_cache = {
                "generated_at_unix": now,
                "payload": payload,
            }
        return payload

    def _build_vault_explorer_payload(self, manager: VaultLearningManager) -> dict[str, Any]:
        def _safe_rel(path: Path) -> str:
            try:
                return str(path.resolve().relative_to(manager.vault_root))
            except Exception:
                return str(path.resolve())

        def _tree(path: Path) -> list[dict[str, Any]]:
            entries: list[dict[str, Any]] = []
            for item in sorted(path.iterdir() if path.exists() else [], key=lambda p: (not p.is_dir(), p.name.lower())):
                node: dict[str, Any] = {
                    "name": item.name,
                    "path": _safe_rel(item),
                    "kind": "directory" if item.is_dir() else "file",
                }
                if item.is_dir():
                    node["children"] = _tree(item)
                else:
                    try:
                        node["size"] = int(item.stat().st_size)
                    except OSError:
                        node["size"] = 0
                entries.append(node)
            return entries

        sources = list(manager._manifest.get("sources", {}).items())
        raw_sources = sorted(
            [
                {
                    "source_id": source_id,
                    "title": str(record.get("title") or record.get("url") or source_id),
                    "url": str(record.get("url") or ""),
                    "ingested_at": str(record.get("last_ingested_at") or record.get("created_at") or ""),
                    "raw_path": _safe_rel(Path(str(record.get("raw_path") or ""))) if str(record.get("raw_path") or "").strip() else "",
                    "compiled_path": _safe_rel(Path(str(record.get("compiled_path") or ""))) if str(record.get("compiled_path") or "").strip() else "",
                }
                for source_id, record in sources
                if isinstance(record, dict)
            ],
            key=lambda item: item["ingested_at"],
            reverse=True,
        )

        knowledge_groups = {
            "entities": _tree(manager.compiled_entities_dir),
            "concepts": _tree(manager.compiled_concepts_dir),
            "sources": _tree(manager.compiled_sources_dir),
            "others": _tree(manager.compiled_dir / "syntheses") + _tree(manager.compiled_dir / "queries"),
        }

        graph = manager.get_graph(limit=200)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "cache_ttl_seconds": self._vault_explorer_cache_ttl_seconds,
            "raw_sources": raw_sources,
            "knowledge": knowledge_groups,
            "files": _tree(manager.vault_root),
            "graph": {
                "generated_at": graph.get("generated_at"),
                "counts": graph.get("counts", {}),
                "nodes": graph.get("nodes", []),
                "edges": graph.get("edges", []),
            },
        }

    def get_vault_file(self, *, relative_path: str) -> dict[str, Any]:
        manager = self._default_vault_manager()
        resolved = self._resolve_vault_file_path(manager, relative_path)
        content = resolved.read_text(encoding="utf-8")
        editable = self._is_vault_raw_source_path(manager, resolved)
        return {
            "path": str(resolved.relative_to(manager.vault_root)),
            "editable": editable,
            "content": content,
        }

    def save_vault_file(self, *, relative_path: str, content: str) -> dict[str, Any]:
        manager = self._default_vault_manager()
        resolved = self._resolve_vault_file_path(manager, relative_path)
        if not self._is_vault_raw_source_path(manager, resolved):
            raise ValueError("Only raw source files are editable.")
        resolved.write_text(content, encoding="utf-8")
        self.get_vault_explorer(force_refresh=True)
        return {
            "status": "saved",
            "path": str(resolved.relative_to(manager.vault_root)),
            "bytes": len(content.encode("utf-8")),
        }

    def delete_vault_file(self, *, relative_path: str) -> dict[str, Any]:
        manager = self._default_vault_manager()
        resolved = self._resolve_vault_file_path(manager, relative_path)
        if not self._is_vault_raw_source_path(manager, resolved):
            raise ValueError("Only raw source files are deletable.")
        resolved.unlink(missing_ok=False)
        self.get_vault_explorer(force_refresh=True)
        return {
            "status": "deleted",
            "path": str(resolved.relative_to(manager.vault_root)),
        }

    def _resolve_vault_file_path(self, manager: VaultLearningManager, relative_path: str) -> Path:
        normalized = relative_path.strip().lstrip("/")
        if not normalized:
            raise ValueError("Path is required.")
        target = (manager.vault_root / normalized).resolve()
        if manager.vault_root not in target.parents and target != manager.vault_root:
            raise ValueError("Path is outside vault root.")
        if not target.exists() or not target.is_file():
            raise ValueError("Vault file not found.")
        return target

    def _is_vault_raw_source_path(self, manager: VaultLearningManager, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(manager.vault_root).as_posix()
        except Exception:
            return False
        return relative.startswith("01_raw/sources/")

    def _new_vault_ingest_job_state(self) -> dict[str, Any]:
        return {
            "job_id": "",
            "status": "idle",
            "total": 0,
            "processed": 0,
            "updated": 0,
            "skipped_no_raw": 0,
            "failed": 0,
            "current_index": 0,
            "current_source_id": "",
            "current_title": "",
            "last_status": "",
            "last_error": None,
            "started_at": None,
            "finished_at": None,
            "updated_at": None,
            "log_path": "",
        }

    def _vault_ingest_log_path(self) -> Path:
        # base_dir is typically `<repo>/backend/.capybara-home`; logs live at `<repo>/logs/`.
        base_dir = get_paths().base_dir
        logs_dir = base_dir.parent.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir / "vault_ingest.log"

    def _get_vault_ingest_logger(self) -> logging.Logger:
        if self._vault_ingest_logger is not None:
            return self._vault_ingest_logger
        logger_obj = logging.getLogger("capybara.vault_ingest")
        logger_obj.setLevel(logging.INFO)
        logger_obj.propagate = False
        log_path = self._vault_ingest_log_path()
        already_attached = any(
            isinstance(handler, logging.FileHandler)
            and getattr(handler, "baseFilename", "") == str(log_path)
            for handler in logger_obj.handlers
        )
        if not already_attached:
            handler = logging.FileHandler(str(log_path), encoding="utf-8")
            handler.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            logger_obj.addHandler(handler)
        self._vault_ingest_logger = logger_obj
        return logger_obj

    def start_vault_ingest_job(self, *, force_reanalyze: bool = False) -> dict[str, Any]:
        with self._vault_ingest_lock:
            if self._vault_ingest_job.get("status") == "running":
                snapshot = dict(self._vault_ingest_job)
                snapshot["accepted"] = False
                snapshot["message"] = "A vault ingest job is already running."
                return snapshot
            job_id = f"vault_ingest_{uuid4().hex[:12]}"
            log_path = self._vault_ingest_log_path()
            self._vault_ingest_job = self._new_vault_ingest_job_state()
            self._vault_ingest_job.update(
                {
                    "job_id": job_id,
                    "status": "running",
                    "started_at": self._utcnow_iso(),
                    "updated_at": self._utcnow_iso(),
                    "log_path": str(log_path),
                }
            )

        logger_obj = self._get_vault_ingest_logger()
        logger_obj.info(
            "vault_ingest_start job_id=%s force_reanalyze=%s log_path=%s",
            job_id,
            force_reanalyze,
            log_path,
        )

        def _runner() -> None:
            try:
                manager = self._default_vault_manager()

                def _progress(
                    index: int,
                    total: int,
                    source_id: str,
                    title: str,
                    status: str,
                    error: str | None,
                ) -> None:
                    with self._vault_ingest_lock:
                        self._vault_ingest_job.update(
                            {
                                "total": total,
                                "processed": index,
                                "current_index": index,
                                "current_source_id": source_id,
                                "current_title": title,
                                "last_status": status,
                                "last_error": error,
                                "updated_at": self._utcnow_iso(),
                            }
                        )
                        if status == "updated":
                            self._vault_ingest_job["updated"] = int(self._vault_ingest_job.get("updated", 0)) + 1
                        elif status == "skipped_no_raw":
                            self._vault_ingest_job["skipped_no_raw"] = int(self._vault_ingest_job.get("skipped_no_raw", 0)) + 1
                        elif status == "failed":
                            self._vault_ingest_job["failed"] = int(self._vault_ingest_job.get("failed", 0)) + 1
                    if status == "failed":
                        logger_obj.warning(
                            "vault_ingest_item index=%d/%d source_id=%s title=%r status=%s error=%s",
                            index,
                            total,
                            source_id,
                            title,
                            status,
                            error,
                        )
                    else:
                        logger_obj.info(
                            "vault_ingest_item index=%d/%d source_id=%s title=%r status=%s",
                            index,
                            total,
                            source_id,
                            title,
                            status,
                        )

                report = manager.reprocess_existing_sources(
                    only_missing=not force_reanalyze,
                    progress_callback=_progress,
                )

                with self._vault_ingest_lock:
                    self._vault_ingest_job.update(
                        {
                            "status": "success",
                            "total": int(report.get("total") or 0),
                            "processed": int(report.get("processed") or 0),
                            "updated": int(report.get("updated") or 0),
                            "skipped_no_raw": int(report.get("skipped_no_raw") or 0),
                            "failed": int(report.get("failed") or 0),
                            "finished_at": self._utcnow_iso(),
                            "updated_at": self._utcnow_iso(),
                            "last_error": None,
                        }
                    )
                logger_obj.info(
                    "vault_ingest_done job_id=%s total=%d processed=%d updated=%d skipped_no_raw=%d failed=%d",
                    job_id,
                    int(report.get("total") or 0),
                    int(report.get("processed") or 0),
                    int(report.get("updated") or 0),
                    int(report.get("skipped_no_raw") or 0),
                    int(report.get("failed") or 0),
                )
                with self._vault_explorer_cache_lock:
                    self._vault_explorer_cache = {}
            except Exception as exc:
                logger_obj.exception("vault_ingest_failed job_id=%s error=%s", job_id, exc)
                with self._vault_ingest_lock:
                    self._vault_ingest_job.update(
                        {
                            "status": "failed",
                            "last_error": str(exc),
                            "finished_at": self._utcnow_iso(),
                            "updated_at": self._utcnow_iso(),
                        }
                    )

        thread = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"vault-ingest-{job_id}",
        )
        thread.start()

        with self._vault_ingest_lock:
            snapshot = dict(self._vault_ingest_job)
        snapshot["accepted"] = True
        snapshot["message"] = "Vault ingest job started."
        return snapshot

    def get_vault_ingest_status(self) -> dict[str, Any]:
        with self._vault_ingest_lock:
            return dict(self._vault_ingest_job)

    def list_vault_action_items(self, *, limit: int = 100) -> dict[str, Any]:
        manager = self._default_vault_manager()
        payload = manager.get_action_items(limit=limit)
        snapshot = self._store.read()

        scheduler_items = self._vault_scheduler_error_action_items(snapshot=snapshot, limit=limit)
        merged_items = list(payload.get("items", [])) + scheduler_items
        merged_items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        sliced = merged_items[: max(1, int(limit))]

        counts: dict[str, int] = {}
        for item in sliced:
            kind = str(item.get("kind") or "unknown")
            counts[kind] = counts.get(kind, 0) + 1
        counts["total"] = len(sliced)

        return {
            "generated_at": payload.get("generated_at"),
            "counts": counts,
            "items": sliced,
        }

    def _vault_scheduler_error_action_items(self, *, snapshot, limit: int) -> list[dict[str, Any]]:
        runtime_jobs = snapshot.runtime_scheduler_jobs
        autoresearch_template_id = "knowledge-vault-autoresearch"
        objective_by_job_id = {
            str(obj.scheduler_job_id): obj
            for obj in snapshot.autoresearch_objectives.values()
            if str(obj.scheduler_job_id or "").strip()
        }

        items: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()
        relevant_kinds = {"scheduler_job_error", "scheduler_job_manual_blocked"}
        max_items = max(1, min(int(limit), 25))
        for event in reversed(snapshot.audit_log):
            if event.kind not in relevant_kinds:
                continue
            job_id = str(event.metadata.get("job_id") or "").strip()
            if not job_id:
                continue
            job = runtime_jobs.get(job_id)
            template_id = str(event.metadata.get("template_id") or (job.pipeline_template_id if job else "")).strip()
            if template_id != autoresearch_template_id:
                continue
            dedupe_key = (job_id, event.kind)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            objective = objective_by_job_id.get(job_id)
            objective_id = str(objective.objective_id if objective else event.metadata.get("objective_id") or "").strip()
            items.append(
                {
                    "kind": "scheduler_error",
                    "priority": "high",
                    "title": f"Scheduler issue: {job_id}",
                    "detail": str(event.message),
                    "created_at": event.created_at.isoformat(),
                    "status": "pending",
                    "objective_id": objective_id or None,
                }
            )
            if len(items) >= max_items:
                break
        return items

    def evaluate_vault_sufficiency(
        self,
        *,
        objective_id: str,
        topic: str = "",
        min_score: float = 78.0,
    ) -> dict[str, Any]:
        manager = self._default_vault_manager()
        return manager.evaluate_sufficiency(
            objective_id=objective_id,
            topic=topic,
            min_score=min_score,
        )

    def record_workspace_activity(self, *, thread_id: str | None, message: str) -> TriggerEvent:
        preview = (message or "").strip()
        if len(preview) > 300:
            preview = preview[:300] + "..."
        trigger = self.create_trigger_event(
            source="workspace",
            message=preview,
            classification="workspace_chat",
            metadata={"thread_id": thread_id},
        )
        self._resume_inactive_autoresearch_jobs()
        return trigger

    def _resume_inactive_autoresearch_jobs(self) -> None:
        snapshot = self._store.read()
        for objective in snapshot.autoresearch_objectives.values():
            if objective.status != "active":
                continue
            job_id = objective.scheduler_job_id
            if not job_id:
                continue
            job = snapshot.runtime_scheduler_jobs.get(job_id)
            if job is None or job.enabled:
                continue
            self.set_runtime_scheduler_job_enabled(job_id, enabled=True, reason="workspace_activity_resumed")

    def has_recent_workspace_activity(self, *, hours: int = 24) -> bool:
        snapshot = self._store.read()
        since = utcnow() - timedelta(hours=max(1, int(hours)))
        for trigger in snapshot.triggers.values():
            if trigger.classification != "workspace_chat":
                continue
            if trigger.created_at >= since:
                return True
        return False

    def pause_runtime_scheduler_job(self, job_id: str, *, reason: str | None = None) -> bool:
        return self._scheduler.pause_runtime_scheduler_job(job_id, reason=reason)

    def _collect_discovered_urls(self, run: PipelineRun) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for step in run.steps:
            output = step.output if isinstance(step.output, dict) else {}
            report = output.get("report")
            if not isinstance(report, dict):
                continue
            candidates = report.get("candidates")
            if not isinstance(candidates, list):
                continue
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                url = str(candidate.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                urls.append(url)
        return urls

    def _resolve_vault_urls(self, *, run: PipelineRun, definition: PipelineStepDefinition) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        inline_urls = definition.config.get("urls")
        if isinstance(inline_urls, list):
            candidates = inline_urls
        else:
            input_key = str(definition.config.get("input_key") or "urls")
            raw = run.inputs.get(input_key)
            if isinstance(raw, list):
                candidates = raw
            elif isinstance(raw, str):
                candidates = [part.strip() for part in raw.splitlines() if part.strip()]
            else:
                candidates = []

        for item in candidates:
            url = str(item).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)

        max_urls = int(definition.config.get("max_urls") or 50)
        return urls[: max(1, max_urls)]

    def _build_folder_sync_manifest(
        self,
        *,
        target_id: str | None,
        override_path: str | None = None,
    ) -> dict[str, Any]:
        config = get_app_config().pipelines
        target: FolderSyncTarget | None = None
        if target_id:
            target = next((item for item in config.folder_sync_targets if item.id == target_id and item.enabled), None)
            if target is None:
                raise ValueError(f"Unknown folder sync target: {target_id}")

        root = Path(override_path or (target.path if target else "")).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Folder sync path does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Folder sync path is not a directory: {root}")

        patterns = target.file_globs if target is not None else ["*"]
        collected: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        iterator = root.rglob if (target.recursive if target is not None else True) else root.glob
        seen: set[Path] = set()
        max_files = max(1, config.folder_sync_max_files)
        max_bytes = max(1, config.folder_sync_max_bytes)

        for pattern in patterns:
            for path in iterator(pattern):
                if path in seen or not path.is_file():
                    continue
                seen.add(path)

                try:
                    size_bytes = path.stat().st_size
                except OSError as exc:
                    skipped.append({"path": str(path), "reason": f"stat_failed:{exc}"})
                    continue

                if size_bytes > max_bytes:
                    skipped.append({"path": str(path), "reason": "size_limit"})
                    continue
                if len(collected) >= max_files:
                    skipped.append({"path": str(path), "reason": "file_limit"})
                    continue

                collected.append(
                    {
                        "path": str(path),
                        "name": path.name,
                        "size_bytes": size_bytes,
                    }
                )

        manifest = {
            "target_id": target.id if target is not None else None,
            "root": str(root),
            "files": collected,
            "file_count": len(collected),
            "skipped_files": skipped,
        }
        return manifest

    def _extract_file_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in _TEXT_EXTENSIONS:
            return path.read_text(encoding="utf-8", errors="replace")
        if suffix in _CONVERTIBLE_EXTENSIONS:
            try:
                from markitdown import MarkItDown

                md = MarkItDown()
                result = md.convert(str(path))
                return result.text_content or ""
            except Exception:
                return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _run_http_request(self, definition: PipelineStepDefinition) -> dict[str, Any]:
        method = str(definition.config.get("method", "GET")).upper()
        url = definition.config.get("url")
        if not url:
            raise ValueError("http_request step requires a URL.")

        headers = definition.config.get("headers", {})
        if not isinstance(headers, dict):
            headers = {}
        json_body = definition.config.get("json")
        data = definition.config.get("data")
        timeout = float(definition.config.get("timeout_seconds", 20))

        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, str(url), headers=headers, json=json_body, data=data)
            text = response.text
            parsed: Any
            try:
                parsed = response.json()
            except Exception:
                parsed = text

        return {
            "method": method,
            "url": str(url),
            "status_code": response.status_code,
            "ok": response.is_success,
            "body": parsed,
        }

    # Backward-compatible wrappers retained for tests and monkeypatch-based overrides.
    def _run_self_improver_draft(
        self,
        *,
        run: PipelineRun,
        definition: PipelineStepDefinition,
    ) -> dict[str, Any]:
        return self._improver_agent._run_self_improver_draft(run=run, definition=definition)  # noqa: SLF001

    def _run_improver_scan(self, definition: PipelineStepDefinition) -> dict[str, Any]:
        return self._improver_agent._run_improver_scan(definition)  # noqa: SLF001

    def _validate_skill_markdown(self, content: str) -> dict[str, Any]:
        return self._improver_agent.validate_skill_markdown(content)

    def list_approvals(self) -> list[ApprovalRequest]:
        return self._approvals.list_approvals()

    def resolve_approval(
        self,
        approval_id: str,
        *,
        approve: bool,
        note: str | None = None,
        auto_start: bool = True,
    ) -> PipelineRun:
        return self._approvals.resolve_approval(
            approval_id,
            approve=approve,
            note=note,
            auto_start=auto_start,
        )

    def list_feedback(self) -> list[FeedbackEvent]:
        return self._feedback.list_feedback()

    def add_feedback(
        self,
        *,
        target_type: str,
        target_id: str,
        value: str,
        comment: str = "",
        source: str = "web",
        metadata: dict[str, Any] | None = None,
    ) -> FeedbackEvent:
        return self._feedback.add_feedback(
            target_type=target_type,
            target_id=target_id,
            value=value,
            comment=comment,
            source=source,
            metadata=metadata,
        )

    def _check_http_health(
        self,
        *,
        base_url: str | None,
        health_path: str,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        if not base_url:
            return {"healthy": False, "reason": "missing_base_url"}

        try:
            url = urljoin(base_url.rstrip("/") + "/", health_path.lstrip("/"))
            with httpx.Client(timeout=timeout) as client:
                response = client.get(url, headers=headers or {})
            return {
                "healthy": response.is_success,
                "status_code": response.status_code,
                "url": url,
            }
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}

    def _utcnow_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def _parse_host_port(self, base_url: str | None) -> tuple[str | None, int | None]:
        if not base_url:
            return (None, None)
        try:
            parsed = urlparse(base_url)
            host = parsed.hostname
            if parsed.port is not None:
                return (host, parsed.port)
            if parsed.scheme == "https":
                return (host, 443)
            if parsed.scheme == "http":
                return (host, 80)
            return (host, None)
        except Exception:
            return (None, None)

    def _get_local_llm_base_url(self, app_config: Any) -> str | None:
        env_base_url = os.getenv("LOCAL_LLM_BASE_URL")
        if env_base_url:
            return env_base_url

        policy = app_config.model_extra.get("local_llm_policy", {})
        if isinstance(policy, dict):
            allowed_urls = policy.get("allowed_base_urls", [])
            if isinstance(allowed_urls, list) and allowed_urls:
                first = allowed_urls[0]
                if isinstance(first, str) and first:
                    return first
        return os.getenv("LLAMA_CPP_BASE_URL", "http://localhost:1234/v1")

    def _integration_service_catalog(self) -> list[dict[str, str]]:
        return [
            {
                "id": "comfyui",
                "label": "ComfyUI",
                "start_command": "start-comfyui",
                "stop_command": "stop-comfyui",
            },
            {
                "id": "lightrag",
                "label": "LightRAG",
                "start_command": "start-lightrag",
                "stop_command": "stop-lightrag",
            },
            {
                "id": "websearch",
                "label": "WebSearch",
                "start_command": "start-websearch",
                "stop_command": "stop-websearch",
            },
        ]

    def _resolve_integration_services(self) -> list[dict[str, Any]]:
        app_config = get_app_config()
        services: list[dict[str, Any]] = []

        llm_base_url = self._get_local_llm_base_url(app_config)
        services.append(
            {
                "id": "llm",
                "label": "LLM available",
                "base_url": llm_base_url,
                "health_path": "models",
                "headers": {},
                "timeout": 8.0,
                "can_start": False,
            }
        )

        comfyui_cfg = app_config.tool_backends.comfyui
        comfyui_base_url = comfyui_cfg.base_url or os.getenv("COMFYUI_BASE_URL", "http://localhost:8188")
        comfyui_health_path = comfyui_cfg.health_path or "/system_stats"
        services.append(
            {
                "id": "comfyui",
                "label": "ComfyUI",
                "base_url": comfyui_base_url,
                "health_path": comfyui_health_path,
                "headers": comfyui_cfg.headers,
                "timeout": max(1.0, float(comfyui_cfg.timeout_seconds)),
                "can_start": True,
            }
        )

        lightrag_cfg = app_config.knowledge_vault.lightrag
        lightrag_base_url = lightrag_cfg.base_url or os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621")
        services.append(
            {
                "id": "lightrag",
                "label": "LightRAG",
                "base_url": lightrag_base_url,
                "health_path": "/health",
                "headers": {},
                "timeout": max(1.0, float(lightrag_cfg.timeout_seconds)),
                "can_start": True,
            }
        )

        tool_backends_extra = app_config.tool_backends.model_extra or {}
        websearch_cfg = tool_backends_extra.get("websearch", {})
        if not isinstance(websearch_cfg, dict):
            websearch_cfg = {}
        websearch_base_url = websearch_cfg.get("base_url") or os.getenv("WEBSEARCH_BASE_URL", "http://127.0.0.1:9000")
        websearch_health_path = websearch_cfg.get("health_path") or "/health"
        websearch_headers = websearch_cfg.get("headers", {})
        websearch_timeout = websearch_cfg.get("timeout_seconds", 10.0)
        services.append(
            {
                "id": "websearch",
                "label": "WebSearch",
                "base_url": websearch_base_url,
                "health_path": websearch_health_path,
                "headers": websearch_headers,
                "timeout": max(1.0, float(websearch_timeout)),
                "can_start": True,
            }
        )
        return services

    def get_integration_services_status(self) -> dict[str, Any]:
        docker_desktop = self._docker_desktop_status()
        container_names = self._running_docker_container_names() if docker_desktop["online"] else set()
        services = []
        healthy_count = 0
        managed_services = {item["id"] for item in self._integration_service_catalog()}
        for service in self._resolve_integration_services():
            health = self._check_http_health(
                base_url=service["base_url"],
                health_path=service["health_path"],
                headers=service["headers"],
                timeout=service["timeout"],
            )
            host, port = self._parse_host_port(service["base_url"])
            docker_online = self._service_docker_online(service["id"], container_names)
            runtime = self._service_state.get(service["id"], {})
            error_reason = health.get("error") or health.get("reason")
            effective_healthy = bool(health.get("healthy", False))
            effective_status_code = health.get("status_code")
            if effective_healthy:
                phase = "healthy"
            elif docker_online:
                phase = "degraded"
            elif runtime.get("phase") == "starting":
                phase = "starting"
            else:
                phase = "failed"
            if effective_healthy:
                healthy_count += 1
            services.append(
                {
                    "id": service["id"],
                    "label": service["label"],
                    "base_url": service["base_url"],
                    "host": host,
                    "port": port,
                    "healthy": effective_healthy,
                    "status_code": effective_status_code,
                    "error": error_reason,
                    "can_start": service["can_start"],
                    "can_stop": service["id"] in managed_services,
                    "docker_online": docker_online,
                    "phase": phase,
                    "last_failure_reason": error_reason if not effective_healthy else None,
                    "last_transition_at": runtime.get("last_transition_at") or self._utcnow_iso(),
                }
            )

        core_checks = self._core_services_readiness()
        core_services = [item["service_id"] for item in core_checks]
        core_healthy = sum(1 for item in core_checks if item["healthy"])
        readiness_summary = {
            "all_ready": core_healthy == len(core_services),
            "healthy_count": core_healthy,
            "required_count": len(core_services),
            "stability_target_seconds": self._startup_stability_seconds(),
        }

        return {
            "generated_at": utcnow(),
            "docker_desktop_online": docker_desktop["online"],
            "docker_desktop_error": docker_desktop.get("error"),
            "docker_services": self._list_docker_services() if docker_desktop["online"] else [],
            "required_core_services": core_services,
            "readiness_summary": readiness_summary,
            "services": services,
        }

    def _local_stack_script_path(self) -> Path:
        script_path = Path(__file__).resolve().parents[3] / "scripts" / "local-stack.sh"
        if not script_path.exists():
            raise ValueError(f"Local stack script not found: {script_path}")
        return script_path

    def _run_local_stack_command(
        self,
        command: str,
        *,
        timeout_seconds: int | None = None,
        log_callback: Any | None = None,
    ) -> str:
        script_path = self._local_stack_script_path()
        process = subprocess.Popen(
            ["bash", str(script_path), command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        started = time.monotonic()
        lines: list[str] = []
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            lines.append(line)
            if log_callback:
                log_callback(line)
            if timeout_seconds is not None and (time.monotonic() - started) > timeout_seconds:
                process.kill()
                raise RuntimeError(f"Command '{command}' timed out after {timeout_seconds}s.")
        return_code = process.wait()
        output = "\n".join(lines)
        if return_code != 0:
            raise RuntimeError(output or f"Failed to run '{command}'.")
        return output

    def _docker_desktop_status(self) -> dict[str, Any]:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return {"online": True, "error": None}
        error = (result.stderr or result.stdout).strip() or "docker info failed"
        return {"online": False, "error": error}

    def _running_docker_container_names(self) -> set[str]:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}

    def _list_docker_services(self) -> list[dict[str, Any]]:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        items: list[dict[str, Any]] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            name, _, status = line.partition("|")
            normalized = status.lower()
            running = normalized.startswith("up")
            items.append(
                {
                    "name": name,
                    "status": status,
                    "online": running,
                }
            )
        return items

    def _docker_keywords_for_service(self, service_id: str) -> list[str]:
        if service_id == "comfyui":
            return ["comfyui"]
        if service_id == "lightrag":
            return ["lightrag"]
        if service_id == "websearch":
            return ["websearch"]
        return []

    def _service_docker_online(self, service_id: str, container_names: set[str]) -> bool:
        keywords = self._docker_keywords_for_service(service_id)
        if not keywords:
            return False
        return any(keyword in container_name for keyword in keywords for container_name in container_names)

    def _startup_stability_seconds(self) -> int:
        return int(os.getenv("INTEGRATIONS_STABILITY_SECONDS", "300"))

    def _startup_poll_seconds(self) -> float:
        return float(os.getenv("INTEGRATIONS_STABILITY_POLL_SECONDS", "5"))

    def _startup_command_timeout_seconds(self) -> int:
        return int(os.getenv("INTEGRATIONS_STARTUP_COMMAND_TIMEOUT_SECONDS", "600"))

    def _new_startup_job(
        self,
        *,
        target_service: str,
        command: str,
    ) -> dict[str, Any]:
        now = self._utcnow_iso()
        return {
            "id": f"startup_{uuid4().hex[:12]}",
            "target_service": target_service,
            "command": command,
            "status": "queued",
            "started_at": None,
            "finished_at": None,
            "created_at": now,
            "updated_at": now,
            "steps": [],
            "logs_tail": [],
            "error": None,
        }

    def _append_startup_log(self, job: dict[str, Any], line: str) -> None:
        logs = job["logs_tail"]
        logs.append(line)
        if len(logs) > 120:
            del logs[: len(logs) - 120]
        job["updated_at"] = self._utcnow_iso()

    def _upsert_startup_step(
        self,
        job: dict[str, Any],
        *,
        service_id: str,
        phase: str,
        ok: bool | None,
        detail: str,
    ) -> None:
        now = self._utcnow_iso()
        step = {
            "service_id": service_id,
            "phase": phase,
            "ok": ok,
            "detail": detail,
            "updated_at": now,
        }
        steps = job["steps"]
        replaced = False
        for index, existing in enumerate(steps):
            if existing.get("service_id") == service_id:
                steps[index] = step
                replaced = True
                break
        if not replaced:
            steps.append(step)
        self._service_state[service_id] = {
            "phase": phase,
            "last_transition_at": now,
        }
        job["updated_at"] = now

    def _core_services_readiness(self) -> list[dict[str, Any]]:
        return []

    def _set_job_status(self, job: dict[str, Any], status: str, *, error: str | None = None) -> None:
        job["status"] = status
        if status == "running" and not job["started_at"]:
            job["started_at"] = self._utcnow_iso()
        if status in {"success", "failed"}:
            job["finished_at"] = self._utcnow_iso()
        job["updated_at"] = self._utcnow_iso()
        job["error"] = error

    def _run_startup_job(self, job_id: str) -> None:
        with self._startup_lock:
            job = self._startup_jobs[job_id]
            self._set_job_status(job, "running")

        target_service = job["target_service"]
        command = job["command"]

        try:
            if target_service == "all":
                for svc in [item["id"] for item in self._integration_service_catalog()]:
                    self._upsert_startup_step(
                        job,
                        service_id=svc,
                        phase="starting",
                        ok=None,
                        detail="Startup requested.",
                    )
            else:
                self._upsert_startup_step(
                    job,
                    service_id=target_service,
                    phase="starting",
                    ok=None,
                    detail="Startup requested.",
                )

            def on_log(line: str) -> None:
                self._append_startup_log(job, line)

            command_error: str | None = None
            try:
                self._run_local_stack_command(
                    command,
                    timeout_seconds=self._startup_command_timeout_seconds(),
                    log_callback=on_log,
                )
            except Exception as exc:
                command_error = str(exc)
                self._append_startup_log(
                    job,
                    f"Startup command returned non-zero status, continuing with readiness checks: {exc}",
                )

            stability_target = self._startup_stability_seconds()
            poll_seconds = self._startup_poll_seconds()
            stable_since: float | None = None
            deadline = time.monotonic() + max(stability_target * 3, 300)

            while True:
                checks = self._core_services_readiness()
                required = checks
                all_healthy = all(item["healthy"] for item in required)

                for check in checks:
                    phase = "healthy" if check["healthy"] else "degraded"
                    detail = (
                        "healthy"
                        if check["healthy"]
                        else f"{check.get('error') or 'unhealthy'}"
                    )
                    self._upsert_startup_step(
                        job,
                        service_id=check["service_id"],
                        phase=phase,
                        ok=check["healthy"],
                        detail=detail,
                    )

                if all_healthy:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    stable_for = time.monotonic() - stable_since
                    self._append_startup_log(
                        job,
                        f"Core services healthy for {stable_for:.0f}s / {stability_target}s target.",
                    )
                    if stable_for >= stability_target:
                        break
                else:
                    stable_since = None

                if time.monotonic() > deadline:
                    raise RuntimeError("Timed out waiting for all required services to become healthy and stable.")

                time.sleep(poll_seconds)

            self._set_job_status(job, "success")
            if command_error:
                self._append_startup_log(
                    job,
                    "Startup command had errors, but all required services reached stable healthy state.",
                )
            self._append_startup_log(job, "Startup validation completed successfully.")
        except Exception as exc:
            self._set_job_status(job, "failed", error=str(exc))
            self._append_startup_log(job, f"Startup failed: {exc}")
        finally:
            with self._startup_lock:
                if self._active_startup_job_id == job_id:
                    self._active_startup_job_id = None

    def _start_startup_job_thread(self, job_id: str) -> None:
        thread = threading.Thread(
            target=self._run_startup_job,
            args=(job_id,),
            daemon=True,
            name=f"startup-job-{job_id}",
        )
        thread.start()

    def _enqueue_startup_job(self, *, target_service: str, command: str) -> dict[str, Any]:
        start_job_id: str | None = None
        with self._startup_lock:
            if self._active_startup_job_id:
                active = self._startup_jobs.get(self._active_startup_job_id)
                if active and active["status"] in {"queued", "running"}:
                    return {
                        "job_id": active["id"],
                        "status": active["status"],
                        "accepted": False,
                        "message": "A startup job is already running.",
                    }
            job = self._new_startup_job(target_service=target_service, command=command)
            self._startup_jobs[job["id"]] = job
            self._active_startup_job_id = job["id"]
            start_job_id = job["id"]

        assert start_job_id is not None
        self._start_startup_job_thread(start_job_id)
        with self._startup_lock:
            queued_job = self._startup_jobs[start_job_id]
            return {
                "job_id": queued_job["id"],
                "status": queued_job["status"],
                "accepted": True,
                "message": "Startup job queued.",
            }

    def get_startup_job(self, job_id: str) -> dict[str, Any]:
        with self._startup_lock:
            job = self._startup_jobs.get(job_id)
            if not job:
                raise ValueError(f"Unknown startup job: {job_id}")
            return dict(job)

    def start_integration_service(self, service_id: str) -> dict[str, Any]:
        command_map = {item["id"]: item["start_command"] for item in self._integration_service_catalog()}
        if service_id not in command_map:
            raise ValueError(f"Unsupported integration service: {service_id}")
        return self._enqueue_startup_job(
            target_service=service_id,
            command=command_map[service_id],
        )

    def stop_integration_service(self, service_id: str) -> dict[str, Any]:
        command_map = {item["id"]: item["stop_command"] for item in self._integration_service_catalog()}
        command = command_map.get(service_id)
        if not command:
            raise ValueError(f"Unsupported integration service: {service_id}")
        self._run_local_stack_command(command, timeout_seconds=self._startup_command_timeout_seconds())
        return {
            "service_id": service_id,
            "accepted": True,
            "status": "completed",
            "action": "stop",
            "message": f"Stop command completed for {service_id}.",
        }

    def set_integration_service_enabled(self, service_id: str, enabled: bool) -> dict[str, Any]:
        if enabled:
            result = self.start_integration_service(service_id)
            return {
                "service_id": service_id,
                "accepted": result.get("accepted", True),
                "status": result.get("status", "queued"),
                "action": "start",
                "job_id": result.get("job_id"),
                "message": result.get("message", f"Startup job queued for {service_id}."),
            }
        return self.stop_integration_service(service_id)

    def start_all_integration_services(self) -> dict[str, Any]:
        return self._enqueue_startup_job(
            target_service="all",
            command="start",
        )

    def get_integrations_status(self) -> dict[str, Any]:
        app_config = get_app_config()
        extensions = get_extensions_config()
        channel_service = get_channel_service()
        snapshot = self._store.read()
        scheduler_jobs: list[dict[str, Any]] = []
        config_job_ids = set()
        for job in app_config.scheduler.jobs:
            config_job_ids.add(job.id)
            payload = job.model_dump(mode="json")
            payload["source"] = "config"
            scheduler_jobs.append(payload)
        for job in snapshot.runtime_scheduler_jobs.values():
            if job.id in config_job_ids:
                continue
            payload = job.model_dump(mode="json")
            payload["source"] = "runtime"
            scheduler_jobs.append(payload)

        tool_backends = {}
        for name in ["comfyui"]:
            backend = getattr(app_config.tool_backends, name)
            tool_backends[name] = {
                "enabled": backend.enabled,
                "base_url": backend.base_url,
                "secrets_ready": all(
                    (not secret.required) or bool(os.getenv(secret.env_var))
                    for secret in backend.secret_refs
                ),
                "health": self._check_http_health(
                    base_url=backend.base_url,
                    health_path=backend.health_path,
                    headers=backend.headers,
                    timeout=backend.timeout_seconds,
                )
                if backend.enabled
                else {"healthy": False, "reason": "disabled"},
            }

        mcp_servers = {}
        for name, server in extensions.mcp_servers.items():
            mcp_servers[name] = {
                "enabled": server.enabled,
                "type": server.type,
                "url": server.url,
                "description": server.description,
                "health": self._check_http_health(
                    base_url=server.url,
                    health_path="/health",
                    headers=server.headers,
                    timeout=10.0,
                )
                if server.enabled and server.type in {"http", "sse"}
                else {"healthy": False, "reason": "not_http"},
            }

        return {
            "generated_at": utcnow(),
            "channels": channel_service.get_status() if channel_service is not None else {"service_running": False, "channels": {}},
            "tool_backends": tool_backends,
            "mcp_servers": mcp_servers,
            "folder_sync_targets": [target.model_dump(mode="json") for target in app_config.pipelines.folder_sync_targets],
            "audit_log": [event.model_dump(mode="json") for event in snapshot.audit_log[-50:]],
            "scheduler": {
                "enabled": app_config.scheduler.enabled,
                "jobs": scheduler_jobs,
                "state": [state.model_dump(mode="json") for state in snapshot.scheduler_jobs.values()],
                "autoresearch_objectives": [
                    objective.model_dump(mode="json")
                    for objective in sorted(
                        snapshot.autoresearch_objectives.values(),
                        key=lambda item: item.updated_at,
                        reverse=True,
                    )
                ],
            },
        }

    def run_scheduler_tick(self) -> list[PipelineRun]:
        return self._scheduler.run_scheduler_tick()

    def run_scheduler_job_now(self, job_id: str) -> PipelineRun:
        return self._scheduler.run_scheduler_job_now(job_id)


_control_plane_service: ControlPlaneService | None = None


def get_control_plane_service() -> ControlPlaneService:
    global _control_plane_service
    if _control_plane_service is None:
        _control_plane_service = ControlPlaneService()
    return _control_plane_service
