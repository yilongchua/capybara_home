"""Configuration for JSONL trajectory logging."""

from pydantic import BaseModel, Field


class TrajectoryConfig(BaseModel):
    """Runtime trajectory logging configuration."""

    enabled: bool = Field(
        default=True,
        description="Whether to persist per-run middleware/model/tool events to JSONL.",
    )
    file_prefix: str = Field(
        default="trajectory",
        description="Prefix for generated trajectory filenames.",
    )
    max_payload_chars: int = Field(
        default=1200,
        ge=100,
        le=10000,
        description="Maximum number of chars to persist for verbose payload fields.",
    )
    fsync: bool = Field(
        default=True,
        description="Whether to call fsync() after each write for crash durability.",
    )


_trajectory_config: TrajectoryConfig = TrajectoryConfig()


def get_trajectory_config() -> TrajectoryConfig:
    """Get current trajectory configuration."""
    return _trajectory_config


def set_trajectory_config(config: TrajectoryConfig) -> None:
    """Set trajectory configuration."""
    global _trajectory_config
    _trajectory_config = config


def load_trajectory_config_from_dict(config_dict: dict) -> None:
    """Load trajectory configuration from dictionary."""
    global _trajectory_config
    _trajectory_config = TrajectoryConfig(**config_dict)
