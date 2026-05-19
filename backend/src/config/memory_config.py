"""Configuration for memory mechanism."""

from pydantic import BaseModel, Field


class MemoryConfig(BaseModel):
    """Configuration for global memory mechanism."""

    enabled: bool = Field(
        default=True,
        description="Whether to enable memory mechanism",
    )
    storage_path: str = Field(
        default="",
        description=(
            "Path to store memory data. "
            "If empty, defaults to `{base_dir}/memory.json` (see Paths.memory_file). "
            "Absolute paths are used as-is. "
            "Relative paths are resolved against `Paths.base_dir` "
            "(not the backend working directory). "
            "Note: if you previously set this to `.capybara-home/memory.json`, "
            "the file will now be resolved as `{base_dir}/.capybara-home/memory.json`; "
            "migrate existing data or use an absolute path to preserve the old location."
        ),
    )
    debounce_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds to wait before processing queued updates (debounce)",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for memory updates (None = use default model)",
    )
    max_facts: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Maximum number of facts to store",
    )
    fact_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for storing facts",
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to inject memory into system prompt",
    )
    max_injection_tokens: int = Field(
        default=2000,
        ge=100,
        le=8000,
        description="Maximum tokens to use for memory injection",
    )
    global_scope_enabled: bool = Field(
        default=True,
        description="Enable global (user-level) memory scope.",
    )
    workspace_scope_enabled: bool = Field(
        default=True,
        description="Enable workspace/chat-level memory scope.",
    )
    behavior_rules_enabled: bool = Field(
        default=True,
        description="Enable persistent behavior rules that are injected into system prompts.",
    )
    decay_enabled: bool = Field(
        default=True,
        description="Enable temporal decay scoring for fact retrieval.",
    )
    decay_half_life_days: int = Field(
        default=60,
        ge=7,
        le=365,
        description="Half-life in days used for temporal decay of fact relevance.",
    )
    decay_archive_threshold: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Facts below this relevance score become archival candidates.",
    )
    recall_top_k: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Default top-k for recall tool retrieval.",
    )
    injection_relevance_threshold: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Minimum vector/lexical relevance score for facts injected into the lead-agent prompt when current turn text is available.",
    )


# Global configuration instance
_memory_config: MemoryConfig = MemoryConfig()


def get_memory_config() -> MemoryConfig:
    """Get the current memory configuration."""
    return _memory_config


def set_memory_config(config: MemoryConfig) -> None:
    """Set the memory configuration."""
    global _memory_config
    _memory_config = config


def load_memory_config_from_dict(config_dict: dict) -> None:
    """Load memory configuration from a dictionary."""
    global _memory_config
    _memory_config = MemoryConfig(**config_dict)
