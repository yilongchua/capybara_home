"""Stage-aware model router."""

from __future__ import annotations

from src.config.app_config import AppConfig, get_app_config


class ModelRouter:
    """Resolve model names for agent stages with fallback cascade."""

    def __init__(self, app_config: AppConfig | None = None):
        self._app_config = app_config or get_app_config()

    def _is_valid(self, model_name: str | None) -> bool:
        if not model_name:
            return False
        return self._app_config.get_model_config(model_name) is not None

    def resolve(self, stage: str, requested_model: str | None = None) -> str:
        """Resolve model for a stage.

        Fallback order:
        1) generator stage requested model (when valid)
        2) routing.stages[stage]
        3) requested model (for non-generator)
        4) routing.fallback
        5) app default model
        """
        routing = self._app_config.routing
        default_model = self._app_config.models[0].name if self._app_config.models else None

        if stage == "generator" and self._is_valid(requested_model):
            return requested_model  # explicit generator override

        mapped_model = routing.stages.get(stage) if routing and routing.stages else None
        if self._is_valid(mapped_model):
            return str(mapped_model)

        if self._is_valid(requested_model):
            return str(requested_model)

        if self._is_valid(routing.fallback):
            return str(routing.fallback)

        if default_model is None:
            raise ValueError("No chat models are configured.")
        return default_model

    def endpoint_label(self, stage: str, requested_model: str | None = None) -> str:
        """Best-effort endpoint label used by metrics/schedulers."""
        resolved = self.resolve(stage, requested_model=requested_model)
        primary = self.resolve("generator", requested_model=requested_model)
        return "primary" if resolved == primary else "helper"
