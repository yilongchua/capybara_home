"""Configuration for dreamy execution timeouts and long-running task controls."""

from pydantic import BaseModel, Field


class DreamyTimeoutConfig(BaseModel):
    """Controls for long-running dreamy threads and stuck-run recovery."""

    enabled: bool = Field(
        default=True,
        description="Whether dreamy timeout controls are active.",
    )
    max_model_call_duration: float = Field(
        default=600.0,
        gt=0,
        description="Maximum allowed duration (seconds) for a single model call before watchdog fires.",
    )
    max_run_wall_clock: float = Field(
        default=1800.0,
        gt=0,
        description="Maximum total wall-clock time (seconds) for an entire agent run before forced termination.",
    )
    model_call_warn_threshold: float = Field(
        default=300.0,
        gt=0,
        description="Duration (seconds) after which a warning is injected when a model call is still in progress.",
    )
    checkpoint_on_after_agent: bool = Field(
        default=True,
        description="Whether to write checkpoint.json on every after_agent event.",
    )
    bootstrap_validate_data_source: bool = Field(
        default=True,
        description="Whether to validate the detected data source during bootstrap.",
    )
    executor_poc_threshold: int = Field(
        default=4,
        ge=1,
        description="Minimum poc rows after which the Python executor can take over (instead of waiting for bulk phase).",
    )
    executor_poc_max_rows: int = Field(
        default=50,
        ge=1,
        description="Maximum total rows allowed for poc-phase executor takeover.",
    )
    bootstrap_loader_timeout_seconds: float = Field(
        default=15.0,
        gt=0.0,
        le=600.0,
        description="Timeout for dreamy bootstrap helper subprocesses (e.g. load_tasks.py).",
    )


_dreamy_timeout_config: DreamyTimeoutConfig = DreamyTimeoutConfig()


def get_dreamy_timeout_config() -> DreamyTimeoutConfig:
    """Get current dreamy timeout configuration."""
    return _dreamy_timeout_config


def set_dreamy_timeout_config(config: DreamyTimeoutConfig) -> None:
    """Set dreamy timeout configuration."""
    global _dreamy_timeout_config
    _dreamy_timeout_config = config


def load_dreamy_timeout_config_from_dict(config_dict: dict) -> None:
    """Load dreamy timeout configuration from dictionary."""
    global _dreamy_timeout_config
    _dreamy_timeout_config = DreamyTimeoutConfig(**config_dict)
