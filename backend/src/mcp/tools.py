"""Load MCP tools using langchain-mcp-adapters."""

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool

from src.config.extensions_config import ExtensionsConfig, McpServerConfig
from src.mcp.client import build_server_params, build_servers_config
from src.mcp.internal_search import register_internal_search_target, search_internal_documents_tool
from src.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers

logger = logging.getLogger(__name__)

_PREVIEW_TIMEOUT_SECONDS = 10

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
except ImportError:
    MultiServerMCPClient = None  # type: ignore[assignment,misc]


async def preview_mcp_server(server_config: McpServerConfig, server_name: str = "preview") -> dict[str, Any]:
    """Connect to a single MCP server and return its tool list without saving anything.

    Args:
        server_config: The server configuration to test.
        server_name: Logical name used only for this ephemeral connection.

    Returns:
        Dict with keys ``ok`` (bool), ``tools`` (list of dicts), ``error`` (str | None).
    """
    if MultiServerMCPClient is None:
        return {"ok": False, "tools": [], "error": "langchain-mcp-adapters is not installed"}

    try:
        params = build_server_params(server_name, server_config)
    except ValueError as exc:
        return {"ok": False, "tools": [], "error": str(exc)}

    try:
        client = MultiServerMCPClient({server_name: params})
        tools: list[BaseTool] = await asyncio.wait_for(client.get_tools(), timeout=_PREVIEW_TIMEOUT_SECONDS)

        def _extract_input_schema(tool: BaseTool) -> dict[str, Any]:
            """Normalize tool input schema across adapter/tool implementations."""
            schema = getattr(tool, "args_schema", None)
            if schema is None:
                return {}
            if isinstance(schema, dict):
                return schema
            model_json_schema = getattr(schema, "model_json_schema", None)
            if callable(model_json_schema):
                try:
                    return model_json_schema()
                except Exception:
                    return {}
            return {}

        return {
            "ok": True,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": _extract_input_schema(t),
                }
                for t in tools
            ],
            "error": None,
        }
    except TimeoutError:
        return {"ok": False, "tools": [], "error": f"Connection timed out after {_PREVIEW_TIMEOUT_SECONDS}s"}
    except Exception as exc:
        return {"ok": False, "tools": [], "error": str(exc)}


async def _get_tools_for_server(server_name: str, params: dict[str, Any], excluded_tools: list[str]) -> list[BaseTool]:
    """Fetch tools from a single server and apply the exclusion list."""
    client = MultiServerMCPClient({server_name: params})
    tools = await client.get_tools()
    if not excluded_tools:
        return tools
    excluded = set(excluded_tools)
    filtered = [t for t in tools if t.name not in excluded]
    if len(filtered) != len(tools):
        logger.info("Server '%s': excluded %d tool(s) %s", server_name, len(tools) - len(filtered), sorted(excluded & {t.name for t in tools}))
    return filtered


async def get_mcp_tools() -> list[BaseTool]:
    """Get all tools from enabled MCP servers.

    Servers with ``excluded_tools`` are fetched individually so per-server
    filtering can be applied before merging.  Servers without exclusions are
    fetched together in a single MultiServerMCPClient call for efficiency.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    if MultiServerMCPClient is None:
        logger.warning("langchain-mcp-adapters not installed. Install it to enable MCP tools: pip install langchain-mcp-adapters")
        return []

    # NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected when initializing MCP tools.
    extensions_config = ExtensionsConfig.from_file()
    enabled_servers = extensions_config.get_enabled_mcp_servers()

    if not enabled_servers:
        logger.info("No enabled MCP servers configured")
        return []

    # Split servers into those with and without tool exclusions.
    servers_with_exclusions = {name: cfg for name, cfg in enabled_servers.items() if cfg.excluded_tools}
    servers_without_exclusions = {name: cfg for name, cfg in enabled_servers.items() if not cfg.excluded_tools}

    all_tools: list[BaseTool] = []

    # ── Bulk fetch for servers without exclusions ──────────────────────────
    if servers_without_exclusions:
        bulk_config = ExtensionsConfig(mcp_servers=servers_without_exclusions)
        servers_params = build_servers_config(bulk_config)

        if servers_params:
            try:
                logger.info("Initializing MCP client with %d server(s) (no exclusions)", len(servers_params))

                initial_oauth_headers = await get_initial_oauth_headers(extensions_config)
                for sname, auth_header in initial_oauth_headers.items():
                    if sname not in servers_params:
                        continue
                    if servers_params[sname].get("transport") in ("sse", "http"):
                        existing = dict(servers_params[sname].get("headers", {}))
                        existing["Authorization"] = auth_header
                        servers_params[sname]["headers"] = existing

                tool_interceptors = []
                oauth_interceptor = build_oauth_tool_interceptor(extensions_config)
                if oauth_interceptor is not None:
                    tool_interceptors.append(oauth_interceptor)

                client = MultiServerMCPClient(servers_params, tool_interceptors=tool_interceptors)
                bulk_tools = await client.get_tools()
                logger.info("Loaded %d tool(s) from %d server(s) (bulk)", len(bulk_tools), len(servers_params))
                all_tools.extend(bulk_tools)
            except Exception as exc:
                logger.error("Failed to load MCP tools (bulk): %s", exc, exc_info=True)
                register_internal_search_target(None)

    # ── Per-server fetch for servers with exclusions ───────────────────────
    for server_name, server_cfg in servers_with_exclusions.items():
        try:
            params = build_server_params(server_name, server_cfg)
            server_tools = await _get_tools_for_server(server_name, params, server_cfg.excluded_tools)
            logger.info("Loaded %d tool(s) from '%s' (with exclusions)", len(server_tools), server_name)
            all_tools.extend(server_tools)
        except Exception as exc:
            logger.error("Failed to load MCP tools from '%s': %s", server_name, exc, exc_info=True)

    logger.info("Total MCP tools loaded: %d", len(all_tools))

    indexed_search_tool = next((t for t in all_tools if t.name == "search_indexed_documents"), None)
    register_internal_search_target(indexed_search_tool)

    if indexed_search_tool is not None:
        return [search_internal_documents_tool, *all_tools]
    return all_tools
