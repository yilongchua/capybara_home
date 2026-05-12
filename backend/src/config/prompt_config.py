"""Configuration for lead-agent prompt rendering."""

from pydantic import BaseModel, Field


class PromptConfig(BaseModel):
    """Configuration for prompt assembly behavior."""

    componentized: bool = Field(
        default=True,
        description="Whether to render the lead-agent system prompt via component registry.",
    )


_prompt_config: PromptConfig = PromptConfig()


def get_prompt_config() -> PromptConfig:
    """Get the current prompt configuration."""
    return _prompt_config


def set_prompt_config(config: PromptConfig) -> None:
    """Set the prompt configuration."""
    global _prompt_config
    _prompt_config = config


def load_prompt_config_from_dict(config_dict: dict) -> None:
    """Load prompt configuration from a dictionary."""
    global _prompt_config
    _prompt_config = PromptConfig(**config_dict)
