from types import SimpleNamespace

from langgraph.prebuilt.tool_node import ToolCallRequest

from src.agents.middlewares.search_privacy_middleware import SearchPrivacyMiddleware


def _request(*, enabled: bool, query: str = "original query") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={
            "id": "call-1",
            "name": "web_search",
            "args": {"query": query},
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=SimpleNamespace(
            context={
                "mask_sensitive_search": enabled,
                "model_name": "local-model",
            }
        ),
    )


def test_search_privacy_middleware_rewrites_query(monkeypatch):
    middleware = SearchPrivacyMiddleware()
    seen: dict[str, str] = {}

    monkeypatch.setattr(
        "src.agents.middlewares.search_privacy_middleware.rewrite_search_query_for_privacy",
        lambda query, model_name=None: "masked query",
    )

    def handler(request: ToolCallRequest) -> str:
        seen["query"] = request.tool_call["args"]["query"]
        return "ok"

    result = middleware.wrap_tool_call(_request(enabled=True), handler)

    assert result == "ok"
    assert seen["query"] == "masked query"


def test_search_privacy_middleware_leaves_query_unchanged_when_disabled():
    middleware = SearchPrivacyMiddleware()
    seen: dict[str, str] = {}

    def handler(request: ToolCallRequest) -> str:
        seen["query"] = request.tool_call["args"]["query"]
        return "ok"

    result = middleware.wrap_tool_call(_request(enabled=False), handler)

    assert result == "ok"
    assert seen["query"] == "original query"
