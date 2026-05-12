"""Configuration for todo DAG behavior."""

from pydantic import BaseModel, Field


class TodosConfig(BaseModel):
    """Todo system configuration."""

    dag_enabled: bool = Field(
        default=True,
        description="Enable DAG-based todo graph processing.",
    )
    max_exit_reminders: int = Field(
        default=2,
        ge=0,
        le=20,
        description="Maximum number of reminder injections when model stops with incomplete todos.",
    )


_todos_config: TodosConfig = TodosConfig()


def get_todos_config() -> TodosConfig:
    """Get current todos configuration."""
    return _todos_config


def set_todos_config(config: TodosConfig) -> None:
    """Set todos configuration."""
    global _todos_config
    _todos_config = config


def load_todos_config_from_dict(config_dict: dict) -> None:
    """Load todos configuration from dictionary."""
    global _todos_config
    _todos_config = TodosConfig(**config_dict)
