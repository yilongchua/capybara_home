"""Memory updater for reading, writing, and updating memory data."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agents.memory.prompt import (
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
)
from src.agents.memory.store import (
    MEMORY_SCOPE_GLOBAL,
    MEMORY_SCOPE_WORKSPACE,
    get_latest_memory_ref,
    persist_memory_data,
)
from src.agents.memory.vector_store import get_memory_vector_store
from src.config.memory_config import get_memory_config
from src.config.paths import get_paths
from src.models import ModelRouter, create_chat_model


def _utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_scope(scope: str) -> str:
    normalized = (scope or MEMORY_SCOPE_GLOBAL).strip().lower()
    if normalized not in {MEMORY_SCOPE_GLOBAL, MEMORY_SCOPE_WORKSPACE}:
        return MEMORY_SCOPE_GLOBAL
    return normalized


def _scope_cache_key(agent_name: str | None, scope: str, workspace_id: str | None) -> str:
    return f"{agent_name or '_global'}::{_normalize_scope(scope)}::{workspace_id or '_'}"


def _vector_scope_id(scope: str, workspace_id: str | None) -> str:
    return workspace_id or "default-workspace" if _normalize_scope(scope) == MEMORY_SCOPE_WORKSPACE else "global"


def _get_memory_file_path(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> Path:
    scope = _normalize_scope(scope)
    if scope == MEMORY_SCOPE_WORKSPACE:
        sid = workspace_id or "default-workspace"
        return get_paths().thread_dir(sid) / "memory.json"
    if agent_name is not None:
        return get_paths().agent_memory_file(agent_name)

    config = get_memory_config()
    if config.storage_path:
        p = Path(config.storage_path)
        return p if p.is_absolute() else get_paths().base_dir / p
    return get_paths().memory_file


def _create_empty_memory(scope: str = MEMORY_SCOPE_GLOBAL, scope_id: str | None = None) -> dict[str, Any]:
    """Create an empty memory structure."""
    return {
        "version": "2.0",
        "scope": _normalize_scope(scope),
        "scopeId": scope_id or ("global" if scope == MEMORY_SCOPE_GLOBAL else "workspace"),
        "lastUpdated": _utc_now_iso_z(),
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
        "behaviorRules": [],
    }


# Value: (memory_data, file_mtime)
_memory_cache: dict[str, tuple[dict[str, Any], float | None]] = {}


def get_memory_data(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Get the current memory data with mtime-aware cache."""
    file_path = _get_memory_file_path(agent_name, scope=scope, workspace_id=workspace_id)
    cache_key = _scope_cache_key(agent_name, scope, workspace_id)
    try:
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        current_mtime = None

    cached = _memory_cache.get(cache_key)
    if cached is None or cached[1] != current_mtime:
        memory_data = _load_memory_from_file(agent_name, scope=scope, workspace_id=workspace_id)
        _memory_cache[cache_key] = (memory_data, current_mtime)
        return memory_data
    return cached[0]


def reload_memory_data(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Reload memory data from file, forcing cache invalidation."""
    file_path = _get_memory_file_path(agent_name, scope=scope, workspace_id=workspace_id)
    cache_key = _scope_cache_key(agent_name, scope, workspace_id)
    memory_data = _load_memory_from_file(agent_name, scope=scope, workspace_id=workspace_id)
    try:
        mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        mtime = None

    _memory_cache[cache_key] = (memory_data, mtime)
    return memory_data


def _load_memory_from_file(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    file_path = _get_memory_file_path(agent_name, scope=scope, workspace_id=workspace_id)
    normalized_scope = _normalize_scope(scope)
    scope_id = workspace_id if normalized_scope == MEMORY_SCOPE_WORKSPACE else "global"
    if not file_path.exists():
        return _create_empty_memory(normalized_scope, scope_id=scope_id)

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("scope", normalized_scope)
        data.setdefault("scopeId", scope_id or "global")
        data.setdefault("behaviorRules", [])
        data.setdefault("facts", [])
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"Failed to load memory file: {e}")
        return _create_empty_memory(normalized_scope, scope_id=scope_id)


_UPLOAD_SENTENCE_RE = re.compile(
    r"[^.!?]*\b(?:"
    r"upload(?:ed|ing)?(?:\s+\w+){0,3}\s+(?:file|files?|document|documents?|attachment|attachments?)"
    r"|file\s+upload"
    r"|/mnt/user-data/uploads/"
    r"|<uploaded_files>"
    r")[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)


def _strip_upload_mentions_from_memory(memory_data: dict[str, Any]) -> dict[str, Any]:
    for section in ("user", "history"):
        section_data = memory_data.get(section, {})
        for _key, val in section_data.items():
            if isinstance(val, dict) and "summary" in val:
                cleaned = _UPLOAD_SENTENCE_RE.sub("", str(val["summary"])).strip()
                cleaned = re.sub(r"  +", " ", cleaned)
                val["summary"] = cleaned
    facts = memory_data.get("facts", [])
    if facts:
        memory_data["facts"] = [f for f in facts if not _UPLOAD_SENTENCE_RE.search(str(f.get("content", "")))]
    return memory_data


def _save_memory_to_file(
    memory_data: dict[str, Any],
    agent_name: str | None = None,
    source_thread: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> bool:
    file_path = _get_memory_file_path(agent_name, scope=scope, workspace_id=workspace_id)
    cache_key = _scope_cache_key(agent_name, scope, workspace_id)

    try:
        persist_memory_data(
            memory_data,
            agent_name=agent_name,
            source_thread=source_thread,
            scope=scope,
            workspace_id=workspace_id,
        )
        persisted = _load_memory_from_file(agent_name, scope=scope, workspace_id=workspace_id)
        try:
            mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            mtime = None
        _memory_cache[cache_key] = (persisted, mtime)
        return True
    except OSError as e:
        print(f"Failed to save memory file: {e}")
        return False
    except ValueError as e:
        print(f"Memory save rejected: {e}")
        return False


def _scope_flags_allow(scope: str, config) -> bool:
    normalized = _normalize_scope(scope)
    if normalized == MEMORY_SCOPE_GLOBAL:
        return bool(config.global_scope_enabled)
    if normalized == MEMORY_SCOPE_WORKSPACE:
        return bool(config.workspace_scope_enabled)
    return True


class MemoryUpdater:
    """Updates memory using LLM based on conversation context."""

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name

    def _get_model(self):
        config = get_memory_config()
        requested_name = self._model_name or config.model_name
        model_name = ModelRouter().resolve("memory_extractor", requested_model=requested_name)
        return create_chat_model(name=model_name, thinking_enabled=False)

    def update_memory(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        *,
        scope: str = MEMORY_SCOPE_GLOBAL,
        workspace_id: str | None = None,
    ) -> bool:
        config = get_memory_config()
        normalized_scope = _normalize_scope(scope)
        if not config.enabled or not _scope_flags_allow(normalized_scope, config):
            return False
        if not messages:
            return False
        if normalized_scope == MEMORY_SCOPE_WORKSPACE and not workspace_id:
            workspace_id = thread_id
        try:
            current_memory = get_memory_data(agent_name, scope=normalized_scope, workspace_id=workspace_id)
            previous_fact_ids = {
                str(fact.get("id"))
                for fact in (current_memory.get("facts") or [])
                if isinstance(fact, dict) and str(fact.get("id") or "").strip()
            }
            conversation_text = format_conversation_for_update(messages)
            if not conversation_text.strip():
                return False
            prompt = MEMORY_UPDATE_PROMPT.format(
                current_memory=json.dumps(current_memory, indent=2),
                conversation=conversation_text,
            )
            model = self._get_model()
            response = model.invoke(prompt)
            response_text = str(response.content).strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            update_data = json.loads(response_text)
            updated_memory = self._apply_updates(current_memory, update_data, thread_id)
            updated_memory = _strip_upload_mentions_from_memory(updated_memory)
            ok = _save_memory_to_file(
                updated_memory,
                agent_name,
                source_thread=thread_id,
                scope=normalized_scope,
                workspace_id=workspace_id,
            )
            if ok:
                updated_facts = list(updated_memory.get("facts") or [])
                updated_fact_ids = {
                    str(fact.get("id"))
                    for fact in updated_facts
                    if isinstance(fact, dict) and str(fact.get("id") or "").strip()
                }
                vector_store = get_memory_vector_store()
                stale_fact_ids = sorted(previous_fact_ids - updated_fact_ids)
                vector_scope_id = _vector_scope_id(normalized_scope, workspace_id)
                if stale_fact_ids:
                    vector_store.delete_fact_ids(
                        scope=normalized_scope,
                        scope_id=vector_scope_id,
                        fact_ids=stale_fact_ids,
                    )
                vector_store.upsert_facts(
                    scope=normalized_scope,
                    scope_id=vector_scope_id,
                    facts=updated_facts,
                )
            return ok
        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response for memory update: {e}")
            return False
        except Exception as e:
            print(f"Memory update failed: {e}")
            return False

    def _apply_updates(
        self,
        current_memory: dict[str, Any],
        update_data: dict[str, Any],
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        config = get_memory_config()
        now = _utc_now_iso_z()
        current_memory.setdefault("behaviorRules", [])
        current_memory.setdefault("facts", [])

        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["user"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["history"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        facts_to_remove = set(update_data.get("factsToRemove", []))
        if facts_to_remove:
            current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in facts_to_remove]

        new_facts = update_data.get("newFacts", [])
        for fact in new_facts:
            confidence = fact.get("confidence", 0.5)
            if confidence >= config.fact_confidence_threshold:
                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": fact.get("content", ""),
                    "category": fact.get("category", "context"),
                    "confidence": confidence,
                    "createdAt": now,
                    "source": thread_id or "unknown",
                }
                current_memory["facts"].append(fact_entry)

        if len(current_memory["facts"]) > config.max_facts:
            current_memory["facts"] = sorted(
                current_memory["facts"],
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )[: config.max_facts]
        return current_memory


def add_behavior_rule(
    *,
    instruction: str,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
    source: str = "api",
    active: bool = True,
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    memory = get_memory_data(scope=normalized_scope, workspace_id=workspace_id)
    memory.setdefault("behaviorRules", [])
    now = _utc_now_iso_z()
    entry = {
        "id": f"rule_{uuid.uuid4().hex[:10]}",
        "instruction": instruction.strip(),
        "active": bool(active),
        "scope": normalized_scope,
        "scopeId": workspace_id if normalized_scope == MEMORY_SCOPE_WORKSPACE else "global",
        "source": source,
        "createdAt": now,
        "updatedAt": now,
    }
    memory["behaviorRules"].append(entry)
    _save_memory_to_file(memory, source_thread=source, scope=normalized_scope, workspace_id=workspace_id)
    return entry


def update_behavior_rule(
    *,
    rule_id: str,
    instruction: str | None = None,
    active: bool | None = None,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    memory = get_memory_data(scope=normalized_scope, workspace_id=workspace_id)
    rules = list(memory.get("behaviorRules") or [])
    for idx, rule in enumerate(rules):
        if str(rule.get("id")) != rule_id:
            continue
        if instruction is not None:
            rule["instruction"] = instruction.strip()
        if active is not None:
            rule["active"] = bool(active)
        rule["updatedAt"] = _utc_now_iso_z()
        rules[idx] = rule
        memory["behaviorRules"] = rules
        _save_memory_to_file(memory, scope=normalized_scope, workspace_id=workspace_id)
        return rule
    raise ValueError(f"Behavior rule '{rule_id}' not found")


def delete_behavior_rule(
    *,
    rule_id: str,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> bool:
    normalized_scope = _normalize_scope(scope)
    memory = get_memory_data(scope=normalized_scope, workspace_id=workspace_id)
    before = len(memory.get("behaviorRules") or [])
    memory["behaviorRules"] = [r for r in (memory.get("behaviorRules") or []) if str(r.get("id")) != rule_id]
    after = len(memory["behaviorRules"])
    if after == before:
        return False
    return _save_memory_to_file(memory, scope=normalized_scope, workspace_id=workspace_id)


def upsert_fact(
    *,
    fact_id: str,
    content: str,
    category: str = "context",
    confidence: float = 0.9,
    source: str = "manual",
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    memory = get_memory_data(scope=normalized_scope, workspace_id=workspace_id)
    facts = list(memory.get("facts") or [])
    now = _utc_now_iso_z()
    for idx, fact in enumerate(facts):
        if str(fact.get("id")) != fact_id:
            continue
        fact["content"] = content
        fact["category"] = category
        fact["confidence"] = confidence
        fact["source"] = source or fact.get("source", "manual")
        facts[idx] = fact
        memory["facts"] = facts
        _save_memory_to_file(memory, source_thread=source, scope=normalized_scope, workspace_id=workspace_id)
        get_memory_vector_store().upsert_facts(
            scope=normalized_scope,
            scope_id=workspace_id if normalized_scope == MEMORY_SCOPE_WORKSPACE else "global",
            facts=[fact],
        )
        return fact

    new_fact = {
        "id": fact_id,
        "content": content,
        "category": category,
        "confidence": confidence,
        "createdAt": now,
        "source": source,
    }
    facts.append(new_fact)
    memory["facts"] = facts
    _save_memory_to_file(memory, source_thread=source, scope=normalized_scope, workspace_id=workspace_id)
    get_memory_vector_store().upsert_facts(
        scope=normalized_scope,
        scope_id=workspace_id if normalized_scope == MEMORY_SCOPE_WORKSPACE else "global",
        facts=[new_fact],
    )
    return new_fact


def delete_fact(
    *,
    fact_id: str,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> bool:
    normalized_scope = _normalize_scope(scope)
    memory = get_memory_data(scope=normalized_scope, workspace_id=workspace_id)
    before = len(memory.get("facts") or [])
    memory["facts"] = [f for f in (memory.get("facts") or []) if str(f.get("id")) != fact_id]
    after = len(memory["facts"])
    if after == before:
        return False
    ok = _save_memory_to_file(memory, scope=normalized_scope, workspace_id=workspace_id)
    if ok:
        get_memory_vector_store().delete_fact_ids(
            scope=normalized_scope,
            scope_id=workspace_id if normalized_scope == MEMORY_SCOPE_WORKSPACE else "global",
            fact_ids=[fact_id],
        )
    return ok


def forget_thread_facts(thread_id: str, *, scope: str = MEMORY_SCOPE_WORKSPACE, workspace_id: str | None = None) -> int:
    normalized_scope = _normalize_scope(scope)
    memory = get_memory_data(scope=normalized_scope, workspace_id=workspace_id)
    facts = list(memory.get("facts") or [])
    kept = [f for f in facts if str(f.get("source")) != thread_id]
    removed_ids = [str(f.get("id")) for f in facts if str(f.get("source")) == thread_id and str(f.get("id"))]
    removed = len(facts) - len(kept)
    if removed <= 0:
        return 0
    memory["facts"] = kept
    _save_memory_to_file(memory, source_thread=thread_id, scope=normalized_scope, workspace_id=workspace_id)
    scope_id = _vector_scope_id(normalized_scope, workspace_id)
    get_memory_vector_store().delete_fact_ids(scope=normalized_scope, scope_id=scope_id, fact_ids=removed_ids)
    get_memory_vector_store().upsert_facts(
        scope=normalized_scope,
        scope_id=scope_id,
        facts=kept,
    )
    return removed


def clear_memory(
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
    source: str = "memory-ui",
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    scope_id = workspace_id if normalized_scope == MEMORY_SCOPE_WORKSPACE else "global"
    empty = _create_empty_memory(normalized_scope, scope_id=scope_id)
    _save_memory_to_file(empty, source_thread=source, scope=normalized_scope, workspace_id=workspace_id)
    get_memory_vector_store().delete_scope(
        scope=normalized_scope,
        scope_id=_vector_scope_id(normalized_scope, workspace_id),
    )
    return empty


def update_memory_from_conversation(
    messages: list[Any],
    thread_id: str | None = None,
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> bool:
    updater = MemoryUpdater()
    return updater.update_memory(messages, thread_id, agent_name, scope=scope, workspace_id=workspace_id)


def get_memory_version_reference(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    return get_latest_memory_ref(agent_name, scope=scope, workspace_id=workspace_id)
