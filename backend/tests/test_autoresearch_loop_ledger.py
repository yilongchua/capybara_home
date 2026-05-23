"""Unit tests for the autoresearch question ledger."""

from __future__ import annotations

import json
from pathlib import Path

from src.control_plane.autoresearch_loop.ledger import QuestionLedger


def _ledger(tmp_path: Path) -> QuestionLedger:
    return QuestionLedger(vault_root=tmp_path, objective_slug="obj-soba")


def test_load_returns_empty_state_when_no_file(tmp_path: Path) -> None:
    state = _ledger(tmp_path).load()
    assert state["questions"] == []
    assert state["iterations"] == []
    assert state["loop_iteration"] == 0


def test_append_questions_assigns_unique_ids_and_persists(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    added = ledger.append_questions(
        items=[
            {"content": "What is soba?", "cluster": 1, "level": 1},
            {"content": "What is soba?", "cluster": 1, "level": 1},  # duplicate text
        ],
        loop_iteration=1,
        topic="Soba",
        endpoint_goal="Expand coverage of Soba.",
    )
    assert len(added) == 2
    assert added[0]["id"] != added[1]["id"], "duplicate text must still get a unique id suffix"
    assert added[0]["loop_iteration"] == 1

    on_disk = json.loads(ledger.json_path.read_text(encoding="utf-8"))
    assert on_disk["loop_iteration"] == 1
    assert len(on_disk["questions"]) == 2


def test_append_writes_markdown_view(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.append_questions(
        items=[{"content": "How is soba made?", "cluster": 3, "level": 1}],
        loop_iteration=1,
        topic="Soba",
        endpoint_goal="Expand coverage of Soba.",
    )
    md = ledger.md_path.read_text(encoding="utf-8")
    assert "How is soba made?" in md
    assert "C3L1" in md
    assert "Expand coverage of Soba" in md


def test_update_question_modifies_status_and_returns_node(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    [node] = ledger.append_questions(
        items=[{"content": "What is soba?", "cluster": 1, "level": 1}],
        loop_iteration=1,
    )
    updated = ledger.update_question(
        node["id"],
        status="answered",
        vault_entries=["soba-101"],
        researcher_summary="A buckwheat noodle from Japan.",
    )
    assert updated is not None
    assert updated["status"] == "answered"
    assert updated["vault_entries"] == ["soba-101"]
    assert "buckwheat" in updated["researcher_summary"]


def test_update_question_returns_none_for_missing_id(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    assert ledger.update_question("does-not-exist", status="answered") is None


def test_cluster_coverage_returns_deepest_answered_level_per_cluster(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    items = [
        {"content": "Cluster 1 L1", "cluster": 1, "level": 1},
        {"content": "Cluster 1 L2", "cluster": 1, "level": 2},
        {"content": "Cluster 2 L1 unanswered", "cluster": 2, "level": 1},
        {"content": "Cluster 3 L3", "cluster": 3, "level": 3},
    ]
    added = ledger.append_questions(items=items, loop_iteration=1)
    # Answer C1L1, C1L2, C3L3 only; leave C2L1 pending.
    for node, expected in zip(added, ["answered", "answered", "pending", "answered"], strict=True):
        if expected == "answered":
            ledger.update_question(node["id"], status="answered")
    coverage = ledger.cluster_coverage()
    assert coverage == {1: 2, 3: 3}  # cluster 2 not in dict (no answered questions)


def test_recent_questions_returns_chronological_tail(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    for idx in range(5):
        ledger.append_questions(
            items=[{"content": f"Question {idx}", "cluster": 1, "level": 1}],
            loop_iteration=idx + 1,
        )
    recent = ledger.recent_questions(limit=3)
    assert [n["content"] for n in recent] == ["Question 2", "Question 3", "Question 4"]


def test_record_iteration_appends_to_iterations_log(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.record_iteration(
        loop_iteration=1,
        summary={"generated": 3, "answered": 2, "novelty_rate": 0.66},
    )
    state = ledger.load()
    assert len(state["iterations"]) == 1
    entry = state["iterations"][0]
    assert entry["iteration"] == 1
    assert entry["generated"] == 3
    assert entry["novelty_rate"] == 0.66
    assert "at" in entry


def test_objective_slug_is_sanitised_into_directory_name(tmp_path: Path) -> None:
    ledger = QuestionLedger(vault_root=tmp_path, objective_slug="Obj: Crazy/Path?? Soba!")
    ledger.append_questions(
        items=[{"content": "What is soba?", "cluster": 1, "level": 1}],
        loop_iteration=1,
    )
    # The directory must exist and contain ledger.json — i.e. slugification did
    # not produce an invalid filesystem path.
    assert ledger.json_path.exists()
    assert ledger.md_path.exists()
