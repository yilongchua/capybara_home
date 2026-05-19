"""Tests for versioned memory store and redaction."""

from pathlib import Path

import pytest

from src.agents.memory.store import get_memory_version, list_memory_versions, persist_memory_data, redact_memory
from src.agents.memory.vector_store import MemoryVectorStore
from src.config.memory_config import MemoryConfig, set_memory_config
from src.config.memory_versioning_config import MemoryVersioningConfig, set_memory_versioning_config
from src.config.paths import Paths


@pytest.fixture(autouse=True)
def _configure_memory(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("src.agents.memory.store.get_paths", lambda: Paths(base_dir=tmp_path))
    set_memory_config(MemoryConfig(enabled=True, storage_path="memory.json"))
    set_memory_versioning_config(MemoryVersioningConfig(enabled=True, storage_dir=".capybara-home/memory_versions", require_expected_sha=False))
    yield


def _memory_payload(content: str) -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "",
        "user": {
            "workContext": {"summary": content, "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [{"id": "fact-1", "content": content, "category": "context", "confidence": 0.9, "createdAt": "", "source": "thread-1"}],
    }


def test_persist_memory_creates_versions_and_honors_expected_sha():
    first = persist_memory_data(_memory_payload("alpha"), source_thread="thread-1")
    assert first["version_id"] is not None
    second = persist_memory_data(_memory_payload("beta"), expected_sha=first["sha"], source_thread="thread-1")
    assert second["version_id"] is not None

    versions = list_memory_versions(limit=10)
    assert len(versions) >= 2
    assert versions[0]["operation"] in {"update", "redact"}

    with pytest.raises(ValueError, match="expected_sha"):
        persist_memory_data(_memory_payload("gamma"), expected_sha="bad-sha", source_thread="thread-1")


def test_redact_memory_creates_new_version_and_tracks_audit():
    first = persist_memory_data(_memory_payload("secret@example.com"), source_thread="thread-1")
    result = redact_memory(
        agent_name=None,
        fact_ids=["fact-1"],
        pattern=None,
        reason="cleanup",
        actor="tester",
        expected_sha=first["sha"],
    )
    ref = result["ref"]
    assert ref["version_id"] is not None
    version = get_memory_version(ref["version_id"])
    assert version is not None
    assert version["operation"] == "redact"
    assert version["audit"]["reason"] == "cleanup"
    assert "fact-1" in version["audit"]["affected_fact_ids"]


def test_redact_memory_removes_fact_from_vector_store(tmp_path: Path, monkeypatch):
    vector_store = MemoryVectorStore(tmp_path / "memory.db")
    monkeypatch.setattr("src.agents.memory.store.get_memory_vector_store", lambda: vector_store)
    vector_store.upsert_facts(scope="global", scope_id="global", facts=_memory_payload("secret@example.com")["facts"])
    first = persist_memory_data(_memory_payload("secret@example.com"), source_thread="thread-1")

    redact_memory(
        agent_name=None,
        fact_ids=["fact-1"],
        pattern=None,
        reason="cleanup",
        actor="tester",
        expected_sha=first["sha"],
    )

    assert vector_store.query(query="secret@example.com", scopes=[("global", "global")], top_k=5) == []
