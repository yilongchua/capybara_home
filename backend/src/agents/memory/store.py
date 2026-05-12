"""Version-aware persistence layer for memory data with scope support."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config.memory_config import get_memory_config
from src.config.memory_versioning_config import get_memory_versioning_config
from src.config.paths import get_paths
from src.control_plane.redaction import CARD_RE, EMAIL_RE, PHONE_RE

LATEST_POINTER = "latest.json"

MEMORY_SCOPE_GLOBAL = "global"
MEMORY_SCOPE_WORKSPACE = "workspace"


def _utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _stable_sha(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_scope(scope: str) -> str:
    normalized = (scope or MEMORY_SCOPE_GLOBAL).strip().lower()
    if normalized not in {MEMORY_SCOPE_GLOBAL, MEMORY_SCOPE_WORKSPACE}:
        return MEMORY_SCOPE_GLOBAL
    return normalized


def _normalize_scope_id(scope: str, workspace_id: str | None) -> str:
    if _normalize_scope(scope) == MEMORY_SCOPE_WORKSPACE:
        return str(workspace_id or "default-workspace")
    return "global"


def _memory_file_path(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> Path:
    scope = _normalize_scope(scope)
    if scope == MEMORY_SCOPE_WORKSPACE:
        sid = _normalize_scope_id(scope, workspace_id)
        return get_paths().thread_dir(sid) / "memory.json"

    if agent_name is not None:
        return get_paths().agent_memory_file(agent_name)

    cfg = get_memory_config()
    if cfg.storage_path:
        p = Path(cfg.storage_path)
        return p if p.is_absolute() else get_paths().base_dir / p
    return get_paths().memory_file


def _version_root(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> Path:
    cfg = get_memory_versioning_config()
    root = Path(cfg.storage_dir)
    if not root.is_absolute():
        root = get_paths().base_dir / root

    scope = _normalize_scope(scope)
    if scope == MEMORY_SCOPE_WORKSPACE:
        sid = _normalize_scope_id(scope, workspace_id)
        return root / "workspaces" / sid
    if agent_name:
        return root / "agents" / agent_name.lower()
    return root / "global"


def _latest_pointer_path(agent_name: str | None = None, *, scope: str = MEMORY_SCOPE_GLOBAL, workspace_id: str | None = None) -> Path:
    return _version_root(agent_name, scope=scope, workspace_id=workspace_id) / LATEST_POINTER


def _versions_dir(agent_name: str | None = None, *, scope: str = MEMORY_SCOPE_GLOBAL, workspace_id: str | None = None) -> Path:
    return _version_root(agent_name, scope=scope, workspace_id=workspace_id) / "versions"


def _load_latest_pointer(agent_name: str | None = None, *, scope: str = MEMORY_SCOPE_GLOBAL, workspace_id: str | None = None) -> dict[str, Any] | None:
    path = _latest_pointer_path(agent_name, scope=scope, workspace_id=workspace_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def _load_memory_file(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    path = _memory_file_path(agent_name, scope=scope, workspace_id=workspace_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def persist_memory_data(
    memory_data: dict[str, Any],
    *,
    agent_name: str | None = None,
    expected_sha: str | None = None,
    source_thread: str | None = None,
    operation: str = "update",
    audit: dict[str, Any] | None = None,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Persist memory, optionally creating append-only versions."""
    scope = _normalize_scope(scope)
    scope_id = _normalize_scope_id(scope, workspace_id)
    memory_file = _memory_file_path(agent_name, scope=scope, workspace_id=workspace_id)
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    cfg = get_memory_versioning_config()

    previous_memory = _load_memory_file(agent_name, scope=scope, workspace_id=workspace_id) or {}
    previous_sha = _stable_sha(previous_memory) if previous_memory else None
    if expected_sha and previous_sha and expected_sha != previous_sha:
        raise ValueError("Memory write rejected: expected_sha does not match current memory.")
    if cfg.require_expected_sha and not expected_sha:
        raise ValueError("Memory write rejected: expected_sha is required by configuration.")

    payload = dict(memory_data)
    payload["lastUpdated"] = _utc_now_iso_z()
    payload["scope"] = scope
    payload["scopeId"] = scope_id
    current_sha = _stable_sha(payload)

    if cfg.enabled:
        version_id = f"memv-{uuid.uuid4().hex[:12]}"
        record = {
            "version_id": version_id,
            "created_at": _utc_now_iso_z(),
            "sha": current_sha,
            "parent_sha": previous_sha,
            "source_thread": source_thread,
            "operation": operation,
            "scope": scope,
            "scope_id": scope_id,
            "audit": audit or {},
            "memory": payload,
        }
        version_path = _versions_dir(agent_name, scope=scope, workspace_id=workspace_id) / f"{version_id}.json"
        _write_json(version_path, record)
        pointer = {
            "version_id": version_id,
            "sha": current_sha,
            "scope": scope,
            "scope_id": scope_id,
            "updated_at": _utc_now_iso_z(),
            "storage_path": str(version_path),
        }
        _write_json(_latest_pointer_path(agent_name, scope=scope, workspace_id=workspace_id), pointer)
        _write_json(memory_file, payload)
        return {
            "version_id": version_id,
            "sha": current_sha,
            "scope": scope,
            "scope_id": scope_id,
            "storage_path": str(version_path),
        }

    _write_json(memory_file, payload)
    return {
        "version_id": None,
        "sha": current_sha,
        "scope": scope,
        "scope_id": scope_id,
        "storage_path": str(memory_file),
    }


def list_memory_versions(
    agent_name: str | None = None,
    *,
    limit: int = 50,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    """List recent version metadata without full memory payloads."""
    version_dir = _versions_dir(agent_name, scope=scope, workspace_id=workspace_id)
    if not version_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    files = sorted(version_dir.glob("*.json"), reverse=True)
    for file_path in files[: max(1, limit)]:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            records.append(
                {
                    "version_id": payload.get("version_id"),
                    "created_at": payload.get("created_at"),
                    "sha": payload.get("sha"),
                    "parent_sha": payload.get("parent_sha"),
                    "source_thread": payload.get("source_thread"),
                    "operation": payload.get("operation"),
                    "scope": payload.get("scope"),
                    "scope_id": payload.get("scope_id"),
                    "audit": payload.get("audit") or {},
                }
            )
        except Exception:
            continue
    return records


def get_memory_version(
    version_id: str,
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    """Get a specific version record."""
    version_path = _versions_dir(agent_name, scope=scope, workspace_id=workspace_id) / f"{version_id}.json"
    if not version_path.exists():
        return None
    try:
        return json.loads(version_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_latest_memory_ref(
    agent_name: str | None = None,
    *,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    """Get latest version pointer metadata."""
    return _load_latest_pointer(agent_name, scope=scope, workspace_id=workspace_id)


def redact_memory(
    *,
    agent_name: str | None,
    fact_ids: list[str] | None = None,
    pattern: str | None = None,
    reason: str,
    actor: str,
    expected_sha: str | None = None,
    scope: str = MEMORY_SCOPE_GLOBAL,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Create a new memory version with redacted content."""
    fact_ids = [item for item in (fact_ids or []) if item]
    current = _load_memory_file(agent_name, scope=scope, workspace_id=workspace_id)
    if current is None:
        raise ValueError("No memory data found for redaction.")

    working = json.loads(json.dumps(current))
    facts = working.get("facts", [])
    if not isinstance(facts, list):
        facts = []
    removed_ids: list[str] = []
    kept_facts: list[dict[str, Any]] = []
    compiled = re.compile(pattern) if pattern else None

    def _deterministic_redact_text(text: str) -> str:
        if not text:
            return text
        cleaned = EMAIL_RE.sub("[REDACTED]", text)
        cleaned = PHONE_RE.sub("[REDACTED]", cleaned)
        cleaned = CARD_RE.sub("[REDACTED]", cleaned)
        return cleaned

    for fact in facts:
        if not isinstance(fact, dict):
            continue
        fact_id = str(fact.get("id") or "")
        content = str(fact.get("content") or "")
        if fact_id and fact_id in fact_ids:
            removed_ids.append(fact_id)
            continue
        if compiled and compiled.search(content):
            removed_ids.append(fact_id or f"pattern:{len(removed_ids)+1}")
            continue
        if content:
            fact["content"] = _deterministic_redact_text(content)
        kept_facts.append(fact)

    working["facts"] = kept_facts
    for section in ("user", "history"):
        section_data = working.get(section, {})
        if not isinstance(section_data, dict):
            continue
        for key, item in section_data.items():
            if not isinstance(item, dict):
                continue
            summary = item.get("summary")
            if isinstance(summary, str) and summary:
                cleaned = _deterministic_redact_text(summary)
                if compiled:
                    cleaned = compiled.sub("[REDACTED]", cleaned)
                section_data[key]["summary"] = cleaned

    if compiled:
        for fact in kept_facts:
            content = str(fact.get("content") or "")
            fact["content"] = compiled.sub("[REDACTED]", content)

    ref = persist_memory_data(
        working,
        agent_name=agent_name,
        expected_sha=expected_sha,
        operation="redact",
        audit={
            "reason": reason,
            "actor": actor,
            "affected_fact_ids": removed_ids,
            "pattern": pattern,
            "redacted_at": _utc_now_iso_z(),
        },
        scope=scope,
        workspace_id=workspace_id,
    )
    return {
        "ref": ref,
        "affected_fact_ids": removed_ids,
    }

