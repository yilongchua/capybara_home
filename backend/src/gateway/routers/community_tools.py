"""Gateway API router for community tool enable/disable management."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.community.registry import COMMUNITY_TOOL_REGISTRY
from src.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["community-tools"])


class CommunityToolResponse(BaseModel):
    name: str
    display_name: str
    description: str
    enabled: bool
    source: str = Field(description="'builtin' or 'config'")


class CommunityToolsListResponse(BaseModel):
    tools: list[CommunityToolResponse]


class CommunityToolUpdateRequest(BaseModel):
    enabled: bool


def _build_tool_response(name: str, enabled: bool) -> CommunityToolResponse:
    entry = COMMUNITY_TOOL_REGISTRY[name]
    return CommunityToolResponse(
        name=name,
        display_name=entry["display_name"],
        description=entry["description"],
        enabled=enabled,
        source=entry["source"],
    )


def _save_community_tool_override(tool_name: str, enabled: bool) -> ExtensionsConfig:
    """Persist a community tool override to extensions_config.json.

    Reads the file on disk, updates only the communityTools section, writes
    back, and returns the reloaded ExtensionsConfig.
    """
    config_path = ExtensionsConfig.resolve_config_path()
    if config_path is None:
        config_path = Path.cwd().parent / "extensions_config.json"
        logger.info("No existing extensions config found; creating at %s", config_path)

    current = get_extensions_config()

    # Rebuild communityTools with the update applied.
    community_tools = {name: {"enabled": ct.enabled} for name, ct in current.community_tools.items()}
    community_tools[tool_name] = {"enabled": enabled}

    config_data = {
        "mcpServers": {name: server.model_dump() for name, server in current.mcp_servers.items()},
        "skills": {name: {"enabled": skill.enabled} for name, skill in current.skills.items()},
        "communityTools": community_tools,
    }

    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    logger.info("Community tool '%s' set to enabled=%s, saved to %s", tool_name, enabled, config_path)
    return reload_extensions_config()


@router.get(
    "/tools/community",
    response_model=CommunityToolsListResponse,
    summary="List Community Tools",
    description="Return all known community tools with their current enabled/disabled state.",
)
def list_community_tools() -> CommunityToolsListResponse:
    config = get_extensions_config()
    tools = []
    for name in COMMUNITY_TOOL_REGISTRY:
        override = config.community_tools.get(name)
        enabled = override.enabled if override is not None else True
        tools.append(_build_tool_response(name, enabled))
    return CommunityToolsListResponse(tools=tools)


@router.put(
    "/tools/community/{tool_name}",
    response_model=CommunityToolResponse,
    summary="Update Community Tool State",
    description="Enable or disable a community tool. The change is persisted to extensions_config.json.",
)
def update_community_tool(tool_name: str, request: CommunityToolUpdateRequest) -> CommunityToolResponse:
    if tool_name not in COMMUNITY_TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown community tool: '{tool_name}'")
    try:
        reloaded = _save_community_tool_override(tool_name, request.enabled)
        override = reloaded.community_tools.get(tool_name)
        enabled = override.enabled if override is not None else True
        return _build_tool_response(tool_name, enabled)
    except Exception as exc:
        logger.error("Failed to update community tool '%s': %s", tool_name, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update community tool: {exc}")
