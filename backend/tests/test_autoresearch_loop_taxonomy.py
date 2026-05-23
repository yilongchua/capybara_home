"""Unit tests for the autoresearch question taxonomy loader."""

from __future__ import annotations

import json
from pathlib import Path

from src.control_plane.autoresearch_loop.taxonomy import (
    DEFAULT_TAXONOMY,
    TAXONOMY_FILENAME,
    Cluster,
    load_taxonomy,
    seed_taxonomy_if_missing,
    taxonomy_path,
)


def test_seed_writes_default_when_missing(tmp_path: Path) -> None:
    seeded_path = seed_taxonomy_if_missing(tmp_path)
    assert seeded_path == taxonomy_path(tmp_path)
    assert seeded_path.exists()
    payload = json.loads(seeded_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    cluster_ids = {c["id"] for c in payload["clusters"]}
    assert cluster_ids == {c.id for c in DEFAULT_TAXONOMY}


def test_seed_is_idempotent_and_preserves_user_edits(tmp_path: Path) -> None:
    seeded = seed_taxonomy_if_missing(tmp_path)
    # User customises the file — seeding again must not overwrite.
    custom = {"version": 1, "clusters": [{"id": 99, "name": "Custom", "level_1": "L1", "level_2": "L2", "level_3": "L3"}]}
    seeded.write_text(json.dumps(custom), encoding="utf-8")
    re_seeded = seed_taxonomy_if_missing(tmp_path)
    assert re_seeded == seeded
    assert json.loads(re_seeded.read_text(encoding="utf-8"))["clusters"][0]["id"] == 99


def test_load_returns_full_default_taxonomy_when_file_missing(tmp_path: Path) -> None:
    taxonomy = load_taxonomy(tmp_path)
    assert len(taxonomy) == len(DEFAULT_TAXONOMY)
    assert {c.id for c in taxonomy} == {c.id for c in DEFAULT_TAXONOMY}
    assert all(isinstance(c, Cluster) for c in taxonomy)


def test_load_parses_user_edited_taxonomy(tmp_path: Path) -> None:
    target = tmp_path / "00_schema" / TAXONOMY_FILENAME
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "clusters": [
                    {
                        "id": 1,
                        "name": "Definition",
                        "description": "What is X?",
                        "level_1": "What is X?",
                        "level_2": "Types of X?",
                        "level_3": "Distinguishing X?",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    taxonomy = load_taxonomy(tmp_path)
    assert len(taxonomy) == 1
    assert taxonomy[0].id == 1
    assert taxonomy[0].name == "Definition"


def test_load_falls_back_to_default_on_malformed_json(tmp_path: Path) -> None:
    target = tmp_path / "00_schema" / TAXONOMY_FILENAME
    target.parent.mkdir(parents=True)
    target.write_text("{not valid json", encoding="utf-8")
    taxonomy = load_taxonomy(tmp_path)
    assert len(taxonomy) == len(DEFAULT_TAXONOMY)


def test_load_falls_back_to_default_on_empty_cluster_list(tmp_path: Path) -> None:
    target = tmp_path / "00_schema" / TAXONOMY_FILENAME
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"clusters": []}), encoding="utf-8")
    taxonomy = load_taxonomy(tmp_path)
    assert len(taxonomy) == len(DEFAULT_TAXONOMY)


def test_load_skips_malformed_cluster_entries_but_keeps_valid_ones(tmp_path: Path) -> None:
    target = tmp_path / "00_schema" / TAXONOMY_FILENAME
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "clusters": [
                    {"id": 1, "name": "Good", "level_1": "L1", "level_2": "L2", "level_3": "L3"},
                    "not even a dict",
                    {"name": "missing id"},  # no id → skip
                    {"id": 2, "name": "Also good", "level_1": "L1", "level_2": "L2", "level_3": "L3"},
                ]
            }
        ),
        encoding="utf-8",
    )
    taxonomy = load_taxonomy(tmp_path)
    assert [c.id for c in taxonomy] == [1, 2]
