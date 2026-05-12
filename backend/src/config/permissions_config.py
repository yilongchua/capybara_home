"""Configuration for declarative tool-permission policy."""

from typing import Literal

from pydantic import BaseModel, Field

PermissionDefaultMode = Literal["auto", "ask", "plan"]


class PermissionsConfig(BaseModel):
    """Permission policy for tool invocation."""

    allow: list[str] = Field(
        default_factory=list,
        description="List of allow rules (tool names or tool(arg-pattern) rules).",
    )
    deny: list[str] = Field(
        default_factory=list,
        description="List of deny rules (tool names or tool(arg-pattern) rules).",
    )
    ask: list[str] = Field(
        default_factory=list,
        description="List of ask rules (tool names or tool(arg-pattern) rules).",
    )
    default_mode: PermissionDefaultMode = Field(
        default="auto",
        description="Fallback mode when no rule matches: auto | ask | plan.",
    )


_permissions_config: PermissionsConfig = PermissionsConfig()


def get_permissions_config() -> PermissionsConfig:
    """Get current permissions configuration."""
    return _permissions_config


def set_permissions_config(config: PermissionsConfig) -> None:
    """Set permissions configuration."""
    global _permissions_config
    _permissions_config = config


def load_permissions_config_from_dict(config_dict: dict) -> None:
    """Load permissions configuration from dict."""
    global _permissions_config
    _permissions_config = PermissionsConfig(**config_dict)
