import logging
from pathlib import Path

from langchain.tools import BaseTool

from src.community.knowledge_vault_search import query_knowledge_vault_tool, save_to_knowledge_vault_tool
from src.community.scope_search import scope_search_tool
from src.community.web_search import web_search_tool
from src.config import get_app_config
from src.reflection import resolve_variable
from src.tools.builtins import ask_user_for_clarification_tool, present_file_tool, recall_tool, task_tool, view_image_tool, write_todos_tool
from src.tools.loader import build_structured_tool, filter_mcp_tools_by_policy, load_external_policy, load_tool_definitions

logger = logging.getLogger(__name__)

INTERNAL_TOOLS_JSON = Path(__file__).resolve().parent / "internal_tools.json"
EXTERNAL_TOOLS_JSON = Path(__file__).resolve().parent / "external_tools.json"

BUILTIN_TOOLS = [
    present_file_tool,
    ask_user_for_clarification_tool,
    recall_tool,
    write_todos_tool,
    web_search_tool,
    # scope_search is the Plan-Mode-friendly wrapper around web_search. Both
    # are registered; PhaseToolFilterMiddleware hides web_search while a plan
    # is in draft so the LLM only ever sees scope_search until approval.
    scope_search_tool,
    query_knowledge_vault_tool,
    save_to_knowledge_vault_tool,
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

    # Apply external_tools.json MCP policy when JSON-driven mode is on.
    # No-op when the policy file declares no mcp_servers (default state).
    if mcp_tools and getattr(config, "json_driven_tools", False):
        try:
            external_policy = load_external_policy(EXTERNAL_TOOLS_JSON)
            if external_policy.mcp_servers:
                before = len(mcp_tools)
                mcp_tools = filter_mcp_tools_by_policy(
                    mcp_tools,
                    external_policy,
                    subagent=subagent_enabled,
                )
                if before != len(mcp_tools):
                    logger.info(
                        "external_tools.json policy reduced MCP tools from %d to %d",
                        before,
                        len(mcp_tools),
                    )
        except Exception:
            logger.exception("Failed to apply external_tools.json policy; serving full MCP catalog")

    # If no model_name specified, use the first model (default)
    if model_name is None and config.models:
        model_name = config.models[0].name

    # Add view_image_tool only if the model supports vision
    model_config = config.get_model_config(model_name) if model_name else None
    supports_vision = bool(model_config is not None and model_config.supports_vision)

    if getattr(config, "json_driven_tools", False):
        builtin_tools = _build_builtin_tools_from_json(
            subagent_enabled=subagent_enabled,
            supports_vision=supports_vision,
        )
    else:
        # Legacy path — keep the hard-coded BUILTIN_TOOLS until Phase 6 cutover.
        builtin_tools = [t for t in BUILTIN_TOOLS if _get_community_tool_enabled(t.name)]
        disabled_builtins = [t.name for t in BUILTIN_TOOLS if t.name not in {b.name for b in builtin_tools}]
        if disabled_builtins:
            logger.info("Community tool overrides disabled: %s", disabled_builtins)
        if subagent_enabled:
            builtin_tools.extend(SUBAGENT_TOOLS)
            logger.info("Including subagent tools (task)")
        if supports_vision:
            builtin_tools.append(view_image_tool)
            logger.info(f"Including view_image_tool for model '{model_name}' (supports_vision=True)")

    # When JSON drives tools, prefer the JSON-built BaseTool on name collisions so
    # the JSON-sourced description/policy wins over any config.yaml duplicate.
    # Legacy path preserves prior ordering (config.yaml first).
    if getattr(config, "json_driven_tools", False):
        merged = builtin_tools + loaded_tools + mcp_tools
    else:
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


def _build_builtin_tools_from_json(*, subagent_enabled: bool, supports_vision: bool) -> list[BaseTool]:
    """Materialize built-in/sandbox tools from internal_tools.json.

    Applies the same declarative filters the legacy path enforces imperatively:
    community on/off overrides, subagent gating (`requires_subagent_enabled`),
    and vision gating (`requires_vision`). Tools whose handlers fail to resolve
    are logged and skipped so a single bad entry never breaks the agent.

    Community tools listed in BUILTIN_TOOLS that have no JSON entry yet are
    appended at the end so flipping the flag doesn't shrink the catalog.
    """
    try:
        defns = load_tool_definitions(INTERNAL_TOOLS_JSON)
    except Exception:
        logger.exception("Failed to load internal_tools.json; falling back to legacy BUILTIN_TOOLS")
        return list(BUILTIN_TOOLS) + (list(SUBAGENT_TOOLS) if subagent_enabled else [])

    tools: list[BaseTool] = []
    json_names: set[str] = set()
    for defn in defns:
        if defn.deprecated:
            continue
        if defn.requires_subagent_enabled and not subagent_enabled:
            continue
        if defn.requires_vision and not supports_vision:
            continue
        if not _get_community_tool_enabled(defn.name):
            continue
        try:
            tools.append(build_structured_tool(defn))
            json_names.add(defn.name)
        except Exception:
            logger.exception("Skipping tool '%s' — handler resolution failed", defn.name)

    # Carry over BUILTIN_TOOLS entries (community tools like web_search,
    # scope_search, knowledge_vault_*) that don't yet have a JSON entry.
    for tool in BUILTIN_TOOLS:
        if tool.name in json_names:
            continue
        if not _get_community_tool_enabled(tool.name):
            continue
        tools.append(tool)
    if subagent_enabled:
        for tool in SUBAGENT_TOOLS:
            if tool.name in json_names:
                continue
            tools.append(tool)
    return tools
