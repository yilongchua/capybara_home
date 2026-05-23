from __future__ import annotations

import re

from src.control_plane.agents.base import BaseControlPlaneAgent
from src.control_plane.agents.schemas import (
    AgentExecutionContext,
    AgentExecutionResult,
    KnowledgeVaultExecutionProfile,
)


class KnowledgeVaultAgent(BaseControlPlaneAgent):
    agent_id = "knowledge_vault"

    @classmethod
    def supported_kinds(cls) -> set[str]:
        return {
            "vault_discover",
            "vault_ingest",
            "vault_compile",
            "vault_lint",
            "synthesize_knowledge_graph",
            "vault_sufficiency_evaluate",
        }

    def execute(self, context: AgentExecutionContext) -> AgentExecutionResult:
        profile = self._execution_profile(context)
        kind = context.definition.kind
        if kind == "vault_discover":
            return self._execute_discover(context, profile)
        if kind == "vault_ingest":
            return self._execute_ingest(context, profile)
        if kind == "vault_compile":
            return self._execute_compile(context, profile)
        if kind == "vault_lint":
            return self._execute_lint(context, profile)
        if kind == "synthesize_knowledge_graph":
            return self._execute_synthesis(context, profile)
        if kind == "vault_sufficiency_evaluate":
            return self._execute_sufficiency(context, profile)
        raise ValueError(f"Unsupported vault step kind: {kind}")

    def _execution_profile(self, context: AgentExecutionContext) -> KnowledgeVaultExecutionProfile:
        source = str(context.definition.config.get("source") or "").strip()
        # The new autoresearch loop does not use this vault-agent path at all, but a few
        # legacy step configs may still set `source = "autoresearch"`. Honour that flag for
        # the continuous-learning template's inactivity gating.
        inferred_mode = "autoresearch" if source == "autoresearch" else "continuous"
        topic_input_key = str(context.definition.config.get("topic_input_key") or "autoresearch_topic")
        stop_if_inactive = bool(context.definition.config.get("stop_if_inactive", inferred_mode == "autoresearch"))
        activity_window_hours = int(context.definition.config.get("activity_window_hours") or 24)
        effective_source = source or (
            "autoresearch" if inferred_mode == "autoresearch" else f"pipeline:{context.run.template_name or context.run.id}"
        )
        return KnowledgeVaultExecutionProfile(
            mode=inferred_mode,
            source=effective_source,
            topic_input_key=topic_input_key,
            stop_if_inactive=stop_if_inactive,
            activity_window_hours=activity_window_hours,
        )

    def _topic(self, context: AgentExecutionContext, profile: KnowledgeVaultExecutionProfile) -> str:
        return str(
            context.run.inputs.get(profile.topic_input_key) or context.definition.config.get("topic") or ""
        ).strip()

    def _objective_id(self, context: AgentExecutionContext, topic: str) -> str:
        return str(
            context.run.inputs.get("objective_id")
            or context.definition.config.get("objective_id")
            or f"obj-{re.sub(r'[^a-zA-Z0-9]+', '-', topic.strip().lower()).strip('-') or 'general'}"
        )

    def _inactive_skip_result(
        self,
        *,
        context: AgentExecutionContext,
        profile: KnowledgeVaultExecutionProfile,
        phase: str,
    ) -> AgentExecutionResult:
        scheduler_job_id = str(context.run.metadata.get("scheduler_job_id") or "")
        report = {
            "status": "skipped_inactive",
            "activity_window_hours": profile.activity_window_hours,
            "paused_scheduler_job": False,
            "scheduler_job_id": scheduler_job_id or None,
            "note": "Scheduler job remains enabled; inactivity skip does not disable schedules.",
        }
        artifacts = self._service._write_vault_step_artifacts(
            run_id=context.run_id,
            step_id=context.step.step_id,
            phase=phase,
            report=report,
        )
        return self._result(
            context,
            status="skipped",
            note="Workspace inactive; vault step skipped.",
            output={
                "report": report,
                "artifact_path": artifacts["json_path"],
                "artifact_markdown_path": artifacts["md_path"],
            },
            details={"graph": ["check_activity", "skip", "write_artifacts"], "profile": profile.model_dump(mode="json")},
        )

    def _execute_discover(
        self,
        context: AgentExecutionContext,
        profile: KnowledgeVaultExecutionProfile,
    ) -> AgentExecutionResult:
        manager = self._service._build_vault_manager(context.definition)
        if profile.stop_if_inactive and not self._service.has_recent_workspace_activity(hours=profile.activity_window_hours):
            return self._inactive_skip_result(context=context, profile=profile, phase="discover")

        urls = self._service._resolve_vault_urls(run=context.run, definition=context.definition)
        topic = self._topic(context, profile)
        objective_id = self._objective_id(context, topic)
        loop_guard = manager.check_loop_guard(
            objective_id=objective_id,
            topic=topic or objective_id,
            query_text=topic or "vault_discover",
            key_entities=[topic] if topic else [],
            cooldown_hours=int(context.definition.config.get("loop_cooldown_hours") or 24),
            retry_budget=int(context.definition.config.get("loop_retry_budget") or 3),
        )
        if not loop_guard.get("allowed", False):
            report = {
                "status": "skipped_loop_guard",
                "objective_id": objective_id,
                "topic": topic,
                **loop_guard,
            }
            artifacts = self._service._write_vault_step_artifacts(
                run_id=context.run_id,
                step_id=context.step.step_id,
                phase="discover",
                report=report,
            )
            return self._result(
                context,
                status="skipped",
                note="Loop guard blocked discover execution.",
                output={
                    "report": report,
                    "artifact_path": artifacts["json_path"],
                    "artifact_markdown_path": artifacts["md_path"],
                },
                details={"graph": ["resolve_urls", "check_loop_guard", "skip", "write_artifacts"], "profile": profile.model_dump(mode="json")},
            )

        report = manager.discover(
            urls=urls,
            source=profile.source,
            topic=topic,
            max_results=int(context.definition.config.get("max_discovery_results") or 8),
        )
        report["objective_id"] = objective_id
        artifacts = self._service._write_vault_step_artifacts(
            run_id=context.run_id,
            step_id=context.step.step_id,
            phase="discover",
            report=report,
        )
        return self._result(
            context,
            output={
                "report": report,
                "artifact_path": artifacts["json_path"],
                "artifact_markdown_path": artifacts["md_path"],
            },
            details={"graph": ["resolve_urls", "check_loop_guard", "discover", "write_artifacts"], "profile": profile.model_dump(mode="json")},
        )

    def _execute_ingest(
        self,
        context: AgentExecutionContext,
        profile: KnowledgeVaultExecutionProfile,
    ) -> AgentExecutionResult:
        manager = self._service._build_vault_manager(context.definition)
        if profile.stop_if_inactive and not self._service.has_recent_workspace_activity(hours=profile.activity_window_hours):
            return self._inactive_skip_result(context=context, profile=profile, phase="ingest")

        urls = self._service._resolve_vault_urls(run=context.run, definition=context.definition)
        if not urls:
            urls = self._service._collect_discovered_urls(context.run)
        topic = self._topic(context, profile)
        objective_id = self._objective_id(context, topic)
        queue_items = manager.claim_search_queue_items(
            topic=topic,
            max_items=int(context.definition.config.get("max_queue_items") or 10),
        )
        try:
            report = manager.ingest(
                urls=urls,
                source=profile.source,
                topic=topic,
                queue_items=queue_items,
            )
        except Exception:
            queue_ids = [str(item.get("queue_id") or "") for item in queue_items if str(item.get("queue_id") or "").strip()]
            manager.requeue_claimed_items(queue_ids, reason="ingest_failed_retry")
            raise
        report["objective_id"] = objective_id
        artifacts = self._service._write_vault_step_artifacts(
            run_id=context.run_id,
            step_id=context.step.step_id,
            phase="ingest",
            report=report,
        )
        return self._result(
            context,
            output={
                "report": report,
                "artifact_path": artifacts["json_path"],
                "artifact_markdown_path": artifacts["md_path"],
            },
            details={"graph": ["resolve_urls", "claim_queue", "ingest", "write_artifacts"], "profile": profile.model_dump(mode="json")},
        )

    def _execute_compile(
        self,
        context: AgentExecutionContext,
        profile: KnowledgeVaultExecutionProfile,
    ) -> AgentExecutionResult:
        manager = self._service._build_vault_manager(context.definition)
        report = manager.compile_indexes()
        artifacts = self._service._write_vault_step_artifacts(
            run_id=context.run_id,
            step_id=context.step.step_id,
            phase="compile",
            report=report,
        )
        return self._result(
            context,
            output={
                "report": report,
                "artifact_path": artifacts["json_path"],
                "artifact_markdown_path": artifacts["md_path"],
            },
            details={"graph": ["compile_indexes", "write_artifacts"], "profile": profile.model_dump(mode="json")},
        )

    def _execute_lint(
        self,
        context: AgentExecutionContext,
        profile: KnowledgeVaultExecutionProfile,
    ) -> AgentExecutionResult:
        manager = self._service._build_vault_manager(context.definition)
        report = manager.lint_vault(
            freshness_window_days=int(context.definition.config.get("freshness_window_days") or 30)
        )
        artifacts = self._service._write_vault_step_artifacts(
            run_id=context.run_id,
            step_id=context.step.step_id,
            phase="lint",
            report=report,
        )
        return self._result(
            context,
            output={
                "report": report,
                "artifact_path": artifacts["json_path"],
                "artifact_markdown_path": artifacts["md_path"],
            },
            details={"graph": ["lint_vault", "write_artifacts"], "profile": profile.model_dump(mode="json")},
        )

    def _execute_synthesis(
        self,
        context: AgentExecutionContext,
        profile: KnowledgeVaultExecutionProfile,
    ) -> AgentExecutionResult:
        manager = self._service._build_vault_manager(context.definition)
        topic = self._topic(context, profile)
        objective_id = self._objective_id(context, topic)

        report = manager.synthesize_knowledge_graph(
            objective_id=objective_id,
            topic=topic,
        )
        artifacts = self._service._write_vault_step_artifacts(
            run_id=context.run_id,
            step_id=context.step.step_id,
            phase="synthesis",
            report=report,
        )
        return self._result(
            context,
            output={
                "report": report,
                "artifact_path": artifacts["json_path"],
                "artifact_markdown_path": artifacts["md_path"],
            },
            details={
                "graph": ["derive_evidence", "synthesize_graph", "write_artifacts"],
                "profile": profile.model_dump(mode="json"),
            },
        )

    def _execute_sufficiency(
        self,
        context: AgentExecutionContext,
        profile: KnowledgeVaultExecutionProfile,
    ) -> AgentExecutionResult:
        manager = self._service._build_vault_manager(context.definition)
        topic = self._topic(context, profile)
        objective_id = self._objective_id(context, topic)
        report = manager.evaluate_sufficiency(
            objective_id=objective_id,
            topic=topic,
            min_score=float(context.definition.config.get("min_score") or 78),
        )
        if bool(report.get("auto_pause_recommended", False)):
            scheduler_job_id = str(context.run.metadata.get("scheduler_job_id") or "")
            if scheduler_job_id:
                paused = self._service.pause_runtime_scheduler_job(
                    scheduler_job_id,
                    reason="sufficiency_reached_with_no_blockers",
                )
                report["auto_paused_scheduler_job"] = paused
                report["scheduler_job_id"] = scheduler_job_id

        # Sufficiency evaluation only applies to the continuous-learning template; the
        # autoresearch loop has its own novelty-decay stop criterion (no sufficiency report).

        artifacts = self._service._write_vault_step_artifacts(
            run_id=context.run_id,
            step_id=context.step.step_id,
            phase="sufficiency",
            report=report,
        )
        return self._result(
            context,
            output={
                "report": report,
                "artifact_path": artifacts["json_path"],
                "artifact_markdown_path": artifacts["md_path"],
            },
            details={
                "graph": ["evaluate_sufficiency", "optional_auto_pause", "write_artifacts"],
                "profile": profile.model_dump(mode="json"),
            },
        )
