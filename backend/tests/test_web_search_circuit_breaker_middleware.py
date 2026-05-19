from types import SimpleNamespace

from langchain_core.messages import HumanMessage, ToolMessage

from src.agents.middlewares.web_search_circuit_breaker_middleware import WebSearchCircuitBreakerMiddleware


def test_web_search_circuit_breaker_blocks_after_two_failures():
    middleware = WebSearchCircuitBreakerMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "web_search", "id": "call-3"},
        state={
            "messages": [
                HumanMessage(content="Research current market data."),
                ToolMessage(content="[model_timeout]\nTool `web_search` exceeded the 30s timeout.", name="web_search", tool_call_id="call-1"),
                ToolMessage(content='{"ok": false, "error": "backend down"}', name="web_search", tool_call_id="call-2"),
            ]
        },
    )

    blocked = middleware._maybe_block(request)

    assert blocked is not None
    assert blocked.name == "web_search"
    assert "[web_search_circuit_open]" in blocked.content


def test_web_search_circuit_breaker_resets_for_new_user_message():
    middleware = WebSearchCircuitBreakerMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "web_search", "id": "call-3"},
        state={
            "messages": [
                HumanMessage(content="Research current market data."),
                ToolMessage(content="[model_timeout]\nTool `web_search` exceeded the 30s timeout.", name="web_search", tool_call_id="call-1"),
                ToolMessage(content='{"ok": false, "error": "backend down"}', name="web_search", tool_call_id="call-2"),
                HumanMessage(content="New request."),
            ]
        },
    )

    assert middleware._maybe_block(request) is None
