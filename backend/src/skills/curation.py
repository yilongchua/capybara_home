"""Skill auto-curation proposal helpers."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from src.config.paths import get_paths
from src.config.skill_curation_config import get_skill_curation_config
from src.skills.loader import get_skills_root_path


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "auto-skill"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _collect_tool_usage() -> dict[str, dict[str, Any]]:
    root = get_paths().base_dir / "threads"
    usage: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return usage
    for trajectory_file in root.glob("*/logs/trajectory/*.jsonl"):
        for event in _load_jsonl(trajectory_file):
            if event.get("event") != "tool_call_start":
                continue
            payload = event.get("payload") or {}
            tool_name = str(payload.get("tool") or "").strip()
            if not tool_name:
                continue
            item = usage.setdefault(
                tool_name,
                {
                    "count": 0,
                    "evidence_refs": [],
                },
            )
            item["count"] += 1
            if len(item["evidence_refs"]) < 5:
                item["evidence_refs"].append(str(trajectory_file))
    return usage


def _confidence(count: int) -> float:
    return min(0.95, 0.45 + (count / 12))


def _write_skill_proposal(skill_name: str, tool_name: str, confidence: float, evidence_refs: list[str], review_status: str, proposed_at: str) -> Path:
    custom_root = get_skills_root_path() / "custom"
    proposal_root = custom_root / "auto-proposals"
    proposal_root.mkdir(parents=True, exist_ok=True)
    target = proposal_root / skill_name
    suffix = 2
    while target.exists():
        target = proposal_root / f"{skill_name}-{suffix}"
        suffix += 1
    target.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        "---\n"
        f"name: {target.name}\n"
        f"description: Auto-curated helper for frequent `{tool_name}` workflows.\n"
        "license: Apache-2.0\n"
        f"allowed-tools: [{tool_name}]\n"
        "metadata:\n"
        "  generated_by: skill-curation\n"
        f"  confidence: {confidence:.3f}\n"
        f"  review_status: {review_status}\n"
        f"  proposed_at: {proposed_at}\n"
        f"  evidence_refs: {json.dumps(evidence_refs)}\n"
        "---\n\n"
    )
    body = (
        f"# {target.name}\n\n"
        f"Use this skill when tasks repeatedly require `{tool_name}`.\n\n"
        "## Workflow\n"
        "1. Inspect request and decide whether this tool-centric flow is needed.\n"
        "2. Execute the tool with focused arguments.\n"
        "3. Summarize outcomes and next actions.\n"
    )
    (target / "SKILL.md").write_text(frontmatter + body, encoding="utf-8")
    return target


def _disable_proposals(skill_names: list[str]) -> None:
    config_path = ExtensionsConfig.resolve_config_path()
    if config_path is None:
        return
    current = get_extensions_config()
    skill_map = {name: SkillStateConfig(enabled=state.enabled) for name, state in current.skills.items()}
    for skill_name in skill_names:
        skill_map[skill_name] = SkillStateConfig(enabled=False)
    config_payload = {
        "mcpServers": {name: server.model_dump() for name, server in current.mcp_servers.items()},
        "skills": {name: {"enabled": state.enabled} for name, state in skill_map.items()},
    }
    config_path.write_text(json.dumps(config_payload, indent=2), encoding="utf-8")
    reload_extensions_config()


def generate_skill_proposals(limit: int = 5) -> list[dict[str, Any]]:
    """Generate proposal-only skills from trajectory usage evidence."""
    cfg = get_skill_curation_config()
    if not cfg.enabled:
        return []

    usage = _collect_tool_usage()
    candidates = sorted(usage.items(), key=lambda item: item[1]["count"], reverse=True)
    proposals: list[dict[str, Any]] = []
    proposed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for tool_name, stats in candidates:
        count = int(stats["count"])
        confidence = _confidence(count)
        if confidence < cfg.min_confidence:
            continue
        skill_name = f"auto-{_slugify(tool_name)}-workflow"
        proposed_path = _write_skill_proposal(
            skill_name=skill_name,
            tool_name=tool_name,
            confidence=confidence,
            evidence_refs=list(stats["evidence_refs"]),
            review_status="pending_review",
            proposed_at=proposed_at,
        )
        proposals.append(
            {
                "name": proposed_path.name,
                "tool": tool_name,
                "confidence": confidence,
                "review_status": "pending_review",
                "evidence_refs": list(stats["evidence_refs"]),
                "path": str(proposed_path),
                "proposal_only": cfg.proposal_only,
                "require_human_approval": cfg.require_human_approval,
            }
        )
        if len(proposals) >= max(1, limit):
            break

    if proposals:
        _disable_proposals([item["name"] for item in proposals])
    return proposals
