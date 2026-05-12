"""Configuration for lead-agent runtime metrics."""

from pydantic import BaseModel, Field


class MetricsConfig(BaseModel):
    """Runtime metrics configuration."""

    enabled: bool = Field(
        default=True,
        description="Whether middleware/runtime metrics should be collected.",
    )


_metrics_config: MetricsConfig = MetricsConfig()


def get_metrics_config() -> MetricsConfig:
    """Get current metrics configuration."""
    return _metrics_config


def set_metrics_config(config: MetricsConfig) -> None:
    """Set metrics configuration."""
    global _metrics_config
    _metrics_config = config


def load_metrics_config_from_dict(config_dict: dict) -> None:
    """Load metrics configuration from dictionary."""
    global _metrics_config
    _metrics_config = MetricsConfig(**config_dict)
