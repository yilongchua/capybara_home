"""Mtime-based cache for the lead agent system prompt.

``apply_prompt_template`` performs three synchronous disk reads on every call:
  - memory.json   (updated by the background memory worker, ~30 s debounce)
  - extensions_config.json  (skills enabled/disabled state)
  - SOUL.md       (agent personality, rarely changes)

For the typical back-and-forth in an active session these files are identical
between consecutive turns.  Caching the rendered prompt and invalidating only
when a file actually changes eliminates those reads on hot paths.

The cache also invalidates when the calendar date changes so the
``<current_date>`` tag stays accurate without a full rebuild.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

_lock = threading.Lock()


@dataclass
class _CacheEntry:
    prompt: str
    date: date
    mtimes: dict[str, float | None] = field(default_factory=dict)


# key → _CacheEntry
_cache: dict[tuple, _CacheEntry] = {}


def _mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _extensions_config_path() -> Path | None:
    try:
        from src.config.extensions_config import ExtensionsConfig

        return ExtensionsConfig.resolve_config_path()
    except Exception:
        return None


def _app_config_path() -> Path | None:
    try:
        from src.config.app_config import AppConfig

        return AppConfig.resolve_config_path()
    except Exception:
        return None


def _memory_file_path(agent_name: str | None) -> Path | None:
    try:
        from src.agents.memory.updater import _get_memory_file_path

        return _get_memory_file_path(agent_name)
    except Exception:
        return None


def _soul_file_path(agent_name: str | None) -> Path | None:
    try:
        from src.config.paths import get_paths

        paths = get_paths()
        if agent_name:
            candidate = paths.base_dir / "agents" / agent_name / "SOUL.md"
            return candidate if candidate.exists() else None
        return None
    except Exception:
        return None


def _current_mtimes(agent_name: str | None) -> dict[str, float | None]:
    return {
        "memory": _mtime(_memory_file_path(agent_name)),
        "extensions": _mtime(_extensions_config_path()),
        "soul": _mtime(_soul_file_path(agent_name)),
        "config": _mtime(_app_config_path()),
    }


def _is_stale(entry: _CacheEntry, agent_name: str | None) -> bool:
    if entry.date != date.today():
        return True
    current = _current_mtimes(agent_name)
    for key, current_val in current.items():
        cached_val = entry.mtimes.get(key)
        # If both are None (file absent both times) → not stale
        if cached_val is None and current_val is None:
            continue
        if cached_val != current_val:
            return True
    return False


def _cache_key(
    agent_name: str | None,
    subagent_enabled: bool,
    max_concurrent_subagents: int,
    available_skills: set[str] | None,
    prompt_componentized: bool,
    progressive_skills: bool,
) -> tuple[Any, ...]:
    skills_key = frozenset(available_skills) if available_skills is not None else None
    return (agent_name, subagent_enabled, max_concurrent_subagents, skills_key, prompt_componentized, progressive_skills)


def get_cached_prompt(
    build_fn,
    agent_name: str | None,
    subagent_enabled: bool,
    max_concurrent_subagents: int,
    available_skills: set[str] | None,
    prompt_componentized: bool,
    progressive_skills: bool,
) -> str:
    """Return a cached system prompt, rebuilding only when source files change.

    Args:
        build_fn: Zero-argument callable that builds and returns the full prompt
                  string.  Called only on a cache miss or stale entry.
        agent_name: Agent name (affects memory and soul file paths).
        subagent_enabled: Whether subagent mode is on.
        max_concurrent_subagents: Concurrency limit (affects the subagent block).
        available_skills: Skill filter set, or None for all enabled skills.
        prompt_componentized: Whether componentized prompt rendering is enabled.
        progressive_skills: Whether progressive skill disclosure is enabled.

    Returns:
        The rendered system prompt string.
    """
    key = _cache_key(agent_name, subagent_enabled, max_concurrent_subagents, available_skills, prompt_componentized, progressive_skills)

    with _lock:
        entry = _cache.get(key)
        if entry is not None and not _is_stale(entry, agent_name):
            return entry.prompt

        prompt = build_fn()
        _cache[key] = _CacheEntry(
            prompt=prompt,
            date=date.today(),
            mtimes=_current_mtimes(agent_name),
        )
        return prompt


def invalidate(agent_name: str | None = None) -> None:
    """Remove all cached entries for ``agent_name`` (or everything if None)."""
    with _lock:
        if agent_name is None:
            _cache.clear()
        else:
            keys_to_drop = [k for k in _cache if k[0] == agent_name]
            for k in keys_to_drop:
                del _cache[k]
