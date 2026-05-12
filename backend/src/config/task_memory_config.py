"""Configuration for task-scoped episodic memory."""

from pydantic import BaseModel, Field


class TaskMemoryConfig(BaseModel):
    """Task-memory middleware configuration."""

    enabled: bool = Field(default=False, description="Enable task-scoped episodic memory.")
    max_facts_per_task: int = Field(default=6, ge=1, le=100, description="Maximum stored facts per task.")
    retention_turns: int = Field(default=40, ge=1, le=500, description="Approximate retention window used during compaction.")


_task_memory_config: TaskMemoryConfig = TaskMemoryConfig()


def get_task_memory_config() -> TaskMemoryConfig:
    """Get current task-memory configuration."""
    return _task_memory_config


def set_task_memory_config(config: TaskMemoryConfig) -> None:
    """Set task-memory configuration."""
    global _task_memory_config
    _task_memory_config = config


def load_task_memory_config_from_dict(config_dict: dict) -> None:
    """Load task-memory configuration from dictionary."""
    global _task_memory_config
    _task_memory_config = TaskMemoryConfig(**config_dict)
