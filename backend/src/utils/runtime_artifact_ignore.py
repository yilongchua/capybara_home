"""Shared ignore policy for non-essential runtime/build/dependency artifacts."""

from __future__ import annotations

import fnmatch
from pathlib import PurePath

# Directory names that should be skipped during broad repository traversal.
RUNTIME_ARTIFACT_DIR_NAMES: set[str] = {
    # VCS
    ".git",
    ".hg",
    ".svn",
    ".bzr",
    # Python
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "site-packages",
    # JavaScript / frontend
    "node_modules",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    # Build outputs (multi-language)
    "dist",
    "build",
    "target",
    "out",
    "bin",
    "obj",
    # Tooling / editor
    ".idea",
    ".vscode",
    # Coverage / caches / temp
    "coverage",
    ".nyc_output",
    "htmlcov",
    ".cache",
    ".runtime",
    "logs",
}

# Name globs for files/dirs that are usually non-essential runtime artifacts.
RUNTIME_ARTIFACT_NAME_PATTERNS: tuple[str, ...] = (
    "*.log",
    "*.tmp",
    "*.temp",
    "*.cache",
    "*.bak",
    "*.swp",
    "*.swo",
    "*~",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
)


def is_runtime_artifact_name(name: str) -> bool:
    if name in RUNTIME_ARTIFACT_DIR_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in RUNTIME_ARTIFACT_NAME_PATTERNS)


def should_skip_relative_path(path: str | PurePath) -> bool:
    """Return True if any path segment matches runtime-artifact ignore policy."""
    pure = path if isinstance(path, PurePath) else PurePath(path)
    return any(is_runtime_artifact_name(part) for part in pure.parts)

