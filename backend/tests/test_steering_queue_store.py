"""Tests for durable steering queue store."""

from __future__ import annotations

from src.agents.steering_queue_store import (
    claim_next_steering_intent,
    enqueue_steering_intent,
    list_pending_steering_intents,
    reset_steering_queue_store_for_tests,
)


def test_enqueue_duplicate_and_conflict(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPYBARA_HOME", str(tmp_path))
    reset_steering_queue_store_for_tests()

    first = enqueue_steering_intent(thread_id="thread-1", intent_id="intent-1", message="Focus on UX")
    assert first["status"] == "accepted"

    duplicate = enqueue_steering_intent(thread_id="thread-1", intent_id="intent-1", message="Focus on UX")
    assert duplicate["status"] == "duplicate"

    conflict = enqueue_steering_intent(thread_id="thread-1", intent_id="intent-1", message="Different")
    assert conflict["status"] == "conflict"


def test_claim_is_exactly_once(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPYBARA_HOME", str(tmp_path))
    reset_steering_queue_store_for_tests()

    enqueue_steering_intent(thread_id="thread-1", intent_id="intent-1", message="First")
    enqueue_steering_intent(thread_id="thread-1", intent_id="intent-2", message="Second")

    claimed_1 = claim_next_steering_intent("thread-1")
    claimed_2 = claim_next_steering_intent("thread-1")
    claimed_3 = claim_next_steering_intent("thread-1")

    assert claimed_1 is not None and claimed_1["intent_id"] == "intent-1"
    assert claimed_2 is not None and claimed_2["intent_id"] == "intent-2"
    assert claimed_3 is None


def test_pending_list_reflects_unclaimed_items(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPYBARA_HOME", str(tmp_path))
    reset_steering_queue_store_for_tests()

    enqueue_steering_intent(thread_id="thread-1", intent_id="intent-1", message="First")
    enqueue_steering_intent(thread_id="thread-1", intent_id="intent-2", message="Second")
    _ = claim_next_steering_intent("thread-1")

    pending = list_pending_steering_intents("thread-1")
    assert [item["intent_id"] for item in pending] == ["intent-2"]
