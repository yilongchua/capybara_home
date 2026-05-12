"""Configuration for evaluator middleware."""

from pydantic import BaseModel, Field


class EvaluatorConfig(BaseModel):
    """Evaluator behavior configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable evaluator stage in Plan mode.",
    )
    max_attempts: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum evaluation feedback attempts per run.",
    )
    plan_evaluator_timeout_seconds: float = Field(
        default=180.0,
        gt=0.0,
        le=3600.0,
        description="Hard timeout (seconds) for the plan evaluator's internal LLM check.",
    )


_evaluator_config: EvaluatorConfig = EvaluatorConfig()


def get_evaluator_config() -> EvaluatorConfig:
    """Get current evaluator configuration."""
    return _evaluator_config


def set_evaluator_config(config: EvaluatorConfig) -> None:
    """Set evaluator configuration."""
    global _evaluator_config
    _evaluator_config = config


def load_evaluator_config_from_dict(config_dict: dict) -> None:
    """Load evaluator configuration from dictionary."""
    global _evaluator_config
    _evaluator_config = EvaluatorConfig(**config_dict)
