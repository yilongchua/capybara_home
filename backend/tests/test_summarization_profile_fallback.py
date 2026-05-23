"""Regression tests for token-only compaction normalization."""

from __future__ import annotations

from types import SimpleNamespace

from src.agents.lead_agent import agent as lead_agent_module
from src.config.summarization_config import ContextSize, SummarizationConfig, SummarizationModeOverride


class _FakeSummarizationMiddleware:
    calls: list[dict] = []

    def __init__(self, **kwargs):
        self.calls.append(kwargs)


def _app_config(*, context_window: int | None = None):
    model_config = SimpleNamespace(
        name="default-model",
        model_extra={"context_window": context_window} if context_window is not None else {},
    )
    return SimpleNamespace(
        models=[model_config],
        get_model_config=lambda name: model_config if name == "default-model" else None,
    )


def _install_common(monkeypatch, cfg: SummarizationConfig, *, model=None, context_window: int | None = None):
    _FakeSummarizationMiddleware.calls = []
    fake_model = model if model is not None else SimpleNamespace(profile=None)
    monkeypatch.setattr(lead_agent_module, "get_summarization_config", lambda: cfg)
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: _app_config(context_window=context_window))
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: fake_model)
    monkeypatch.setattr(lead_agent_module, "get_memory_config", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(lead_agent_module, "CapyHomeSummarizationMiddleware", _FakeSummarizationMiddleware)


def test_fraction_trigger_resolves_from_model_profile(monkeypatch):
    cfg = SummarizationConfig(
        enabled=True,
        trigger=ContextSize(type="fraction", value=0.8),
        keep=ContextSize(type="tokens", value=32000),
        max_context_tokens=128000,
    )
    model = SimpleNamespace(profile=SimpleNamespace(max_input_tokens=64000))
    _install_common(monkeypatch, cfg, model=model)

    middleware = lead_agent_module._create_summarization_middleware()

    assert isinstance(middleware, _FakeSummarizationMiddleware)
    assert _FakeSummarizationMiddleware.calls[0]["trigger"] == ("tokens", 51200)
    assert _FakeSummarizationMiddleware.calls[0]["keep"] == ("tokens", 32000)


def test_fraction_trigger_resolves_from_configured_max_context(monkeypatch):
    cfg = SummarizationConfig(
        enabled=True,
        trigger=ContextSize(type="fraction", value=0.8),
        keep=ContextSize(type="tokens", value=32000),
        max_context_tokens=128000,
        trim_tokens_to_summarize=12345,
    )
    _install_common(monkeypatch, cfg)

    lead_agent_module._create_summarization_middleware()

    assert _FakeSummarizationMiddleware.calls[0]["trigger"] == ("tokens", 102400)
    assert _FakeSummarizationMiddleware.calls[0]["trigger"] != ("tokens", 12345)


def test_fraction_trigger_resolves_from_model_config_when_global_missing(monkeypatch):
    cfg = SummarizationConfig(
        enabled=True,
        trigger=ContextSize(type="fraction", value=0.8),
        keep=ContextSize(type="tokens", value=32000),
    )
    _install_common(monkeypatch, cfg, context_window=100000)

    lead_agent_module._create_summarization_middleware()

    assert _FakeSummarizationMiddleware.calls[0]["trigger"] == ("tokens", 80000)


def test_message_trigger_ignored_and_message_keep_converted(monkeypatch):
    cfg = SummarizationConfig(
        enabled=True,
        trigger=[
            ContextSize(type="messages", value=30),
            ContextSize(type="fraction", value=0.8),
        ],
        keep=ContextSize(type="messages", value=10),
        max_context_tokens=128000,
    )
    _install_common(monkeypatch, cfg)

    lead_agent_module._create_summarization_middleware()

    call = _FakeSummarizationMiddleware.calls[0]
    assert call["trigger"] == ("tokens", 102400)
    assert call["keep"] == ("tokens", 32000)


def test_modes_inherit_token_only_policy(monkeypatch):
    cfg = SummarizationConfig(
        enabled=True,
        trigger=ContextSize(type="fraction", value=0.8),
        keep=ContextSize(type="tokens", value=32000),
        max_context_tokens=128000,
        modes={
            "default": SummarizationModeOverride(trim_tokens_to_summarize=32000),
            "dreamy": SummarizationModeOverride(trim_tokens_to_summarize=32000),
        },
    )
    _install_common(monkeypatch, cfg)

    lead_agent_module._create_summarization_middleware(mode="work")
    lead_agent_module._create_summarization_middleware(mode="plan")
    lead_agent_module._create_summarization_middleware(mode="work", dreamy_mode=True)

    for call in _FakeSummarizationMiddleware.calls:
        assert call["trigger"] == ("tokens", 102400)
        assert call["keep"] == ("tokens", 32000)
    assert len(_FakeSummarizationMiddleware.calls) == 3


def test_summary_prompt_omitted_when_config_uses_middleware_default(monkeypatch):
    cfg = SummarizationConfig(
        enabled=True,
        trigger=ContextSize(type="fraction", value=0.8),
        keep=ContextSize(type="tokens", value=32000),
        max_context_tokens=128000,
        summary_prompt=None,
    )
    _install_common(monkeypatch, cfg)

    lead_agent_module._create_summarization_middleware()

    assert "summary_prompt" not in _FakeSummarizationMiddleware.calls[0]
