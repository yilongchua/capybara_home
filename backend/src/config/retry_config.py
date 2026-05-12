"""Configuration for retry policy middleware."""

from pydantic import BaseModel, Field


class RetryRuleConfig(BaseModel):
    """Per-tool retry rule."""

    tool: str = Field(..., description="Tool name glob pattern.")
    max_attempts: int = Field(default=2, ge=1, le=10)
    backoff_ms: int = Field(default=1000, ge=0, le=120000)
    retryable_errors: list[str] = Field(
        default_factory=lambda: ["timeout", "connection"],
        description="Case-insensitive substring matches against exception text.",
    )
    idempotent: bool = Field(
        default=True,
        description="Whether the tool can be retried without side effects.",
    )


class RetryConfig(BaseModel):
    """Global retry middleware configuration."""

    enabled: bool = Field(default=True, description="Enable retry middleware.")
    default: bool = Field(
        default=False,
        description="Whether retry applies to tools without explicit rule matches.",
    )
    max_attempts: int = Field(default=2, ge=1, le=10)
    backoff_ms: int = Field(default=1000, ge=0, le=120000)
    rules: list[RetryRuleConfig] = Field(
        default_factory=lambda: [
            RetryRuleConfig(
                tool="task",
                max_attempts=2,
                backoff_ms=2000,
                retryable_errors=["timeout"],
                idempotent=False,
            )
        ]
    )


_retry_config: RetryConfig = RetryConfig()


def get_retry_config() -> RetryConfig:
    """Get current retry configuration."""
    return _retry_config


def set_retry_config(config: RetryConfig) -> None:
    """Set retry configuration."""
    global _retry_config
    _retry_config = config


def load_retry_config_from_dict(config_dict: dict) -> None:
    """Load retry configuration from dictionary."""
    global _retry_config
    _retry_config = RetryConfig(**config_dict)
