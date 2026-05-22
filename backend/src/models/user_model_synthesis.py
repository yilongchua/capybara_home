"""Synthesize ModelConfig entries from user-added LLM endpoints.

User endpoints (stored in extensions_config.json under `userModels`) carry a
list of discovered model IDs per endpoint. This module flattens those into
ModelConfig entries with namespaced names of the form `{endpoint_key}/{model_id}`,
so the rest of the agent runtime (create_chat_model, ModelRouter, /api/models,
tool gating) can treat them as ordinary configured models.

A sentinel `__user_endpoint__` extra field is set on every synthesized entry so
refresh logic can later strip the old set before re-synthesizing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.config.extensions_config import (
    ExtensionsConfig,
    UserLlmEndpointConfig,
)
from src.config.model_config import ModelConfig

logger = logging.getLogger(__name__)

USER_ENDPOINT_MARKER = "__user_endpoint__"


def _build_model_config(
    endpoint_key: str,
    endpoint: UserLlmEndpointConfig,
    model_id: str,
) -> ModelConfig:
    """Build a single ModelConfig from one (endpoint, model_id) pair."""
    name = f"{endpoint_key}/{model_id}"
    # Chatbox shows only the endpoint's display name — the underlying model id
    # remains part of `name` for routing and is still surfaced in admin/debug
    # surfaces that read `model_extra`.
    display_name = endpoint.display_name

    # ChatOpenAI requires a non-empty api_key string even for local backends
    # that ignore it (Ollama, LM Studio). Use a placeholder when blank.
    api_key = endpoint.api_key or "not-needed"

    return ModelConfig(
        name=name,
        display_name=display_name,
        description=f"User endpoint: {endpoint.display_name} ({endpoint.provider})",
        use="langchain_openai:ChatOpenAI",
        model=model_id,
        base_url=endpoint.base_url,
        api_key=api_key,
        supports_thinking=endpoint.supports_thinking,
        supports_vision=endpoint.supports_vision,
        **{USER_ENDPOINT_MARKER: endpoint_key},
    )


def synthesize_user_models(
    extensions_config: ExtensionsConfig,
) -> list[ModelConfig]:
    """Return ModelConfig entries flattened from enabled user endpoints."""
    synthesized: list[ModelConfig] = []
    for endpoint_key, endpoint in extensions_config.user_models.items():
        if not endpoint.enabled:
            continue
        for model_id in endpoint.models:
            if not model_id:
                continue
            try:
                synthesized.append(_build_model_config(endpoint_key, endpoint, model_id))
            except Exception as exc:
                logger.warning(
                    "Failed to synthesize user model '%s/%s': %s",
                    endpoint_key, model_id, exc,
                )
    return synthesized


def is_user_synthesized(model_config: ModelConfig) -> bool:
    """Return True if a ModelConfig was synthesized from a user endpoint."""
    extra = model_config.model_extra or {}
    return USER_ENDPOINT_MARKER in extra


def extensions_config_mtime() -> float | None:
    """Best-effort mtime of the active extensions_config.json, or None if absent."""
    try:
        path = ExtensionsConfig.resolve_config_path()
    except FileNotFoundError:
        return None
    if path is None:
        return None
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None
