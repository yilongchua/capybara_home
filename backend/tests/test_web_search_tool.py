from types import SimpleNamespace

import httpx
import pytest

from src.community.web_search.tools import web_search_tool
from src.tools import tools as tools_module


def test_get_available_tools_includes_web_search(monkeypatch):
    fake_model_config = SimpleNamespace(supports_vision=False)
    fake_app_config = SimpleNamespace(
        tools=[],
        models=[SimpleNamespace(name="test-model")],
        get_model_config=lambda _name: fake_model_config,
    )

    monkeypatch.setattr(tools_module, "get_app_config", lambda: fake_app_config)

    tools = tools_module.get_available_tools(include_mcp=False, model_name="test-model")
    names = {tool.name for tool in tools}

    assert "web_search" in names


@pytest.mark.anyio
async def test_web_search_tool_returns_normalized_results(monkeypatch):
    fake_tool_cfg = SimpleNamespace(model_extra={})
    fake_backend = SimpleNamespace(enabled=True, base_url="http://127.0.0.1:9000", timeout_seconds=20.0)
    fake_app_config = SimpleNamespace(
        tool_backends=SimpleNamespace(websearch=fake_backend),
        get_tool_config=lambda name: fake_tool_cfg if name == "web_search" else None,
    )

    monkeypatch.setattr("src.community.web_search.tools.get_app_config", lambda: fake_app_config)
    monkeypatch.setattr("src.community.web_search.tools.enforce_query_guardrails", lambda query, tool_name=None: None)

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "Result 1",
                        "url": "https://example.com/1",
                        "content": "Snippet 1",
                        "engine": "duckduckgo",
                    }
                ]
            }

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr("src.community.web_search.tools.httpx.AsyncClient", _FakeAsyncClient)

    raw = await web_search_tool.ainvoke({"query": "latest Iran news", "max_results": 5})

    assert '"ok": true' in raw
    assert "https://example.com/1" in raw


@pytest.mark.anyio
async def test_web_search_tool_retries_transient_request_error(monkeypatch):
    fake_tool_cfg = SimpleNamespace(model_extra={})
    fake_backend = SimpleNamespace(enabled=True, base_url="http://127.0.0.1:9000", timeout_seconds=None)
    fake_app_config = SimpleNamespace(
        tool_backends=SimpleNamespace(websearch=fake_backend),
        get_tool_config=lambda name: fake_tool_cfg if name == "web_search" else None,
    )

    monkeypatch.setattr("src.community.web_search.tools.get_app_config", lambda: fake_app_config)
    monkeypatch.setattr("src.community.web_search.tools.enforce_query_guardrails", lambda query, tool_name=None: None)

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"title": "Recovered", "url": "https://example.com/recovered", "content": "ok", "engine": "duckduckgo"}
                ]
            }

    call_counter = {"count": 0}

    class _FlakyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, **kwargs):
            call_counter["count"] += 1
            if call_counter["count"] == 1:
                req = httpx.Request("POST", "http://127.0.0.1:9000/search")
                raise httpx.ReadTimeout("transient timeout", request=req)
            return _FakeResponse()

    monkeypatch.setattr("src.community.web_search.tools.httpx.AsyncClient", _FlakyAsyncClient)

    raw = await web_search_tool.ainvoke({"query": "agentic ai updates", "max_results": 3})

    assert call_counter["count"] == 2
    assert '"ok": true' in raw
    assert "https://example.com/recovered" in raw
