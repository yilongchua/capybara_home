"""Configuration for after-model question generation middleware."""

from pydantic import BaseModel, Field


class QuestionGenerationConfig(BaseModel):
    """Generate follow-up questions after the model produces a final response."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable follow-up question generation after each final model response.",
    )
    count: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of follow-up questions to generate.",
    )
    model_name: str | None = Field(
        default=None,
        description="Model to use for question generation (null = use default model).",
    )
    max_response_chars: int = Field(
        default=2000,
        ge=100,
        description="Maximum characters of the model response to include in the generation prompt.",
    )
    timeout_seconds: float = Field(
        default=180.0,
        gt=0.0,
        le=3600.0,
        description="Maximum time to wait for follow-up question generation model responses.",
    )
    prompt_template: str = Field(
        default=(
            "Given the following conversation exchange, generate {count} concise follow-up questions "
            "a user might want to ask next. Focus on natural continuations, clarifications, or deeper dives.\n\n"
            "User: {user_message}\n"
            "Assistant: {assistant_response}\n\n"
            "Return ONLY the questions as a numbered list (1. ... 2. ... etc.), one per line, no extra commentary."
        ),
        description="Prompt template for question generation. "
        "Available placeholders: {count}, {user_message}, {assistant_response}.",
    )


_question_generation_config: QuestionGenerationConfig = QuestionGenerationConfig()


def get_question_generation_config() -> QuestionGenerationConfig:
    """Return the current question-generation configuration."""
    return _question_generation_config


def set_question_generation_config(config: QuestionGenerationConfig) -> None:
    """Replace the question-generation configuration."""
    global _question_generation_config
    _question_generation_config = config


def load_question_generation_config_from_dict(config_dict: dict) -> None:
    """Load question-generation configuration from a plain dictionary."""
    global _question_generation_config
    _question_generation_config = QuestionGenerationConfig(**config_dict)
