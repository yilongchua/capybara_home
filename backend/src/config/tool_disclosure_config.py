"""Configuration for phase-gated tool disclosure."""

from typing import Literal

from pydantic import BaseModel, Field


class ToolDisclosureConfig(BaseModel):
    """Runtime tool disclosure policy."""

    enabled: bool = Field(
        default=False,
        description="Enable phase-gated tool disclosure checks.",
    )
    default_phase: Literal["planner", "generator", "evaluator"] = Field(
        default="generator",
        description="Fallback phase used when middleware cannot infer a phase.",
    )
    block_mode: Literal["tool_error"] = Field(
        default="tool_error",
        description="Block behavior when a tool is not allowed for the current phase.",
    )
    phase_tools: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "planner": [],
            "generator": [],
            "evaluator": [],
        },
        description="Allow-list of tool names per phase. Empty list means no restriction for that phase.",
    )

    def allowed_tools_for(self, phase: str) -> list[str]:
        """Return the allow-list for a phase."""
        return list(self.phase_tools.get(phase, []))


_tool_disclosure_config: ToolDisclosureConfig = ToolDisclosureConfig()


def get_tool_disclosure_config() -> ToolDisclosureConfig:
    """Get current tool disclosure configuration."""
    return _tool_disclosure_config


def set_tool_disclosure_config(config: ToolDisclosureConfig) -> None:
    """Set tool disclosure configuration."""
    global _tool_disclosure_config
    _tool_disclosure_config = config


def load_tool_disclosure_config_from_dict(config_dict: dict) -> None:
    """Load tool disclosure configuration from dictionary."""
    global _tool_disclosure_config
    _tool_disclosure_config = ToolDisclosureConfig(**config_dict)
