"""Configuration for event hooks middleware."""

from pydantic import BaseModel, Field


class HookCommandConfig(BaseModel):
    """Command handler declaration for a hook event."""

    command: str = Field(..., description="Shell command to run.")
    matcher: str | None = Field(
        default=None,
        description="Optional matcher (tool name or glob path, depending on event).",
    )
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Command timeout in seconds.",
    )


class HooksConfig(BaseModel):
    """Lifecycle hook configuration."""

    SessionStart: list[HookCommandConfig] = Field(default_factory=list)
    PreToolUse: list[HookCommandConfig] = Field(default_factory=list)
    PostToolUse: list[HookCommandConfig] = Field(default_factory=list)
    FileChanged: list[HookCommandConfig] = Field(default_factory=list)


_hooks_config: HooksConfig = HooksConfig()


def get_hooks_config() -> HooksConfig:
    """Get current hooks configuration."""
    return _hooks_config


def set_hooks_config(config: HooksConfig) -> None:
    """Set hooks configuration."""
    global _hooks_config
    _hooks_config = config


def load_hooks_config_from_dict(config_dict: dict) -> None:
    """Load hooks configuration from dictionary."""
    global _hooks_config
    _hooks_config = HooksConfig(**config_dict)
