"""Configuration for execution trace middleware behavior."""

from pydantic import BaseModel, Field


class ExecutionTraceConfig(BaseModel):
    """Execution trace middleware configuration."""

    enabled: bool = Field(
        default=True,
        description="Whether execution trace middleware should run and emit trace events.",
    )


_execution_trace_config: ExecutionTraceConfig = ExecutionTraceConfig()


def get_execution_trace_config() -> ExecutionTraceConfig:
    """Get current execution trace configuration."""
    return _execution_trace_config


def set_execution_trace_config(config: ExecutionTraceConfig) -> None:
    """Set execution trace configuration."""
    global _execution_trace_config
    _execution_trace_config = config


def load_execution_trace_config_from_dict(config_dict: dict) -> None:
    """Load execution trace configuration from dictionary."""
    global _execution_trace_config
    _execution_trace_config = ExecutionTraceConfig(**config_dict)
