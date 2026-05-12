"""Regression tests for thread c5edd504 corrective findings."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain.chat_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.checkpointer.extended_sqlite_saver import ExtendedAsyncSqliteSaver
from src.agents.middlewares.summarization_middleware import CapybaraSummarizationMiddleware
from src.agents.middlewares.write_file_artifact_middleware import WriteFileArtifactMiddleware
from src.community.web_search import tools as web_search_tools
from src.models import factory as factory_module


class _FakeChatModel(BaseChatModel):
    captured_kwargs: dict = {}

    def __init__(self, **kwargs):
        _FakeChatModel.captured_kwargs = dict(kwargs)
        super().__init__(**kwargs)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    def _stream(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError


def _tool_call_request(path: str, *, tool_name: str = "write_file"):
    return SimpleNamespace(
        tool_call={
            "name": tool_name,
            "id": "tc-1",
            "args": {"path": path},
        }
    )


def test_write_file_artifact_middleware_promotes_outputs_path_on_ok():
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request("/mnt/user-data/outputs/report.md")

    async def handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))
    assert isinstance(result, Command)
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/report.md"]


def test_write_file_artifact_middleware_skips_non_ok_or_non_outputs_path():
    middleware = WriteFileArtifactMiddleware()
    bad_request = _tool_call_request("/mnt/user-data/outputs/report.md")
    external_request = _tool_call_request("/tmp/report.md")

    async def non_ok_handler(_request):
        return ToolMessage(content="Error: failed", tool_call_id="tc-1", name="write_file")

    async def ok_handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    non_ok_result = asyncio.run(middleware.awrap_tool_call(bad_request, non_ok_handler))
    external_result = asyncio.run(middleware.awrap_tool_call(external_request, ok_handler))

    assert isinstance(non_ok_result, ToolMessage)
    assert isinstance(external_result, ToolMessage)


def test_model_factory_strips_endpoints_kwarg_before_model_ctor(monkeypatch):
    class _FakeModelConfig:
        use = "langchain_openai:ChatOpenAI"
        name = "fake"
        display_name = None
        description = None
        supports_thinking = False
        supports_reasoning_effort = False
        when_thinking_enabled = None
        thinking = None
        supports_vision = False

        def model_dump(self, **kwargs):
            return {
                "model": "gpt-4o-mini",
                "api_key": "test",
                "endpoints": ["http://127.0.0.1:1234/v1"],
            }

    class _FakeAppConfig:
        model_extra = {}
        models = [SimpleNamespace(name="fake")]

        def get_model_config(self, _name):
            return _FakeModelConfig()

    monkeypatch.setattr(factory_module, "get_app_config", lambda: _FakeAppConfig())
    monkeypatch.setattr(factory_module, "resolve_class", lambda _path, _base: _FakeChatModel)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)

    _FakeChatModel.captured_kwargs = {}
    factory_module.create_chat_model(name="fake")

    assert "endpoints" not in _FakeChatModel.captured_kwargs
    assert _FakeChatModel.captured_kwargs.get("base_url") == "http://127.0.0.1:1234/v1"


def test_web_search_timeout_defaults_to_routing_timeout(monkeypatch):
    fake_tool_cfg = SimpleNamespace(model_extra={})
    fake_backend = SimpleNamespace(enabled=True, base_url="http://127.0.0.1:9000", timeout_seconds=None)
    fake_app_config = SimpleNamespace(
        tool_backends=SimpleNamespace(websearch=fake_backend),
        get_tool_config=lambda name: fake_tool_cfg if name == "web_search" else None,
    )
    fake_routing = SimpleNamespace(timeouts=SimpleNamespace(for_tool=lambda _name: 45))

    monkeypatch.setattr(web_search_tools, "get_app_config", lambda: fake_app_config)
    monkeypatch.setattr(web_search_tools, "get_routing_config", lambda: fake_routing)

    cfg = web_search_tools._load_web_search_config()
    assert cfg["timeout_seconds"] == 45.0
    assert cfg["routing_timeout_seconds"] == 45
    assert cfg["timeout_source"] == "routing.timeouts.tools.web_search"


def test_web_search_timeout_override_logs_mismatch_warning(monkeypatch, caplog):
    caplog.set_level("WARNING")

    fake_tool_cfg = SimpleNamespace(model_extra={})
    fake_backend = SimpleNamespace(enabled=True, base_url="http://127.0.0.1:9000", timeout_seconds=20)
    fake_app_config = SimpleNamespace(
        tool_backends=SimpleNamespace(websearch=fake_backend),
        get_tool_config=lambda name: fake_tool_cfg if name == "web_search" else None,
    )
    fake_routing = SimpleNamespace(timeouts=SimpleNamespace(for_tool=lambda _name: 45))

    monkeypatch.setattr(web_search_tools, "get_app_config", lambda: fake_app_config)
    monkeypatch.setattr(web_search_tools, "get_routing_config", lambda: fake_routing)

    cfg = web_search_tools._load_web_search_config()
    assert cfg["timeout_seconds"] == 20.0
    assert cfg["timeout_source"] == "tool_backends.websearch.timeout_seconds"
    assert "web_search timeout mismatch" in caplog.text


def test_summarization_trigger_type_uses_preserved_trigger_tuples():
    model = MagicMock()
    model.invoke = MagicMock(return_value=MagicMock(content="summary"))

    with patch("langchain.agents.middleware.summarization.init_chat_model", return_value=model):
        middleware = CapybaraSummarizationMiddleware(
            model="mock-model",
            trigger=[("tokens", 1000), ("messages", 50)],
            keep=("messages", 10),
        )

    fake_messages = [MagicMock() for _ in range(60)]
    assert middleware._detect_trigger_type(fake_messages, 1500) == "tokens"
    assert middleware._detect_trigger_type(fake_messages, 500) == "messages"


def test_extended_sqlite_saver_exposes_required_methods():
    for method in ("adelete_for_runs", "aprune", "acopy_thread"):
        assert method in ExtendedAsyncSqliteSaver.__dict__


def test_extended_sqlite_saver_noop_calls_do_not_raise():
    async def _run():
        async with ExtendedAsyncSqliteSaver.from_conn_string(":memory:") as saver:
            await saver.setup()
            await saver.adelete_for_runs([])
            await saver.aprune([])
            await saver.acopy_thread("missing-thread", "target-thread")

    asyncio.run(_run())
