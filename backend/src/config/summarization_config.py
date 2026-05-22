"""Configuration for conversation summarization."""

from typing import Literal

from pydantic import BaseModel, Field

ContextSizeType = Literal["fraction", "tokens", "messages"]


class ContextSize(BaseModel):
    """Context size specification for trigger or keep parameters."""

    type: ContextSizeType = Field(description="Type of context size specification")
    value: int | float = Field(description="Value for the context size specification")

    def to_tuple(self) -> tuple[ContextSizeType, int | float]:
        """Convert to tuple format expected by SummarizationMiddleware."""
        return (self.type, self.value)


class SummarizationConfig(BaseModel):
    """Configuration for automatic conversation summarization."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable automatic conversation summarization",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for summarization (None = use a lightweight model)",
    )
    trigger: ContextSize | list[ContextSize] | None = Field(
        default=None,
        description="One or more thresholds that trigger summarization. When any threshold is met, summarization runs. "
        "Prefer {'type': 'fraction', 'value': 0.8} for token-pressure compaction at 80% of the model context window. "
        "Legacy message-count triggers are accepted by config parsing but ignored by the lead-agent factory.",
    )
    keep: ContextSize = Field(
        default_factory=lambda: ContextSize(type="tokens", value=32000),
        description="Context retention policy after summarization. Specifies how much history to preserve. "
        "Prefer token-based retention, e.g. {'type': 'tokens', 'value': 32000}. "
        "Legacy message-count keep policies are converted to a token keep budget by the lead-agent factory.",
    )
    trim_tokens_to_summarize: int | None = Field(
        default=None,
        description="Maximum tokens to keep when preparing messages for summarization. Pass null to skip trimming.",
    )
    summary_prompt: str | None = Field(
        default=None,
        description="Custom prompt template for generating summaries. If not provided, uses the default LangChain prompt.",
    )
    max_context_tokens: int | None = Field(
        default=None,
        description="Maximum context window tokens for fraction-based compaction. Resolution prefers model profile -> this value -> model config -> default 128000.",
    )
    modes: dict[str, "SummarizationModeOverride"] = Field(
        default_factory=dict,
        description="Optional per-mode overrides keyed by mode name: work, plan, dreamy. Legacy aliases fast/pro are also recognized.",
    )


class SummarizationModeOverride(BaseModel):
    """Per-mode overrides for summarization behavior."""

    trigger: ContextSize | list[ContextSize] | None = Field(default=None)
    keep: ContextSize | None = Field(default=None)
    trim_tokens_to_summarize: int | None = Field(default=None)
    summary_prompt: str | None = Field(default=None)
    max_context_tokens: int | None = Field(default=None)


# Global configuration instance
_summarization_config: SummarizationConfig = SummarizationConfig()


def get_summarization_config() -> SummarizationConfig:
    """Get the current summarization configuration."""
    return _summarization_config


def set_summarization_config(config: SummarizationConfig) -> None:
    """Set the summarization configuration."""
    global _summarization_config
    _summarization_config = config


def load_summarization_config_from_dict(config_dict: dict) -> None:
    """Load summarization configuration from a dictionary."""
    global _summarization_config
    _summarization_config = SummarizationConfig(**config_dict)
