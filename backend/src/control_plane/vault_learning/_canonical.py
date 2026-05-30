"""Canonical entity/concept registry.

Maintains ``02_compiled/_canonical.json`` — a table of canonical slugs and
the surface forms (aliases) that merge into them. Used to collapse
``JP Morgan`` / ``J.P. Morgan`` / ``JPM`` into one entity, and ``Singapore`` /
``SG`` / ``sgp`` into one. Storage is intentionally separate from
``manifest.json`` because the canonical table is rewritten by lint runs
while the manifest is updated by every ingest — different lifecycles.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.control_plane.vault_text_utils import (
    slugify as _slugify,
)
from src.control_plane.vault_text_utils import (
    utcnow as _utcnow,
)
from src.control_plane.vault_text_utils import (
    utcnow_iso as _utcnow_iso,
)

from ._canonical_similarity import (
    DEFAULT_THRESHOLDS,
    MergeCandidate,
    MergeThresholds,
    SurfaceForm,
    propose_merges,
)

logger = logging.getLogger(__name__)

CANONICAL_VERSION = "vault-canonical.v1"
_VALID_KINDS = {"entity", "concept"}


class CanonicalMixin:
    @property
    def canonical_path(self):
        return self.compiled_dir / "_canonical.json"

    @staticmethod
    def _empty_canonical() -> dict[str, Any]:
        return {
            "version": CANONICAL_VERSION,
            "updated_at": _utcnow_iso(),
            "entries": {},
            "pending_review": [],
        }

    def _load_canonical(self) -> dict[str, Any]:
        path = self.canonical_path
        if not path.exists():
            return self._empty_canonical()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("vault_canonical_load_failed")
            return self._empty_canonical()
        if not isinstance(data, dict):
            return self._empty_canonical()
        entries = data.get("entries")
        pending = data.get("pending_review")
        return {
            "version": str(data.get("version") or CANONICAL_VERSION),
            "updated_at": str(data.get("updated_at") or _utcnow_iso()),
            "entries": entries if isinstance(entries, dict) else {},
            "pending_review": pending if isinstance(pending, list) else [],
        }

    def _save_canonical(self, table: dict[str, Any]) -> None:
        table["updated_at"] = _utcnow_iso()
        self.canonical_path.parent.mkdir(parents=True, exist_ok=True)
        self.canonical_path.write_text(
            json.dumps(table, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def canonical_alias_map(self, *, kind: str) -> dict[str, str]:
        """Return ``{alias_slug: canonical_slug}`` for the given kind.

        The canonical slug itself maps to itself so callers can do a single
        dict lookup without a fallback branch.
        """
        if kind not in _VALID_KINDS:
            raise ValueError(f"Invalid canonical kind: {kind!r}")
        table = self._load_canonical()
        mapping: dict[str, str] = {}
        for canonical_slug, entry in (table.get("entries") or {}).items():
            if not isinstance(entry, dict) or entry.get("kind") != kind:
                continue
            mapping[canonical_slug] = canonical_slug
            for alias_slug in (entry.get("aliases") or {}):
                mapping[str(alias_slug)] = canonical_slug
        return mapping

    def resolve_canonical_slug(
        self,
        raw_label: str,
        *,
        kind: str = "entity",
        domain_hint: str | None = None,
    ) -> str:
        slug = _slugify(str(raw_label or ""))
        if not slug:
            return slug
        if kind not in _VALID_KINDS:
            return slug
        table = self._load_canonical()
        entries = table.get("entries") or {}
        entry = entries.get(slug)
        if isinstance(entry, dict) and entry.get("kind") == kind:
            entry_domain = entry.get("domain_hint")
            if not domain_hint or not entry_domain or entry_domain == domain_hint:
                return slug
        for canonical_slug, payload in entries.items():
            if not isinstance(payload, dict) or payload.get("kind") != kind:
                continue
            if slug not in (payload.get("aliases") or {}):
                continue
            payload_domain = payload.get("domain_hint")
            if domain_hint and payload_domain and payload_domain != domain_hint:
                continue
            return canonical_slug
        return slug

    def record_canonical_merge(
        self,
        *,
        canonical_slug: str,
        alias_slug: str,
        kind: str,
        canonical_label: str = "",
        alias_label: str = "",
        domain_hint: str | None = None,
        confidence: float = 1.0,
        signals: dict[str, Any] | None = None,
        evidence_sources: list[str] | None = None,
        reviewed: bool = False,
        source_kind: str = "lexical",
    ) -> dict[str, Any]:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Invalid canonical kind: {kind!r}")
        canonical_slug = _slugify(canonical_slug)
        alias_slug = _slugify(alias_slug)
        if not canonical_slug or not alias_slug:
            raise ValueError("Both canonical_slug and alias_slug are required.")
        if canonical_slug == alias_slug:
            raise ValueError("Alias slug cannot equal canonical slug.")

        table = self._load_canonical()
        entries = table.setdefault("entries", {})
        now = _utcnow_iso()
        entry = entries.get(canonical_slug)
        if not isinstance(entry, dict):
            entry = {
                "kind": kind,
                "canonical_label": canonical_label or canonical_slug.replace("-", " ").title(),
                "domain_hint": domain_hint,
                "aliases": {},
                "confidence": float(confidence),
                "evidence_sources": list(evidence_sources or []),
                "reviewed": bool(reviewed),
                "merged_at": now,
                "merge_reasons": [],
            }
            entries[canonical_slug] = entry
        else:
            if canonical_label and len(canonical_label) > len(str(entry.get("canonical_label") or "")):
                entry["canonical_label"] = canonical_label
            if domain_hint and not entry.get("domain_hint"):
                entry["domain_hint"] = domain_hint
            if reviewed:
                entry["reviewed"] = True

        aliases = entry.setdefault("aliases", {})
        aliases[alias_slug] = {
            "source": source_kind,
            "added_at": now,
            "label": alias_label or alias_slug,
            "signals": signals or {},
        }
        evidence = set(entry.get("evidence_sources") or [])
        evidence.update(evidence_sources or [])
        entry["evidence_sources"] = sorted(evidence)
        if signals:
            reasons = entry.setdefault("merge_reasons", [])
            reasons.append({"alias": alias_slug, "signals": signals, "at": now})

        table["pending_review"] = [
            item
            for item in (table.get("pending_review") or [])
            if not (
                isinstance(item, dict)
                and item.get("alias_slug") == alias_slug
                and item.get("canonical_slug") == canonical_slug
            )
        ]
        self._save_canonical(table)
        return entry

    def queue_canonical_review(
        self,
        *,
        canonical_slug: str,
        alias_slug: str,
        kind: str,
        canonical_label: str = "",
        alias_label: str = "",
        signals: dict[str, Any] | None = None,
        confidence: float = 0.0,
        evidence_sources: list[str] | None = None,
    ) -> None:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Invalid canonical kind: {kind!r}")
        canonical_slug = _slugify(canonical_slug)
        alias_slug = _slugify(alias_slug)
        if not canonical_slug or not alias_slug or canonical_slug == alias_slug:
            return
        table = self._load_canonical()
        existing = (table.get("entries") or {}).get(canonical_slug)
        if isinstance(existing, dict) and alias_slug in (existing.get("aliases") or {}):
            return
        pending = [
            item
            for item in (table.get("pending_review") or [])
            if not (
                isinstance(item, dict)
                and item.get("alias_slug") == alias_slug
                and item.get("canonical_slug") == canonical_slug
            )
        ]
        pending.append(
            {
                "canonical_slug": canonical_slug,
                "alias_slug": alias_slug,
                "kind": kind,
                "labels": {
                    "canonical": canonical_label or canonical_slug,
                    "alias": alias_label or alias_slug,
                },
                "signals": signals or {},
                "confidence": float(confidence),
                "evidence_sources": list(evidence_sources or []),
                "proposed_at": _utcnow_iso(),
            }
        )
        table["pending_review"] = pending
        self._save_canonical(table)

    def split_canonical_alias(self, *, canonical_slug: str, alias_slug: str) -> bool:
        canonical_slug = _slugify(canonical_slug)
        alias_slug = _slugify(alias_slug)
        if not canonical_slug or not alias_slug:
            return False
        table = self._load_canonical()
        entries = table.get("entries") or {}
        entry = entries.get(canonical_slug)
        if not isinstance(entry, dict):
            return False
        aliases = entry.get("aliases") or {}
        if alias_slug not in aliases:
            return False
        del aliases[alias_slug]
        if not aliases and not entry.get("reviewed"):
            entries.pop(canonical_slug, None)
        self._save_canonical(table)
        return True

    def list_canonical_entries(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        table = self._load_canonical()
        items: list[dict[str, Any]] = []
        for slug, payload in (table.get("entries") or {}).items():
            if not isinstance(payload, dict):
                continue
            if kind and payload.get("kind") != kind:
                continue
            items.append({"canonical_slug": slug, **payload})
        items.sort(key=lambda item: str(item.get("canonical_label") or item["canonical_slug"]).lower())
        return items

    def list_canonical_pending_review(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        table = self._load_canonical()
        items = [item for item in (table.get("pending_review") or []) if isinstance(item, dict)]
        if kind:
            items = [item for item in items if item.get("kind") == kind]
        items.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
        return items

    def resolve_canonical_review(
        self,
        *,
        canonical_slug: str,
        alias_slug: str,
        approve: bool,
    ) -> dict[str, Any]:
        canonical_slug = _slugify(canonical_slug)
        alias_slug = _slugify(alias_slug)
        table = self._load_canonical()
        match: dict[str, Any] | None = None
        rest: list[dict[str, Any]] = []
        for item in (table.get("pending_review") or []):
            if (
                isinstance(item, dict)
                and item.get("canonical_slug") == canonical_slug
                and item.get("alias_slug") == alias_slug
            ):
                match = item
            else:
                rest.append(item)
        if match is None:
            raise ValueError(f"No pending review for canonical={canonical_slug!r} alias={alias_slug!r}")
        table["pending_review"] = rest
        self._save_canonical(table)
        if approve:
            labels = match.get("labels") or {}
            return self.record_canonical_merge(
                canonical_slug=canonical_slug,
                alias_slug=alias_slug,
                kind=str(match.get("kind") or "entity"),
                canonical_label=str(labels.get("canonical") or ""),
                alias_label=str(labels.get("alias") or ""),
                confidence=float(match.get("confidence") or 0.0),
                signals=match.get("signals") or {},
                evidence_sources=list(match.get("evidence_sources") or []),
                reviewed=True,
                source_kind="human",
            )
        return {"rejected": True, "canonical_slug": canonical_slug, "alias_slug": alias_slug}

    # ------------------------------------------------------------------
    # Lint driver: scan vault surface forms and propose merges.
    # ------------------------------------------------------------------
    def _resolve_merge_thresholds(self) -> MergeThresholds:
        canonical_cfg = getattr(self.vault_config, "canonical", None)
        if canonical_cfg is None:
            return DEFAULT_THRESHOLDS
        try:
            return MergeThresholds(
                auto_lexical_strong=float(canonical_cfg.auto_lexical_strong),
                auto_lexical_high=float(canonical_cfg.auto_lexical_high),
                auto_lexical_high_cooc=float(canonical_cfg.auto_lexical_high_cooc),
                auto_abbreviation_cooc=float(canonical_cfg.auto_abbreviation_cooc),
                auto_lexical_mid=float(canonical_cfg.auto_lexical_mid),
                auto_lexical_mid_cooc=float(canonical_cfg.auto_lexical_mid_cooc),
                review_abbreviation_cooc=float(canonical_cfg.review_abbreviation_cooc),
                review_cooc_strong=float(canonical_cfg.review_cooc_strong),
                review_lexical=float(canonical_cfg.review_lexical),
                review_abbreviation_alone=bool(canonical_cfg.review_abbreviation_alone),
            )
        except (TypeError, ValueError, AttributeError):
            logger.exception("vault_canonical_thresholds_invalid")
            return DEFAULT_THRESHOLDS

    def lint_canonical_aliases(
        self,
        *,
        dry_run: bool = True,
        thresholds: MergeThresholds | None = None,
    ) -> dict[str, Any]:
        sources = self._manifest.get("sources", {}) or {}
        dismissed = set((self._manifest.get("entity_dismissals", {}) or {}).keys())
        active_thresholds = thresholds or self._resolve_merge_thresholds()

        entity_surfaces, concept_surfaces = self._collect_surface_forms(sources, dismissed)

        existing = self._load_canonical()
        entity_aliases_in_table = self._aliased_slugs_for_kind(existing, "entity")
        concept_aliases_in_table = self._aliased_slugs_for_kind(existing, "concept")
        entity_surfaces = {s: sf for s, sf in entity_surfaces.items() if s not in entity_aliases_in_table}
        concept_surfaces = {s: sf for s, sf in concept_surfaces.items() if s not in concept_aliases_in_table}

        entity_candidates = propose_merges(entity_surfaces, thresholds=active_thresholds)
        concept_candidates = propose_merges(concept_surfaces, thresholds=active_thresholds)

        auto_applied: list[dict[str, Any]] = []
        queued_review: list[dict[str, Any]] = []
        used_as_alias_this_run: set[tuple[str, str]] = set()
        used_as_canonical_this_run: set[tuple[str, str]] = set()

        for candidate in entity_candidates + concept_candidates:
            alias_key = (candidate.kind, candidate.alias_slug)
            canonical_key = (candidate.kind, candidate.canonical_slug)
            # Demote to review if the alias was already used as a canonical
            # (or vice versa) in this same lint pass — prevents alias-of-alias.
            forced_review = (
                alias_key in used_as_canonical_this_run
                or canonical_key in used_as_alias_this_run
            )
            action = "review" if forced_review else candidate.action
            if action == "auto":
                if not dry_run:
                    self.record_canonical_merge(
                        canonical_slug=candidate.canonical_slug,
                        alias_slug=candidate.alias_slug,
                        kind=candidate.kind,
                        canonical_label=candidate.canonical_label,
                        alias_label=candidate.alias_label,
                        domain_hint=candidate.domain_hint,
                        confidence=candidate.confidence,
                        signals=candidate.signals,
                        evidence_sources=candidate.evidence_sources,
                        reviewed=False,
                        source_kind=self._infer_source_kind(candidate.signals),
                    )
                used_as_canonical_this_run.add(canonical_key)
                used_as_alias_this_run.add(alias_key)
                auto_applied.append(self._candidate_to_report(candidate))
            else:
                if not dry_run:
                    self.queue_canonical_review(
                        canonical_slug=candidate.canonical_slug,
                        alias_slug=candidate.alias_slug,
                        kind=candidate.kind,
                        canonical_label=candidate.canonical_label,
                        alias_label=candidate.alias_label,
                        signals=candidate.signals,
                        confidence=candidate.confidence,
                        evidence_sources=candidate.evidence_sources,
                    )
                queued_review.append(self._candidate_to_report(candidate))

        report = {
            "generated_at": _utcnow_iso(),
            "dry_run": bool(dry_run),
            "surface_counts": {
                "entities": len(entity_surfaces),
                "concepts": len(concept_surfaces),
            },
            "thresholds": {
                "auto_lexical_strong": active_thresholds.auto_lexical_strong,
                "auto_lexical_high": active_thresholds.auto_lexical_high,
                "auto_lexical_high_cooc": active_thresholds.auto_lexical_high_cooc,
                "auto_abbreviation_cooc": active_thresholds.auto_abbreviation_cooc,
                "auto_lexical_mid": active_thresholds.auto_lexical_mid,
                "auto_lexical_mid_cooc": active_thresholds.auto_lexical_mid_cooc,
                "review_abbreviation_cooc": active_thresholds.review_abbreviation_cooc,
                "review_cooc_strong": active_thresholds.review_cooc_strong,
                "review_lexical": active_thresholds.review_lexical,
                "review_abbreviation_alone": active_thresholds.review_abbreviation_alone,
            },
            "auto_applied": auto_applied,
            "queued_review": queued_review,
        }
        if not dry_run:
            report_path = (
                self.lint_reports_dir / f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-canonical.json"
            )
            try:
                self.lint_reports_dir.mkdir(parents=True, exist_ok=True)
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                logger.exception("vault_canonical_report_write_failed")
        return report

    @staticmethod
    def _aliased_slugs_for_kind(table: dict[str, Any], kind: str) -> set[str]:
        out: set[str] = set()
        for entry in (table.get("entries") or {}).values():
            if not isinstance(entry, dict) or entry.get("kind") != kind:
                continue
            for alias_slug in (entry.get("aliases") or {}):
                out.add(str(alias_slug))
        return out

    @staticmethod
    def _collect_surface_forms(
        sources: dict[str, Any],
        dismissed_entity_slugs: set[str],
    ) -> tuple[dict[str, SurfaceForm], dict[str, SurfaceForm]]:
        entity_surfaces: dict[str, SurfaceForm] = {}
        concept_surfaces: dict[str, SurfaceForm] = {}

        for source_id, record in sources.items():
            if not isinstance(record, dict):
                continue
            topic_tags = [
                str(tag).strip().lower()
                for tag in (record.get("topic_tags") or [])
                if str(tag).strip()
            ]
            entity_slugs_here: set[str] = set()
            for raw in record.get("entity_refs") or []:
                label = str(raw).strip()
                if not label:
                    continue
                slug = _slugify(label)
                if not slug or slug in dismissed_entity_slugs:
                    continue
                sf = entity_surfaces.setdefault(slug, SurfaceForm(slug=slug, label=label, kind="entity"))
                if len(label) > len(sf.label):
                    sf.label = label
                sf.sources.add(str(source_id))
                entity_slugs_here.add(slug)
                for tag in topic_tags:
                    sf.domain_counts[tag] = sf.domain_counts.get(tag, 0) + 1
            for slug in entity_slugs_here:
                entity_surfaces[slug].neighbors.update(entity_slugs_here - {slug})

            concept_slugs_here: set[str] = set()
            for raw in record.get("concept_refs") or []:
                label = str(raw).strip()
                if not label:
                    continue
                slug = _slugify(label)
                if not slug:
                    continue
                sf = concept_surfaces.setdefault(slug, SurfaceForm(slug=slug, label=label, kind="concept"))
                if len(label) > len(sf.label):
                    sf.label = label
                sf.sources.add(str(source_id))
                concept_slugs_here.add(slug)
                for tag in topic_tags:
                    sf.domain_counts[tag] = sf.domain_counts.get(tag, 0) + 1
            for slug in concept_slugs_here:
                concept_surfaces[slug].neighbors.update(concept_slugs_here - {slug})

        return entity_surfaces, concept_surfaces

    @staticmethod
    def _candidate_to_report(candidate: MergeCandidate) -> dict[str, Any]:
        return {
            "canonical_slug": candidate.canonical_slug,
            "alias_slug": candidate.alias_slug,
            "kind": candidate.kind,
            "canonical_label": candidate.canonical_label,
            "alias_label": candidate.alias_label,
            "confidence": candidate.confidence,
            "action": candidate.action,
            "signals": candidate.signals,
            "domain_hint": candidate.domain_hint,
            "reason": candidate.reason,
            "evidence_sources": list(candidate.evidence_sources),
        }

    @staticmethod
    def _infer_source_kind(signals: dict[str, Any]) -> str:
        if signals.get("abbreviation"):
            return "abbreviation"
        lexical = float(signals.get("lexical") or 0.0)
        cooccurrence = float(signals.get("cooccurrence") or 0.0)
        return "lexical" if lexical >= cooccurrence else "cooccurrence"


__all__ = ["CanonicalMixin", "CANONICAL_VERSION"]
