from __future__ import annotations

import json
from pathlib import Path

from src.control_plane.vault_learning import VaultLearningManager
from src.control_plane.vault_learning._canonical_similarity import (
    DEFAULT_THRESHOLDS,
    MergeThresholds,
    SurfaceForm,
    initialism_of,
    is_abbreviation_candidate,
    is_abbreviation_of,
    lexical_similarity,
    propose_merges,
)


def test_lexical_collapses_jp_morgan_variants() -> None:
    assert lexical_similarity("JP Morgan", "J.P. Morgan") >= 0.95
    assert lexical_similarity("JPMorgan Chase", "JPMorgan Chase & Co") >= 0.9
    assert lexical_similarity("JPMorgan", "Goldman Sachs") < 0.5


def test_abbreviation_detection_for_sg_and_singapore() -> None:
    assert is_abbreviation_candidate("SG")
    assert is_abbreviation_candidate("sgp")
    assert is_abbreviation_of("SG", "Singapore")
    assert is_abbreviation_of("sgp", "Singapore")
    assert is_abbreviation_of("MAS", "Monetary Authority of Singapore")
    assert not is_abbreviation_of("Singapore", "Vietnam")


def test_initialism_of_skips_stopwords() -> None:
    assert initialism_of("Monetary Authority of Singapore") == "mas"
    assert initialism_of("Singapore") == ""


def test_propose_merges_auto_applies_lexical_high_match() -> None:
    surfaces = {
        "jp-morgan": SurfaceForm(slug="jp-morgan", label="JP Morgan", kind="entity", sources={"s1", "s2"}),
        "j-p-morgan": SurfaceForm(slug="j-p-morgan", label="J.P. Morgan", kind="entity", sources={"s2", "s3"}),
    }
    candidates = propose_merges(surfaces)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.action == "auto"
    assert {c.canonical_slug, c.alias_slug} == {"jp-morgan", "j-p-morgan"}


def test_propose_merges_requires_cooccurrence_for_abbreviation() -> None:
    same_source = {
        "sg": SurfaceForm(slug="sg", label="SG", kind="entity", sources={"s1", "s2"}),
        "singapore": SurfaceForm(slug="singapore", label="Singapore", kind="entity", sources={"s1", "s2", "s3"}),
    }
    candidates = propose_merges(same_source)
    assert len(candidates) == 1
    assert candidates[0].action == "auto"
    assert candidates[0].canonical_slug == "singapore"
    assert candidates[0].alias_slug == "sg"

    disjoint = {
        "sg": SurfaceForm(slug="sg", label="SG", kind="entity", sources={"s9"}),
        "singapore": SurfaceForm(slug="singapore", label="Singapore", kind="entity", sources={"s1", "s2"}),
    }
    candidates = propose_merges(disjoint)
    assert len(candidates) == 1
    assert candidates[0].action == "review"


def test_propose_merges_respects_domain_disambiguation() -> None:
    surfaces = {
        "apple-org": SurfaceForm(
            slug="apple-org",
            label="Apple",
            kind="entity",
            sources={"s1", "s2", "s3"},
            domain_counts={"finance": 3, "technology": 1},
        ),
        "apple-fruit": SurfaceForm(
            slug="apple-fruit",
            label="Apple",
            kind="entity",
            sources={"s4", "s5"},
            domain_counts={"food": 2},
        ),
    }
    candidates = propose_merges(surfaces)
    assert not candidates, "cross-domain merge should be rejected"


def test_canonical_table_round_trip(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path)
    vault.record_canonical_merge(
        canonical_slug="jpmorgan-chase",
        alias_slug="jp-morgan",
        kind="entity",
        canonical_label="JPMorgan Chase",
        alias_label="JP Morgan",
        domain_hint="finance",
        confidence=0.95,
        signals={"lexical": 0.96, "abbreviation": False, "cooccurrence": 0.7},
        evidence_sources=["src-1", "src-2"],
        source_kind="lexical",
    )

    assert vault.resolve_canonical_slug("JP Morgan", kind="entity") == "jpmorgan-chase"
    assert vault.resolve_canonical_slug("JPMorgan Chase", kind="entity") == "jpmorgan-chase"
    assert vault.resolve_canonical_slug("Unrelated", kind="entity") == "unrelated"

    canonical_map = vault.canonical_alias_map(kind="entity")
    assert canonical_map["jp-morgan"] == "jpmorgan-chase"
    assert canonical_map["jpmorgan-chase"] == "jpmorgan-chase"

    raw = json.loads(vault.canonical_path.read_text())
    assert raw["version"].startswith("vault-canonical.")
    assert "jpmorgan-chase" in raw["entries"]


def test_canonical_review_workflow(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path)
    vault.queue_canonical_review(
        canonical_slug="singapore",
        alias_slug="sgp",
        kind="entity",
        canonical_label="Singapore",
        alias_label="sgp",
        signals={"abbreviation": True, "cooccurrence": 0.3},
        confidence=0.65,
        evidence_sources=["src-1"],
    )
    pending = vault.list_canonical_pending_review(kind="entity")
    assert len(pending) == 1
    assert pending[0]["alias_slug"] == "sgp"

    vault.resolve_canonical_review(canonical_slug="singapore", alias_slug="sgp", approve=True)
    assert vault.resolve_canonical_slug("sgp", kind="entity") == "singapore"
    assert not vault.list_canonical_pending_review(kind="entity")


def test_split_canonical_alias_removes_mapping(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path)
    vault.record_canonical_merge(
        canonical_slug="singapore",
        alias_slug="sgp",
        kind="entity",
        canonical_label="Singapore",
    )
    assert vault.resolve_canonical_slug("sgp", kind="entity") == "singapore"
    assert vault.split_canonical_alias(canonical_slug="singapore", alias_slug="sgp") is True
    assert vault.resolve_canonical_slug("sgp", kind="entity") == "sgp"


def test_thresholds_default_matches_app_config() -> None:
    from src.config.control_plane_config import CanonicalThresholdsConfig

    cfg = CanonicalThresholdsConfig()
    assert cfg.auto_lexical_strong == DEFAULT_THRESHOLDS.auto_lexical_strong
    assert cfg.auto_lexical_high == DEFAULT_THRESHOLDS.auto_lexical_high
    assert cfg.auto_lexical_high_cooc == DEFAULT_THRESHOLDS.auto_lexical_high_cooc
    assert cfg.auto_abbreviation_cooc == DEFAULT_THRESHOLDS.auto_abbreviation_cooc
    assert cfg.auto_lexical_mid == DEFAULT_THRESHOLDS.auto_lexical_mid
    assert cfg.auto_lexical_mid_cooc == DEFAULT_THRESHOLDS.auto_lexical_mid_cooc
    assert cfg.review_abbreviation_cooc == DEFAULT_THRESHOLDS.review_abbreviation_cooc
    assert cfg.review_cooc_strong == DEFAULT_THRESHOLDS.review_cooc_strong
    assert cfg.review_lexical == DEFAULT_THRESHOLDS.review_lexical
    assert cfg.review_abbreviation_alone == DEFAULT_THRESHOLDS.review_abbreviation_alone


def test_thresholds_override_changes_action() -> None:
    surfaces = {
        "sg": SurfaceForm(slug="sg", label="SG", kind="entity", sources={"s1", "s2"}),
        "singapore": SurfaceForm(slug="singapore", label="Singapore", kind="entity", sources={"s1", "s2", "s3"}),
    }
    # Default thresholds: same source + abbreviation + cooc>=0.3 → auto
    default = propose_merges(surfaces)
    assert default[0].action == "auto"

    # Raise the abbreviation cooc bar above the actual co-occurrence (~0.67).
    strict = MergeThresholds(auto_abbreviation_cooc=0.95, auto_lexical_mid_cooc=0.99)
    strict_out = propose_merges(surfaces, thresholds=strict)
    assert strict_out[0].action == "review"


def test_thresholds_disable_abbreviation_alone() -> None:
    surfaces = {
        "sg": SurfaceForm(slug="sg", label="SG", kind="entity", sources={"s9"}),
        "singapore": SurfaceForm(slug="singapore", label="Singapore", kind="entity", sources={"s1"}),
    }
    assert propose_merges(surfaces)[0].action == "review"
    off = MergeThresholds(review_abbreviation_alone=False)
    assert not propose_merges(surfaces, thresholds=off)


def test_lint_canonical_aliases_runs_against_manifest(tmp_path: Path) -> None:
    vault = VaultLearningManager(vault_root=tmp_path)
    vault._manifest["sources"] = {
        "src-1": {
            "title": "JPM article 1",
            "entity_refs": ["JP Morgan", "Singapore"],
            "concept_refs": ["large language model"],
            "topic_tags": ["finance"],
        },
        "src-2": {
            "title": "JPM article 2",
            "entity_refs": ["J.P. Morgan", "SG"],
            "concept_refs": ["LLM"],
            "topic_tags": ["finance"],
        },
        "src-3": {
            "title": "Singapore profile",
            "entity_refs": ["Singapore", "SG"],
            "concept_refs": ["large language model"],
            "topic_tags": ["singapore"],
        },
    }

    report = vault.lint_canonical_aliases(dry_run=False)
    assert report["surface_counts"]["entities"] >= 3
    assert report["surface_counts"]["concepts"] >= 1
    auto_pairs = {(item["canonical_slug"], item["alias_slug"]) for item in report["auto_applied"]}
    assert any({"jp-morgan", "j-p-morgan"} == set(pair) for pair in auto_pairs)
    assert any({"singapore", "sg"} == set(pair) for pair in auto_pairs)

    browser = vault.get_entity_browser(top_n=5, bottom_n=5)
    slugs_after = {entry["slug"] for entry in browser["top"]}
    assert "jp-morgan" not in slugs_after or "j-p-morgan" not in slugs_after
    assert browser["counts"]["canonical_merges"] >= 1
