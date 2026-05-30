"""Progressive skill disclosure middleware."""

from __future__ import annotations

import fnmatch
import hashlib
import re
from collections import OrderedDict
from threading import Lock
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.config import get_app_config
from src.skills import load_skills
from src.skills.types import Skill

_PATH_TOKEN_RE = re.compile(r"(?:/|\.{1,2}/|[A-Za-z0-9_\-./]+/[A-Za-z0-9_\-./]+)")

# Bounded LRU cache for skill-file contents keyed by absolute path; invalidated
# when mtime shifts. mtime check alone would leak entries for deleted/renamed
# skills, so we also cap the number of distinct paths held.
_SKILL_BODY_CACHE_MAX = 128
_SKILL_BODY_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_SKILL_BODY_LOCK = Lock()


def _read_skill_body(skill: Skill) -> str:
    path = skill.skill_file
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        # Fall back to uncached read when stat fails; caller bubbles the error.
        return path.read_text(encoding="utf-8")
    with _SKILL_BODY_LOCK:
        cached = _SKILL_BODY_CACHE.get(key)
        if cached is not None and cached[0] == mtime:
            _SKILL_BODY_CACHE.move_to_end(key)  # LRU bump
            return cached[1]
    body = path.read_text(encoding="utf-8")
    with _SKILL_BODY_LOCK:
        _SKILL_BODY_CACHE[key] = (mtime, body)
        _SKILL_BODY_CACHE.move_to_end(key)
        while len(_SKILL_BODY_CACHE) > _SKILL_BODY_CACHE_MAX:
            _SKILL_BODY_CACHE.popitem(last=False)  # evict oldest
    return body


class SkillDisclosureState(AgentState):
    skill_disclosure: NotRequired[dict | None]


def _normalize_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [str(part.get("text", "")) for part in content if isinstance(part, dict)]
        return " ".join(text_parts)
    return str(content or "")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class SkillDisclosureMiddleware(AgentMiddleware[SkillDisclosureState]):
    """Keep skill descriptions global, load full bodies only when active."""

    state_schema = SkillDisclosureState

    def _last_human_text(self, state: SkillDisclosureState) -> str:
        messages = state.get("messages", []) or []
        for msg in reversed(messages):
            if getattr(msg, "type", None) != "human":
                continue
            return _normalize_text(getattr(msg, "content", ""))
        return ""

    def _candidate_paths(self, state: SkillDisclosureState, text: str) -> list[str]:
        candidates: set[str] = set()
        uploaded_files = state.get("uploaded_files", []) or []
        for item in uploaded_files:
            if isinstance(item, dict):
                path = item.get("path")
                if isinstance(path, str) and path:
                    candidates.add(path)
        for token in _PATH_TOKEN_RE.findall(text):
            if token:
                candidates.add(token)
        return sorted(candidates)

    @staticmethod
    def _explicitly_requested(skill: Skill, text_lower: str) -> bool:
        skill_name = skill.name.lower()
        return f"/{skill_name}" in text_lower or f"${skill_name}" in text_lower

    @staticmethod
    def _matches_paths(skill: Skill, candidates: list[str]) -> bool:
        if not skill.paths:
            return False
        for pattern in skill.paths:
            for path in candidates:
                if fnmatch.fnmatch(path, pattern):
                    return True
        return False

    def _build_active_skills_block(self, skills: list[Skill]) -> str:
        blocks = []
        for skill in skills:
            body = _read_skill_body(skill)
            blocks.append(
                f"<skill>\n<name>{skill.name}</name>\n<path>{skill.get_container_file_path(get_app_config().skills.container_path)}</path>\n{body}\n</skill>"
            )
        return "<active_skills>\n" + "\n\n".join(blocks) + "\n</active_skills>"

    def _select_skills(
        self,
        all_skills: list[Skill],
        active_map: dict[str, int],
        budget: int,
    ) -> list[Skill]:
        by_name = {s.name: s for s in all_skills}
        ordered_names = sorted(active_map, key=lambda n: active_map[n], reverse=True)
        selected: list[Skill] = []
        used = 0
        for name in ordered_names:
            skill = by_name.get(name)
            if skill is None:
                continue
            tokens = _estimate_tokens(_read_skill_body(skill))
            if selected and used + tokens > budget:
                continue
            if not selected and tokens > budget:
                # Always keep at least one requested skill.
                selected.append(skill)
                break
            selected.append(skill)
            used += tokens
        return selected

    @override
    def before_model(self, state: SkillDisclosureState, runtime: Runtime) -> dict | None:
        app_config = get_app_config()
        if not app_config.skills.progressive_disclosure:
            return None

        enabled_skills = load_skills(enabled_only=True)
        if not enabled_skills:
            return None

        sd = dict(state.get("skill_disclosure") or {})
        active_map: dict[str, int] = dict(sd.get("active") or {})
        turn = int(sd.get("turn", 0)) + 1

        text = self._last_human_text(state)
        text_lower = text.lower()
        candidates = self._candidate_paths(state, text)

        for skill in enabled_skills:
            if self._explicitly_requested(skill, text_lower):
                active_map[skill.name] = turn
                continue
            if app_config.skills.matcher_trigger_enabled and self._matches_paths(skill, candidates):
                active_map[skill.name] = turn

        if not active_map:
            return {"skill_disclosure": {"active": {}, "turn": turn, "last_injected_hash": ""}}

        selected = self._select_skills(enabled_skills, active_map, app_config.skills.active_body_token_budget)
        selected_names = {skill.name for skill in selected}
        active_map = {name: last_turn for name, last_turn in active_map.items() if name in selected_names}
        if not selected:
            return {"skill_disclosure": {"active": active_map, "turn": turn, "last_injected_hash": ""}}

        active_block = self._build_active_skills_block(selected)
        block_hash = hashlib.sha256(active_block.encode("utf-8")).hexdigest()
        if block_hash == sd.get("last_injected_hash"):
            return {"skill_disclosure": {"active": active_map, "turn": turn, "last_injected_hash": block_hash}}

        reminder = HumanMessage(
            name="active_skills",
            content=(
                "<system_reminder>\n"
                "Active skills loaded for this turn:\n"
                f"{active_block}\n"
                "</system_reminder>"
            ),
        )
        return {
            "messages": [reminder],
            "skill_disclosure": {"active": active_map, "turn": turn, "last_injected_hash": block_hash},
        }

    @override
    async def abefore_model(self, state: SkillDisclosureState, runtime: Runtime) -> dict | None:
        return self.before_model(state, runtime)
