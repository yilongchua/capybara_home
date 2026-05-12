"""Configuration for resumable run behavior."""

from pydantic import BaseModel, Field


class ResumeConfig(BaseModel):
    """Resume feature configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable resumable run helpers and state tracking.",
    )
    require_checkpoint: bool = Field(
        default=True,
        description="Whether resume should require checkpoint metadata before attempting resume.",
    )
    max_resume_depth: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum nested resume attempts for the same run context.",
    )


_resume_config: ResumeConfig = ResumeConfig()


def get_resume_config() -> ResumeConfig:
    """Get current resume configuration."""
    return _resume_config


def set_resume_config(config: ResumeConfig) -> None:
    """Set resume configuration."""
    global _resume_config
    _resume_config = config


def load_resume_config_from_dict(config_dict: dict) -> None:
    """Load resume configuration from dictionary."""
    global _resume_config
    _resume_config = ResumeConfig(**config_dict)
