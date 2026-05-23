from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from src.config import get_app_config, get_paths
from src.config.loop_detection_config import get_loop_detection_config
from src.control_plane.prompts.vault_analyze import ANALYZE_SOURCE_PROMPT
from src.control_plane.prompts.vault_generate import GENERATE_PAGE_PROMPT
from src.control_plane.services.unified_vault_search import UnifiedVaultSearchService
from src.control_plane.vault_text_utils import (
    extract_title as _extract_title,
)
from src.control_plane.vault_text_utils import (
    frontmatter_dump as _frontmatter_dump,
)
from src.control_plane.vault_text_utils import (
    parse_frontmatter as _parse_frontmatter,
)
from src.control_plane.vault_text_utils import (
    slugify as _slugify,
)
from src.control_plane.vault_text_utils import (
    strip_html as _strip_html,
)
from src.control_plane.vault_text_utils import (
    utcnow as _utcnow,
)
from src.control_plane.vault_text_utils import (
    utcnow_iso as _utcnow_iso,
)
from src.models.factory import create_chat_model


class VaultLoopGuardConfig(BaseModel):
    cooldown_hours: int = 24
    retry_budget: int = 3
    model_config = ConfigDict(extra="allow")


class VaultManifest(BaseModel):
    version: str = "vault-manifest.v4"
    updated_at: str = ""
    last_compile_at: str | None = None
    last_lint_at: str | None = None
    sources: dict[str, Any] = Field(default_factory=dict)
    queries: dict[str, Any] = Field(default_factory=dict)
    candidates: dict[str, Any] = Field(default_factory=dict)
    trust_decisions: dict[str, Any] = Field(default_factory=dict)
    dirty_pages: list[str] = Field(default_factory=list)
    source_dependencies: dict[str, Any] = Field(default_factory=dict)
    search_index: dict[str, Any] = Field(default_factory=dict)
    topic_syntheses: dict[str, Any] = Field(default_factory=dict)
    last_run_summary: dict[str, Any] = Field(default_factory=dict)
    objectives: dict[str, Any] = Field(default_factory=dict)
    action_history: list[dict[str, Any]] = Field(default_factory=list)
    attempt_fingerprints: dict[str, Any] = Field(default_factory=dict)
    loop_guard: VaultLoopGuardConfig = Field(default_factory=VaultLoopGuardConfig)
    coverage_signals: dict[str, Any] = Field(default_factory=dict)
    sufficiency_state: dict[str, Any] = Field(default_factory=dict)
    memory_stats: dict[str, Any] = Field(default_factory=dict)
    schema_migrated_from: str = "vault-manifest.v4"
    model_config = ConfigDict(extra="allow")


class VaultLearningManager:
    def __init__(
        self,
        *,
        vault_root: Path,
        allowed_domains: list[str] | None = None,
        max_content_chars: int = 20000,
        min_trust_score: float = 0.55,
        query_retention_hours: int = 72,
        search_results_queue_path: str | None = None,
        search_results_dedupe_window_hours: int = 72,
        search_results_max_queue_items: int = 5000,
    ) -> None:
        self.vault_root = vault_root.expanduser().resolve()
        try:
            self.vault_config = get_app_config().knowledge_vault
        except Exception:
            self.vault_config = SimpleNamespace(
                cot_ingest_enabled=True,
                cot_min_chars=1200,
                cot_model="",
                vector_search_enabled=False,
                vector_backend="hash",
                vector_embedding_model="",
                vector_dimensions=256,
                vector_chunk_chars=1200,
                vector_chunk_overlap_chars=200,
                hybrid_rrf_k=60,
            )
        self.allowed_domains = set(allowed_domains or [])
        self.max_content_chars = max(1000, int(max_content_chars))
        self.min_trust_score = float(min_trust_score)
        self.query_retention_hours = int(query_retention_hours)
        self.search_results_dedupe_window_hours = int(search_results_dedupe_window_hours)
        self.search_results_max_queue_items = int(search_results_max_queue_items)

        self.schema_dir = self.vault_root / "00_schema"
        self.raw_dir = self.vault_root / "01_raw"
        self.compiled_dir = self.vault_root / "02_compiled"
        self.ops_dir = self.vault_root / "03_ops"

        self.raw_sources_dir = self.raw_dir / "sources"
        self.compiled_sources_dir = self.compiled_dir / "sources"
        self.compiled_entities_dir = self.compiled_dir / "entities"
        self.compiled_concepts_dir = self.compiled_dir / "concepts"
        self.compiled_syntheses_dir = self.compiled_dir / "syntheses"
        self.compiled_queries_dir = self.compiled_dir / "queries"
        self.compiled_index_path = self.compiled_dir / "index.md"
        self.compiled_log_path = self.compiled_dir / "log.md"

        self.inbox_dir = self.ops_dir / "inbox"
        self.tasks_dir = self.ops_dir / "tasks"
        self.reports_dir = self.ops_dir / "reports"
        self.queues_dir = self.ops_dir / "queues"
        self.quarantine_dir = self.ops_dir / "quarantine"

        self.discover_reports_dir = self.reports_dir / "discover"
        self.ingest_reports_dir = self.reports_dir / "ingest"
        self.compile_reports_dir = self.reports_dir / "compile"
        self.lint_reports_dir = self.reports_dir / "lint"
        self.synthesis_reports_dir = self.reports_dir / "synthesis"
        self.sufficiency_reports_dir = self.reports_dir / "sufficiency"
        self.task_backlog_dir = self.tasks_dir / "backlog"
        self.task_review_dir = self.tasks_dir / "review"
        self.task_done_dir = self.tasks_dir / "done"

        self.state_dir = self.vault_root / ".vault_state"
        self.manifest_path = self.state_dir / "manifest.json"

        if search_results_queue_path:
            queue_path = Path(search_results_queue_path)
            if not queue_path.is_absolute():
                queue_path = get_paths().base_dir / queue_path
            self.search_results_queue_path = queue_path.resolve()
        else:
            self.search_results_queue_path = self.queues_dir / "search_results_ingestion_queue.json"

        for directory in (
            self.vault_root,
            self.schema_dir,
            self.raw_dir,
            self.compiled_dir,
            self.ops_dir,
            self.raw_sources_dir,
            self.compiled_sources_dir,
            self.compiled_entities_dir,
            self.compiled_concepts_dir,
            self.compiled_syntheses_dir,
            self.compiled_queries_dir,
            self.inbox_dir,
            self.tasks_dir,
            self.reports_dir,
            self.queues_dir,
            self.quarantine_dir,
            self.discover_reports_dir,
            self.ingest_reports_dir,
            self.compile_reports_dir,
            self.lint_reports_dir,
            self.synthesis_reports_dir,
            self.sufficiency_reports_dir,
            self.task_backlog_dir,
            self.task_review_dir,
            self.task_done_dir,
            self.state_dir,
            self.search_results_queue_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self._seed_schema_docs()
        self._manifest = self._load_manifest()
        self._ensure_queue_file()

    @staticmethod
    def default_vault_root() -> Path:
        return get_paths().base_dir / "knowledge_vault"

    def _seed_schema_docs(self) -> None:
        docs = {
            self.schema_dir / "VAULT_SCHEMA.md": (
                "# Vault Schema\n\n"
                "This vault uses layered storage:\n"
                "- `01_raw/` immutable fetched source packages\n"
                "- `02_compiled/` maintained markdown knowledge pages\n"
                "- `03_ops/` operational queues, reports, and tasks\n"
            ),
            self.schema_dir / "RESEARCH_POLICY.md": (
                "# Research Policy\n\n"
                "Only trusted, provenance-linked knowledge may flow into compiled pages.\n"
                "Low-trust or policy-rejected items must remain outside durable synthesis updates.\n"
            ),
            self.schema_dir / "QUERY_RETENTION_POLICY.md": (
                "# Query Retention Policy\n\n"
                f"Query notes remain active for {self.query_retention_hours} hours to reduce duplicate short-horizon research.\n"
            ),
        }
        for path, content in docs.items():
            if not path.exists():
                path.write_text(content, encoding="utf-8")

    def _load_manifest(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        version = str(data.get("version") or "vault-manifest.v3")
        payload = {
            "version": "vault-manifest.v4",
            "updated_at": _utcnow_iso(),
            "last_compile_at": data.get("last_compile_at"),
            "last_lint_at": data.get("last_lint_at"),
            "sources": data.get("sources", {}),
            "queries": data.get("queries", {}),
            "candidates": data.get("candidates", {}),
            "trust_decisions": data.get("trust_decisions", {}),
            "dirty_pages": data.get("dirty_pages", []),
            "source_dependencies": data.get("source_dependencies", {}),
            "search_index": data.get("search_index", {}),
            "topic_syntheses": data.get("topic_syntheses", {}),
            "last_run_summary": data.get("last_run_summary", {}),
            "objectives": data.get("objectives", {}),
            "action_history": data.get("action_history", []),
            "attempt_fingerprints": data.get("attempt_fingerprints", {}),
            "loop_guard": data.get(
                "loop_guard",
                {"cooldown_hours": 24, "retry_budget": 3},
            ),
            "coverage_signals": data.get("coverage_signals", {}),
            "sufficiency_state": data.get("sufficiency_state", {}),
            "memory_stats": data.get("memory_stats", {}),
            "schema_migrated_from": version,
        }
        return VaultManifest.model_validate(payload).model_dump(mode="python")

    def _save_manifest(self) -> None:
        self._manifest["updated_at"] = _utcnow_iso()
        validated = VaultManifest.model_validate(self._manifest).model_dump(mode="json")
        self.manifest_path.write_text(
            json.dumps(validated, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _ensure_queue_file(self) -> None:
        if not self.search_results_queue_path.exists():
            self.search_results_queue_path.write_text("[]", encoding="utf-8")

    def _fingerprint_attempt(self, *, objective_id: str, query_text: str, key_entities: list[str] | None = None, source_hash: str | None = None) -> str:
        entities = sorted(_slugify(item) for item in (key_entities or []) if str(item).strip())
        raw = f"{objective_id.strip().lower()}|{query_text.strip().lower()}|{'|'.join(entities)}|{str(source_hash or '').strip().lower()}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _ensure_objective(self, *, objective_id: str, topic: str) -> dict[str, Any]:
        objective = self._manifest["objectives"].get(objective_id)
        if isinstance(objective, dict):
            return objective
        now = _utcnow_iso()
        objective = {
            "objective_id": objective_id,
            "topic": topic,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "last_action_at": now,
            "attempts_total": 0,
            "blocked_attempts": 0,
            "completed_attempts": 0,
        }
        self._manifest["objectives"][objective_id] = objective
        return objective

    def _append_action_history(self, payload: dict[str, Any]) -> None:
        event = {
            "event_id": f"evt-{uuid4().hex[:12]}",
            "created_at": _utcnow_iso(),
            **payload,
        }
        events = self._manifest.get("action_history", [])
        events.append(event)
        self._manifest["action_history"] = events[-2000:]

    def check_loop_guard(
        self,
        *,
        objective_id: str,
        topic: str,
        query_text: str,
        key_entities: list[str] | None = None,
        source_hash: str | None = None,
        cooldown_hours: int | None = None,
        retry_budget: int | None = None,
    ) -> dict[str, Any]:
        if not get_loop_detection_config().enabled:
            return {
                "allowed": True,
                "reason": "disabled",
                "fingerprint": "",
                "cooldown_hours": 0,
                "retry_budget": 0,
            }

        objective = self._ensure_objective(objective_id=objective_id, topic=topic)
        loop_guard = self._manifest.get("loop_guard", {})
        eff_cooldown = max(1, int(cooldown_hours or loop_guard.get("cooldown_hours") or 24))
        eff_retry_budget = max(1, int(retry_budget or loop_guard.get("retry_budget") or 3))
        fingerprint = self._fingerprint_attempt(
            objective_id=objective_id,
            query_text=query_text,
            key_entities=key_entities,
            source_hash=source_hash,
        )
        now = _utcnow()
        record = self._manifest["attempt_fingerprints"].get(fingerprint, {})
        last_attempt_at_raw = record.get("last_attempt_at")
        last_attempt_at = None
        if last_attempt_at_raw:
            try:
                last_attempt_at = datetime.fromisoformat(str(last_attempt_at_raw)).replace(tzinfo=UTC)
            except Exception:
                last_attempt_at = None
        attempts = int(record.get("attempts") or 0)

        blocked_reason = ""
        if attempts >= eff_retry_budget:
            blocked_reason = "retry_budget_exhausted"
        elif last_attempt_at and last_attempt_at >= (now - timedelta(hours=eff_cooldown)):
            blocked_reason = "cooldown_active"

        allowed = not bool(blocked_reason)
        self._append_action_history(
            {
                "objective_id": objective_id,
                "topic": topic,
                "phase": "loop_guard",
                "status": "allowed" if allowed else "blocked",
                "reason": blocked_reason or "passed",
                "fingerprint": fingerprint,
                "query_text": query_text,
            }
        )
        objective["updated_at"] = _utcnow_iso()
        objective["last_action_at"] = objective["updated_at"]
        objective["attempts_total"] = int(objective.get("attempts_total") or 0) + 1
        if not allowed:
            objective["blocked_attempts"] = int(objective.get("blocked_attempts") or 0) + 1

        if allowed:
            self._manifest["attempt_fingerprints"][fingerprint] = {
                "objective_id": objective_id,
                "topic": topic,
                "last_attempt_at": _utcnow_iso(),
                "attempts": attempts + 1,
                "status": "allowed",
            }
        self._save_manifest()
        return {
            "allowed": allowed,
            "reason": blocked_reason,
            "fingerprint": fingerprint,
            "cooldown_hours": eff_cooldown,
            "retry_budget": eff_retry_budget,
        }

    def _raw_memory_bytes(self) -> int:
        total = 0
        if not self.raw_dir.exists():
            return 0
        for path in self.raw_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    @staticmethod
    def _human_bytes(num_bytes: int) -> str:
        size = float(max(0, num_bytes))
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while size >= 1024.0 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        return f"{size:.2f} {units[idx]}"

    def _load_queue(self) -> list[dict[str, Any]]:
        self._ensure_queue_file()
        try:
            payload = json.loads(self.search_results_queue_path.read_text(encoding="utf-8"))
        except Exception:
            payload = []
        return payload if isinstance(payload, list) else []

    def _save_queue(self, items: list[dict[str, Any]]) -> None:
        trimmed = items[-self.search_results_max_queue_items :]
        self.search_results_queue_path.write_text(
            json.dumps(trimmed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _domain_allowed(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        if not self.allowed_domains:
            return True
        return any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)

    def _is_web_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _normalize_urls(self, urls: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for item in urls:
            url = str(item).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append(url)
        return normalized


    def _source_id_for_url(self, url: str) -> str:
        host = urlparse(url).hostname or "source"
        return f"{_slugify(host)}-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}"

    def _query_id_for_text(self, query_text: str) -> str:
        return f"query-{hashlib.sha1(query_text.strip().lower().encode('utf-8')).hexdigest()[:12]}"

    def _topic_slug(self, topic: str, fallback: str = "general-research") -> str:
        return _slugify(topic) if topic.strip() else fallback

    def _topic_tags(self, topic: str, metadata: dict[str, Any] | None = None) -> list[str]:
        tags = []
        if isinstance(metadata, dict):
            raw_tags = metadata.get("topic_tags")
            if isinstance(raw_tags, list):
                tags.extend(str(item).strip() for item in raw_tags if str(item).strip())
        if topic.strip():
            tags.append(self._topic_slug(topic))
        seen: set[str] = set()
        deduped: list[str] = []
        for tag in tags:
            normalized = _slugify(tag)
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        return deduped

    def _record_trust_decision(
        self,
        *,
        source_id: str,
        url: str,
        score: float,
        reasons: list[str],
        decision: str,
    ) -> None:
        self._manifest["trust_decisions"][source_id] = {
            "source_id": source_id,
            "url": url,
            "score": round(score, 4),
            "reasons": reasons,
            "decision": decision,
            "decided_at": _utcnow_iso(),
        }

    def _trust_score(self, *, url: str, text: str) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.35
        host = (urlparse(url).hostname or "").lower()
        if host:
            score += 0.1
        if len(text) >= 300:
            score += 0.25
        else:
            reasons.append("content_too_short")
        if "http" in text.lower():
            score += 0.1
        if any(token in host for token in ("gov", "edu", "org")):
            score += 0.15
        if not reasons:
            reasons.append("basic_quality_checks_passed")
        return min(1.0, score), reasons

    def _raw_package_dir(self, source_id: str, fetched_at: datetime) -> Path:
        return self.raw_sources_dir / fetched_at.strftime("%Y") / fetched_at.strftime("%m") / source_id

    def _compiled_source_path(self, source_id: str) -> Path:
        return self.compiled_sources_dir / f"{source_id}.md"

    def _compiled_entity_path(self, entity_id: str) -> Path:
        return self.compiled_entities_dir / f"{_slugify(entity_id)}.md"

    def _compiled_concept_path(self, concept_id: str) -> Path:
        return self.compiled_concepts_dir / f"{_slugify(concept_id)}.md"

    def _compiled_synthesis_path(self, topic_slug: str) -> Path:
        return self.compiled_syntheses_dir / f"{topic_slug}.md"

    def _compiled_query_path(self, query_id: str) -> Path:
        return self.compiled_queries_dir / f"{query_id}.md"

    def _write_page(
        self,
        *,
        path: Path,
        frontmatter: dict[str, Any],
        title: str,
        sections: list[str],
    ) -> None:
        body = "\n\n".join([f"# {title}", *sections]).strip() + "\n"
        path.write_text(f"{_frontmatter_dump(frontmatter)}\n\n{body}", encoding="utf-8")

    def _index_document(
        self,
        *,
        doc_id: str,
        kind: str,
        title: str,
        path: Path,
        text: str,
        tags: list[str] | None = None,
    ) -> None:
        self._manifest["search_index"][doc_id] = {
            "id": doc_id,
            "kind": kind,
            "title": title,
            "path": str(path),
            "snippet": text[:500],
            "text": text[:4000],
            "tags": tags or [],
            "updated_at": _utcnow_iso(),
        }

    @staticmethod
    def _extract_json_payload(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _heuristic_sentences(text: str, *, limit: int) -> list[str]:
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]
        return sentences[: max(1, limit)]

    _ENTITY_STOPWORDS: frozenset[str] = frozenset(
        {
            # pronouns / determiners
            "the", "and", "for", "with", "from", "into", "onto", "your", "their", "there", "they",
            "them", "our", "ours", "his", "her", "hers", "its", "this", "that", "these", "those",
            "what", "which", "who", "whom", "whose", "why", "how", "when", "where",
            # generic adjectives / fillers commonly capitalized in titles
            "best", "good", "great", "top", "new", "old", "use", "uses", "using", "ancient",
            "modern", "more", "most", "less", "many", "much", "some", "any", "all", "every",
            "guide", "intro", "overview", "review", "tips", "ways", "list", "blog", "post",
            "article", "page", "site", "home", "next", "back", "here", "now", "soon", "today",
            "yesterday", "tomorrow", "still", "just", "also", "ever", "even", "only", "very",
            "really", "quite", "rather", "such", "than", "then", "still", "yet", "again",
            "etc", "via", "about", "above", "below", "across", "after", "before", "between",
            "during", "without", "within", "behind", "beyond", "under", "over",
            "is", "are", "was", "were", "be", "been", "being",
            # generic nouns that aren't useful as entities
            "thing", "things", "stuff", "people", "person", "way", "ways", "part", "parts",
            "kind", "kinds", "type", "types", "case", "cases", "fact", "facts", "idea", "ideas",
        }
    )

    @classmethod
    def _is_quality_entity(cls, token: str) -> bool:
        cleaned = token.strip(" -_/&")
        if len(cleaned) < 4:
            return False
        lowered = cleaned.lower()
        if lowered in cls._ENTITY_STOPWORDS:
            return False
        # Require at least one vowel (filters acronyms / typos / pure punctuation residue)
        if not re.search(r"[aeiouAEIOU]", cleaned):
            return False
        # Reject if all characters are the same letter or it's purely numeric
        if cleaned.isdigit():
            return False
        return True

    def _heuristic_analysis(
        self,
        *,
        title: str,
        url: str,
        topic: str,
        raw_text: str,
        topic_tags: list[str],
        concept_refs: list[str],
        entity_refs: list[str],
        target_synthesis_refs: list[str],
    ) -> dict[str, Any]:
        summary = " ".join(self._heuristic_sentences(raw_text, limit=3))[:1000]
        key_claims = self._heuristic_sentences(raw_text, limit=5)
        # Prefer multi-word capitalized phrases (proper nouns) over isolated capitalized words,
        # which in titles are usually just adjectives ("Best", "Ancient", "Your").
        multiword = re.findall(r"(?:[A-Z][A-Za-z0-9&/-]{2,}(?:\s+[A-Z][A-Za-z0-9&/-]{2,})+)", title)
        single = re.findall(r"[A-Z][A-Za-z0-9&/-]{3,}", title)
        candidate_tokens = list(dict.fromkeys(multiword + single))
        title_tokens = [token for token in candidate_tokens if self._is_quality_entity(token)]
        topic_words = [item for item in re.findall(r"[A-Za-z0-9]+", topic) if len(item) > 4 and self._is_quality_entity(item)]
        cleaned_entity_refs = [ref for ref in entity_refs if self._is_quality_entity(ref)]
        entities = list(dict.fromkeys(cleaned_entity_refs + title_tokens[:5]))
        concepts = list(dict.fromkeys(concept_refs + topic_words[:6]))
        synthesis_refs = list(dict.fromkeys(target_synthesis_refs + topic_tags[:3] + ([self._topic_slug(topic)] if topic else [])))
        open_questions = [f"What evidence is still missing around {topic or title}?", f"Which facts should be re-verified from {url}?"]
        gap_queries = [f"{topic or title} latest evidence", f"{topic or title} contradictory sources"]
        return {
            "summary": summary or title,
            "key_claims": key_claims or [title],
            "entities": entities,
            "concepts": concepts,
            "topic_tags": topic_tags,
            "open_questions": open_questions,
            "gap_queries": gap_queries,
            "synthesis_refs": [item for item in synthesis_refs if item],
        }

    def _call_vault_model_json(self, prompt: str) -> dict[str, Any]:
        model_name = str(self.vault_config.cot_model or "").strip()
        try:
            app_config = get_app_config()
        except Exception:
            return {}
        if not app_config.models:
            return {}
        model = create_chat_model(name=model_name or None, thinking_enabled=False)
        response = model.invoke(prompt)
        raw = response.content if isinstance(response.content, str) else str(response.content)
        return self._extract_json_payload(raw)

    def _analyze_source(
        self,
        *,
        title: str,
        url: str,
        topic: str,
        raw_text: str,
        topic_tags: list[str],
        concept_refs: list[str],
        entity_refs: list[str],
        target_synthesis_refs: list[str],
    ) -> dict[str, Any]:
        fallback = self._heuristic_analysis(
            title=title,
            url=url,
            topic=topic,
            raw_text=raw_text,
            topic_tags=topic_tags,
            concept_refs=concept_refs,
            entity_refs=entity_refs,
            target_synthesis_refs=target_synthesis_refs,
        )
        if not self.vault_config.cot_ingest_enabled or len(raw_text) < int(self.vault_config.cot_min_chars):
            return {**fallback, "analysis_mode": "heuristic"}
        try:
            parsed = self._call_vault_model_json(
                ANALYZE_SOURCE_PROMPT.format(
                    title=title,
                    url=url,
                    topic=topic,
                    content=raw_text[: self.max_content_chars],
                )
            )
        except Exception:
            parsed = {}
        merged = {
            **fallback,
            **{key: value for key, value in parsed.items() if value not in (None, "", [], {})},
        }
        merged["analysis_mode"] = "model" if parsed else "heuristic"
        for key in ("key_claims", "entities", "concepts", "topic_tags", "open_questions", "gap_queries", "synthesis_refs"):
            value = merged.get(key)
            if not isinstance(value, list):
                merged[key] = fallback.get(key, [])
            else:
                merged[key] = [str(item).strip() for item in value if str(item).strip()]
        merged["entities"] = [item for item in merged["entities"] if self._is_quality_entity(item)]
        merged["summary"] = str(merged.get("summary") or fallback["summary"]).strip()
        return merged

    def _generate_source_sections(
        self,
        *,
        title: str,
        url: str,
        topic: str,
        raw_text: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = {
            "summary_markdown": str(analysis.get("summary") or title).strip(),
            "claims_markdown": "\n".join(f"- {item}" for item in analysis.get("key_claims", [])[:8]) or f"- {title}",
            "evidence_markdown": "\n".join(f"- {item}" for item in self._heuristic_sentences(raw_text, limit=6)) or raw_text[:1200],
            "backlink_lines": [f"[[../syntheses/{item}.md]]" for item in analysis.get("synthesis_refs", [])[:8]],
            "review_items": [str(item) for item in analysis.get("open_questions", [])[:8]],
        }
        if not self.vault_config.cot_ingest_enabled or len(raw_text) < int(self.vault_config.cot_min_chars):
            return {**fallback, "generation_mode": "heuristic"}
        try:
            parsed = self._call_vault_model_json(
                GENERATE_PAGE_PROMPT.format(
                    title=title,
                    url=url,
                    topic=topic,
                    analysis_json=json.dumps(analysis, ensure_ascii=False, indent=2),
                    content=raw_text[: self.max_content_chars],
                )
            )
        except Exception:
            parsed = {}
        merged = {
            **fallback,
            **{key: value for key, value in parsed.items() if value not in (None, "", [], {})},
        }
        merged["generation_mode"] = "model" if parsed else "heuristic"
        merged["summary_markdown"] = str(merged.get("summary_markdown") or fallback["summary_markdown"]).strip()
        merged["claims_markdown"] = str(merged.get("claims_markdown") or fallback["claims_markdown"]).strip()
        merged["evidence_markdown"] = str(merged.get("evidence_markdown") or fallback["evidence_markdown"]).strip()
        merged["backlink_lines"] = [str(item).strip() for item in merged.get("backlink_lines", []) if str(item).strip()]
        merged["review_items"] = [str(item).strip() for item in merged.get("review_items", []) if str(item).strip()]
        return merged

    def discover(
        self,
        *,
        urls: list[str],
        source: str,
        topic: str = "",
        max_results: int = 8,
    ) -> dict[str, Any]:
        candidates = self._normalize_urls(urls)

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []

        for url in candidates:
            if not self._is_web_url(url):
                rejected.append({"url": url, "reason": "invalid_scheme"})
                continue
            if not self._domain_allowed(url):
                rejected.append({"url": url, "reason": "domain_not_allowed"})
                continue
            accepted.append({"url": url, "source": source, "discovered_at": _utcnow_iso(), "topic": topic})
            if len(accepted) >= max(1, max_results):
                break

        for candidate in accepted:
            key = hashlib.sha256(candidate["url"].encode("utf-8")).hexdigest()
            self._manifest["candidates"][key] = {**candidate, "status": "discovered"}

        inbox_payload = {
            "source": source,
            "topic": topic,
            "generated_at": _utcnow_iso(),
            "candidates": accepted,
            "rejected": rejected,
            "candidate_count": len(accepted),
            "rejected_count": len(rejected),
        }
        inbox_name = f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}-discover.json"
        inbox_path = self.inbox_dir / inbox_name
        inbox_path.write_text(json.dumps(inbox_payload, indent=2), encoding="utf-8")
        self._manifest["last_run_summary"] = {
            "step": "discover",
            "candidate_count": len(accepted),
            "rejected_count": len(rejected),
            "queue_path": str(self.search_results_queue_path),
            "updated_at": _utcnow_iso(),
        }
        self._save_manifest()
        return {**inbox_payload, "inbox_path": str(inbox_path)}

    def enqueue_search_results(self, *, query: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        queue = self._load_queue()
        appended: list[dict[str, Any]] = []
        duplicates = 0
        skipped = 0
        now = _utcnow()
        dedupe_deadline = now - timedelta(hours=self.search_results_dedupe_window_hours)

        for result in results:
            if not isinstance(result, dict):
                skipped += 1
                continue
            extracted = str(result.get("extracted_content") or "").strip()
            url = str(result.get("url") or "").strip()
            if not extracted or not url:
                skipped += 1
                continue
            content_hash = hashlib.sha256(extracted.encode("utf-8")).hexdigest()
            duplicate_match = next(
                (
                    item
                    for item in queue
                    if str(item.get("url") or "") == url
                    and str(item.get("content_hash") or "") == content_hash
                    and str(item.get("status") or "") in {"queued", "claimed", "ingested"}
                    and datetime.fromisoformat(str(item.get("queued_at"))).replace(tzinfo=UTC) >= dedupe_deadline
                ),
                None,
            )
            if duplicate_match is not None:
                duplicates += 1
                continue

            entry = {
                "queue_id": f"queue-{uuid4().hex[:12]}",
                "queued_at": now.isoformat(),
                "source_tool": str(result.get("source_tool") or "web_search").strip() or "web_search",
                "query": query,
                "title": str(result.get("title") or "").strip(),
                "url": url,
                "snippet": str(result.get("snippet") or "").strip(),
                "extracted_content": extracted,
                "topic_tags": [str(item).strip() for item in result.get("topic_tags", []) if str(item).strip()],
                "concept_refs": [str(item).strip() for item in result.get("concept_refs", []) if str(item).strip()],
                "entity_refs": [str(item).strip() for item in result.get("entity_refs", []) if str(item).strip()],
                "target_synthesis_refs": [str(item).strip() for item in result.get("target_synthesis_refs", []) if str(item).strip()],
                "status": "queued",
                "reason": str(result.get("reason") or "enriched_web_search_result").strip() or "enriched_web_search_result",
                "content_hash": content_hash,
            }
            source_markdown_path = str(result.get("source_markdown_path") or "").strip()
            if source_markdown_path:
                entry["source_markdown_path"] = source_markdown_path
            metadata = result.get("metadata")
            if isinstance(metadata, dict) and metadata:
                entry["metadata"] = metadata
            queue.append(entry)
            appended.append(entry)

        self._save_queue(queue)
        return {
            "query": query,
            "appended_count": len(appended),
            "duplicate_count": duplicates,
            "skipped_count": skipped,
            "queue_path": str(self.search_results_queue_path),
            "items": appended,
        }

    def claim_search_queue_items(self, *, topic: str = "", max_items: int = 10) -> list[dict[str, Any]]:
        queue = self._load_queue()
        claimed: list[dict[str, Any]] = []
        topic_slug = self._topic_slug(topic) if topic.strip() else ""

        for item in queue:
            if str(item.get("status") or "") != "queued":
                continue
            if topic_slug:
                tags = [str(tag).strip() for tag in item.get("topic_tags", [])]
                text = f"{item.get('query', '')} {item.get('title', '')}".lower()
                if topic_slug not in tags and topic_slug not in text:
                    continue
            item["status"] = "claimed"
            item["claimed_at"] = _utcnow_iso()
            claimed.append(dict(item))
            if len(claimed) >= max(1, int(max_items)):
                break

        self._save_queue(queue)
        return claimed

    def _mark_queue_items(self, queue_ids: list[str], *, status: str, reason: str = "") -> None:
        if not queue_ids:
            return
        queue = self._load_queue()
        now = _utcnow_iso()
        queue_id_set = set(queue_ids)
        for item in queue:
            if str(item.get("queue_id") or "") not in queue_id_set:
                continue
            item["status"] = status
            item["updated_at"] = now
            if reason:
                item["reason"] = reason
        self._save_queue(queue)

    def requeue_claimed_items(self, queue_ids: list[str], *, reason: str = "ingest_failed_retry") -> None:
        """Return claimed items back to queued so a later ingest run can retry them."""
        if not queue_ids:
            return
        queue = self._load_queue()
        now = _utcnow_iso()
        queue_id_set = set(queue_ids)
        for item in queue:
            if str(item.get("queue_id") or "") not in queue_id_set:
                continue
            if str(item.get("status") or "") != "claimed":
                continue
            item["status"] = "queued"
            item["updated_at"] = now
            if reason:
                item["reason"] = reason
            item.pop("claimed_at", None)
        self._save_queue(queue)

    def requeue_all_claimed_items(self, *, reason: str = "orphaned_from_prior_run") -> int:
        """Return *every* item currently in 'claimed' state back to 'queued'.

        Used at ingest job start to recover from prior runs that died mid-flight
        (backend restart, crash, hard kill) and left items orphaned in 'claimed'
        with no live worker. Returns the number of items requeued.
        """
        queue = self._load_queue()
        now = _utcnow_iso()
        count = 0
        for item in queue:
            if str(item.get("status") or "") != "claimed":
                continue
            item["status"] = "queued"
            item["updated_at"] = now
            if reason:
                item["reason"] = reason
            item.pop("claimed_at", None)
            count += 1
        if count:
            self._save_queue(queue)
        return count

    def clear_queued_search_results(self, *, reason: str = "rejected_by_user") -> int:
        queue = self._load_queue()
        queued_ids = [str(item.get("queue_id") or "") for item in queue if str(item.get("status") or "") == "queued"]
        queued_ids = [queue_id for queue_id in queued_ids if queue_id]
        if not queued_ids:
            return 0
        self._mark_queue_items(queued_ids, status="rejected", reason=reason)
        return len(queued_ids)

    def dedupe_recent_queries(self, *, query_text: str, topic_tags: list[str] | None = None) -> dict[str, Any] | None:
        normalized_key = _query_id_for_identity(query_text, topic_tags or [])
        now = _utcnow()
        for record in self._manifest["queries"].values():
            if str(record.get("identity_key") or "") != normalized_key:
                continue
            expires_at = record.get("expires_at")
            if not expires_at:
                continue
            if datetime.fromisoformat(str(expires_at)).replace(tzinfo=UTC) < now:
                continue
            return record
        return None

    def write_query_note(
        self,
        *,
        query_text: str,
        topic_tags: list[str] | None = None,
        concept_refs: list[str] | None = None,
        synthesis_refs: list[str] | None = None,
        content: str = "",
    ) -> dict[str, Any]:
        topic_tags = [str(item).strip() for item in (topic_tags or []) if str(item).strip()]
        identity_key = _query_id_for_identity(query_text, topic_tags)
        existing = self.dedupe_recent_queries(query_text=query_text, topic_tags=topic_tags)
        if existing is not None:
            existing["last_seen_at"] = _utcnow_iso()
            self._manifest["queries"][str(existing["query_id"])] = existing
            self._save_manifest()
            return {"status": "deduped", "query_id": existing["query_id"], "path": existing["path"]}

        query_id = self._query_id_for_text(query_text)
        created_at = _utcnow()
        expires_at = created_at + timedelta(hours=self.query_retention_hours)
        path = self._compiled_query_path(query_id)
        payload = {
            "query_id": query_id,
            "query_text": query_text,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "status": "active",
            "topic_tags": topic_tags,
            "concept_refs": concept_refs or [],
            "synthesis_refs": synthesis_refs or [],
        }
        sections = [content.strip() or "## Summary\n\nTransient research note retained for anti-duplication purposes."]
        self._write_page(path=path, frontmatter=payload, title=query_text, sections=sections)
        record = {
            **payload,
            "identity_key": identity_key,
            "path": str(path),
            "last_seen_at": created_at.isoformat(),
        }
        self._manifest["queries"][query_id] = record
        self._manifest["dirty_pages"] = sorted(set(self._manifest["dirty_pages"]) | {"queries/index.md", "index.md"})
        self._index_document(
            doc_id=query_id,
            kind="query",
            title=query_text,
            path=path,
            text=content or query_text,
            tags=topic_tags,
        )
        self._save_manifest()
        return {"status": "created", "query_id": query_id, "path": str(path)}

    def expire_queries(self) -> dict[str, Any]:
        expired: list[str] = []
        now = _utcnow()
        for query_id, record in list(self._manifest["queries"].items()):
            expires_at = record.get("expires_at")
            if not expires_at:
                continue
            if datetime.fromisoformat(str(expires_at)).replace(tzinfo=UTC) > now:
                continue
            if str(record.get("status") or "") == "active":
                record["status"] = "expired"
                expired.append(query_id)
                path = Path(str(record.get("path") or ""))
                if path.exists():
                    frontmatter, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
                    frontmatter["status"] = "expired"
                    path.write_text(f"{_frontmatter_dump(frontmatter)}\n\n{body}", encoding="utf-8")
        if expired:
            self._save_manifest()
        return {"expired_count": len(expired), "expired_query_ids": expired}

    def _update_reference_page(
        self,
        *,
        path: Path,
        title: str,
        kind: str,
        source_id: str,
        source_title: str,
        topic_tags: list[str],
        extra_frontmatter: dict[str, Any] | None = None,
        open_questions: list[str] | None = None,
    ) -> None:
        frontmatter: dict[str, Any]
        body: str
        if path.exists():
            frontmatter, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        else:
            frontmatter, body = {}, ""
        source_refs = {str(item) for item in frontmatter.get("source_refs", []) if str(item).strip()}
        source_refs.add(source_id)
        frontmatter.update(
            {
                "id": path.stem,
                "kind": kind,
                "last_supported_by": source_id,
                "last_reviewed_at": _utcnow_iso(),
                "freshness_window_days": int(frontmatter.get("freshness_window_days") or 30),
                "source_refs": sorted(source_refs),
                "topic_tags": sorted(set(topic_tags) | set(frontmatter.get("topic_tags", []))),
                "open_questions": open_questions or frontmatter.get("open_questions", []),
            }
        )
        if extra_frontmatter:
            frontmatter.update(extra_frontmatter)

        sections = [
            "## Evidence\n\n" + "\n".join(f"- Supports source `{ref}`" for ref in frontmatter["source_refs"]),
        ]
        if body.strip():
            sections.insert(0, body.strip())
        else:
            sections.insert(0, f"## Overview\n\nMaintained {kind} page derived from ingested sources.")
        self._write_page(path=path, frontmatter=frontmatter, title=title, sections=sections)
        self._index_document(
            doc_id=path.stem,
            kind=kind,
            title=title,
            path=path,
            text=f"{title}\n\n{sections[0]}\n\n{source_title}",
            tags=frontmatter.get("topic_tags", []),
        )

    def _update_synthesis_page(
        self,
        *,
        topic: str,
        source_id: str,
        source_title: str,
        topic_tags: list[str],
        concept_refs: list[str],
        entity_refs: list[str],
        source_excerpt: str,
        target_synthesis_refs: list[str] | None = None,
    ) -> list[str]:
        synthesis_refs = list(target_synthesis_refs or [])
        if not synthesis_refs:
            synthesis_refs.append(self._topic_slug(topic or source_title))

        for synthesis_ref in synthesis_refs:
            path = self._compiled_synthesis_path(_slugify(synthesis_ref))
            open_questions = []
            if not path.exists():
                open_questions = [f"What new evidence is still missing for {synthesis_ref}?"]
            self._update_reference_page(
                path=path,
                title=synthesis_ref.replace("-", " ").title(),
                kind="synthesis",
                source_id=source_id,
                source_title=source_title,
                topic_tags=topic_tags,
                extra_frontmatter={
                    "concept_refs": concept_refs,
                    "entity_refs": entity_refs,
                },
                open_questions=open_questions,
            )
            frontmatter, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            if "## Latest Supporting Evidence" not in body:
                body = f"{body.rstrip()}\n\n## Latest Supporting Evidence\n\n"
            evidence_line = f"- `{_utcnow_iso()}` {source_title}: {source_excerpt[:280]}"
            if evidence_line not in body:
                body = body.rstrip() + "\n" + evidence_line + "\n"
            path.write_text(f"{_frontmatter_dump(frontmatter)}\n\n{body.lstrip()}", encoding="utf-8")
            self._index_document(
                doc_id=path.stem,
                kind="synthesis",
                title=frontmatter.get("id", path.stem).replace("-", " ").title(),
                path=path,
                text=body,
                tags=frontmatter.get("topic_tags", []),
            )
            self._manifest["topic_syntheses"][_slugify(synthesis_ref)] = {
                "path": str(path),
                "last_updated_at": _utcnow_iso(),
                "topic_tags": topic_tags,
            }

        return [_slugify(item) for item in synthesis_refs]

    def reingest_if_changed(
        self,
        *,
        url: str,
        source: str,
        topic: str = "",
        pre_extracted_content: str | None = None,
        queue_entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_id = self._source_id_for_url(url)
        source_record = self._manifest["sources"].get(source_id, {})
        fetched_at = _utcnow()

        queue_markdown_path = str((queue_entry or {}).get("source_markdown_path") or "").strip()
        queue_markdown_content = ""
        if queue_markdown_path:
            try:
                queue_markdown_content = Path(queue_markdown_path).expanduser().resolve().read_text(encoding="utf-8")
            except Exception:
                queue_markdown_content = ""

        if queue_markdown_content or pre_extracted_content:
            markdown_payload = queue_markdown_content or pre_extracted_content
            raw_text = markdown_payload[: self.max_content_chars]
            title = str((queue_entry or {}).get("title") or url).strip() or url
            raw_payload = markdown_payload
            raw_extension = ".md"
        else:
            response = httpx.get(url, timeout=20.0, follow_redirects=True)
            response.raise_for_status()
            html = response.text
            title = _extract_title(html, fallback=url)
            raw_text = _strip_html(html)[: self.max_content_chars]
            raw_payload = html
            raw_extension = ".html"

        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        hash_history = list(source_record.get("hash_history", []))
        if hash_history and hash_history[-1] == content_hash:
            source_record.update(
                {
                    "source_id": source_id,
                    "url": url,
                    "title": title,
                    "status": "skipped_unchanged",
                    "last_seen_at": _utcnow_iso(),
                }
            )
            self._manifest["sources"][source_id] = source_record
            self._record_trust_decision(
                source_id=source_id,
                url=url,
                score=float(source_record.get("trust_score") or 0.0),
                reasons=["content_hash_unchanged"],
                decision="skipped_unchanged",
            )
            return {"status": "skipped_unchanged", "source_id": source_id, "url": url}

        trust_score, trust_reasons = self._trust_score(url=url, text=raw_text)
        raw_package_dir = self._raw_package_dir(source_id, fetched_at)
        raw_package_dir.mkdir(parents=True, exist_ok=True)
        raw_source_path = raw_package_dir / f"source{raw_extension}"
        raw_source_path.write_text(raw_payload, encoding="utf-8")
        raw_metadata_path = raw_package_dir / "metadata.json"

        topic_tags = self._topic_tags(topic, queue_entry)
        concept_refs = [str(item).strip() for item in (queue_entry or {}).get("concept_refs", []) if str(item).strip()]
        entity_refs = [str(item).strip() for item in (queue_entry or {}).get("entity_refs", []) if str(item).strip()]
        target_synthesis_refs = [
            str(item).strip() for item in (queue_entry or {}).get("target_synthesis_refs", []) if str(item).strip()
        ]
        analysis = self._analyze_source(
            title=title,
            url=url,
            topic=topic,
            raw_text=raw_text,
            topic_tags=topic_tags,
            concept_refs=concept_refs,
            entity_refs=entity_refs,
            target_synthesis_refs=target_synthesis_refs,
        )
        topic_tags = self._topic_tags(topic, {"topic_tags": analysis.get("topic_tags", topic_tags)})
        concept_refs = list(dict.fromkeys(concept_refs + [str(item).strip() for item in analysis.get("concepts", []) if str(item).strip()]))
        entity_refs = list(dict.fromkeys(entity_refs + [str(item).strip() for item in analysis.get("entities", []) if str(item).strip()]))
        target_synthesis_refs = list(
            dict.fromkeys(target_synthesis_refs + [str(item).strip() for item in analysis.get("synthesis_refs", []) if str(item).strip()])
        )
        generated_page = self._generate_source_sections(
            title=title,
            url=url,
            topic=topic,
            raw_text=raw_text,
            analysis=analysis,
        )

        raw_metadata = {
            "source_id": source_id,
            "source": source,
            "url": url,
            "title": title,
            "fetched_at": fetched_at.isoformat(),
            "content_hash": content_hash,
            "mime_type": "text/markdown" if raw_extension == ".md" else "text/html",
            "trust_score": round(trust_score, 4),
            "trust_reasons": trust_reasons,
            "topic_tags": topic_tags,
            "concept_refs": concept_refs,
            "entity_refs": entity_refs,
            "analysis": analysis,
            "generated_page": {
                "generation_mode": generated_page.get("generation_mode"),
                "review_items": generated_page.get("review_items", []),
            },
        }
        raw_metadata_path.write_text(json.dumps(raw_metadata, indent=2), encoding="utf-8")

        if trust_score < self.min_trust_score:
            source_record.update(
                {
                    "source_id": source_id,
                    "url": url,
                    "title": title,
                    "status": "rejected_for_trust",
                    "trust_score": trust_score,
                    "last_seen_at": _utcnow_iso(),
                    "raw_path": str(raw_source_path),
                    "metadata_path": str(raw_metadata_path),
                }
            )
            self._manifest["sources"][source_id] = source_record
            self._record_trust_decision(
                source_id=source_id,
                url=url,
                score=trust_score,
                reasons=trust_reasons,
                decision="rejected_for_trust",
            )
            return {
                "status": "rejected_for_trust",
                "source_id": source_id,
                "url": url,
                "score": trust_score,
                "raw_path": str(raw_source_path),
            }

        compiled_source_path = self._compiled_source_path(source_id)
        synthesis_refs = self._update_synthesis_page(
            topic=topic,
            source_id=source_id,
            source_title=title,
            topic_tags=topic_tags,
            concept_refs=concept_refs,
            entity_refs=entity_refs,
            source_excerpt=raw_text,
            target_synthesis_refs=target_synthesis_refs,
        )
        for concept_ref in concept_refs:
            self._update_reference_page(
                path=self._compiled_concept_path(concept_ref),
                title=concept_ref.replace("-", " ").title(),
                kind="concept",
                source_id=source_id,
                source_title=title,
                topic_tags=topic_tags,
            )
        for entity_ref in entity_refs:
            self._update_reference_page(
                path=self._compiled_entity_path(entity_ref),
                title=entity_ref.replace("-", " ").title(),
                kind="entity",
                source_id=source_id,
                source_title=title,
                topic_tags=topic_tags,
            )

        source_frontmatter = {
            "source_id": source_id,
            "source_url": url,
            "fetched_at": fetched_at.isoformat(),
            "trust_status": "accepted",
            "trust_score": round(trust_score, 4),
            "raw_path": str(raw_source_path),
            "metadata_path": str(raw_metadata_path),
            "topic_tags": topic_tags,
            "entity_refs": entity_refs,
            "concept_refs": concept_refs,
            "synthesis_refs": synthesis_refs,
            "last_reviewed_at": _utcnow_iso(),
            "analysis_mode": analysis.get("analysis_mode"),
            "generation_mode": generated_page.get("generation_mode"),
            "open_questions": analysis.get("open_questions", []),
            "gap_queries": analysis.get("gap_queries", []),
        }
        sections = [
            "## Summary\n\n" + str(generated_page.get("summary_markdown") or raw_text[:1200]).strip(),
            "## Claims\n\n" + str(generated_page.get("claims_markdown") or "").strip(),
            "## Evidence\n\n" + str(generated_page.get("evidence_markdown") or "").strip(),
            "## Backlinks\n\n"
            + "\n".join([f"- {line}" for line in generated_page.get("backlink_lines", [])] or [f"- [[../syntheses/{ref}.md]]" for ref in synthesis_refs] or ["- None"]),
            "## Review Items\n\n" + "\n".join(f"- {item}" for item in (generated_page.get("review_items", [])[:10] or analysis.get("open_questions", [])[:10] or ["None"])),
            "## Gap Queries\n\n" + "\n".join(f"- {item}" for item in (analysis.get("gap_queries", [])[:10] or ["None"])),
        ]
        self._write_page(path=compiled_source_path, frontmatter=source_frontmatter, title=title, sections=sections)

        hash_history.append(content_hash)
        source_record.update(
            {
                "source_id": source_id,
                "url": url,
                "title": title,
                "status": "ingested",
                "trust_score": trust_score,
                "hash_history": hash_history[-10:],
                "last_ingested_at": _utcnow_iso(),
                "compiled_path": str(compiled_source_path),
                "raw_path": str(raw_source_path),
                "metadata_path": str(raw_metadata_path),
                "source": source,
                "topic_tags": topic_tags,
                "source_tool": str((queue_entry or {}).get("source_tool") or source),
                "analysis_mode": analysis.get("analysis_mode"),
                "generation_mode": generated_page.get("generation_mode"),
            }
        )
        self._manifest["sources"][source_id] = source_record
        self._record_trust_decision(
            source_id=source_id,
            url=url,
            score=trust_score,
            reasons=trust_reasons,
            decision="accepted",
        )

        dependencies = set(self._manifest["source_dependencies"].get(source_id, []))
        dependencies.update(
            {
                "02_compiled/index.md",
                "02_compiled/log.md",
                "02_compiled/sources/index.md",
                "02_compiled/syntheses/index.md",
                "02_compiled/queries/index.md",
            }
        )
        self._manifest["source_dependencies"][source_id] = sorted(dependencies)
        self._manifest["dirty_pages"] = sorted(set(self._manifest["dirty_pages"]) | dependencies)

        self._index_document(
            doc_id=source_id,
            kind="source",
            title=title,
            path=compiled_source_path,
            text="\n\n".join(
                [
                    str(analysis.get("summary") or ""),
                    "\n".join(str(item) for item in analysis.get("key_claims", [])[:8]),
                    raw_text,
                ]
            ),
            tags=topic_tags,
        )
        for question in analysis.get("open_questions", [])[:10]:
            question_text = str(question).strip()
            if not question_text:
                continue
            task_name = f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-{_slugify(question_text)[:48] or 'review'}-vault-review.md"
            task_path = self.task_review_dir / task_name
            if not task_path.exists():
                task_path.write_text(
                    f"# Vault Review Item\n\n- Source: `{title}`\n- URL: {url}\n- Review: {question_text}\n",
                    encoding="utf-8",
                )
        return {
            "status": "ingested",
            "source_id": source_id,
            "url": url,
            "score": trust_score,
            "compiled_path": str(compiled_source_path),
            "raw_path": str(raw_source_path),
            "analysis_mode": analysis.get("analysis_mode"),
            "generation_mode": generated_page.get("generation_mode"),
        }

    def ingest(
        self,
        *,
        urls: list[str],
        source: str,
        topic: str = "",
        queue_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # Strict embedding gate: do not ingest any sources unless /embeddings is reachable.
        search_service = UnifiedVaultSearchService(self.vault_root)
        try:
            vector_preflight = search_service.ensure_vector_ready()
        except Exception as exc:
            queue_item_ids = [str(item.get("queue_id") or "") for item in (queue_items or []) if str(item.get("queue_id") or "").strip()]
            self.requeue_claimed_items(queue_item_ids, reason="embedding_unavailable_retry")
            report = {
                "source": source,
                "topic": topic,
                "status": "deferred_embedding_unavailable",
                "processed_count": 0,
                "ingested_count": 0,
                "skipped_unchanged_count": 0,
                "rejected_for_trust_count": 0,
                "rejected_for_policy_count": 0,
                "queue_items_claimed": len(queue_items or []),
                "queue_items_requeued": len(queue_item_ids),
                "error": str(exc),
            }
            report_path = self.ingest_reports_dir / f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-ingest.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            self._manifest["last_run_summary"] = {
                "step": "ingest",
                "status": report["status"],
                "updated_at": _utcnow_iso(),
                "queue_items_claimed": report["queue_items_claimed"],
                "queue_items_requeued": report["queue_items_requeued"],
            }
            self._save_manifest()
            return report

        normalized = self._normalize_urls(urls)
        ingested: list[dict[str, Any]] = []
        skipped_unchanged: list[dict[str, Any]] = []
        rejected_for_trust: list[dict[str, Any]] = []
        rejected_for_policy: list[dict[str, Any]] = []
        queue_item_ids: list[str] = []

        for item in queue_items or []:
            queue_item_ids.append(str(item.get("queue_id") or ""))
            try:
                result = self.reingest_if_changed(
                    url=str(item.get("url") or ""),
                    source=source,
                    topic=topic or str(item.get("query") or ""),
                    pre_extracted_content=str(item.get("extracted_content") or ""),
                    queue_entry=item,
                )
            except Exception as exc:
                rejected_for_policy.append({"url": str(item.get("url") or ""), "reason": f"queue_ingest_error:{exc}"})
                continue
            status = result.get("status")
            if status == "ingested":
                ingested.append(result)
            elif status == "skipped_unchanged":
                skipped_unchanged.append(result)
            elif status == "rejected_for_trust":
                rejected_for_trust.append(result)

        for url in normalized:
            if not self._is_web_url(url):
                rejected_for_policy.append({"url": url, "reason": "invalid_scheme"})
                continue
            if not self._domain_allowed(url):
                rejected_for_policy.append({"url": url, "reason": "domain_not_allowed"})
                continue
            try:
                result = self.reingest_if_changed(url=url, source=source, topic=topic)
            except Exception as exc:
                rejected_for_policy.append({"url": url, "reason": f"fetch_error:{exc}"})
                continue
            status = result.get("status")
            if status == "ingested":
                ingested.append(result)
            elif status == "skipped_unchanged":
                skipped_unchanged.append(result)
            elif status == "rejected_for_trust":
                rejected_for_trust.append(result)

        try:
            compile_report = self.compile_incremental()
        except Exception:
            if queue_item_ids:
                self.requeue_claimed_items(queue_item_ids, reason="compile_failed_retry")
            raise

        if queue_item_ids:
            ingested_ids = {item["url"] for item in ingested if item.get("url")}
            skipped_ids = {item["url"] for item in skipped_unchanged if item.get("url")}
            rejected_ids = {item["url"] for item in rejected_for_trust if item.get("url")}
            policy_rejected_ids = {item["url"] for item in rejected_for_policy if item.get("url")}
            queue_to_ingested = [str(item.get("queue_id")) for item in (queue_items or []) if str(item.get("url") or "") in ingested_ids]
            queue_to_skipped = [str(item.get("queue_id")) for item in (queue_items or []) if str(item.get("url") or "") in skipped_ids]
            queue_to_rejected = [str(item.get("queue_id")) for item in (queue_items or []) if str(item.get("url") or "") in rejected_ids]
            queue_to_failed = [str(item.get("queue_id")) for item in (queue_items or []) if str(item.get("url") or "") in policy_rejected_ids]
            self._mark_queue_items(queue_to_ingested, status="ingested", reason="converted_to_vault_source")
            self._mark_queue_items(queue_to_skipped, status="ingested", reason="content_hash_unchanged")
            self._mark_queue_items(queue_to_rejected, status="rejected", reason="trust_score_below_threshold")
            self._mark_queue_items(queue_to_failed, status="rejected", reason="policy_or_fetch_error")
            # Final safety net: any queue_item with a known queue_id that didn't end up
            # in any of the buckets above must not be left in "claimed" state.
            handled = set(queue_to_ingested) | set(queue_to_skipped) | set(queue_to_rejected) | set(queue_to_failed)
            unhandled = [qid for qid in queue_item_ids if qid and qid not in handled]
            if unhandled:
                self.requeue_claimed_items(unhandled, reason="unhandled_status_retry")
        report = {
            "source": source,
            "topic": topic,
            "status": "completed",
            "processed_count": len(normalized) + len(queue_items or []),
            "ingested_count": len(ingested),
            "skipped_unchanged_count": len(skipped_unchanged),
            "rejected_for_trust_count": len(rejected_for_trust),
            "rejected_for_policy_count": len(rejected_for_policy),
            "ingested": ingested,
            "skipped_unchanged": skipped_unchanged,
            "rejected_for_trust": rejected_for_trust,
            "rejected_for_policy": rejected_for_policy,
            "queue_items_claimed": len(queue_items or []),
            "vector_preflight": vector_preflight,
            "compile": compile_report,
        }
        report_path = self.ingest_reports_dir / f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-ingest.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self._manifest["last_run_summary"] = {
            "step": "ingest",
            "updated_at": _utcnow_iso(),
            **{k: v for k, v in report.items() if k.endswith("_count") or k == "queue_items_claimed"},
        }
        self._save_manifest()
        return report

    def enqueue_clip(
        self,
        *,
        url: str,
        title: str,
        markdown: str,
        topic: str = "",
        topic_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_url = str(url).strip()
        if not normalized_url or not self._is_web_url(normalized_url):
            raise ValueError("A valid http(s) URL is required for vault clips.")
        rendered_markdown = markdown.strip()
        if not rendered_markdown:
            raise ValueError("Clip markdown cannot be empty.")
        result = self.enqueue_search_results(
            query=topic or title or normalized_url,
            results=[
                {
                    "title": title.strip() or normalized_url,
                    "url": normalized_url,
                    "snippet": rendered_markdown[:500],
                    "extracted_content": rendered_markdown,
                    "topic_tags": topic_tags or self._topic_tags(topic),
                    "source_tool": "browser_clipper",
                    "reason": "clipped_page",
                    "metadata": {"ingest_origin": "browser_clipper"},
                }
            ],
        )
        self._manifest["last_run_summary"] = {
            "step": "clip",
            "updated_at": _utcnow_iso(),
            "appended_count": int(result.get("appended_count") or 0),
        }
        self._save_manifest()
        return result

    def save_document(
        self,
        *,
        title: str,
        content: str,
        topic: str = "",
        topic_tags: list[str] | None = None,
        source_url: str = "",
        source_thread_id: str = "",
    ) -> dict[str, Any]:
        normalized_title = title.strip()
        normalized_content = content.strip()
        if not normalized_title:
            raise ValueError("Title is required.")
        if not normalized_content:
            raise ValueError("Content is required.")
        slug = _slugify(normalized_title) or "saved-note"
        synthetic_url = source_url.strip() or f"https://vault.local/saved/{slug}"
        queue_entry = {
            "title": normalized_title,
            "topic_tags": topic_tags or self._topic_tags(topic or normalized_title),
            "target_synthesis_refs": [self._topic_slug(topic or normalized_title)],
            "source_tool": "explicit_save",
            "metadata": {"source_thread_id": source_thread_id.strip()} if source_thread_id.strip() else {},
        }
        result = self.reingest_if_changed(
            url=synthetic_url,
            source="explicit_save",
            topic=topic or normalized_title,
            pre_extracted_content=normalized_content,
            queue_entry=queue_entry,
        )
        self.compile_incremental()
        self._manifest["last_run_summary"] = {
            "step": "save",
            "updated_at": _utcnow_iso(),
            "source_id": result.get("source_id"),
            "status": result.get("status"),
        }
        self._save_manifest()
        return result

    def get_graph(self, *, limit: int = 200) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        edge_seen: set[tuple[str, str, str]] = set()

        def ensure_node(node_id: str, *, label: str, kind: str, path: str, tags: list[str] | None = None) -> None:
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id,
                    "label": label,
                    "kind": kind,
                    "path": path,
                    "tags": tags or [],
                    "degree": 0,
                }

        for category_dir in sorted(self.compiled_dir.iterdir() if self.compiled_dir.exists() else []):
            if not category_dir.is_dir():
                continue
            category = category_dir.name
            for path in sorted(category_dir.glob("*.md")):
                if path.name == "index.md":
                    continue
                frontmatter, _body = _parse_frontmatter(path.read_text(encoding="utf-8"))
                stem = path.stem
                node_id = f"{category}:{stem}"
                ensure_node(
                    node_id,
                    label=str(frontmatter.get("title") or stem.replace("-", " ").title()),
                    kind=category,
                    path=str(path),
                    tags=[str(item) for item in frontmatter.get("topic_tags", []) if str(item).strip()],
                )

                for ref in frontmatter.get("source_refs", []) if isinstance(frontmatter.get("source_refs"), list) else []:
                    target_id = f"sources:{_slugify(str(ref))}"
                    ensure_node(target_id, label=str(ref), kind="sources", path="")
                    edge_key = (node_id, target_id, "source_ref")
                    if edge_key not in edge_seen:
                        edge_seen.add(edge_key)
                        edges.append({"source": node_id, "target": target_id, "type": "source_ref"})
                for field, kind in (("concept_refs", "concepts"), ("entity_refs", "entities"), ("synthesis_refs", "syntheses")):
                    raw_refs = frontmatter.get(field, [])
                    if not isinstance(raw_refs, list):
                        continue
                    for ref in raw_refs:
                        target_slug = _slugify(str(ref))
                        if not target_slug:
                            continue
                        target_id = f"{kind}:{target_slug}"
                        ensure_node(target_id, label=str(ref), kind=kind, path="")
                        edge_key = (node_id, target_id, field)
                        if edge_key in edge_seen:
                            continue
                        edge_seen.add(edge_key)
                        edges.append({"source": node_id, "target": target_id, "type": field})

        for edge in edges:
            if edge["source"] in nodes:
                nodes[edge["source"]]["degree"] += 1
            if edge["target"] in nodes:
                nodes[edge["target"]]["degree"] += 1

        ranked_nodes = sorted(nodes.values(), key=lambda item: (int(item.get("degree") or 0), str(item.get("label") or "")), reverse=True)
        limited_nodes = ranked_nodes[: max(1, int(limit))]
        node_ids = {str(item["id"]) for item in limited_nodes}
        limited_edges = [edge for edge in edges if edge["source"] in node_ids and edge["target"] in node_ids]
        category_counts: dict[str, int] = {}
        for item in limited_nodes:
            kind = str(item.get("kind") or "unknown")
            category_counts[kind] = category_counts.get(kind, 0) + 1

        return {
            "generated_at": _utcnow_iso(),
            "counts": {
                "nodes": len(limited_nodes),
                "edges": len(limited_edges),
                "categories": category_counts,
            },
            "nodes": limited_nodes,
            "edges": limited_edges,
            "highlights": {
                "top_connected": limited_nodes[:10],
                "orphans": [item for item in limited_nodes if int(item.get("degree") or 0) == 0][:10],
            },
        }

    def _render_index_for_dir(self, title: str, directory: Path) -> str:
        lines = [f"# {title}", ""]
        for path in sorted(directory.glob("*.md")):
            if path.name == "index.md":
                continue
            lines.append(f"- [{path.stem.replace('-', ' ').title()}]({path.name})")
        return "\n".join(lines) + "\n"

    def _render_main_index(self) -> str:
        lines = [
            "# Knowledge Vault Index",
            "",
            f"Updated: {_utcnow_iso()}",
            "",
            "## Compiled Areas",
            "- [Sources](sources/index.md)",
            "- [Concepts](concepts/index.md)",
            "- [Entities](entities/index.md)",
            "- [Syntheses](syntheses/index.md)",
            "- [Queries](queries/index.md)",
            "",
            "## Recent Sources",
        ]
        sources = sorted(
            self._manifest["sources"].values(),
            key=lambda item: str(item.get("last_ingested_at") or ""),
            reverse=True,
        )
        for item in sources[:20]:
            title = str(item.get("title") or item.get("url") or "Untitled")
            path = Path(str(item.get("compiled_path") or ""))
            if path.name:
                lines.append(f"- [{title}](sources/{path.name})")
        return "\n".join(lines) + "\n"

    def _render_log(self, changed_pages: list[str]) -> str:
        lines = [
            "# Knowledge Vault Log",
            "",
            f"Compiled at: {_utcnow_iso()}",
            f"Changed pages: {len(changed_pages)}",
            "",
        ]
        lines.extend(f"- {page}" for page in changed_pages)
        return "\n".join(lines) + "\n"

    def compile_incremental(self) -> dict[str, Any]:
        dirty_pages = list(dict.fromkeys(self._manifest.get("dirty_pages", [])))
        compiled_pages: list[str] = []

        indexes = {
            "02_compiled/index.md": (self.compiled_index_path, self._render_main_index()),
            "02_compiled/log.md": (self.compiled_log_path, self._render_log(dirty_pages or ["bootstrap"])),
            "02_compiled/sources/index.md": (
                self.compiled_sources_dir / "index.md",
                self._render_index_for_dir("Sources", self.compiled_sources_dir),
            ),
            "02_compiled/concepts/index.md": (
                self.compiled_concepts_dir / "index.md",
                self._render_index_for_dir("Concepts", self.compiled_concepts_dir),
            ),
            "02_compiled/entities/index.md": (
                self.compiled_entities_dir / "index.md",
                self._render_index_for_dir("Entities", self.compiled_entities_dir),
            ),
            "02_compiled/syntheses/index.md": (
                self.compiled_syntheses_dir / "index.md",
                self._render_index_for_dir("Syntheses", self.compiled_syntheses_dir),
            ),
            "02_compiled/queries/index.md": (
                self.compiled_queries_dir / "index.md",
                self._render_index_for_dir("Queries", self.compiled_queries_dir),
            ),
        }

        if not dirty_pages:
            dirty_pages = list(indexes.keys())

        for key, (path, content) in indexes.items():
            if key not in dirty_pages and path.exists():
                continue
            path.write_text(content, encoding="utf-8")
            compiled_pages.append(key)
            self._index_document(
                doc_id=key,
                kind="index",
                title=path.stem.replace("-", " ").title(),
                path=path,
                text=content,
                tags=["index"],
            )

        compile_report = {
            "status": "compiled",
            "compiled_count": len(compiled_pages),
            "compiled_pages": compiled_pages,
            "index_path": str(self.compiled_index_path),
            "log_path": str(self.compiled_log_path),
        }
        search_service = UnifiedVaultSearchService(self.vault_root)
        vector_status = search_service.vector_status()
        compile_report["vector_index"] = vector_status
        report_path = self.compile_reports_dir / f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-compile.json"
        report_path.write_text(json.dumps(compile_report, indent=2), encoding="utf-8")
        self._manifest["dirty_pages"] = []
        self._manifest["last_compile_at"] = _utcnow_iso()
        self._manifest["last_run_summary"] = {"step": "compile", "updated_at": _utcnow_iso(), **compile_report}
        self._save_manifest()
        return compile_report

    def compile_indexes(self) -> dict[str, Any]:
        return self.compile_incremental()

    def lint_vault(self, *, freshness_window_days: int = 30) -> dict[str, Any]:
        expired_queries = self.expire_queries()
        stale_syntheses: list[str] = []
        orphan_pages: list[str] = []
        missing_backlinks: list[str] = []
        contradictions: list[str] = []
        open_questions: list[str] = []

        now = _utcnow()
        for path in sorted(self.compiled_syntheses_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            frontmatter, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            reviewed_at_raw = frontmatter.get("last_reviewed_at")
            reviewed_at = (
                datetime.fromisoformat(str(reviewed_at_raw)).replace(tzinfo=UTC)
                if reviewed_at_raw
                else now - timedelta(days=freshness_window_days + 1)
            )
            freshness = int(frontmatter.get("freshness_window_days") or freshness_window_days)
            if reviewed_at < now - timedelta(days=freshness):
                stale_syntheses.append(path.name)
            if not frontmatter.get("source_refs"):
                orphan_pages.append(path.name)
            if not frontmatter.get("open_questions"):
                missing_backlinks.append(path.name)
            if "contradiction" in body.lower():
                contradictions.append(path.name)
            for question in frontmatter.get("open_questions", []):
                open_questions.append(f"{path.name}: {question}")

        for directory in (self.compiled_concepts_dir, self.compiled_entities_dir):
            for path in sorted(directory.glob("*.md")):
                if path.name == "index.md":
                    continue
                frontmatter, _ = _parse_frontmatter(path.read_text(encoding="utf-8"))
                if not frontmatter.get("source_refs"):
                    orphan_pages.append(path.name)

        report = {
            "generated_at": _utcnow_iso(),
            "stale_syntheses_count": len(stale_syntheses),
            "orphan_pages_count": len(orphan_pages),
            "missing_backlinks_count": len(missing_backlinks),
            "contradictions_count": len(contradictions),
            "open_questions_count": len(open_questions),
            "expired_queries_count": expired_queries["expired_count"],
            "stale_syntheses": stale_syntheses,
            "orphan_pages": orphan_pages,
            "missing_backlinks": missing_backlinks,
            "contradictions": contradictions,
            "open_questions": open_questions,
            "queue_backlog_count": len([item for item in self._load_queue() if str(item.get("status") or "") == "queued"]),
        }
        report_path = self.lint_reports_dir / f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-lint.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if report["open_questions_count"] or report["stale_syntheses_count"] or report["orphan_pages_count"]:
            task_path = self.task_review_dir / f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-vault-lint.md"
            task_path.write_text(
                "# Vault Lint Review\n\n"
                + "\n".join(f"- {item}" for item in open_questions[:20] or stale_syntheses[:20] or orphan_pages[:20]),
                encoding="utf-8",
            )
        self._manifest["last_lint_at"] = _utcnow_iso()
        self._manifest["last_run_summary"] = {"step": "lint", "updated_at": _utcnow_iso(), **report}
        self._save_manifest()
        return report

    def _collect_lint_snapshot(self, *, freshness_window_days: int = 30) -> dict[str, Any]:
        stale_syntheses = 0
        contradictions = 0
        open_questions = 0
        now = _utcnow()
        for path in sorted(self.compiled_syntheses_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            frontmatter, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            reviewed_at_raw = frontmatter.get("last_reviewed_at")
            reviewed_at = (
                datetime.fromisoformat(str(reviewed_at_raw)).replace(tzinfo=UTC)
                if reviewed_at_raw
                else now - timedelta(days=freshness_window_days + 1)
            )
            freshness = int(frontmatter.get("freshness_window_days") or freshness_window_days)
            if reviewed_at < now - timedelta(days=freshness):
                stale_syntheses += 1
            if "contradiction" in body.lower():
                contradictions += 1
            if isinstance(frontmatter.get("open_questions"), list):
                open_questions += len(frontmatter.get("open_questions", []))
        queue_backlog = len([item for item in self._load_queue() if str(item.get("status") or "") == "queued"])
        return {
            "stale_syntheses_count": stale_syntheses,
            "contradictions_count": contradictions,
            "open_questions_count": open_questions,
            "queue_backlog_count": queue_backlog,
        }

    def synthesize_knowledge_graph(
        self,
        *,
        objective_id: str,
        topic: str = "",
        graph_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        objective = self._ensure_objective(objective_id=objective_id, topic=topic)
        lint = self._collect_lint_snapshot()
        graph_payload = graph_evidence or {}
        findings: list[str] = []
        gaps: list[str] = []
        contradictions: list[str] = []
        next_actions: list[str] = []

        queued = lint.get("queue_backlog_count", 0)
        if isinstance(queued, int) and queued > 0:
            gaps.append(f"{queued} queued search results pending ingestion.")
            next_actions.append("Run vault_ingest with queue items for this objective.")

        stale = lint.get("stale_syntheses", [])
        if isinstance(stale, list) and stale:
            gaps.append(f"{len(stale)} stale synthesis pages require review.")
            next_actions.append("Refresh stale synthesis pages with current evidence.")

        open_questions = lint.get("open_questions", [])
        if isinstance(open_questions, list) and open_questions:
            gaps.append(f"{len(open_questions)} open questions remain unresolved.")
            next_actions.append("Address top-priority open questions in synthesis pages.")

        lint_contradictions = lint.get("contradictions", [])
        if isinstance(lint_contradictions, list):
            contradictions.extend(str(item) for item in lint_contradictions[:20])

        graph_summary = graph_payload.get("summary")
        if isinstance(graph_summary, str) and graph_summary.strip():
            findings.append(graph_summary.strip())
        graph_entities = graph_payload.get("entities")
        if isinstance(graph_entities, list) and graph_entities:
            findings.append(f"Graph evidence references {len(graph_entities)} entities for this objective.")

        if not findings:
            findings.append("Vault evidence compiled; no additional graph summary available yet.")
        if not gaps:
            next_actions.append("Maintain periodic lint and freshness checks.")

        report = {
            "generated_at": _utcnow_iso(),
            "objective_id": objective_id,
            "topic": topic or objective.get("topic", ""),
            "findings": findings,
            "gaps": gaps,
            "contradictions": contradictions,
            "next_actions": next_actions,
            "graph_evidence": graph_payload,
            "lint_snapshot": {
                "stale_syntheses_count": lint.get("stale_syntheses_count", 0),
                "open_questions_count": lint.get("open_questions_count", 0),
                "contradictions_count": lint.get("contradictions_count", 0),
                "queue_backlog_count": lint.get("queue_backlog_count", 0),
            },
        }
        report_path = self.synthesis_reports_dir / f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-synthesis.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self._append_action_history(
            {
                "objective_id": objective_id,
                "topic": report["topic"],
                "phase": "synthesize_knowledge_graph",
                "status": "completed",
                "report_path": str(report_path),
            }
        )
        objective["updated_at"] = _utcnow_iso()
        objective["last_action_at"] = objective["updated_at"]
        self._manifest["last_run_summary"] = {
            "step": "synthesize_knowledge_graph",
            "updated_at": _utcnow_iso(),
            "objective_id": objective_id,
            "findings_count": len(findings),
            "gaps_count": len(gaps),
            "contradictions_count": len(contradictions),
        }
        self._save_manifest()
        return report

    def _coverage_progress(self, *, objective_id: str = "") -> dict[str, Any]:
        sources_total = len(self._manifest.get("sources", {}))
        syntheses_total = len(self._manifest.get("topic_syntheses", {}))
        lint = self._collect_lint_snapshot()
        stale = int(lint.get("stale_syntheses_count") or 0)
        contradictions = int(lint.get("contradictions_count") or 0)
        open_questions = int(lint.get("open_questions_count") or 0)

        breadth = min(1.0, sources_total / 40.0)
        synthesis_depth = min(1.0, syntheses_total / 20.0)
        freshness = max(0.0, 1.0 - (stale / max(1, syntheses_total or 1)))
        contradiction_resolution = max(0.0, 1.0 - (contradictions / max(1, syntheses_total or 1)))
        question_closure = max(0.0, 1.0 - (open_questions / max(1, syntheses_total or 1)))

        weighted = (
            0.25 * breadth
            + 0.25 * synthesis_depth
            + 0.2 * freshness
            + 0.15 * contradiction_resolution
            + 0.15 * question_closure
        )
        percent = round(max(0.0, min(100.0, weighted * 100.0)), 2)
        return {
            "objective_id": objective_id,
            "percent": percent,
            "breakdown": {
                "source_breadth": round(breadth * 100.0, 2),
                "synthesis_depth": round(synthesis_depth * 100.0, 2),
                "freshness": round(freshness * 100.0, 2),
                "contradiction_resolution": round(contradiction_resolution * 100.0, 2),
                "open_question_closure": round(question_closure * 100.0, 2),
            },
            "last_updated_at": _utcnow_iso(),
        }

    def get_coverage_progress(self, *, objective_id: str = "") -> dict[str, Any]:
        return self._coverage_progress(objective_id=objective_id)

    def evaluate_sufficiency(self, *, objective_id: str, topic: str = "", min_score: float = 78.0) -> dict[str, Any]:
        objective = self._ensure_objective(objective_id=objective_id, topic=topic)
        progress = self._coverage_progress(objective_id=objective_id)
        lint = self._collect_lint_snapshot()
        blockers: list[str] = []
        if int(lint.get("contradictions_count") or 0) > 0:
            blockers.append("unresolved_contradictions")
        if int(lint.get("open_questions_count") or 0) > 0:
            blockers.append("open_questions")
        if int(lint.get("stale_syntheses_count") or 0) > 0:
            blockers.append("stale_syntheses")
        score = float(progress.get("percent") or 0.0)
        decision = "insufficient"
        if score >= min_score and not blockers:
            decision = "sufficient"
        elif score >= min_score * 0.85:
            decision = "near_sufficient"

        state = self._manifest.get("sufficiency_state", {}).get(objective_id, {})
        streak = int(state.get("sufficient_streak") or 0)
        if decision == "sufficient" and not blockers:
            streak += 1
        else:
            streak = 0
        auto_pause_recommended = streak >= 2 and not blockers

        report = {
            "generated_at": _utcnow_iso(),
            "objective_id": objective_id,
            "topic": topic or objective.get("topic", ""),
            "score": round(score, 2),
            "decision": decision,
            "blocking_checks": blockers,
            "reasons": [
                "weighted_coverage_progress" if score >= min_score else "coverage_below_threshold",
                *([f"blocker:{item}" for item in blockers] or ["no_blockers_detected"]),
            ],
            "recommended_actions": [
                "Prioritize contradiction resolution." if "unresolved_contradictions" in blockers else "",
                "Resolve high-priority open questions." if "open_questions" in blockers else "",
                "Refresh stale syntheses." if "stale_syntheses" in blockers else "",
                "Continue periodic monitoring." if not blockers else "",
            ],
            "min_score": min_score,
            "auto_pause_recommended": auto_pause_recommended,
            "sufficient_streak": streak,
            "progress": progress,
        }
        report["recommended_actions"] = [item for item in report["recommended_actions"] if item]
        report_path = self.sufficiency_reports_dir / f"{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-sufficiency.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        suff_state = self._manifest.setdefault("sufficiency_state", {})
        suff_state[objective_id] = {
            "updated_at": _utcnow_iso(),
            "score": report["score"],
            "decision": decision,
            "blocking_checks": blockers,
            "sufficient_streak": streak,
            "auto_pause_recommended": auto_pause_recommended,
            "report_path": str(report_path),
        }
        objective["updated_at"] = _utcnow_iso()
        objective["last_action_at"] = objective["updated_at"]
        self._append_action_history(
            {
                "objective_id": objective_id,
                "topic": report["topic"],
                "phase": "vault_sufficiency_evaluate",
                "status": decision,
                "score": report["score"],
                "report_path": str(report_path),
            }
        )
        self._manifest["last_run_summary"] = {
            "step": "vault_sufficiency_evaluate",
            "updated_at": _utcnow_iso(),
            "objective_id": objective_id,
            "score": report["score"],
            "decision": decision,
            "auto_pause_recommended": auto_pause_recommended,
        }
        self._save_manifest()
        return report

    def get_action_items(self, *, limit: int = 100) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        queue = self._load_queue()
        queued = [item for item in queue if str(item.get("status") or "") == "queued"]
        for queued_item in queued[: max(1, min(limit, 20))]:
            items.append(
                {
                    "kind": "queue",
                    "priority": "medium",
                    "title": str(queued_item.get("title") or queued_item.get("url") or "Queued source"),
                    "detail": str(queued_item.get("reason") or "queued_search_result"),
                    "created_at": str(queued_item.get("queued_at") or _utcnow_iso()),
                    "status": "pending",
                }
            )
        for directory, kind, priority in (
            (self.task_backlog_dir, "task_backlog", "high"),
            (self.task_review_dir, "task_review", "high"),
        ):
            for path in sorted(directory.glob("*.md"), reverse=True)[: max(1, min(limit, 30))]:
                items.append(
                    {
                        "kind": kind,
                        "priority": priority,
                        "title": path.stem.replace("-", " ").title(),
                        "detail": str(path),
                        "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                        "status": "pending",
                    }
                )
        for objective in self._manifest.get("objectives", {}).values():
            if not isinstance(objective, dict):
                continue
            if str(objective.get("status") or "active") != "active":
                continue
            items.append(
                {
                    "kind": "objective",
                    "priority": "medium",
                    "title": f"Objective: {objective.get('topic') or objective.get('objective_id')}",
                    "detail": f"attempts={objective.get('attempts_total', 0)} blocked={objective.get('blocked_attempts', 0)}",
                    "created_at": str(objective.get("updated_at") or _utcnow_iso()),
                    "status": "active",
                    "objective_id": str(objective.get("objective_id") or ""),
                }
            )

        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        sliced = items[: max(1, limit)]
        counts = {
            "total": len(sliced),
            "queue": len([item for item in sliced if item["kind"] == "queue"]),
            "task_backlog": len([item for item in sliced if item["kind"] == "task_backlog"]),
            "task_review": len([item for item in sliced if item["kind"] == "task_review"]),
            "objective": len([item for item in sliced if item["kind"] == "objective"]),
        }
        return {"generated_at": _utcnow_iso(), "counts": counts, "items": sliced}

    def search(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        return UnifiedVaultSearchService(self.vault_root).search_payload(query=query, limit=limit)

    def get_run_summary(self) -> dict[str, Any]:
        queue = self._load_queue()
        search_service = UnifiedVaultSearchService(self.vault_root)
        vector_status = search_service.vector_status()
        raw_bytes = self._raw_memory_bytes()
        memory = {
            "raw_bytes": raw_bytes,
            "raw_human": self._human_bytes(raw_bytes),
            "scope": "knowledge_vault/01_raw",
            "updated_at": _utcnow_iso(),
        }
        progress = self._coverage_progress()
        latest_sufficiency = {}
        sufficiency_state = self._manifest.get("sufficiency_state", {})
        if isinstance(sufficiency_state, dict) and sufficiency_state:
            latest_key = sorted(
                sufficiency_state.items(),
                key=lambda item: str(item[1].get("updated_at") if isinstance(item[1], dict) else ""),
                reverse=True,
            )[0][0]
            latest_sufficiency = {"objective_id": latest_key, **sufficiency_state.get(latest_key, {})}
        action_items = self.get_action_items(limit=50)
        return {
            "summary": self._manifest.get("last_run_summary", {}),
            "counts": {
                "sources_total": len(self._manifest.get("sources", {})),
                "queries_total": len(self._manifest.get("queries", {})),
                "candidates_total": len(self._manifest.get("candidates", {})),
                "trust_decisions_total": len(self._manifest.get("trust_decisions", {})),
                "search_index_total": len(self._manifest.get("search_index", {})),
                "dirty_pages": len(self._manifest.get("dirty_pages", [])),
                "queued_search_results": len([item for item in queue if str(item.get("status") or "") == "queued"]),
                "queued_clips": len([item for item in queue if str(item.get("source_tool") or "") == "browser_clipper" and str(item.get("status") or "") == "queued"]),
                "saved_outputs_total": len([item for item in self._manifest.get("sources", {}).values() if str(item.get("source") or "") == "explicit_save"]),
                "clip_sources_total": len([item for item in self._manifest.get("sources", {}).values() if str(item.get("source_tool") or "") == "browser_clipper"]),
                "vector_index_enabled": bool(vector_status.get("enabled")),
                "vector_index_chunks": int(vector_status.get("chunk_count") or 0),
                "vector_index_built_at": vector_status.get("built_at"),
                "last_compile_at": self._manifest.get("last_compile_at"),
                "last_lint_at": self._manifest.get("last_lint_at"),
            },
            "memory": memory,
            "progress": progress,
            "sufficiency": latest_sufficiency,
            "action_items": action_items.get("counts", {}),
            "objectives": {"total": len(self._manifest.get("objectives", {}))},
        }

    def get_source(self, source_id: str) -> dict[str, Any]:
        source = self._manifest.get("sources", {}).get(source_id)
        if not isinstance(source, dict):
            raise ValueError(f"Unknown source id: {source_id}")
        return {
            "source": source,
            "trust_decision": self._manifest.get("trust_decisions", {}).get(source_id, {}),
            "dependencies": self._manifest.get("source_dependencies", {}).get(source_id, []),
        }

    def purge_objective(self, *, objective_id: str) -> dict[str, Any]:
        normalized_objective_id = objective_id.strip()
        if not normalized_objective_id:
            raise ValueError("Objective id is required.")

        removed_paths: list[str] = []

        def remove_path(path: Path) -> bool:
            if path.is_file():
                path.unlink()
                removed_paths.append(str(path))
                return True
            if path.is_dir():
                shutil.rmtree(path)
                removed_paths.append(str(path))
                return True
            return False

        objective_slug = _slugify(normalized_objective_id) or "objective"
        objective_dir = self.ops_dir / "autoresearch" / "objectives" / objective_slug
        raw_objective_dir = self.raw_dir / normalized_objective_id

        removed_count = 0
        if remove_path(objective_dir):
            removed_count += 1
        if remove_path(raw_objective_dir):
            removed_count += 1

        report_removed_count = 0
        report_dirs = (
            self.discover_reports_dir,
            self.ingest_reports_dir,
            self.compile_reports_dir,
            self.lint_reports_dir,
            self.synthesis_reports_dir,
            self.sufficiency_reports_dir,
        )
        for directory in report_dirs:
            for report_path in directory.glob("*.json"):
                try:
                    payload = json.loads(report_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if str(payload.get("objective_id") or "").strip() != normalized_objective_id:
                    continue
                if remove_path(report_path):
                    report_removed_count += 1

        queue_items = self._load_queue()
        filtered_queue_items = [
            item
            for item in queue_items
            if str(item.get("objective_id") or "").strip() != normalized_objective_id
        ]
        queue_removed_count = len(queue_items) - len(filtered_queue_items)
        if queue_removed_count > 0:
            self._save_queue(filtered_queue_items)

        objectives = self._manifest.get("objectives", {})
        objectives.pop(normalized_objective_id, None)

        sufficiency_state = self._manifest.get("sufficiency_state", {})
        sufficiency_state.pop(normalized_objective_id, None)

        action_history = self._manifest.get("action_history", [])
        self._manifest["action_history"] = [
            item
            for item in action_history
            if str(item.get("objective_id") or "").strip() != normalized_objective_id
        ]

        attempt_fingerprints = self._manifest.get("attempt_fingerprints", {})
        self._manifest["attempt_fingerprints"] = {
            key: value
            for key, value in attempt_fingerprints.items()
            if str((value or {}).get("objective_id") or "").strip() != normalized_objective_id
        }

        last_run_summary = self._manifest.get("last_run_summary", {})
        if str(last_run_summary.get("objective_id") or "").strip() == normalized_objective_id:
            self._manifest["last_run_summary"] = {}

        self._save_manifest()
        return {
            "objective_id": normalized_objective_id,
            "removed_paths_count": removed_count + report_removed_count,
            "removed_report_count": report_removed_count,
            "removed_queue_items_count": queue_removed_count,
            "removed_paths": removed_paths,
        }

    def reprocess_existing_sources(
        self,
        *,
        only_missing: bool = True,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Re-run analysis on already-ingested sources to backfill entities/concepts.

        - When ``only_missing`` is True, skip sources whose manifest entry already
          lists at least one entity_ref or concept_ref.
        - ``progress_callback(index, total, source_id, title, status, error)`` is
          invoked after each source so callers can surface progress to users.
        """
        sources = self._manifest.get("sources", {})
        items = [
            (source_id, record)
            for source_id, record in sources.items()
            if isinstance(record, dict) and str(record.get("status") or "") == "ingested"
        ]
        if only_missing:
            items = [
                (source_id, record)
                for source_id, record in items
                if not (record.get("entity_refs") or record.get("concept_refs"))
            ]

        total = len(items)
        processed = 0
        updated = 0
        skipped_no_raw = 0
        failed = 0
        errors: list[dict[str, Any]] = []

        if progress_callback is not None:
            progress_callback(0, total, "", "", "started", None)

        for source_id, record in items:
            processed += 1
            title = str(record.get("title") or record.get("url") or source_id)
            raw_path_str = str(record.get("raw_path") or "").strip()
            if not raw_path_str:
                skipped_no_raw += 1
                if progress_callback is not None:
                    progress_callback(processed, total, source_id, title, "skipped_no_raw", None)
                continue
            raw_path = Path(raw_path_str)
            try:
                raw_text = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
            except Exception as exc:
                failed += 1
                errors.append({"source_id": source_id, "reason": f"read_error:{exc}"})
                if progress_callback is not None:
                    progress_callback(processed, total, source_id, title, "failed", str(exc))
                continue

            if not raw_text.strip():
                skipped_no_raw += 1
                if progress_callback is not None:
                    progress_callback(processed, total, source_id, title, "skipped_no_raw", None)
                continue

            raw_text = raw_text[: self.max_content_chars]
            topic_tags = [str(item).strip() for item in record.get("topic_tags", []) if str(item).strip()]
            topic_hint = topic_tags[0].replace("-", " ") if topic_tags else title
            try:
                analysis = self._analyze_source(
                    title=title,
                    url=str(record.get("url") or ""),
                    topic=topic_hint,
                    raw_text=raw_text,
                    topic_tags=topic_tags,
                    concept_refs=[],
                    entity_refs=[],
                    target_synthesis_refs=[],
                )
            except Exception as exc:
                failed += 1
                errors.append({"source_id": source_id, "reason": f"analysis_error:{exc}"})
                if progress_callback is not None:
                    progress_callback(processed, total, source_id, title, "failed", str(exc))
                continue

            entity_refs = [str(item).strip() for item in analysis.get("entities", []) if str(item).strip()]
            concept_refs = [str(item).strip() for item in analysis.get("concepts", []) if str(item).strip()]

            if not entity_refs and not concept_refs:
                if progress_callback is not None:
                    progress_callback(processed, total, source_id, title, "no_refs", None)
                continue

            for entity_ref in entity_refs:
                self._update_reference_page(
                    path=self._compiled_entity_path(entity_ref),
                    title=entity_ref.replace("-", " ").title(),
                    kind="entity",
                    source_id=source_id,
                    source_title=title,
                    topic_tags=topic_tags,
                )
            for concept_ref in concept_refs:
                self._update_reference_page(
                    path=self._compiled_concept_path(concept_ref),
                    title=concept_ref.replace("-", " ").title(),
                    kind="concept",
                    source_id=source_id,
                    source_title=title,
                    topic_tags=topic_tags,
                )

            record["entity_refs"] = sorted(set(record.get("entity_refs", []) + entity_refs))
            record["concept_refs"] = sorted(set(record.get("concept_refs", []) + concept_refs))
            record["last_reviewed_at"] = _utcnow_iso()
            sources[source_id] = record
            updated += 1

            if updated % 25 == 0:
                self._save_manifest()

            if progress_callback is not None:
                progress_callback(processed, total, source_id, title, "updated", None)

        self._manifest["last_run_summary"] = {
            "step": "reprocess",
            "updated_at": _utcnow_iso(),
            "processed": processed,
            "updated": updated,
            "skipped_no_raw": skipped_no_raw,
            "failed": failed,
        }
        self._save_manifest()

        return {
            "total": total,
            "processed": processed,
            "updated": updated,
            "skipped_no_raw": skipped_no_raw,
            "failed": failed,
            "errors": errors[:50],
        }


def _query_id_for_identity(query_text: str, topic_tags: list[str]) -> str:
    normalized = f"{query_text.strip().lower()}|{'|'.join(sorted(_slugify(tag) for tag in topic_tags if tag.strip()))}"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()
