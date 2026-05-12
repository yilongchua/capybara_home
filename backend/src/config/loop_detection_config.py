"""Configuration for loop-detection middleware safety thresholds."""

from pydantic import BaseModel, Field


class LoopDetectionConfig(BaseModel):
    """Controls repetitive tool-call loop detection behavior."""

    enabled: bool = Field(
        default=True,
        description="Whether loop-detection middleware is active.",
    )
    warn_threshold: int = Field(
        default=3,
        ge=1,
        le=1000,
        description="Repeated identical tool-call hashes before warning.",
    )
    hard_limit: int = Field(
        default=5,
        ge=1,
        le=2000,
        description="Repeated identical tool-call hashes before forced stop behavior.",
    )
    window_size: int = Field(
        default=20,
        ge=1,
        le=5000,
        description="Sliding window size for hash repetition tracking.",
    )
    max_tracked_threads: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum threads kept in loop-detection LRU state.",
    )
    tool_freq_warn: int = Field(
        default=30,
        ge=1,
        le=10000,
        description="Per-tool cumulative call count before warning.",
    )
    tool_freq_hard_limit: int = Field(
        default=50,
        ge=1,
        le=20000,
        description="Per-tool cumulative call count before forced stop behavior.",
    )


_loop_detection_config: LoopDetectionConfig = LoopDetectionConfig()


def get_loop_detection_config() -> LoopDetectionConfig:
    """Get current loop-detection configuration."""
    return _loop_detection_config


def set_loop_detection_config(config: LoopDetectionConfig) -> None:
    """Set loop-detection configuration."""
    global _loop_detection_config
    _loop_detection_config = config


def load_loop_detection_config_from_dict(config_dict: dict) -> None:
    """Load loop-detection configuration from dictionary."""
    global _loop_detection_config
    _loop_detection_config = LoopDetectionConfig(**config_dict)
