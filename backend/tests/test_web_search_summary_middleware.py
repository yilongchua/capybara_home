"""Tests for WebSearchSummaryMiddleware."""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from src.agents.middlewares.web_search_summary_middleware import WebSearchSummaryMiddleware
from src.config.app_config import AppConfig
from src.config.model_config import ModelConfig
from src.config.routing_config import RoutingConfig
from src.config.sandbox_config import SandboxConfig
from src.config.web_search_summary_config import get_web_search_summary_config
from src.models.router import ModelRouter


def _router() -> ModelRouter:
    cfg = AppConfig(
        models=[
            ModelConfig(
                name="primary",
                display_name="primary",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="primary",
                supports_thinking=True,
            )
        ],
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
    )
    cfg.routing = RoutingConfig(stages={"planner": "primary"}, fallback="primary")
    return ModelRouter(app_config=cfg)


def _make_middleware():
    return WebSearchSummaryMiddleware(router=_router(), requested_model="primary")


def _make_request(tool_name: str, content: str, query: str = "") -> SimpleNamespace:
    call_id = "call-1"
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})
    return SimpleNamespace(
        tool_call={"id": call_id, "name": tool_name, "args": {"query": query}},
        runtime=runtime,
    )


def _make_tool_message(tool_name: str, content: str, call_id: str = "call-1") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=tool_name)


SHORT_CONTENT = "x" * 100
LONG_CONTENT = "x" * (get_web_search_summary_config().summary_threshold_chars + 500)


def test_passes_through_short_results():
    middleware = _make_middleware()
    request = _make_request("web_search", SHORT_CONTENT)
    result_msg = _make_tool_message("web_search", SHORT_CONTENT)

    def handler(req):  # noqa: ARG001
        return result_msg

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.content == SHORT_CONTENT


def test_passes_through_non_web_search_tools():
    middleware = _make_middleware()
    request = _make_request("bash", LONG_CONTENT)
    result_msg = _make_tool_message("bash", LONG_CONTENT)

    def handler(req):  # noqa: ARG001
        return result_msg

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.content == LONG_CONTENT


def test_summarizes_long_web_search_results(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content="Summarized: key finding 1, key finding 2.")

    monkeypatch.setattr("src.agents.middlewares.web_search_summary_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    long_json = json.dumps(
        {
            "ok": True,
            "query": "test query",
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com",
                    "snippet": "snippet",
                    "extracted_content": LONG_CONTENT,
                }
            ],
        }
    )
    request = _make_request("web_search", long_json, query="test query")
    result_msg = _make_tool_message("web_search", long_json)

    def handler(req):  # noqa: ARG001
        return result_msg

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    payload = json.loads(str(result.content))
    assert payload.get("summarized") is True
    assert "Summarized" in payload.get("summary", "")
    assert len(str(result.content)) < len(long_json)
    assert payload.get("results") == [
        {"title": "Example", "url": "https://example.com", "snippet": "snippet"}
    ]


def test_keeps_original_on_summary_timeout(monkeypatch):
    import time

    class _SlowModel:
        def invoke(self, prompt):  # noqa: ARG002
            time.sleep(10)
            return SimpleNamespace(content="Never returned")

    monkeypatch.setattr("src.agents.middlewares.web_search_summary_middleware.create_chat_model", lambda **kwargs: _SlowModel())
    middleware = _make_middleware()
    middleware._config.timeout_seconds = 0.05
    request = _make_request("web_search", LONG_CONTENT)
    result_msg = _make_tool_message("web_search", LONG_CONTENT)

    def handler(req):  # noqa: ARG001
        return result_msg

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.content == LONG_CONTENT


def test_keeps_original_on_model_exception(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            raise RuntimeError("API error")

    monkeypatch.setattr("src.agents.middlewares.web_search_summary_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    request = _make_request("web_search", LONG_CONTENT)
    result_msg = _make_tool_message("web_search", LONG_CONTENT)

    def handler(req):  # noqa: ARG001
        return result_msg

    result = middleware.wrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.content == LONG_CONTENT


def test_recognizes_tavily_search_tool():
    middleware = _make_middleware()
    assert middleware._is_web_search("tavily_search_results_json")
    assert middleware._is_web_search("web_search")
    assert middleware._is_web_search("searxng")
    assert not middleware._is_web_search("bash")
    assert not middleware._is_web_search("read_file")
