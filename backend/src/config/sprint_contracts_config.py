"""Configuration for sprint contract behavior."""

from pydantic import BaseModel, Field


class SprintContractsConfig(BaseModel):
    """Sprint contract configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable sprint contract generation in Plan mode.",
    )
    min_todos_trigger: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Generate sprint contracts only when planner produces at least this many todos.",
    )


_sprint_contracts_config: SprintContractsConfig = SprintContractsConfig()


def get_sprint_contracts_config() -> SprintContractsConfig:
    """Get current sprint contracts configuration."""
    return _sprint_contracts_config


def set_sprint_contracts_config(config: SprintContractsConfig) -> None:
    """Set sprint contracts configuration."""
    global _sprint_contracts_config
    _sprint_contracts_config = config


def load_sprint_contracts_config_from_dict(config_dict: dict) -> None:
    """Load sprint contracts configuration from dictionary."""
    global _sprint_contracts_config
    _sprint_contracts_config = SprintContractsConfig(**config_dict)
