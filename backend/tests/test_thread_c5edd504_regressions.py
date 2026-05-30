"""Regression tests for thread c5edd504 corrective findings."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain.chat_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.checkpointer.extended_sqlite_saver import ExtendedAsyncSqliteSaver
from src.agents.middlewares.summarization_middleware import CapyHomeSummarizationMiddleware
from src.agents.middlewares.write_file_artifact_middleware import WriteFileArtifactMiddleware
from src.agents.report_quality import QualityCheckResult
from src.community.web_search import tools as web_search_tools
from src.config.quality_gate_config import QualityGateConfig
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


def _tool_call_request(path: str, *, tool_name: str = "write_file", args: dict | None = None, state: dict | None = None):
    return SimpleNamespace(
        tool_call={
            "name": tool_name,
            "id": "tc-1",
            "args": {"path": path, **(args or {})},
        },
        state=state or {},
    )


def test_write_file_artifact_middleware_promotes_outputs_path_on_ok():
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request("/mnt/user-data/workspace/report.md")

    async def handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))
    assert isinstance(result, Command)
    assert result.update["artifacts"] == ["/mnt/user-data/workspace/report.md"]


def test_write_file_artifact_middleware_sync_promotes_outputs_path_on_ok():
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request("/mnt/user-data/workspace/report.md")

    def handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, Command)
    assert result.update["artifacts"] == ["/mnt/user-data/workspace/report.md"]


def test_write_file_artifact_middleware_sync_blocks_quality_gate_failure(monkeypatch):
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True, block_on_failure=True, max_repair_passes=3),
    )
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.check_report_quality",
        lambda _path, _content: QualityCheckResult(ok=False, reasons=["duplicate rows"]),
    )
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request(
        "/mnt/user-data/workspace/report.md",
        args={"content": "bad report"},
    )
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, Command)
    assert called is False
    assert result.update["quality_gate"]["status"] == "failed"


def test_write_file_artifact_middleware_skips_non_ok_or_non_outputs_path():
    middleware = WriteFileArtifactMiddleware()
    bad_request = _tool_call_request("/mnt/user-data/workspace/report.md")
    external_request = _tool_call_request("/tmp/report.md")

    async def non_ok_handler(_request):
        return ToolMessage(content="Error: failed", tool_call_id="tc-1", name="write_file")

    async def ok_handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    non_ok_result = asyncio.run(middleware.awrap_tool_call(bad_request, non_ok_handler))
    external_result = asyncio.run(middleware.awrap_tool_call(external_request, ok_handler))

    assert isinstance(non_ok_result, ToolMessage)
    assert isinstance(external_result, ToolMessage)


def test_write_file_artifact_middleware_marks_quality_skipped_when_no_check_ran(monkeypatch):
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True),
    )
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request("/mnt/user-data/workspace/report.md")

    async def handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))

    assert isinstance(result, Command)
    assert result.update["quality_gate"]["status"] == "skipped"


def test_write_file_artifact_middleware_checks_append_final_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True, block_on_failure=False),
    )
    checked = {}

    def fake_check(path, content):
        checked["path"] = path
        checked["content"] = content
        return QualityCheckResult(ok=True, reasons=[])

    monkeypatch.setattr("src.agents.middlewares.write_file_artifact_middleware.check_report_quality", fake_check)
    report = tmp_path / "report.md"
    report.write_text("existing\nappended", encoding="utf-8")
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request(
        "/mnt/user-data/workspace/report.md",
        args={"content": "appended", "append": True},
        state={"thread_data": {"workspace_path": str(tmp_path)}},
    )

    async def handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))

    assert isinstance(result, Command)
    assert checked["content"] == "existing\nappended"
    assert result.update["quality_gate"]["status"] == "passed"


def test_write_file_artifact_middleware_checks_str_replace_final_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True, block_on_failure=False),
    )
    checked = {}

    def fake_check(path, content):
        checked["path"] = path
        checked["content"] = content
        return QualityCheckResult(ok=True, reasons=[])

    monkeypatch.setattr("src.agents.middlewares.write_file_artifact_middleware.check_report_quality", fake_check)
    report = tmp_path / "report.md"
    report.write_text("replaced final content", encoding="utf-8")
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request(
        "/mnt/user-data/workspace/report.md",
        tool_name="str_replace",
        args={"old_str": "old", "new_str": "replaced"},
        state={"thread_data": {"workspace_path": str(tmp_path)}},
    )

    async def handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="str_replace")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))

    assert isinstance(result, Command)
    assert checked["content"] == "replaced final content"
    assert result.update["quality_gate"]["status"] == "passed"


def test_write_file_artifact_middleware_tracks_repair_passes_per_path(monkeypatch):
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True, block_on_failure=True, max_repair_passes=3),
    )
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.check_report_quality",
        lambda _path, _content: QualityCheckResult(ok=False, reasons=["duplicate rows"]),
    )
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request(
        "/mnt/user-data/workspace/report-b.md",
        args={"content": "bad report"},
        state={"quality_gate": {"repair_passes_by_path": {"/mnt/user-data/workspace/report-a.md": 2}}},
    )

    result, is_blocking = middleware._quality_gate_precheck(request)

    assert is_blocking is True
    assert isinstance(result, Command)
    assert result.update["quality_gate"]["repair_passes"] == 1
    assert result.update["quality_gate"]["repair_passes_by_path"]["/mnt/user-data/workspace/report-a.md"] == 2
    assert result.update["quality_gate"]["repair_passes_by_path"]["/mnt/user-data/workspace/report-b.md"] == 1


def test_write_file_full_replace_blocks_before_handler_runs(monkeypatch):
    """Pre-write gate must short-circuit the handler for full-replace write_file."""
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True, block_on_failure=True, max_repair_passes=3),
    )
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.check_report_quality",
        lambda _path, _content: QualityCheckResult(ok=False, reasons=["duplicate rows"]),
    )
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request(
        "/mnt/user-data/workspace/report.md",
        args={"content": "bad report"},
    )
    called = False

    async def handler(_request):
        nonlocal called
        called = True
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))

    assert called is False, "handler must not run when pre-write gate blocks"
    assert isinstance(result, Command)
    assert result.update["quality_gate"]["status"] == "failed"
    # Pre-write message wording: tells agent to retry write_file with a fixed report.
    msg = result.update["messages"][0]
    assert "QUALITY_GATE_FAILED" in msg.content
    assert "retry write_file" in msg.content
    assert "POSTWRITE" not in msg.content


def test_str_replace_postwrite_failure_uses_distinct_message(tmp_path, monkeypatch):
    """str_replace lands on disk before the gate can see final content; gate must
    warn with corrective-edit wording, not the pre-write 'retry write_file' wording."""
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True, block_on_failure=True, max_repair_passes=3),
    )
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.check_report_quality",
        lambda _path, _content: QualityCheckResult(ok=False, reasons=["heading numbering"]),
    )
    report = tmp_path / "report.md"
    report.write_text("post-edit content with bad heading", encoding="utf-8")
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request(
        "/mnt/user-data/workspace/report.md",
        tool_name="str_replace",
        args={"old_str": "old", "new_str": "new"},
        state={"thread_data": {"workspace_path": str(tmp_path)}},
    )
    called = False

    async def handler(_request):
        nonlocal called
        called = True
        return ToolMessage(content="OK", tool_call_id="tc-1", name="str_replace")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))

    assert called is True, "str_replace must run; gate is post-write only"
    assert isinstance(result, Command)
    assert result.update["quality_gate"]["status"] == "failed"
    # Last message is the postwrite warning; preceding messages include the original ToolMessage.
    postwrite_msgs = [m for m in result.update["messages"] if "QUALITY_GATE_POSTWRITE_FAILED" in getattr(m, "content", "")]
    assert len(postwrite_msgs) == 1
    text = postwrite_msgs[0].content
    assert "corrective edit" in text
    assert "already been applied" in text
    assert "retry write_file" not in text


def test_write_file_append_uses_postwrite_message(tmp_path, monkeypatch):
    """write_file with append=True is post-write too — same wording as str_replace."""
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True, block_on_failure=True, max_repair_passes=3),
    )
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.check_report_quality",
        lambda _path, _content: QualityCheckResult(ok=False, reasons=["duplicate rows"]),
    )
    report = tmp_path / "report.md"
    report.write_text("existing\nappended bad chunk", encoding="utf-8")
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request(
        "/mnt/user-data/workspace/report.md",
        args={"content": "appended bad chunk", "append": True},
        state={"thread_data": {"workspace_path": str(tmp_path)}},
    )

    async def handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    result = asyncio.run(middleware.awrap_tool_call(request, handler))

    assert isinstance(result, Command)
    postwrite_msgs = [m for m in result.update["messages"] if "QUALITY_GATE_POSTWRITE_FAILED" in getattr(m, "content", "")]
    assert len(postwrite_msgs) == 1


def test_full_replace_write_file_does_not_double_check(monkeypatch):
    """A passing pre-check must not trigger an additional post-check."""
    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.get_quality_gate_config",
        lambda: QualityGateConfig(enabled=True, block_on_failure=True, max_repair_passes=3),
    )
    call_count = {"checks": 0}

    def fake_check(_path, _content):
        call_count["checks"] += 1
        return QualityCheckResult(ok=True, reasons=[])

    monkeypatch.setattr(
        "src.agents.middlewares.write_file_artifact_middleware.check_report_quality",
        fake_check,
    )
    middleware = WriteFileArtifactMiddleware()
    request = _tool_call_request(
        "/mnt/user-data/workspace/report.md",
        args={"content": "good report"},
    )

    async def handler(_request):
        return ToolMessage(content="OK", tool_call_id="tc-1", name="write_file")

    asyncio.run(middleware.awrap_tool_call(request, handler))

    assert call_count["checks"] == 1, "full-replace write_file should run only the pre-check"


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
        middleware = CapyHomeSummarizationMiddleware(
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
