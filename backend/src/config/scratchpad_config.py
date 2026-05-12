"""Configuration for scratchpad runtime memory."""

from pydantic import BaseModel, Field


class ScratchpadConfig(BaseModel):
    """Scratchpad middleware configuration."""

    enabled: bool = Field(default=False, description="Enable scratchpad note capture.")
    max_entries: int = Field(default=40, ge=1, le=500, description="Maximum scratchpad entries retained in state.")
    max_chars_per_entry: int = Field(default=600, ge=64, le=4000, description="Maximum characters retained per entry.")
    artifact_file: str = Field(default="scratchpad.md", description="Scratchpad artifact filename under handoff directory.")


_scratchpad_config: ScratchpadConfig = ScratchpadConfig()


def get_scratchpad_config() -> ScratchpadConfig:
    """Get current scratchpad configuration."""
    return _scratchpad_config


def set_scratchpad_config(config: ScratchpadConfig) -> None:
    """Set scratchpad configuration."""
    global _scratchpad_config
    _scratchpad_config = config


def load_scratchpad_config_from_dict(config_dict: dict) -> None:
    """Load scratchpad configuration from dictionary."""
    global _scratchpad_config
    _scratchpad_config = ScratchpadConfig(**config_dict)
