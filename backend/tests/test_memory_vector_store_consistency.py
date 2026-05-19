"""Regression tests for memory mutation/vector index consistency."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from src.agents.memory import updater as updater_module
from src.agents.memory.updater import MemoryUpdater, clear_memory, forget_thread_facts
from src.agents.memory.vector_store import MemoryVectorStore
from src.config.memory_config import MemoryConfig, set_memory_config
from src.config.paths import Paths


@pytest.fixture(autouse=True)
def _configure_memory(tmp_path: Path, monkeypatch):
    paths = Paths(base_dir=tmp_path)
    vector_store = MemoryVectorStore(tmp_path / "memory.db")
    monkeypatch.setattr("src.agents.memory.updater.get_paths", lambda: paths)
    monkeypatch.setattr("src.agents.memory.store.get_paths", lambda: paths)
    monkeypatch.setattr("src.agents.memory.updater.get_memory_vector_store", lambda: vector_store)
    set_memory_config(MemoryConfig(enabled=True, storage_path="memory.json"))
    updater_module._memory_cache.clear()
    yield vector_store
    updater_module._memory_cache.clear()


def _memory_payload() -> dict:
    return {
        "version": "2.0",
        "scope": "global",
        "scopeId": "global",
        "facts": [
            {"id": "fact-thread", "content": "Thread-only alpaca fact", "category": "context", "confidence": 0.9, "source": "thread-1"},
            {"id": "fact-keep", "content": "Shared capybara fact", "category": "context", "confidence": 0.9, "source": "thread-2"},
        ],
        "behaviorRules": [],
    }


def test_forget_thread_facts_removes_deleted_ids_from_vector_store(_configure_memory: MemoryVectorStore):
    vector_store = _configure_memory
    memory = _memory_payload()
    updater_module._save_memory_to_file(memory, scope="global")
    vector_store.upsert_facts(scope="global", scope_id="global", facts=memory["facts"])

    removed = forget_thread_facts("thread-1", scope="global")

    assert removed == 1
    remaining_ids = [fact["id"] for fact in vector_store.query(query="alpaca", scopes=[("global", "global")], top_k=5)]
    assert "fact-thread" not in remaining_ids
    kept = vector_store.query(query="capybara", scopes=[("global", "global")], top_k=5)
    assert [fact["id"] for fact in kept] == ["fact-keep"]


def test_clear_memory_removes_all_scope_vectors(_configure_memory: MemoryVectorStore):
    vector_store = _configure_memory
    memory = _memory_payload()
    updater_module._save_memory_to_file(memory, scope="global")
    vector_store.upsert_facts(scope="global", scope_id="global", facts=memory["facts"])

    clear_memory(scope="global")

    assert vector_store.query(query="capybara", scopes=[("global", "global")], top_k=5) == []


def test_llm_removed_facts_are_deleted_from_vector_store(_configure_memory: MemoryVectorStore, monkeypatch):
    vector_store = _configure_memory
    memory = _memory_payload()
    updater_module._save_memory_to_file(memory, scope="global")
    vector_store.upsert_facts(scope="global", scope_id="global", facts=memory["facts"])

    monkeypatch.setattr(
        MemoryUpdater,
        "_get_model",
        lambda self: SimpleNamespace(
            invoke=lambda _prompt: SimpleNamespace(
                content='{"user": {}, "history": {}, "newFacts": [], "factsToRemove": ["fact-thread"]}'
            )
        ),
    )

    ok = MemoryUpdater().update_memory([HumanMessage(content="Forget the alpaca detail.")], thread_id="thread-1", scope="global")

    assert ok is True
    remaining_ids = [fact["id"] for fact in vector_store.query(query="alpaca", scopes=[("global", "global")], top_k=5)]
    assert "fact-thread" not in remaining_ids
    assert [fact["id"] for fact in vector_store.query(query="capybara", scopes=[("global", "global")], top_k=5)] == ["fact-keep"]


def test_max_facts_eviction_deletes_vector_rows(_configure_memory: MemoryVectorStore, monkeypatch):
    vector_store = _configure_memory
    set_memory_config(MemoryConfig(enabled=True, storage_path="memory.json", max_facts=10))
    memory = _memory_payload()
    memory["facts"] = [
        {"id": "fact-evict", "content": "Evicted walrus fact", "category": "context", "confidence": 0.1, "source": "thread-1"},
        *[
            {"id": f"fact-keep-{idx}", "content": f"High confidence capybara fact {idx}", "category": "context", "confidence": 0.9, "source": "thread-1"}
            for idx in range(10)
        ],
    ]
    updater_module._save_memory_to_file(memory, scope="global")
    vector_store.upsert_facts(scope="global", scope_id="global", facts=memory["facts"])

    monkeypatch.setattr(
        MemoryUpdater,
        "_get_model",
        lambda self: SimpleNamespace(
            invoke=lambda _prompt: SimpleNamespace(
                content='{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
            )
        ),
    )

    ok = MemoryUpdater().update_memory([HumanMessage(content="Keep only the strongest memory.")], thread_id="thread-1", scope="global")

    assert ok is True
    remaining_ids = [fact["id"] for fact in vector_store.query(query="walrus", scopes=[("global", "global")], top_k=20)]
    assert "fact-evict" not in remaining_ids
