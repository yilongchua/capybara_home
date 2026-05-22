"""Single-model resolver.

Local deployment runs exactly one main LLM endpoint at a time. The stage-based
``ModelRouter.resolve(stage, ...)`` is unnecessary here and risks divergence if
``routing.stages`` is ever populated — it would silently override the user's
chat-selected model. ``resolve_model_name`` honors the user's UI selection
unconditionally, falling back only to the configured app default.

Prefer this helper in middleware/tool code over ``ModelRouter.resolve(...)``.
"""

from __future__ import annotations

import logging

from src.config.app_config import get_app_config

logger = logging.getLogger(__name__)


def resolve_model_name(requested_model_name: str | None = None) -> str:
    """Return the chat-selected model name, or the app default if unset/invalid.

    Args:
        requested_model_name: the model the user picked in the chat UI
            (passed via ``config.configurable.model_name``). Can be None.

    Returns:
        A valid model name registered in ``app_config.models``.

    Raises:
        ValueError: if no models are configured at all.
    """
    app_config = get_app_config()
    default_model_name = app_config.models[0].name if app_config.models else None
    if default_model_name is None:
        raise ValueError("No chat models are configured. Please configure at least one model in config.yaml.")

    if requested_model_name and app_config.get_model_config(requested_model_name):
        return requested_model_name

    if requested_model_name and requested_model_name != default_model_name:
        logger.warning(
            "Model '%s' not found in config; falling back to default '%s'.",
            requested_model_name,
            default_model_name,
        )
    return default_model_name
