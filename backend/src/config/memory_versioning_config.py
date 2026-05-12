"""Configuration for versioned memory storage."""

from pydantic import BaseModel, Field


class MemoryVersioningConfig(BaseModel):
    """Versioned memory configuration."""

    enabled: bool = Field(default=False, description="Enable append-only memory versioning.")
    storage_dir: str = Field(
        default=".capybara-home/memory_versions",
        description="Directory used for version records (relative to backend base_dir unless absolute).",
    )
    require_expected_sha: bool = Field(
        default=False,
        description="Require expected_sha precondition for memory mutations.",
    )


_memory_versioning_config: MemoryVersioningConfig = MemoryVersioningConfig()


def get_memory_versioning_config() -> MemoryVersioningConfig:
    """Get current memory-versioning configuration."""
    return _memory_versioning_config


def set_memory_versioning_config(config: MemoryVersioningConfig) -> None:
    """Set memory-versioning configuration."""
    global _memory_versioning_config
    _memory_versioning_config = config


def load_memory_versioning_config_from_dict(config_dict: dict) -> None:
    """Load memory-versioning configuration from dictionary."""
    global _memory_versioning_config
    _memory_versioning_config = MemoryVersioningConfig(**config_dict)
