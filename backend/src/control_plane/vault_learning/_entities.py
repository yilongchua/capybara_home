from __future__ import annotations

from typing import Any

from src.control_plane.vault_text_utils import (
    slugify as _slugify,
)
from src.control_plane.vault_text_utils import (
    utcnow_iso as _utcnow_iso,
)


class EntitiesMixin:
    # ------------------------------------------------------------------
    # Entity browser — entity-centric view of the vault.
    # ------------------------------------------------------------------
    def _entity_aggregates(self) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        """Walk manifest sources once and return (entity_index, concept_index).

        entity_index[slug] = {label, degree, source_ids: set, concept_slugs: set}
        concept_index[slug] = {label}
        Both indexes skip dismissed entities and collapse aliases through the
        canonical table (so `JP Morgan` / `JPM` show as one row).
        """
        sources = self._manifest.get("sources", {}) or {}
        dismissals = self._manifest.get("entity_dismissals", {}) or {}
        alias_map = {
            slug: str((entry or {}).get("alias_for") or "").strip()
            for slug, entry in dismissals.items()
            if isinstance(entry, dict)
        }

        try:
            entity_canonical_map = self.canonical_alias_map(kind="entity")
            concept_canonical_map = self.canonical_alias_map(kind="concept")
        except AttributeError:
            entity_canonical_map = {}
            concept_canonical_map = {}

        canonical_labels: dict[tuple[str, str], str] = {}
        try:
            canonical_table = self._load_canonical()
            for slug, entry in (canonical_table.get("entries") or {}).items():
                if not isinstance(entry, dict):
                    continue
                label = str(entry.get("canonical_label") or "").strip()
                kind = str(entry.get("kind") or "")
                if label and kind:
                    canonical_labels[(kind, slug)] = label
        except AttributeError:
            pass

        entity_index: dict[str, dict[str, Any]] = {}
        concept_index: dict[str, dict[str, Any]] = {}

        for source_id, record in sources.items():
            if not isinstance(record, dict):
                continue
            entity_refs = record.get("entity_refs") or []
            concept_refs = record.get("concept_refs") or []

            local_entity_slugs: set[str] = set()
            for raw in entity_refs:
                label = str(raw).strip()
                if not label:
                    continue
                slug = _slugify(label)
                if not slug:
                    continue
                slug = entity_canonical_map.get(slug, slug)
                if slug in dismissals:
                    alias = alias_map.get(slug) or ""
                    if not alias:
                        continue
                    slug = alias
                canonical_label = canonical_labels.get(("entity", slug))
                bucket = entity_index.setdefault(
                    slug,
                    {
                        "slug": slug,
                        "label": canonical_label or label,
                        "source_ids": set(),
                        "concept_slugs": set(),
                    },
                )
                bucket["source_ids"].add(str(source_id))
                local_entity_slugs.add(slug)
                if canonical_label:
                    bucket["label"] = canonical_label
                elif len(label) > len(bucket["label"]):
                    bucket["label"] = label

            local_concept_slugs: set[str] = set()
            for raw in concept_refs:
                label = str(raw).strip()
                if not label:
                    continue
                slug = _slugify(label)
                if not slug:
                    continue
                slug = concept_canonical_map.get(slug, slug)
                canonical_label = canonical_labels.get(("concept", slug))
                local_concept_slugs.add(slug)
                bucket = concept_index.setdefault(slug, {"slug": slug, "label": canonical_label or label})
                if canonical_label:
                    bucket["label"] = canonical_label
                elif len(label) > len(bucket["label"]):
                    bucket["label"] = label

            for entity_slug in local_entity_slugs:
                entity_index[entity_slug]["concept_slugs"].update(local_concept_slugs)

        # Materialize degrees.
        for entry in entity_index.values():
            entry["degree"] = len(entry["source_ids"])

        return entity_index, concept_index

    def get_entity_browser(
        self,
        *,
        top_n: int = 15,
        bottom_n: int = 10,
        critical_max_degree: int = 2,
    ) -> dict[str, Any]:
        """Return entity-centric view with top, critical-gap, and less-covered buckets.

        - top: highest-degree entities (most connected, capped at top_n)
        - critical_gaps: entities whose degree <= critical_max_degree (i.e. <3 by default)
        - less_covered: next bottom_n entities by ascending degree, excluding criticals.
          Always populated when entities exist beyond the critical band.
        """
        entity_index, concept_index = self._entity_aggregates()
        sources_map = self._manifest.get("sources", {}) or {}

        def _source_summary(source_id: str) -> dict[str, str]:
            record = sources_map.get(source_id) or {}
            return {
                "source_id": str(source_id),
                "title": str(record.get("title") or record.get("url") or source_id),
                "url": str(record.get("url") or ""),
            }

        def _serialize(entry: dict[str, Any]) -> dict[str, Any]:
            return {
                "slug": entry["slug"],
                "label": entry["label"],
                "degree": int(entry.get("degree") or 0),
                "sources": sorted(
                    (_source_summary(sid) for sid in entry["source_ids"]),
                    key=lambda item: item["title"].lower(),
                ),
                "concepts": sorted(
                    (
                        {
                            "slug": slug,
                            "label": (concept_index.get(slug) or {}).get("label", slug),
                        }
                        for slug in entry["concept_slugs"]
                    ),
                    key=lambda item: item["label"].lower(),
                ),
            }

        all_entries = list(entity_index.values())
        all_entries.sort(key=lambda item: (-int(item["degree"]), item["label"].lower()))

        top = [_serialize(entry) for entry in all_entries[: max(0, int(top_n))]]

        critical_entries = [entry for entry in all_entries if int(entry["degree"]) <= int(critical_max_degree)]
        critical_entries.sort(key=lambda item: (int(item["degree"]), item["label"].lower()))
        critical_gaps = [_serialize(entry) for entry in critical_entries]

        critical_slugs = {entry["slug"] for entry in critical_entries}
        non_critical = [entry for entry in all_entries if entry["slug"] not in critical_slugs]
        non_critical.sort(key=lambda item: (int(item["degree"]), item["label"].lower()))
        less_covered = [_serialize(entry) for entry in non_critical[: max(0, int(bottom_n))]]

        dismissals_raw = self._manifest.get("entity_dismissals", {}) or {}
        try:
            canonical_entries = self.list_canonical_entries(kind="entity")
        except AttributeError:
            canonical_entries = []

        return {
            "generated_at": _utcnow_iso(),
            "counts": {
                "total_entities": len(entity_index),
                "dismissed": len(dismissals_raw),
                "canonical_merges": len(canonical_entries),
                "critical_max_degree": int(critical_max_degree),
            },
            "top": top,
            "critical_gaps": critical_gaps,
            "less_covered": less_covered,
        }

    def list_entity_dismissals(self) -> list[dict[str, Any]]:
        dismissals = self._manifest.get("entity_dismissals", {}) or {}
        items: list[dict[str, Any]] = []
        for slug, raw in dismissals.items():
            if not isinstance(raw, dict):
                continue
            items.append(
                {
                    "slug": str(slug),
                    "label": str(raw.get("label") or slug),
                    "reason": str(raw.get("reason") or ""),
                    "alias_for": str(raw.get("alias_for") or "") or None,
                    "dismissed_at": str(raw.get("dismissed_at") or ""),
                }
            )
        items.sort(key=lambda item: item["dismissed_at"], reverse=True)
        return items

    def dismiss_entity(
        self,
        *,
        slug: str,
        reason: str = "",
        alias_for: str | None = None,
    ) -> dict[str, Any]:
        """Mark an entity slug as dismissed (noise / duplicate).

        - Records the dismissal in manifest["entity_dismissals"].
        - Removes the slug from every source's entity_refs (or rewrites it to
          alias_for when supplied).
        - Deletes 02_compiled/entities/{slug}.md if present.
        - Marks affected pages dirty so the next compile regenerates indexes.
        """
        normalized = _slugify(str(slug or ""))
        if not normalized:
            raise ValueError("Entity slug is required.")

        normalized_alias: str | None = None
        if alias_for:
            normalized_alias = _slugify(str(alias_for))
            if not normalized_alias:
                normalized_alias = None
            elif normalized_alias == normalized:
                raise ValueError("Alias target cannot equal the dismissed slug.")

        # Find a human label to surface in the dismissal record by scanning sources.
        sources = self._manifest.get("sources", {}) or {}
        original_label = normalized
        for record in sources.values():
            if not isinstance(record, dict):
                continue
            for raw in record.get("entity_refs") or []:
                label = str(raw).strip()
                if label and _slugify(label) == normalized and len(label) > len(original_label):
                    original_label = label

        affected_sources: list[str] = []
        for source_id, record in sources.items():
            if not isinstance(record, dict):
                continue
            refs = record.get("entity_refs") or []
            if not isinstance(refs, list):
                continue
            new_refs: list[str] = []
            changed = False
            for raw in refs:
                label = str(raw).strip()
                if not label:
                    continue
                if _slugify(label) == normalized:
                    changed = True
                    if normalized_alias:
                        # Rewrite the ref so future slugify maps to the alias.
                        new_refs.append(normalized_alias)
                    # Otherwise drop the ref entirely (pure dismissal).
                else:
                    new_refs.append(label)
            if changed:
                # Dedupe in case alias collides with an existing ref.
                seen: set[str] = set()
                deduped: list[str] = []
                for ref in new_refs:
                    if ref not in seen:
                        seen.add(ref)
                        deduped.append(ref)
                record["entity_refs"] = deduped
                affected_sources.append(str(source_id))

        dismissals = self._manifest.setdefault("entity_dismissals", {})
        dismissals[normalized] = {
            "label": original_label,
            "reason": str(reason or "").strip(),
            "alias_for": normalized_alias,
            "dismissed_at": _utcnow_iso(),
        }

        # Delete the compiled entity page if present.
        deleted = False
        compiled_path = self.compiled_entities_dir / f"{normalized}.md"
        if compiled_path.exists():
            try:
                compiled_path.unlink()
                deleted = True
            except OSError:
                deleted = False

        # Regenerate entities index now (cheap) and mark dirty pages for the next compile.
        if self.compiled_entities_dir.exists():
            (self.compiled_entities_dir / "index.md").write_text(
                self._render_index_for_dir("Entities", self.compiled_entities_dir),
                encoding="utf-8",
            )
        dirty = set(self._manifest.get("dirty_pages") or [])
        dirty.update({"entities/index.md", "index.md"})
        self._manifest["dirty_pages"] = sorted(dirty)

        self._save_manifest()
        return {
            "slug": normalized,
            "alias_for": normalized_alias,
            "affected_sources": affected_sources,
            "compiled_deleted": deleted,
        }

    def restore_entity_dismissal(self, *, slug: str) -> dict[str, Any]:
        normalized = _slugify(str(slug or ""))
        if not normalized:
            raise ValueError("Entity slug is required.")
        dismissals = self._manifest.get("entity_dismissals", {}) or {}
        if normalized not in dismissals:
            raise ValueError(f"No dismissal found for entity '{normalized}'.")
        del dismissals[normalized]
        self._manifest["entity_dismissals"] = dismissals
        self._save_manifest()
        return {"slug": normalized, "restored": True}
