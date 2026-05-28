"""Pydantic models describing the JSON tool-definition contract.

`internal_tools_plan.json` / `internal_tools_work.json` and `external_tools.json`
are the declarative source of truth for LLM-facing tool descriptions, schemas,
and filter policy. The Python handlers stay where they are; only the LLM
contract layer (description, parameter docs, mode/phase/endpoint gating) moves
to JSON. See docs/improvements/03-tool-descriptions.md for the audit that
motivated this.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ToolMode = Literal["plan", "work", "auto"]
ToolPhase = Literal["draft", "approved"]
ToolEndpoint = Literal["primary", "helper", "any"]


class ToolParameters(BaseModel):
    """JSON-Schema-shaped parameter description (matches the Cursor format)."""

    type: Literal["object"] = "object"
    required: list[str] = Field(default_factory=list)
    properties: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    """One entry in a per-mode internal tool catalog (plan or work)."""

    name: str
    description: str
    handler: str = Field(
        description="Module:variable path resolved via reflection.resolve_variable, e.g. 'src.tools.builtins.recall_tool:recall_tool'.",
    )
    mode: list[ToolMode] = Field(default_factory=lambda: ["plan", "work", "auto"])
    phase: list[ToolPhase] = Field(default_factory=lambda: ["draft", "approved"])
    groups: list[str] = Field(default_factory=list)
    endpoint: ToolEndpoint = "any"
    requires_vision: bool = False
    requires_subagent_enabled: bool = False
    returns: str | None = None
    examples: list[str] = Field(default_factory=list)
    parameters: ToolParameters = Field(default_factory=ToolParameters)
    deprecated: bool = False


class McpServerPolicy(BaseModel):
    """Per-MCP-server policy entry in external_tools.json."""

    name: str
    mode: list[ToolMode] = Field(default_factory=lambda: ["plan", "work", "auto"])
    phase: list[ToolPhase] = Field(default_factory=lambda: ["draft", "approved"])
    name_prefix: str | None = None
    subagent_visible: bool = True


class CliBridgePolicy(BaseModel):
    """Per-CLI-bridge entry in external_tools.json (reserved for future use)."""

    name: str
    handler: str
    mode: list[ToolMode] = Field(default_factory=lambda: ["plan", "work", "auto"])
    phase: list[ToolPhase] = Field(default_factory=lambda: ["draft", "approved"])
    endpoint: ToolEndpoint = "any"


class ExternalPolicy(BaseModel):
    """Top-level shape of external_tools.json."""

    mcp_servers: list[McpServerPolicy] = Field(default_factory=list)
    cli_bridges: list[CliBridgePolicy] = Field(default_factory=list)
