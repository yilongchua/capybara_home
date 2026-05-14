import logging

from langchain.tools import BaseTool

from src.community.knowledge_vault_search import query_knowledge_vault_tool
from src.community.lightrag import query_lightrag_tool
from src.community.web_search import web_search_tool
from src.config import get_app_config
from src.reflection import resolve_variable
from src.tools.builtins import ask_clarification_tool, present_file_tool, recall_tool, task_tool, view_image_tool, write_todos_tool

logger = logging.getLogger(__name__)

BUILTIN_TOOLS = [
    present_file_tool,
    ask_clarification_tool,
    recall_tool,
    write_todos_tool,
    web_search_tool,
    query_knowledge_vault_tool,
    query_lightrag_tool,
]

SUBAGENT_TOOLS = [
    task_tool,
    # task_status_tool is no longer exposed to LLM (backend handles polling internally)
]


def _get_community_tool_enabled(tool_name: str) -> bool:
    """Return the enabled state for a community tool from extensions_config.json.

    Defaults to True when no override exists (backwards compatible).
    """
    try:
        from src.config.extensions_config import ExtensionsConfig

        ext = ExtensionsConfig.from_file()
        override = ext.community_tools.get(tool_name)
        return override.enabled if override is not None else True
    except Exception as exc:
        logger.warning("Could not read community tool state for '%s': %s", tool_name, exc)
        return True


def get_available_tools(
    groups: list[str] | None = None,
    include_mcp: bool = True,
    model_name: str | None = None,
    subagent_enabled: bool = False,
) -> list[BaseTool]:
    """Get all available tools from config.

    Note: MCP tools should be initialized at application startup using
    `initialize_mcp_tools()` from src.mcp module.

    Args:
        groups: Optional list of tool groups to filter by.
        include_mcp: Whether to include tools from MCP servers (default: True).
        model_name: Optional model name to determine if vision tools should be included.
        subagent_enabled: Whether to include subagent tools (task, task_status).

    Returns:
        List of available tools.
    """
    config = get_app_config()

    # Config-defined tools (config.yaml `tools:` section), filtered by group and community override.
    loaded_tools = [
        resolve_variable(tool.use, BaseTool)
        for tool in config.tools
        if (groups is None or tool.group in groups) and _get_community_tool_enabled(tool.name)
    ]

    # Get cached MCP tools if enabled
    # NOTE: We use ExtensionsConfig.from_file() instead of config.extensions
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected when loading MCP tools.
    mcp_tools = []
    if include_mcp:
        try:
            from src.config.extensions_config import ExtensionsConfig
            from src.mcp.cache import get_cached_mcp_tools

            extensions_config = ExtensionsConfig.from_file()
            if extensions_config.get_enabled_mcp_servers():
                mcp_tools = get_cached_mcp_tools()
                if mcp_tools:
                    logger.info(f"Using {len(mcp_tools)} cached MCP tool(s)")
        except ImportError:
            logger.warning("MCP module not available. Install 'langchain-mcp-adapters' package to enable MCP tools.")
        except Exception as e:
            logger.error(f"Failed to get cached MCP tools: {e}")

    # Conditionally add builtin tools, respecting community overrides.
    builtin_tools = [t for t in BUILTIN_TOOLS if _get_community_tool_enabled(t.name)]
    disabled_builtins = [t.name for t in BUILTIN_TOOLS if t.name not in {b.name for b in builtin_tools}]
    if disabled_builtins:
        logger.info("Community tool overrides disabled: %s", disabled_builtins)

    # Add subagent tools only if enabled via runtime parameter
    if subagent_enabled:
        builtin_tools.extend(SUBAGENT_TOOLS)
        logger.info("Including subagent tools (task)")

    # If no model_name specified, use the first model (default)
    if model_name is None and config.models:
        model_name = config.models[0].name

    # Add view_image_tool only if the model supports vision
    model_config = config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        builtin_tools.append(view_image_tool)
        logger.info(f"Including view_image_tool for model '{model_name}' (supports_vision=True)")

    merged = loaded_tools + builtin_tools + mcp_tools
    deduped: list[BaseTool] = []
    seen: set[str] = set()
    for tool in merged:
        name = getattr(tool, "name", "")
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(tool)
    return deduped
