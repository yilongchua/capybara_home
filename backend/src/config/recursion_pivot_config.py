"""Configuration for recursion-budget pivot middleware."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RecursionPivotConfig(BaseModel):
    """Evaluator-driven mid-run steering when the recursion budget is nearly consumed."""

    enabled: bool = Field(
        default=False,
        description="Whether RecursionBudgetPivotMiddleware is active.",
    )
    thresholds: list[float] = Field(
        default_factory=lambda: [0.80, 0.90, 0.95],
        description="Budget fractions at which a pivot may fire. Each fires at most once per run; "
        "shorter remaining headroom on later pivots is the natural shrinking-budget mechanism.",
    )
    evaluator_model: str | None = Field(
        default=None,
        description="Override the evaluator LLM model name. None => resolve via ModelRouter('evaluator').",
    )
    evaluator_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=600.0,
        description="Hard timeout for the evaluator LLM call.",
    )
    on_evaluator_failure: Literal["skip", "terminate"] = Field(
        default="skip",
        description="Behavior when the evaluator errors or times out. 'skip' continues the run; "
        "'terminate' ends it with a synthetic warning.",
    )
    min_recursion_limit: int = Field(
        default=10,
        ge=1,
        description="Skip pivot logic entirely if recursion_limit is below this. Prevents noisy firing on tiny budgets.",
    )

    @field_validator("thresholds")
    @classmethod
    def _validate_thresholds(cls, value: list[float]) -> list[float]:
        if not value:
            raise ValueError("thresholds must contain at least one entry")
        for item in value:
            if not 0.0 < item < 1.0:
                raise ValueError(f"threshold {item!r} must be strictly between 0 and 1")
        # Sort ascending so threshold-crossing detection is deterministic regardless of input order.
        return sorted(set(value))


_recursion_pivot_config: RecursionPivotConfig = RecursionPivotConfig()


def get_recursion_pivot_config() -> RecursionPivotConfig:
    """Get current recursion-pivot configuration."""
    return _recursion_pivot_config


def set_recursion_pivot_config(config: RecursionPivotConfig) -> None:
    """Set recursion-pivot configuration."""
    global _recursion_pivot_config
    _recursion_pivot_config = config


def load_recursion_pivot_config_from_dict(config_dict: dict) -> None:
    """Load recursion-pivot configuration from dictionary."""
    global _recursion_pivot_config
    _recursion_pivot_config = RecursionPivotConfig(**config_dict)
