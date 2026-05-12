from __future__ import annotations

from pathlib import Path

from src.control_plane.models import PipelineStepDefinition, PipelineTemplate
from src.control_plane.service import ControlPlaneService
from src.control_plane.store import ControlPlaneStore


def _make_service(tmp_path):
    store = ControlPlaneStore(path=tmp_path / "state.json")
    return ControlPlaneService(store=store)


def test_workspace_activity_tracking(tmp_path) -> None:
    service = _make_service(tmp_path)
    assert service.has_recent_workspace_activity(hours=24) is False
    service.record_workspace_activity(thread_id="thread-1", message="hello from workspace")
    assert service.has_recent_workspace_activity(hours=24) is True


def test_pause_runtime_scheduler_job(tmp_path) -> None:
    service = _make_service(tmp_path)
    template = PipelineTemplate(
        id="tmp-autoresearch-template",
        name="Tmp",
        requires_approval=False,
        steps=[PipelineStepDefinition(name="noop", kind="note", config={"message": "x"})],
    )
    service.upsert_template(template)

    job = service.create_runtime_scheduler_job(
        name="Tmp Job",
        pipeline_template_id=template.id,
        daily_time="09:30",
        enabled=True,
        requires_approval=False,
    )
    paused = service.pause_runtime_scheduler_job(job.id, reason="inactive")
    assert paused is True

    status = service.get_integrations_status()
    matched = [item for item in status["scheduler"]["jobs"] if item["id"] == job.id]
    assert matched
    assert matched[0]["enabled"] is False


def test_autoresearch_objective_start_pause_resume(tmp_path) -> None:
    service = _make_service(tmp_path)
    result = service.start_autoresearch_objective(
        topic="Maritime decarbonization",
        endpoint_goal="Deliver a complete, evidence-backed research brief.",
        thread_id="thread-1",
    )
    objective = result["objective"]
    assert objective.status == "active"
    assert objective.scheduler_job_id
    assert result["bootstrap_run"] is not None
    assert result["bootstrap_run"].requires_approval is False

    paused = service.pause_autoresearch_objective(objective.objective_id, reason="denied")
    assert paused.status == "paused_denied"
    assert paused.pause_reason == "denied"

    resumed = service.resume_autoresearch_objective(objective.objective_id)
    assert resumed.status == "active"
    assert resumed.pause_reason is None


def test_autoresearch_endpoint_completion_pauses_scheduler(tmp_path) -> None:
    service = _make_service(tmp_path)
    start = service.start_autoresearch_objective(
        topic="Port emissions index",
        endpoint_goal="Publish a complete briefing with no blockers.",
    )
    objective = start["objective"]
    run = start["bootstrap_run"]
    assert run is not None

    service._autoresearch_orchestrator.update_after_sufficiency(  # noqa: SLF001
        run=run,
        report={
            "objective_id": objective.objective_id,
            "decision": "sufficient",
            "score": 88.5,
            "blocking_checks": [],
            "recommended_actions": ["Document endpoint and monitor quarterly."],
        },
    )

    updated = service.get_autoresearch_objective(objective.objective_id)
    assert updated.status == "completed_endpoint"
    assert updated.pause_reason == "endpoint_reached"
    assert updated.latest_sufficiency_decision == "sufficient"
    assert updated.progress_markdown_path
    assert updated.progress_json_path

    status = service.get_integrations_status()
    matched = [item for item in status["scheduler"]["jobs"] if item["id"] == updated.scheduler_job_id]
    assert matched
    assert matched[0]["enabled"] is False


def test_autoresearch_inactivity_skip_does_not_disable_scheduler(tmp_path) -> None:
    service = _make_service(tmp_path)
    start = service.start_autoresearch_objective(
        topic="Marine insurance claims taxonomy",
        endpoint_goal="Produce a curated taxonomy with evidence.",
    )
    objective = start["objective"]
    assert objective.scheduler_job_id

    run = service.run_scheduler_job_now(objective.scheduler_job_id)
    assert run.status == "completed"

    status = service.get_integrations_status()
    matched = [item for item in status["scheduler"]["jobs"] if item["id"] == objective.scheduler_job_id]
    assert matched
    assert matched[0]["enabled"] is True


def test_manual_run_resumes_disabled_vault_scheduler_job(tmp_path) -> None:
    service = _make_service(tmp_path)
    start = service.start_autoresearch_objective(
        topic="Vessel particulars definitions",
        endpoint_goal="Complete a definitions index with source citations.",
    )
    objective = start["objective"]
    assert objective.scheduler_job_id

    service.pause_runtime_scheduler_job(objective.scheduler_job_id, reason="test_manual_pause")
    run = service.run_scheduler_job_now(objective.scheduler_job_id)
    assert run.status == "completed"

    status = service.get_integrations_status()
    matched = [item for item in status["scheduler"]["jobs"] if item["id"] == objective.scheduler_job_id]
    assert matched
    assert matched[0]["enabled"] is True


def test_vault_action_items_include_scheduler_errors(tmp_path) -> None:
    service = _make_service(tmp_path)
    start = service.start_autoresearch_objective(
        topic="Maritime sensor drift baselines",
        endpoint_goal="Deliver calibrated baseline ranges and outlier rules.",
    )
    objective = start["objective"]
    assert objective.scheduler_job_id

    service._append_audit_event(  # noqa: SLF001
        "scheduler_job_error",
        "Scheduler job failed: maritime sensor drift baselines",
        metadata={
            "job_id": objective.scheduler_job_id,
            "template_id": "knowledge-vault-autoresearch",
            "error": "upstream timeout",
        },
    )

    action_items = service.list_vault_action_items(limit=100)
    scheduler_errors = [item for item in action_items["items"] if item.get("kind") == "scheduler_error"]
    assert scheduler_errors
    assert "scheduler job failed" in str(scheduler_errors[0].get("detail", "")).lower()


def test_delete_autoresearch_objective_cascades_scheduler_and_progress_files(tmp_path) -> None:
    service = _make_service(tmp_path)
    start = service.start_autoresearch_objective(
        topic="Southern lights watch windows",
        endpoint_goal="Publish an evidence-backed viewing guide.",
    )
    objective = start["objective"]
    assert objective.scheduler_job_id
    progress_md_path = Path(str(objective.progress_markdown_path or ""))
    assert progress_md_path.exists()

    payload = service.delete_autoresearch_objective(objective.objective_id)
    assert payload["deleted"] is True
    assert payload["objective_id"] == objective.objective_id
    assert objective.scheduler_job_id in payload["removed_scheduler_jobs"]

    status = service.get_integrations_status()
    matched = [item for item in status["scheduler"]["jobs"] if item["id"] == objective.scheduler_job_id]
    assert not matched

    assert progress_md_path.exists() is False
