"""Regression tests for summarization profile-metadata fallback."""

from __future__ import annotations

from types import SimpleNamespace

from src.agents.lead_agent import agent as lead_agent_module
from src.config.summarization_config import ContextSize, SummarizationConfig

PROFILE_ERROR = "Model profile information is required to use fractional token limits"


class _FakeSummarizationMiddleware:
    """Raise the same error as LangChain when fraction thresholds are used."""

    calls: list[dict] = []

    def __init__(self, **kwargs):
        self.calls.append(kwargs)
        trigger = kwargs.get("trigger")
        keep = kwargs.get("keep")
        trigger_has_fraction = False
        if isinstance(trigger, tuple):
            trigger_has_fraction = bool(trigger and trigger[0] == "fraction")
        elif isinstance(trigger, list):
            trigger_has_fraction = any(t and t[0] == "fraction" for t in trigger)
        keep_has_fraction = bool(isinstance(keep, tuple) and keep and keep[0] == "fraction")
        if trigger_has_fraction or keep_has_fraction:
            raise ValueError(PROFILE_ERROR)


def test_fallback_drops_fractional_trigger(monkeypatch):
    _FakeSummarizationMiddleware.calls = []
    cfg = SummarizationConfig(
        enabled=True,
        trigger=[
            ContextSize(type="tokens", value=8000),
            ContextSize(type="fraction", value=0.6),
        ],
        keep=ContextSize(type="messages", value=10),
        trim_tokens_to_summarize=15564,
    )
    monkeypatch.setattr(lead_agent_module, "get_summarization_config", lambda: cfg)
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "fake-model")
    monkeypatch.setattr(lead_agent_module, "get_memory_config", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(lead_agent_module, "CapybaraSummarizationMiddleware", _FakeSummarizationMiddleware)

    middleware = lead_agent_module._create_summarization_middleware()

    assert isinstance(middleware, _FakeSummarizationMiddleware)
    assert len(_FakeSummarizationMiddleware.calls) == 2
    assert _FakeSummarizationMiddleware.calls[0]["trigger"] == [("tokens", 8000), ("fraction", 0.6)]
    assert _FakeSummarizationMiddleware.calls[1]["trigger"] == [("tokens", 8000)]


def test_fallback_replaces_fractional_keep(monkeypatch):
    _FakeSummarizationMiddleware.calls = []
    cfg = SummarizationConfig(
        enabled=True,
        trigger=ContextSize(type="tokens", value=6000),
        keep=ContextSize(type="fraction", value=0.3),
        trim_tokens_to_summarize=12000,
    )
    monkeypatch.setattr(lead_agent_module, "get_summarization_config", lambda: cfg)
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "fake-model")
    monkeypatch.setattr(lead_agent_module, "get_memory_config", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(lead_agent_module, "CapybaraSummarizationMiddleware", _FakeSummarizationMiddleware)

    middleware = lead_agent_module._create_summarization_middleware()

    assert isinstance(middleware, _FakeSummarizationMiddleware)
    assert len(_FakeSummarizationMiddleware.calls) == 2
    assert _FakeSummarizationMiddleware.calls[0]["keep"] == ("fraction", 0.3)
    assert _FakeSummarizationMiddleware.calls[1]["keep"] == ("messages", 20)


def test_fallback_uses_tokens_when_trigger_only_fraction(monkeypatch):
    _FakeSummarizationMiddleware.calls = []
    cfg = SummarizationConfig(
        enabled=True,
        trigger=ContextSize(type="fraction", value=0.6),
        keep=ContextSize(type="messages", value=10),
        trim_tokens_to_summarize=12345,
    )
    monkeypatch.setattr(lead_agent_module, "get_summarization_config", lambda: cfg)
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "fake-model")
    monkeypatch.setattr(lead_agent_module, "get_memory_config", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(lead_agent_module, "CapybaraSummarizationMiddleware", _FakeSummarizationMiddleware)

    middleware = lead_agent_module._create_summarization_middleware()

    assert isinstance(middleware, _FakeSummarizationMiddleware)
    assert len(_FakeSummarizationMiddleware.calls) == 2
    assert _FakeSummarizationMiddleware.calls[1]["trigger"] == ("tokens", 12345)


