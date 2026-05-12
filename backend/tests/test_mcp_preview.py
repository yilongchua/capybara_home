"""Tests for MCP server preview functionality and tool exclusion filtering."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.config.extensions_config import ExtensionsConfig, McpServerConfig
from src.mcp.tools import _get_tools_for_server, preview_mcp_server

# ─── preview_mcp_server ───────────────────────────────────────────────────────


def test_preview_returns_tool_list_on_success():
    mock_tool = MagicMock()
    mock_tool.name = "read_file"
    mock_tool.description = "Read a file"
    mock_tool.args_schema = None

    mock_client = AsyncMock()
    mock_client.get_tools = AsyncMock(return_value=[mock_tool])

    config = McpServerConfig(type="stdio", command="npx", args=["-y", "my-mcp"])

    with patch("src.mcp.tools.MultiServerMCPClient", return_value=mock_client):
        result = asyncio.run(preview_mcp_server(config))

    assert result["ok"] is True
    assert result["error"] is None
    assert len(result["tools"]) == 1
    assert result["tools"][0]["name"] == "read_file"
    assert result["tools"][0]["description"] == "Read a file"


def test_preview_returns_error_on_connection_failure():
    mock_client = AsyncMock()
    mock_client.get_tools = AsyncMock(side_effect=ConnectionRefusedError("refused"))

    config = McpServerConfig(type="stdio", command="npx", args=["-y", "bad-server"])

    with patch("src.mcp.tools.MultiServerMCPClient", return_value=mock_client):
        result = asyncio.run(preview_mcp_server(config))

    assert result["ok"] is False
    assert result["error"] is not None
    assert "refused" in result["error"]
    assert result["tools"] == []


def test_preview_returns_error_on_timeout():
    async def _slow():
        await asyncio.sleep(100)
        return []

    mock_client = AsyncMock()
    mock_client.get_tools = _slow

    config = McpServerConfig(type="stdio", command="slow-server")

    with (
        patch("src.mcp.tools.MultiServerMCPClient", return_value=mock_client),
        patch("src.mcp.tools._PREVIEW_TIMEOUT_SECONDS", 0.01),
    ):
        result = asyncio.run(preview_mcp_server(config))

    assert result["ok"] is False
    assert "timed out" in result["error"].lower()


def test_preview_returns_error_for_invalid_config():
    # stdio without command → build_server_params raises ValueError before connecting
    config = McpServerConfig(type="stdio", command=None)

    result = asyncio.run(preview_mcp_server(config))

    assert result["ok"] is False
    assert result["error"] is not None


def test_preview_returns_error_when_adapters_not_installed():
    config = McpServerConfig(type="stdio", command="npx")

    with patch("src.mcp.tools.MultiServerMCPClient", None):
        result = asyncio.run(preview_mcp_server(config))

    assert result["ok"] is False
    assert result["tools"] == []


# ─── _get_tools_for_server (exclusion filter) ─────────────────────────────────


def test_get_tools_no_exclusions_returns_all():
    tools = [MagicMock(name=n) for n in ["tool_a", "tool_b", "tool_c"]]
    # MagicMock sets .name via spec; set it explicitly
    for i, n in enumerate(["tool_a", "tool_b", "tool_c"]):
        tools[i].name = n

    mock_client = AsyncMock()
    mock_client.get_tools = AsyncMock(return_value=tools)

    with patch("src.mcp.tools.MultiServerMCPClient", return_value=mock_client):
        result = asyncio.run(_get_tools_for_server("srv", {"transport": "stdio", "command": "x"}, excluded_tools=[]))

    assert len(result) == 3


def test_get_tools_filters_excluded():
    tools = [MagicMock() for _ in range(3)]
    for i, n in enumerate(["tool_a", "tool_b", "tool_c"]):
        tools[i].name = n

    mock_client = AsyncMock()
    mock_client.get_tools = AsyncMock(return_value=tools)

    with patch("src.mcp.tools.MultiServerMCPClient", return_value=mock_client):
        result = asyncio.run(
            _get_tools_for_server(
                "srv",
                {"transport": "stdio", "command": "x"},
                excluded_tools=["tool_b"],
            )
        )

    names = [t.name for t in result]
    assert "tool_a" in names
    assert "tool_b" not in names
    assert "tool_c" in names


def test_get_tools_excludes_all():
    tools = [MagicMock()]
    tools[0].name = "only_tool"

    mock_client = AsyncMock()
    mock_client.get_tools = AsyncMock(return_value=tools)

    with patch("src.mcp.tools.MultiServerMCPClient", return_value=mock_client):
        result = asyncio.run(
            _get_tools_for_server(
                "srv",
                {"transport": "stdio", "command": "x"},
                excluded_tools=["only_tool"],
            )
        )

    assert result == []


# ─── extensions_config round-trip with excluded_tools ────────────────────────


def test_extensions_config_excluded_tools_defaults_empty():
    cfg = McpServerConfig(type="stdio", command="npx")
    assert cfg.excluded_tools == []


def test_extensions_config_excluded_tools_round_trips():
    ext = ExtensionsConfig(
        mcp_servers={
            "srv": McpServerConfig(
                enabled=True,
                type="stdio",
                command="npx",
                excluded_tools=["dangerous_tool", "private_tool"],
            )
        }
    )
    assert ext.mcp_servers["srv"].excluded_tools == ["dangerous_tool", "private_tool"]


def test_extensions_config_community_tools_defaults():
    ext = ExtensionsConfig()
    assert ext.community_tools == {}


def test_extensions_config_community_tools_toggle():
    from src.config.extensions_config import CommunityToolStateConfig

    ext = ExtensionsConfig(
        community_tools={"web_search": CommunityToolStateConfig(enabled=False)}
    )
    assert ext.community_tools["web_search"].enabled is False
