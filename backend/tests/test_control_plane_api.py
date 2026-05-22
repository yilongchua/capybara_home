from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.community.knowledge_vault_search import tool as vault_tool_module
from src.config.app_config import AppConfig, set_app_config
from src.config.control_plane_config import (
    ApprovalsConfig,
    CSVProfilesConfig,
    KnowledgeVaultConfig,
    PipelinesConfig,
    RedactionConfig,
    SchedulerConfig,
    ToolBackendsConfig,
)
from src.config.extensions_config import ExtensionsConfig, set_extensions_config
from src.config.paths import Paths
from src.config.sandbox_config import SandboxConfig
from src.config.skills_config import SkillsConfig
from src.control_plane.models import CSVProfile, PipelineStepDefinition, PipelineTemplate
from src.control_plane.service import get_control_plane_service
from src.gateway.routers import approvals, feedback, integrations, pipelines, triggers, vault


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(triggers.router)
    app.include_router(pipelines.router)
    app.include_router(approvals.router)
    app.include_router(feedback.router)
    app.include_router(integrations.router)
    app.include_router(vault.router)
    return app


def _self_improver_report(
    *,
    run_id: str,
    skill_path: str,
    proposal_id: str = "draft-001",
    addition: str = "## Self-Improvement Draft",
):
    return {
        "version": "self-improver-draft.v1",
        "generated_at": "2026-04-09T00:00:00+00:00",
        "run_id": run_id,
        "signal_window": {
            "lookback_days": 14,
            "since": "2026-03-26T00:00:00+00:00",
            "until": "2026-04-09T00:00:00+00:00",
        },
        "limits": {"max_proposals": 20, "max_diff_lines": 200},
        "counts": {
            "skills_total": 1,
            "skills_with_signals": 1,
            "proposals": 1,
            "skipped": 0,
        },
        "proposals": [
            {
                "id": proposal_id,
                "skill_name": "podcast-generation",
                "category": "public",
                "skill_path": skill_path,
                "confidence": 0.8,
                "summary": "Add troubleshooting checklist.",
                "recommended_addition": addition,
                "risk_flags": [],
                "evidence": {},
                "validation": {
                    "frontmatter_ok": True,
                    "parse_ok": True,
                    "issues": [],
                },
                "diff_preview": "--- a/SKILL.md\n+++ b/SKILL.md",
            }
        ],
        "skipped": [],
    }


def _create_self_improver_run(control_plane_client: TestClient) -> dict:
    response = control_plane_client.post(
        "/api/pipelines/runs",
        json={
            "steps": [
                {
                    "id": "self-improver-step",
                    "name": "Generate drafts",
                    "kind": "self_improver_draft",
                    "config": {},
                }
            ],
            "requires_approval": False,
            "auto_start": True,
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture()
def control_plane_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = Paths(tmp_path)
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "public" / "podcast-generation"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: podcast-generation\ndescription: Test skill\n---\n# Skill\n",
        encoding="utf-8",
    )

    config = AppConfig(
        models=[],
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
        tools=[],
        tool_groups=[],
        skills=SkillsConfig(path=str(skills_root)),
        pipelines=PipelinesConfig(
            enabled=True,
            storage_dir="control-plane",
            templates=[
                PipelineTemplate(
                    id="review-template",
                    name="Review Template",
                    description="Test pipeline template",
                    requires_approval=True,
                    steps=[
                        PipelineStepDefinition(
                            id="note-step",
                            name="Write note artifact",
                            kind="note",
                            config={"message": "Hello from control plane tests."},
                        )
                    ],
                )
            ],
        ),
        approvals=ApprovalsConfig(enabled=True),
        redaction=RedactionConfig(enabled=True),
        csv_profiles=CSVProfilesConfig(
            enabled=True,
            profiles=[
                CSVProfile(
                    id="ops-review",
                    description="Test profile",
                    focus="Test focus",
                )
            ],
        ),
        tool_backends=ToolBackendsConfig(),
        scheduler=SchedulerConfig(enabled=False),
        knowledge_vault=KnowledgeVaultConfig(
            enabled=True,
            path=str(tmp_path / "knowledge_vault"),
            min_trust_score=0.2,
            graph_limit=400,
        ),
    )

    set_app_config(config)
    set_extensions_config(ExtensionsConfig(mcpServers={}, skills={}))

    import src.config.paths as paths_module
    import src.control_plane.service as control_plane_service_module
    import src.control_plane.store as control_plane_store_module

    monkeypatch.setattr(paths_module, "_paths", paths, raising=False)
    monkeypatch.setattr(control_plane_service_module, "_control_plane_service", None, raising=False)
    monkeypatch.setattr(control_plane_store_module, "get_paths", lambda: paths)
    monkeypatch.setattr(control_plane_service_module, "get_paths", lambda: paths)

    app = _make_app()
    with TestClient(app) as client:
        yield client


def test_control_plane_api_happy_path(control_plane_client: TestClient):
    templates_response = control_plane_client.get("/api/pipelines")
    assert templates_response.status_code == 200
    templates = templates_response.json()["items"]
    template_ids = {template["id"] for template in templates}
    assert "review-template" in template_ids

    trigger_response = control_plane_client.post(
        "/api/triggers",
        json={
            "source": "telegram",
            "message": "Please review this pipeline request for alice@example.com",
            "classification": "channel_message",
        },
    )
    assert trigger_response.status_code == 201
    trigger = trigger_response.json()
    assert trigger["masked_message"] != trigger["message"]

    create_run_response = control_plane_client.post(
        "/api/pipelines/runs",
        json={
            "template_id": "review-template",
            "trigger_event_id": trigger["id"],
            "inputs": {"prompt": "hello"},
        },
    )
    assert create_run_response.status_code == 201
    run = create_run_response.json()
    assert run["status"] == "pending_approval"
    assert run["approval_request_id"] is not None

    approvals_response = control_plane_client.get("/api/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = approvals_response.json()["items"]
    assert len(approvals_payload) == 1
    approval = approvals_payload[0]
    assert approval["pipeline_run_id"] == run["id"]

    resolve_response = control_plane_client.post(
        f"/api/approvals/{approval['id']}/resolve",
        json={"approve": True, "auto_start": True},
    )
    assert resolve_response.status_code == 200
    resolved_run = resolve_response.json()
    assert resolved_run["status"] == "completed"
    assert resolved_run["artifacts"]
    assert resolved_run["steps"][0]["status"] == "completed"

    feedback_response = control_plane_client.post(
        "/api/feedback",
        json={
            "target_type": "pipeline_run",
            "target_id": resolved_run["id"],
            "value": "up",
            "source": "workspace",
        },
    )
    assert feedback_response.status_code == 201
    feedback_payload = feedback_response.json()
    assert feedback_payload["value"] == "up"

    integrations_response = control_plane_client.get("/api/integrations/status")
    assert integrations_response.status_code == 200
    integrations_payload = integrations_response.json()
    assert integrations_payload["channels"]["service_running"] is False
    assert "comfyui" in integrations_payload["tool_backends"]

    vault_status_response = control_plane_client.get("/api/vault/status")
    assert vault_status_response.status_code == 200
    vault_status = vault_status_response.json()
    assert "memory" in vault_status
    assert "progress" in vault_status
    assert "action_items" in vault_status

    action_items_response = control_plane_client.get("/api/vault/action-items?limit=20")
    assert action_items_response.status_code == 200
    action_items = action_items_response.json()
    assert "items" in action_items
    assert "counts" in action_items

    suff_response = control_plane_client.post(
        "/api/vault/sufficiency/evaluate",
        json={"objective_id": "obj-general", "topic": "general"},
    )
    assert suff_response.status_code == 200
    suff_payload = suff_response.json()
    assert suff_payload["objective_id"] == "obj-general"
    assert suff_payload["decision"] in {"insufficient", "near_sufficient", "sufficient"}


def test_pipeline_runs_support_thread_status_and_limit_filters(control_plane_client: TestClient):
    run_a = control_plane_client.post(
        "/api/pipelines/runs",
        json={
            "steps": [],
            "requires_approval": False,
            "metadata": {"source_thread_id": "thread-a"},
        },
    )
    assert run_a.status_code == 201

    run_b = control_plane_client.post(
        "/api/pipelines/runs",
        json={
            "steps": [],
            "requires_approval": False,
            "metadata": {"source_thread_id": "thread-b"},
        },
    )
    assert run_b.status_code == 201

    filtered = control_plane_client.get(
        "/api/pipelines/runs?thread_id=thread-a&status=approved",
    )
    assert filtered.status_code == 200
    items = filtered.json()["items"]
    assert len(items) == 1
    assert items[0]["metadata"]["source_thread_id"] == "thread-a"
    assert items[0]["status"] == "approved"

    comma_status = control_plane_client.get(
        "/api/pipelines/runs?thread_id=thread-a&status=running,approved",
    )
    assert comma_status.status_code == 200
    comma_items = comma_status.json()["items"]
    assert len(comma_items) == 1
    assert comma_items[0]["metadata"]["source_thread_id"] == "thread-a"

    limited = control_plane_client.get("/api/pipelines/runs?limit=1")
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 1


def test_vault_queue_no_longer_creates_approval(control_plane_client: TestClient):
    """Queue-ingest approval gating was removed: enqueueing results must not
    create any pending approval, and Run Ingest drains directly via
    start_vault_ingest_job(). See backend/src/control_plane/service.py."""
    service = get_control_plane_service()
    manager = service._default_vault_manager()

    manager.enqueue_search_results(
        query="maritime data quality",
        results=[
            {
                "title": "Vessel Particulars Reference",
                "url": "https://example.com/vessel-particulars",
                "snippet": "Reference data",
                "extracted_content": "# Vessel Particulars\n\nTrusted reference content.",
                "topic_tags": ["maritime-data-quality"],
                "concept_refs": ["vessel-particulars"],
                "entity_refs": [],
                "target_synthesis_refs": ["maritime-data-quality-vessel-particulars"],
            }
        ],
    )

    # The no-op method preserved for legacy callers must always return None.
    assert service.ensure_vault_queue_ingest_approval() is None

    # No vault-queue approval should appear in the listing.
    approvals_response = control_plane_client.get("/api/approvals")
    assert approvals_response.status_code == 200
    items = approvals_response.json()["items"]
    vault_queue_items = [
        item for item in items
        if (item.get("metadata") or {}).get("approval_kind") == "knowledge_vault_queue_ingest"
    ]
    assert vault_queue_items == []


def test_integration_services_status_shape(control_plane_client: TestClient):
    response = control_plane_client.get("/api/integrations/services")
    assert response.status_code == 200
    payload = response.json()

    assert "generated_at" in payload
    assert "docker_desktop_online" in payload
    assert "docker_services" in payload
    assert "required_core_services" in payload
    assert "readiness_summary" in payload
    services = payload["services"]
    assert isinstance(services, list)
    assert {item["id"] for item in services} == {
        "llm",
        "comfyui",
        "lightrag",
        "websearch",
    }

    comfyui = next(item for item in services if item["id"] == "comfyui")
    assert "host" in comfyui
    assert "port" in comfyui
    assert "healthy" in comfyui
    assert "docker_online" in comfyui
    assert "phase" in comfyui
    assert "last_failure_reason" in comfyui
    assert "last_transition_at" in comfyui


def test_vault_pipeline_artifacts_and_api(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx

    class _MockResponse:
        def __init__(self, url: str) -> None:
            self.url = url
            self.text = (
                "<html><head><title>Maritime Data Quality</title></head>"
                "<body><main><p>Vessel particulars improve maritime data quality.</p></main></body></html>"
            )

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return _MockResponse(url)

    monkeypatch.setattr(httpx, "get", fake_get)

    response = control_plane_client.post(
        "/api/pipelines/runs",
        json={
            "steps": [
                {
                    "id": "discover-step",
                    "name": "discover",
                    "kind": "vault_discover",
                    "config": {"input_key": "urls", "source": "test"},
                },
                {
                    "id": "ingest-step",
                    "name": "ingest",
                    "kind": "vault_ingest",
                    "config": {"input_key": "urls", "source": "test"},
                },
                {
                    "id": "compile-step",
                    "name": "compile",
                    "kind": "vault_compile",
                    "config": {},
                },
                {
                    "id": "lint-step",
                    "name": "lint",
                    "kind": "vault_lint",
                    "config": {"freshness_window_days": 30},
                },
            ],
            "inputs": {"urls": ["https://example.com/maritime-quality"]},
            "requires_approval": False,
            "auto_start": True,
        },
    )
    assert response.status_code == 201
    run = response.json()

    assert any(item.endswith("-vault-discover.json") for item in run["artifacts"])
    assert any(item.endswith("-vault-discover.md") for item in run["artifacts"])
    assert any(item.endswith("-vault-ingest.md") for item in run["artifacts"])
    assert any(item.endswith("-vault-compile.md") for item in run["artifacts"])
    assert any(item.endswith("-vault-lint.md") for item in run["artifacts"])

    md_name = next(Path(item).name for item in run["artifacts"] if item.endswith("-vault-ingest.md"))
    content_response = control_plane_client.get(
        f"/api/pipelines/runs/{run['id']}/artifacts/{md_name}/content",
    )
    assert content_response.status_code == 200
    content_payload = content_response.json()
    assert content_payload["content_type"] == "text/markdown"
    assert "Vault Ingest Summary" in content_payload["content"]

    status_response = control_plane_client.get("/api/vault/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert "counts" in status_payload
    assert "queued_search_results" in status_payload["counts"]

    search_response = control_plane_client.get("/api/vault/search?q=maritime")
    assert search_response.status_code == 200
    assert search_response.json()["total"] >= 1


def test_vault_tool_and_api_search_share_ranked_results(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    service = get_control_plane_service()
    manager = service._default_vault_manager()
    compiled_sources = manager.compiled_sources_dir

    (compiled_sources / "shipping-rates.md").write_text(
        "---\n"
        "title: \"Shipping Rates Overview\"\n"
        "tags: [\"shipping\", \"rates\"]\n"
        "---\n\n"
        "# Shipping Rates Overview\n\n"
        "Shipping rates surged across major freight lanes.\n",
        encoding="utf-8",
    )
    (compiled_sources / "port-logistics.md").write_text(
        "---\n"
        "title: \"Port Logistics Notes\"\n"
        "tags: [\"ports\"]\n"
        "---\n\n"
        "# Port Logistics Notes\n\n"
        "Port logistics updates mention shipping in passing.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(vault_tool_module, "_searcher", None, raising=False)

    api_response = control_plane_client.get("/api/vault/search?q=shipping rates&limit=2")
    assert api_response.status_code == 200
    api_payload = api_response.json()

    raw_tool_payload = vault_tool_module.query_knowledge_vault_tool.invoke({"query": "shipping rates", "limit": 2})
    tool_payload = json.loads(raw_tool_payload)

    assert tool_payload["ok"] is True
    assert [item["title"] for item in api_payload["items"]] == [item["title"] for item in tool_payload["results"]]
    assert [item["path"] for item in api_payload["items"]] == [item["path"] for item in tool_payload["results"]]


def test_vault_clip_save_and_graph_api(control_plane_client: TestClient):
    clip_response = control_plane_client.post(
        "/api/vault/clip",
        json={
            "url": "https://example.com/clipped-article",
            "title": "Clipped Article",
            "markdown": "# Clipped Article\n\nThis clipped page discusses local cached research workflows.",
            "topic": "cached research",
        },
    )
    assert clip_response.status_code == 200
    assert clip_response.json()["status"] == "queued"
    assert int(clip_response.json()["appended_count"] or 0) == 1

    save_response = control_plane_client.post(
        "/api/vault/save",
        json={
            "title": "Cached Research Summary",
            "content": "This saved note explains how repeated searches can reuse prior evidence.",
            "topic": "cached research",
        },
    )
    assert save_response.status_code == 200
    save_payload = save_response.json()
    assert save_payload["status"] in {"ingested", "skipped_unchanged"}
    assert save_payload["source_id"]

    status_response = control_plane_client.get("/api/vault/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert int(status_payload["counts"]["queued_clips"]) >= 1
    assert "vector_index_chunks" in status_payload["counts"]

    graph_response = control_plane_client.get("/api/vault/graph?limit=50")
    assert graph_response.status_code == 200
    graph_payload = graph_response.json()
    assert graph_payload["counts"]["nodes"] >= 1
    assert isinstance(graph_payload["nodes"], list)


def test_vault_graph_limit_defaults_from_config_and_explorer_snapshot_uses_it(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import src.control_plane.vault_learning as vault_learning_module

    seen_limits: list[int] = []
    original_get_graph = vault_learning_module.VaultLearningManager.get_graph

    def patched_get_graph(self, *, limit: int = 200):  # noqa: ANN001
        seen_limits.append(limit)
        return original_get_graph(self, limit=limit)

    monkeypatch.setattr(
        vault_learning_module.VaultLearningManager,
        "get_graph",
        patched_get_graph,
    )

    graph_response = control_plane_client.get("/api/vault/graph")
    assert graph_response.status_code == 200
    assert seen_limits[-1] == 400

    explicit_graph_response = control_plane_client.get("/api/vault/graph?limit=50")
    assert explicit_graph_response.status_code == 200
    assert seen_limits[-1] == 50

    explorer_response = control_plane_client.get("/api/vault/explorer")
    assert explorer_response.status_code == 200
    assert seen_limits[-1] == 400

def test_start_integration_service_success(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import src.control_plane.service as control_plane_service_module

    def fake_run(self, command: str, **kwargs) -> str:
        assert command in {
            "start-comfyui",
        }
        log_callback = kwargs.get("log_callback")
        if log_callback:
            log_callback("starting service")
        return "started"

    def fake_readiness(self):
        return [
            {"service_id": "comfyui", "healthy": True, "status_code": 200, "error": None},
        ]

    def run_inline(self, job_id: str):
        self._run_startup_job(job_id)

    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_run_local_stack_command",
        fake_run,
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_core_services_readiness",
        fake_readiness,
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_startup_stability_seconds",
        lambda self: 0,
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_start_startup_job_thread",
        run_inline,
    )

    response = control_plane_client.post("/api/integrations/services/comfyui/start")
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"]
    assert payload["accepted"] is True
    job = control_plane_client.get(f"/api/integrations/startup-jobs/{payload['job_id']}")
    assert job.status_code == 200
    job_payload = job.json()
    assert job_payload["status"] == "success"
    assert job_payload["steps"]


def test_start_integration_service_invalid_id(control_plane_client: TestClient):
    response = control_plane_client.post("/api/integrations/services/not-real/start")
    assert response.status_code == 400
    assert "Unsupported integration service" in response.json()["detail"]


def test_start_integration_service_failure(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import src.control_plane.service as control_plane_service_module

    def fail_run(self, command: str, **kwargs) -> str:
        raise RuntimeError(f"failed command: {command}")

    def run_inline(self, job_id: str):
        self._run_startup_job(job_id)

    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_run_local_stack_command",
        fail_run,
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_core_services_readiness",
        lambda self: (_ for _ in ()).throw(RuntimeError("health check failed")),
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_start_startup_job_thread",
        run_inline,
    )

    response = control_plane_client.post("/api/integrations/services/comfyui/start")
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"]
    job = control_plane_client.get(f"/api/integrations/startup-jobs/{payload['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "failed"


def test_start_all_integration_services(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import src.control_plane.service as control_plane_service_module

    def fake_run(self, command: str, **kwargs) -> str:
        assert command == "start"
        return "all started"

    def fake_readiness(self):
        return [
            {"service_id": "comfyui", "healthy": True, "status_code": 200, "error": None},
        ]

    def run_inline(self, job_id: str):
        self._run_startup_job(job_id)

    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_run_local_stack_command",
        fake_run,
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_core_services_readiness",
        fake_readiness,
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_startup_stability_seconds",
        lambda self: 0,
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_start_startup_job_thread",
        run_inline,
    )

    response = control_plane_client.post("/api/integrations/services/start-all")
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"]
    job = control_plane_client.get(f"/api/integrations/startup-jobs/{payload['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "success"


def test_self_improver_draft_run_and_artifact_endpoint(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import src.control_plane.service as control_plane_service_module

    def fake_self_improver(self, *, run, definition):
        return _self_improver_report(run_id=run.id, skill_path="/tmp/SKILL.md")

    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_run_self_improver_draft",
        fake_self_improver,
    )

    run_payload = _create_self_improver_run(control_plane_client)
    assert run_payload["status"] == "completed"
    artifact_name = run_payload["steps"][0]["output"]["artifact_name"]
    assert artifact_name.endswith(".json")

    artifact_response = control_plane_client.get(
        f"/api/pipelines/runs/{run_payload['id']}/artifacts/{artifact_name}"
    )
    assert artifact_response.status_code == 200
    artifact_payload = artifact_response.json()
    assert artifact_payload["version"] == "self-improver-draft.v1"
    assert artifact_payload["counts"]["proposals"] == 1


def test_runtime_scheduler_job_crud_and_manual_run(control_plane_client: TestClient):
    create_response = control_plane_client.post(
        "/api/integrations/scheduler/jobs",
        json={
            "name": "Daily review",
            "pipeline_template_id": "review-template",
            "daily_time": "09:15",
            "requires_approval": False,
        },
    )
    assert create_response.status_code == 200
    created_job = create_response.json()
    assert created_job["schedule_type"] == "daily_time"
    assert created_job["daily_time"] == "09:15"

    duplicate_response = control_plane_client.post(
        "/api/integrations/scheduler/jobs",
        json={
            "name": "Daily review duplicate",
            "pipeline_template_id": "review-template",
            "daily_time": "09:15",
            "requires_approval": False,
        },
    )
    assert duplicate_response.status_code == 400

    status_response = control_plane_client.get("/api/integrations/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    scheduler_jobs = status_payload["scheduler"]["jobs"]
    runtime_jobs = [job for job in scheduler_jobs if job.get("source") == "runtime"]
    assert any(job["id"] == created_job["id"] for job in runtime_jobs)

    run_response = control_plane_client.post(
        f"/api/integrations/scheduler/{created_job['id']}/run"
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["status"] == "completed"
    assert run_payload["template_id"] == "review-template"

    delete_response = control_plane_client.delete(
        f"/api/integrations/scheduler/jobs/{created_job['id']}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    status_after_delete = control_plane_client.get("/api/integrations/status")
    assert status_after_delete.status_code == 200
    remaining_jobs = status_after_delete.json()["scheduler"]["jobs"]
    assert not any(job["id"] == created_job["id"] for job in remaining_jobs)


def test_autoresearch_objective_endpoints(control_plane_client: TestClient):
    start_response = control_plane_client.post(
        "/api/pipelines/autoresearch/start",
        json={
            "topic": "IMO decarbonization milestones",
            "endpoint_goal": "Publish a complete, evidence-backed milestone briefing.",
            "thread_id": "thread-123",
            "bootstrap": True,
        },
    )
    assert start_response.status_code == 200
    started = start_response.json()
    objective = started["objective"]
    assert objective["status"] == "active"
    assert objective["scheduler_job_id"]
    assert started["bootstrap_run"]["requires_approval"] is False

    list_response = control_plane_client.get("/api/pipelines/autoresearch")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert any(item["objective_id"] == objective["objective_id"] for item in items)

    pause_response = control_plane_client.post(
        f"/api/pipelines/autoresearch/{objective['objective_id']}/pause",
        json={"reason": "denied"},
    )
    assert pause_response.status_code == 200
    paused = pause_response.json()
    assert paused["status"] == "paused_denied"
    assert paused["pause_reason"] == "denied"

    resume_response = control_plane_client.post(
        f"/api/pipelines/autoresearch/{objective['objective_id']}/resume",
    )
    assert resume_response.status_code == 200
    resumed = resume_response.json()
    assert resumed["status"] == "active"
    assert resumed["pause_reason"] is None

    get_response = control_plane_client.get(
        f"/api/pipelines/autoresearch/{objective['objective_id']}"
    )
    assert get_response.status_code == 200
    assert get_response.json()["objective_id"] == objective["objective_id"]

    progress_path = Path(get_response.json()["progress_markdown_path"])
    assert progress_path.exists()
    scheduler_job_id = get_response.json()["scheduler_job_id"]
    assert scheduler_job_id

    delete_response = control_plane_client.delete(
        f"/api/pipelines/autoresearch/{objective['objective_id']}"
    )
    assert delete_response.status_code == 200
    deleted_payload = delete_response.json()
    assert deleted_payload["deleted"] is True
    assert deleted_payload["objective_id"] == objective["objective_id"]
    assert scheduler_job_id in deleted_payload["removed_scheduler_jobs"]

    list_after_delete = control_plane_client.get("/api/pipelines/autoresearch")
    assert list_after_delete.status_code == 200
    items_after_delete = list_after_delete.json()["items"]
    assert not any(item["objective_id"] == objective["objective_id"] for item in items_after_delete)

    get_after_delete = control_plane_client.get(
        f"/api/pipelines/autoresearch/{objective['objective_id']}"
    )
    assert get_after_delete.status_code == 404

    progress_after_delete = control_plane_client.get(
        f"/api/vault/objectives/{objective['objective_id']}/progress.md"
    )
    assert progress_after_delete.status_code == 404
    assert progress_path.exists() is False

    integrations_after_delete = control_plane_client.get("/api/integrations/status")
    assert integrations_after_delete.status_code == 200
    jobs_after_delete = integrations_after_delete.json()["scheduler"]["jobs"]
    assert not any(job["id"] == scheduler_job_id for job in jobs_after_delete)


def test_proposal_approvals_list_and_apply(control_plane_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    import src.control_plane.service as control_plane_service_module
    from src.config.app_config import get_app_config

    skill_path = (
        get_app_config().skills.get_skills_path()
        / "public"
        / "podcast-generation"
        / "SKILL.md"
    )

    def fake_self_improver(self, *, run, definition):
        return _self_improver_report(run_id=run.id, skill_path=str(skill_path))

    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_run_self_improver_draft",
        fake_self_improver,
    )

    run_payload = _create_self_improver_run(control_plane_client)
    assert run_payload["status"] == "completed"

    list_response = control_plane_client.get("/api/approvals/proposals")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    target = next((item for item in items if item["run_id"] == run_payload["id"]), None)
    assert target is not None
    assert target["status"] == "pending"

    resolve_response = control_plane_client.post(
        f"/api/approvals/proposals/{target['run_id']}/{target['proposal_id']}/resolve",
        json={"approve": True},
    )
    assert resolve_response.status_code == 200
    resolved = resolve_response.json()
    assert resolved["status"] == "applied"
    assert resolved["applied_path"] == str(skill_path)
    assert "## Self-Improvement Draft" in skill_path.read_text(encoding="utf-8")

    rerun_response = control_plane_client.post(
        f"/api/approvals/proposals/{target['run_id']}/{target['proposal_id']}/resolve",
        json={"approve": False},
    )
    assert rerun_response.status_code == 400
    assert "already resolved" in rerun_response.json()["detail"]


def test_proposal_reject_does_not_modify_file(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import src.control_plane.service as control_plane_service_module
    from src.config.app_config import get_app_config

    skill_path = (
        get_app_config().skills.get_skills_path()
        / "public"
        / "podcast-generation"
        / "SKILL.md"
    )
    before = skill_path.read_text(encoding="utf-8")

    def fake_self_improver(self, *, run, definition):
        return _self_improver_report(
            run_id=run.id,
            skill_path=str(skill_path),
            proposal_id="draft-reject",
            addition="## Reject me",
        )

    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_run_self_improver_draft",
        fake_self_improver,
    )

    run_payload = _create_self_improver_run(control_plane_client)
    list_response = control_plane_client.get("/api/approvals/proposals")
    items = list_response.json()["items"]
    target = next(
        (
            item
            for item in items
            if item["run_id"] == run_payload["id"] and item["proposal_id"] == "draft-reject"
        ),
        None,
    )
    assert target is not None

    resolve_response = control_plane_client.post(
        f"/api/approvals/proposals/{run_payload['id']}/draft-reject/resolve",
        json={"approve": False},
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["status"] == "rejected"
    assert skill_path.read_text(encoding="utf-8") == before


def test_proposal_apply_blocks_path_escape(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import src.control_plane.service as control_plane_service_module

    def fake_self_improver(self, *, run, definition):
        return _self_improver_report(
            run_id=run.id,
            skill_path="/tmp/not-allowed/SKILL.md",
            proposal_id="draft-escape",
        )

    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_run_self_improver_draft",
        fake_self_improver,
    )

    run_payload = _create_self_improver_run(control_plane_client)
    resolve_response = control_plane_client.post(
        f"/api/approvals/proposals/{run_payload['id']}/draft-escape/resolve",
        json={"approve": True},
    )
    assert resolve_response.status_code == 200
    payload = resolve_response.json()
    assert payload["status"] == "apply_failed"
    assert "outside the allowed skills directory" in (payload.get("error") or "")


def test_proposal_apply_rolls_back_on_post_write_validation_failure(
    control_plane_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import src.control_plane.service as control_plane_service_module
    from src.config.app_config import get_app_config

    skill_path = (
        get_app_config().skills.get_skills_path()
        / "public"
        / "podcast-generation"
        / "SKILL.md"
    )
    before = skill_path.read_text(encoding="utf-8")

    def fake_self_improver(self, *, run, definition):
        return _self_improver_report(
            run_id=run.id,
            skill_path=str(skill_path),
            proposal_id="draft-rollback",
            addition="## Rollback test",
        )

    original_validate = control_plane_service_module.ControlPlaneService._validate_skill_markdown
    call_counter = {"count": 0}

    def flaky_validate(self, content):
        call_counter["count"] += 1
        if call_counter["count"] >= 2:
            return {
                "frontmatter_ok": False,
                "parse_ok": False,
                "issues": ["forced post-write validation failure"],
            }
        return original_validate(self, content)

    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_run_self_improver_draft",
        fake_self_improver,
    )
    monkeypatch.setattr(
        control_plane_service_module.ControlPlaneService,
        "_validate_skill_markdown",
        flaky_validate,
    )

    run_payload = _create_self_improver_run(control_plane_client)
    resolve_response = control_plane_client.post(
        f"/api/approvals/proposals/{run_payload['id']}/draft-rollback/resolve",
        json={"approve": True},
    )
    assert resolve_response.status_code == 200
    payload = resolve_response.json()
    assert payload["status"] == "apply_failed"
    assert "rolled back" in (payload.get("error") or "")
    assert skill_path.read_text(encoding="utf-8") == before


def test_vault_ingest_endpoints_idle_then_start(control_plane_client: TestClient):
    initial = control_plane_client.get("/api/vault/ingest/status")
    assert initial.status_code == 200
    initial_payload = initial.json()
    assert initial_payload["status"] == "idle"
    assert initial_payload["processed"] == 0

    start_response = control_plane_client.post(
        "/api/vault/ingest/start",
        json={"force_reanalyze": False},
    )
    assert start_response.status_code == 200
    started_payload = start_response.json()
    assert started_payload["status"] in {"running", "success"}
    assert started_payload["job_id"]
    assert started_payload["log_path"].endswith("vault_ingest.log")
    assert started_payload["accepted"] is True

    # Wait briefly for the background thread to drain (zero sources → finishes fast).
    import time

    deadline = time.monotonic() + 5.0
    final_payload = started_payload
    while time.monotonic() < deadline:
        status_response = control_plane_client.get("/api/vault/ingest/status")
        assert status_response.status_code == 200
        final_payload = status_response.json()
        if final_payload["status"] in {"success", "failed", "idle"}:
            break
        time.sleep(0.05)
    assert final_payload["status"] in {"success", "failed", "idle"}
    if final_payload["status"] == "success":
        assert final_payload["total"] == 0


def test_vault_ingest_start_rejects_when_already_running(control_plane_client: TestClient, monkeypatch):
    import src.gateway.routers.vault as vault_router_module

    service = vault_router_module.get_control_plane_service()
    # Force the job to look running so the next start call is rejected.
    with service._vault_ingest_lock:  # noqa: SLF001
        service._vault_ingest_job.update(  # noqa: SLF001
            {"status": "running", "job_id": "preexisting-job"}
        )
    try:
        response = control_plane_client.post(
            "/api/vault/ingest/start",
            json={"force_reanalyze": False},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["accepted"] is False
        assert "already running" in (payload["message"] or "").lower()
    finally:
        with service._vault_ingest_lock:  # noqa: SLF001
            service._vault_ingest_job = service._new_vault_ingest_job_state()  # noqa: SLF001
