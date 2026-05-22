"""Tests for the single-model resolver.

Locks the invariant: the chat-selected model wins over any stage routing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def patched_app_config(monkeypatch):
    """Inject a synthetic AppConfig with two models — chat-pick and default."""
    model_default = MagicMock(name="default-model", spec=[])
    model_default.name = "default-model"
    model_chat = MagicMock(name="chat-pick", spec=[])
    model_chat.name = "chat-pick"

    app_config = MagicMock()
    app_config.models = [model_default, model_chat]
    # routing.stages is intentionally non-empty to prove it's IGNORED.
    app_config.routing = MagicMock(stages={"planner": "should-be-ignored"})

    def _get_model_config(name: str):
        for m in app_config.models:
            if m.name == name:
                return m
        return None

    app_config.get_model_config = MagicMock(side_effect=_get_model_config)
    monkeypatch.setattr("src.models.resolver.get_app_config", lambda: app_config)
    return app_config


def test_resolver_honors_user_selection(patched_app_config) -> None:
    from src.models.resolver import resolve_model_name

    assert resolve_model_name("chat-pick") == "chat-pick"


def test_resolver_ignores_routing_stages_entirely(patched_app_config) -> None:
    # The user did not pass a model — but routing.stages.planner says
    # "should-be-ignored". The resolver must fall back to app default, NOT
    # to routing.stages.
    from src.models.resolver import resolve_model_name

    assert resolve_model_name(None) == "default-model"


def test_resolver_falls_back_when_invalid(patched_app_config) -> None:
    from src.models.resolver import resolve_model_name

    assert resolve_model_name("does-not-exist") == "default-model"


def test_resolver_raises_when_no_models(monkeypatch) -> None:
    app_config = MagicMock()
    app_config.models = []
    monkeypatch.setattr("src.models.resolver.get_app_config", lambda: app_config)

    from src.models.resolver import resolve_model_name

    with pytest.raises(ValueError, match="No chat models"):
        resolve_model_name(None)
