"""Configuration for the harness-level kill switch.

When ``enabled=True`` (default) the full middleware chain runs. When ``False``,
``_build_middleware_registry`` returns only the small plumbing subset that the
rest of the system hard-depends on (thread data, sandbox, dangling-tool-call,
clarification). This is a single-toggle incident-response lever — flip it off
to shed every Phase-A/B/C feature in one step without editing individual
``*.enabled`` flags.

Runtime-reloadable via ``PUT /api/harness/config``. The Gateway writes the
override to a ``harness_runtime.json`` sidecar next to ``config.yaml``; every
subsequent ``get_harness_config()`` call picks up the new value by comparing
the file's ``mtime`` — so the LangGraph Server (separate process) converges to
the new value on its next run without needing a restart or explicit reload.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_SIDECAR_FILENAME = "harness_runtime.json"


class HarnessConfig(BaseModel):
    """Harness-level kill switch."""

    enabled: bool = Field(
        default=True,
        description=(
            "When False, the lead agent runs with only the minimal plumbing "
            "middlewares (thread_data, sandbox, dangling_tool_call, clarification). "
            "All Phase-A/B/C feature middlewares are skipped."
        ),
    )


_harness_config: HarnessConfig = HarnessConfig()
_sidecar_mtime: float | None = None
_lock = Lock()


def _sidecar_path() -> Path:
    """Resolve where the runtime override sidecar lives.

    Mirrors the config-path resolution for ``config.yaml``: prefer the current
    working directory, fall back to the project root (parent). The override is
    optional; when absent, the in-memory default applies.
    """
    override = os.environ.get("CAPYBARA_HOME_HARNESS_RUNTIME_PATH")
    if override:
        return Path(override)
    cwd_candidate = Path.cwd() / _SIDECAR_FILENAME
    if cwd_candidate.exists():
        return cwd_candidate
    parent_candidate = Path.cwd().parent / _SIDECAR_FILENAME
    return parent_candidate if parent_candidate.exists() else cwd_candidate


def _refresh_from_sidecar_if_stale() -> None:
    """Reload the in-memory config if the sidecar mtime has advanced."""
    global _harness_config, _sidecar_mtime
    path = _sidecar_path()
    try:
        if not path.exists():
            return
        mtime = path.stat().st_mtime
    except OSError:
        return
    if _sidecar_mtime is not None and mtime == _sidecar_mtime:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read harness sidecar %s: %s", path, exc)
        return
    if not isinstance(data, dict):
        return
    with _lock:
        _harness_config = HarnessConfig(**data)
        _sidecar_mtime = mtime
        logger.info("HarnessConfig reloaded from %s: enabled=%s", path, _harness_config.enabled)


def get_harness_config() -> HarnessConfig:
    """Return the current harness configuration (reloads from sidecar if stale)."""
    _refresh_from_sidecar_if_stale()
    return _harness_config


def set_harness_config(config: HarnessConfig) -> None:
    """Replace the harness configuration in-memory (used by Gateway PUT handler)."""
    global _harness_config
    with _lock:
        _harness_config = config


def write_harness_sidecar(config: HarnessConfig, path: Path | None = None) -> Path:
    """Persist the configuration to the sidecar JSON and refresh the in-memory cache."""
    global _sidecar_mtime
    target = path or _sidecar_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config.model_dump(), indent=2), encoding="utf-8")
    with _lock:
        _sidecar_mtime = target.stat().st_mtime
    return target


def load_harness_config_from_dict(config_dict: dict) -> None:
    """Load harness configuration from a dictionary (called by AppConfig)."""
    global _harness_config
    with _lock:
        _harness_config = HarnessConfig(**(config_dict or {}))
    # After baseline load, let sidecar override if present.
    _refresh_from_sidecar_if_stale()
