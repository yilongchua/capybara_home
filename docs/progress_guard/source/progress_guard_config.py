"""Configuration for progress-guard middleware."""

from pydantic import BaseModel, Field


class ProgressGuardConfig(BaseModel):
    """Detect possible no-progress loops with warn-first posture."""

    enabled: bool = Field(
        default=True,
        description="Whether ProgressGuard middleware is active.",
    )
    terminate_on_stall: bool = Field(
        default=False,
        description="Whether to end run when stall threshold is exceeded.",
    )
    no_progress_turn_threshold: int = Field(
        default=50,
        ge=3,
        le=500,
        description="Warning threshold for consecutive turns without progress.",
    )
    context_pressure_threshold: float = Field(
        default=0.85,
        ge=0.1,
        le=1.0,
        description="Warning threshold for context pressure fraction.",
    )
    conversation_inactivity_turn_threshold: int = Field(
        default=8,
        ge=2,
        le=100,
        description="Warning threshold for turns with no user-visible AI content.",
    )
    cyclic_tool_result_threshold: int = Field(
        default=3,
        ge=2,
        le=20,
        description="Warning threshold for repeated identical tool result cycles.",
    )
    terminate_on_cyclic_tool_results: bool = Field(
        default=True,
        description="Whether to end run when repeated identical tool results exceed the hard limit.",
    )
    cyclic_tool_result_hard_limit: int = Field(
        default=8,
        ge=3,
        le=100,
        description="Hard-stop threshold for repeated identical tool result cycles.",
    )


_progress_guard_config: ProgressGuardConfig = ProgressGuardConfig()


def get_progress_guard_config() -> ProgressGuardConfig:
    """Get current progress-guard configuration."""
    return _progress_guard_config


def set_progress_guard_config(config: ProgressGuardConfig) -> None:
    """Set progress-guard configuration."""
    global _progress_guard_config
    _progress_guard_config = config


def load_progress_guard_config_from_dict(config_dict: dict) -> None:
    """Load progress-guard configuration from dictionary."""
    global _progress_guard_config
    _progress_guard_config = ProgressGuardConfig(**config_dict)
