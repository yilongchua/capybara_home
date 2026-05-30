"""Typed accessor for `Runtime` context.

LangGraph plumbs runtime configuration via two surfaces:

* ``runtime.context`` — newer dict-shaped view, preferred when available.
* ``runtime.config["configurable"]`` — legacy location that older code paths
  (e.g. ``make_plan_agent``'s ``forced_config["configurable"]``) still write
  to directly.

This helper reads ``context`` first and falls back to ``configurable`` so
middlewares don't each need to re-implement the lookup. Always returns a
dict (never ``None``) so callers can chain ``.get(...)`` safely.
"""

from __future__ import annotations

from typing import Any


def get_runtime_context(runtime: Any) -> dict[str, Any]:
    """Return the effective runtime context as a dict.

    Reads ``runtime.context`` first; falls back to
    ``runtime.config["configurable"]``. Returns an empty dict when neither
    surface is present.
    """
    context = getattr(runtime, "context", None)
    if isinstance(context, dict) and context:
        return context

    config = getattr(runtime, "config", None)
    if isinstance(config, dict):
        configurable = config.get("configurable")
        if isinstance(configurable, dict):
            return configurable

    if isinstance(context, dict):
        return context
    return {}
