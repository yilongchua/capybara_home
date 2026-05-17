from __future__ import annotations

from pathlib import Path

import httpx

from src.control_plane.vault_learning import VaultLearningManager


def test_discover_writes_inbox_and_filters_urls(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path, allowed_domains=["example.com"])
    report = vault.discover(
        urls=[
            "https://example.com/post-1",
            "ftp://example.com/bad",
            "https://not-allowed.com/post-2",
            "https://example.com/post-1",
        ],
        source="test",
    )

    assert report["candidate_count"] == 1
    assert report["rejected_count"] == 2
    assert Path(report["inbox_path"]).exists()


def test_ingest_creates_raw_and_compiled_layout(tmp_path: Path, monkeypatch) -> None:
    class _MockResponse:
        def __init__(self) -> None:
            self.text = (
                "<html><head><title>Test Article</title></head>"
                "<body><main><p>Hello Capybara Home Vault. Maritime data quality improves.</p></main></body></html>"
            )

        def raise_for_status(self) -> None:
            return None

    def _fake_get(*args, **kwargs):  # noqa: ANN002, ANN003
        return _MockResponse()

    monkeypatch.setattr(httpx, "get", _fake_get)

    vault = VaultLearningManager(vault_root=tmp_path, min_trust_score=0.2)
    report = vault.ingest(
        urls=["https://example.com/test-article"],
        source="test",
        topic="maritime data quality",
    )

    assert report["ingested_count"] == 1
    assert (tmp_path / "00_schema" / "VAULT_SCHEMA.md").exists()
    assert list((tmp_path / "01_raw" / "sources").rglob("metadata.json"))
    assert list((tmp_path / "02_compiled" / "sources").glob("*.md"))
    assert (tmp_path / "02_compiled" / "index.md").exists()
    assert (tmp_path / "02_compiled" / "log.md").exists()
    assert list((tmp_path / "02_compiled" / "syntheses").glob("*.md"))


def test_query_retention_dedupes_for_72h(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path, query_retention_hours=72)
    first = vault.write_query_note(
        query_text="vessel particulars for maritime data quality",
        topic_tags=["maritime-data-quality"],
        content="first note",
    )
    second = vault.write_query_note(
        query_text="vessel particulars for maritime data quality",
        topic_tags=["maritime-data-quality"],
        content="second note",
    )

    assert first["status"] == "created"
    assert second["status"] == "deduped"
    assert len(list((tmp_path / "02_compiled" / "queries").glob("*.md"))) == 1


def test_search_results_queue_requires_extracted_content_and_dedupes(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path)
    report = vault.enqueue_search_results(
        query="maritime quality",
        results=[
            {
                "title": "A",
                "url": "https://example.com/a",
                "snippet": "AA",
                "extracted_content": "# A\n\nAlpha",
                "topic_tags": ["maritime-quality"],
                "concept_refs": ["vessel-particulars"],
            },
            {
                "title": "B",
                "url": "https://example.com/b",
                "snippet": "BB",
            },
            {
                "title": "A2",
                "url": "https://example.com/a",
                "snippet": "AA",
                "extracted_content": "# A\n\nAlpha",
                "topic_tags": ["maritime-quality"],
            },
        ],
    )

    assert report["appended_count"] == 1
    assert report["duplicate_count"] == 1
    assert report["skipped_count"] == 1
    queue_items = vault.claim_search_queue_items(topic="maritime-quality", max_items=5)
    assert len(queue_items) == 1
    assert queue_items[0]["status"] == "claimed"


def test_queue_ingest_uses_extracted_content_and_updates_queue(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path, min_trust_score=0.2)
    enqueue = vault.enqueue_search_results(
        query="vessel particulars",
        results=[
            {
                "title": "Marine Data Quality",
                "url": "https://example.com/vessel-quality",
                "snippet": "desc",
                "extracted_content": "# Marine Data Quality\n\nVessel particulars improve data quality baselines.",
                "topic_tags": ["maritime-data-quality"],
                "concept_refs": ["vessel-particulars"],
                "target_synthesis_refs": ["maritime-data-quality-vessel-particulars"],
            }
        ],
    )
    assert enqueue["appended_count"] == 1

    queue_items = vault.claim_search_queue_items(topic="maritime-data-quality", max_items=5)
    report = vault.ingest(urls=[], source="autoresearch", topic="maritime data quality", queue_items=queue_items)
    assert report["queue_items_claimed"] == 1
    assert report["ingested_count"] == 1

    lint = vault.lint_vault(freshness_window_days=30)
    assert "queue_backlog_count" in lint

    search = vault.search(query="vessel particulars", limit=5)
    assert search["total"] >= 1


def test_loop_guard_blocks_repeated_attempts(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path)
    first = vault.check_loop_guard(
        objective_id="obj-maritime",
        topic="maritime",
        query_text="maritime data quality",
        cooldown_hours=24,
        retry_budget=2,
    )
    second = vault.check_loop_guard(
        objective_id="obj-maritime",
        topic="maritime",
        query_text="maritime data quality",
        cooldown_hours=24,
        retry_budget=2,
    )
    assert first["allowed"] is True
    assert second["allowed"] is False
    assert second["reason"] in {"cooldown_active", "retry_budget_exhausted"}


def test_status_includes_memory_progress_and_action_items(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path)
    (tmp_path / "01_raw" / "sources" / "sample").mkdir(parents=True, exist_ok=True)
    (tmp_path / "01_raw" / "sources" / "sample" / "file.txt").write_text("abc", encoding="utf-8")
    summary = vault.get_run_summary()
    assert "memory" in summary
    assert "progress" in summary
    assert "action_items" in summary
    assert int(summary["memory"]["raw_bytes"]) >= 3


def test_reprocess_existing_sources_backfills_entities_and_concepts(
    tmp_path: Path, monkeypatch
) -> None:
    class _MockResponse:
        def __init__(self) -> None:
            self.text = (
                "<html><head><title>Quantum Compute Review</title></head>"
                "<body><main><p>Quantum hybrid architectures power scientific computing research today.</p></main></body></html>"
            )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _MockResponse())

    vault = VaultLearningManager(vault_root=tmp_path, min_trust_score=0.2)
    vault.ingest(
        urls=["https://example.com/quantum-review"],
        source="test",
        topic="quantum hybrid computing",
    )

    # Simulate older buggy records that left entity_refs/concept_refs empty.
    sources = vault._manifest["sources"]
    assert sources, "Ingest should have produced at least one source"
    for record in sources.values():
        record["entity_refs"] = []
        record["concept_refs"] = []
    vault._save_manifest()

    progress_events: list[tuple[int, int, str]] = []

    def _track(index, total, source_id, title, status, error):  # noqa: ANN001
        progress_events.append((index, total, status))

    report = vault.reprocess_existing_sources(progress_callback=_track)

    assert report["total"] >= 1
    assert report["processed"] >= 1
    assert progress_events, "Progress callback should fire at least once"
    refreshed = list(vault._manifest["sources"].values())[0]
    assert refreshed["concept_refs"], "Reprocess should backfill concept_refs"
    compiled_concepts = list((tmp_path / "02_compiled" / "concepts").glob("*.md"))
    assert any(path.name != "index.md" for path in compiled_concepts)


def test_reprocess_existing_sources_only_missing_skips_populated(tmp_path: Path, monkeypatch) -> None:
    class _MockResponse:
        def __init__(self) -> None:
            self.text = (
                "<html><head><title>Maritime Data</title></head>"
                "<body><main><p>Maritime quality programs continue to improve significantly.</p></main></body></html>"
            )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _MockResponse())

    vault = VaultLearningManager(vault_root=tmp_path, min_trust_score=0.2)
    vault.ingest(
        urls=["https://example.com/maritime"],
        source="test",
        topic="maritime data quality",
    )

    for record in vault._manifest["sources"].values():
        record["entity_refs"] = ["existing-entity"]
        record["concept_refs"] = ["existing-concept"]
    vault._save_manifest()

    report = vault.reprocess_existing_sources(only_missing=True)
    assert report["total"] == 0
    assert report["processed"] == 0
