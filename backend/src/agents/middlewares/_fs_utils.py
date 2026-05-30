"""Filesystem helpers shared across plan-mode middlewares."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write `content` to `path` via a tempfile + os.replace().

    Crash-safety: a partially-written file never appears at the final path.
    The temp file lives in the same directory so the rename is on one
    filesystem (POSIX atomic). A uuid suffix on the tmp name makes the
    helper safe for concurrent callers writing to the same final path —
    each writer owns its own tmp file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content, encoding=encoding)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def write_if_changed(path: Path | str, content: str, *, encoding: str = "utf-8") -> bool:
    """Write `content` to `path` only when on-disk bytes differ.

    Returns ``True`` when a write happened, ``False`` otherwise. Writes go
    through :func:`atomic_write_text` so partial writes never appear at the
    final path. Read errors fall through to a write (best-effort), matching
    the previous inlined behavior in scratchpad and handoff sync paths.
    """
    target = Path(path)
    if target.exists():
        try:
            if target.read_text(encoding=encoding) == content:
                return False
        except OSError:
            pass
    atomic_write_text(target, content, encoding=encoding)
    return True
