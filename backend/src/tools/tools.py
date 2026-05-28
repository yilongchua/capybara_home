import logging
from pathlib import Path

from langchain.tools import BaseTool

from src.community.knowledge_vault_search import query_knowledge_vault_tool, save_to_knowledge_vault_tool

# DEPRECATED: scope_search tool is no longer used. web_search is now available
# directly in Plan Mode (see _COMMUNITY_TOOL_MODES below and the deprecated
# PhaseToolFilter / PlanExecutionGate middlewares). Kept as a commented import
# so the wrapper module is preserved for reference.
# from src.community.scope_search import scope_search_tool
from src.community.web_search import web_search_tool
from src.config import get_app_config
from src.reflection import resolve_variable
from src.tools.builtins import ask_user_for_clarification_tool, present_file_tool, recall_tool, task_tool, view_image_tool, write_todos_tool
from src.tools.loader import build_structured_tool, filter_mcp_tools_by_policy, load_external_policy, load_tool_definitions

logger = logging.getLogger(__name__)

INTERNAL_TOOLS_PLAN_JSON = Path(__file__).resolve().parent / "internal_tools_plan.json"
INTERNAL_TOOLS_WORK_JSON = Path(__file__).resolve().parent / "internal_tools_work.json"
EXTERNAL_TOOLS_JSON = Path(__file__).resolve().parent / "external_tools.json"


def _resolve_internal_tools_path(mode: str | None) -> Path:
    """Pick the per-mode tool catalog file.

    `internal_tools_plan.json` and `internal_tools_work.json` carry mode-tailored
    descriptions so the LLM-facing contract for a tool can differ between plan
    and work without coupling the two surfaces. Mode unset defaults to the work
    file (matches the default runtime).
    """
    mode_lower = (mode or "").strip().lower()
    if mode_lower == "plan":
        return INTERNAL_TOOLS_PLAN_JSON
    return INTERNAL_TOOLS_WORK_JSON


BUILTIN_TOOLS = [
    present_file_tool,
    ask_user_for_clarification_tool,
    recall_tool,
    write_todos_tool,
    web_search_tool,
    # DEPRECATED: scope_search wrapper is no longer registered. web_search is
    # now exposed directly in Plan Mode via _COMMUNITY_TOOL_MODES below.
    # scope_search_tool,
    query_knowledge_vault_tool,
    save_to_knowledge_vault_tool,
]

# Tools that arrive via config.yaml `tools:` or BUILTIN_TOOLS don't carry a
# mode field, so we mode-scope them here. The JSON catalog files already
# encode mode for JSON-driven entries via the file split (plan vs work).
# Membership semantics: a tool is exposed in a mode iff that mode is in its set.
# Tools absent from this map are exposed in every mode.
_COMMUNITY_TOOL_MODES: dict[str, frozenset[str]] = {
    # web_search is now available in plan mode as well (scope_search deprecated).
    "web_search": frozenset({"plan", "work", "auto"}),
    "query_knowledge_vault": frozenset({"work", "auto"}),
    "save_to_knowledge_vault": frozenset({"work", "auto"}),
    # Execution tools defined in config.yaml. The JSON work catalog already
    # excludes these from plan mode, but the config.yaml `loaded_tools` path
    # would otherwise re-introduce them under plan_agent without a policy.
    "bash": frozenset({"work", "auto"}),
    "write_file": frozenset({"work", "auto"}),
    "str_replace": frozenset({"work", "auto"}),
    "comfyui_generate": frozenset({"work", "auto"}),
    # DEPRECATED: scope_search wrapper no longer registered.
    # "scope_search": frozenset({"plan"}),
}

SUBAGENT_TOOLS = [
    task_tool,
    # task_status_tool is no longer exposed to LLM (backend handles polling internally)
]


def _community_tool_allowed_in_mode(tool_name: str, mode: str | None) -> bool:
    """True when `tool_name` is in-scope for `mode` per _COMMUNITY_TOOL_MODES.

    Unmapped tools are unrestricted. Unset/unknown mode falls back to work.
    """
    allowed_modes = _COMMUNITY_TOOL_MODES.get(tool_name)
    if allowed_modes is None:
        return True
    mode_lower = (mode or "work").strip().lower()
    if mode_lower not in {"plan", "work", "auto"}:
        mode_lower = "work"
    return mode_lower in allowed_modes


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
    mode: str | None = None,
) -> list[BaseTool]:
    """Get all available tools from config.

    Note: MCP tools should be initialized at application startup using
    `initialize_mcp_tools()` from src.mcp module.

    Args:
        groups: Optional list of tool groups to filter by.
        include_mcp: Whether to include tools from MCP servers (default: True).
        model_name: Optional model name to determine if vision tools should be included.
        subagent_enabled: Whether to include subagent tools (task, task_status).
        mode: Optional runtime mode (`plan`, `work`, or `auto`). Selects between
            `internal_tools_plan.json` and `internal_tools_work.json` so the
            LLM-facing tool descriptions can be tailored per mode and so
            mode-scoped community tools (web_search, scope_search, etc.) are
            included only in the appropriate mode. Defaults to work when unset.

    Returns:
        List of available tools.
    """
    config = get_app_config()

    # Config-defined tools (config.yaml `tools:` section), filtered by group, community override, and mode.
    loaded_tools = [
        resolve_variable(tool.use, BaseTool)
        for tool in config.tools
        if (groups is None or tool.group in groups)
        and _get_community_tool_enabled(tool.name)
        and _community_tool_allowed_in_mode(tool.name, mode)
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
            mode=mode,
        )
    else:
        # Legacy path — keep the hard-coded BUILTIN_TOOLS until Phase 6 cutover.
        builtin_tools = [
            t
            for t in BUILTIN_TOOLS
            if _get_community_tool_enabled(t.name) and _community_tool_allowed_in_mode(t.name, mode)
        ]
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


def _build_builtin_tools_from_json(*, subagent_enabled: bool, supports_vision: bool, mode: str | None = None) -> list[BaseTool]:
    """Materialize built-in/sandbox tools from the mode-specific JSON catalog.

    Picks `internal_tools_plan.json` or `internal_tools_work.json` based on
    `mode`. Applies the same declarative filters the legacy path enforces
    imperatively: community on/off overrides, subagent gating
    (`requires_subagent_enabled`), and vision gating (`requires_vision`).
    Tools whose handlers fail to resolve are logged and skipped so a single
    bad entry never breaks the agent.

    Community tools listed in BUILTIN_TOOLS that have no JSON entry are
    appended at the end, scoped to the active mode via _COMMUNITY_TOOL_MODES.
    """
    catalog_path = _resolve_internal_tools_path(mode)
    try:
        defns = load_tool_definitions(catalog_path)
    except Exception:
        logger.exception("Failed to load %s; falling back to legacy BUILTIN_TOOLS", catalog_path.name)
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
    # scope_search, knowledge_vault_*) that have no JSON entry, but only when
    # the active mode admits them per _COMMUNITY_TOOL_MODES.
    for tool in BUILTIN_TOOLS:
        if tool.name in json_names:
            continue
        if not _get_community_tool_enabled(tool.name):
            continue
        if not _community_tool_allowed_in_mode(tool.name, mode):
            continue
        tools.append(tool)
    if subagent_enabled:
        for tool in SUBAGENT_TOOLS:
            if tool.name in json_names:
                continue
            tools.append(tool)
    return tools
