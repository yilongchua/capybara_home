"""Configuration for per-stage model routing."""

from pydantic import BaseModel, Field


class RoutingTimeoutsConfig(BaseModel):
    """Bound the wall-clock duration of a single LLM invocation per stage.

    A stage's value caps `model.ainvoke` (and the sync `invoke`). When the
    bound is exceeded, ModelTimeoutMiddleware emits a `model_call_timeout`
    trajectory event and surfaces a synthetic AI-side error message so the
    agent loop can self-correct rather than silently hang.

    Tune defaults to local-LLM behaviour: planner/evaluator stages tend to be
    short and benefit from a tight ceiling; generator stage handles long
    multi-tool reasoning and gets the highest budget.
    """

    enabled: bool = Field(default=True)
    default: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Fallback timeout (seconds) when a stage has no override.",
    )
    stages: dict[str, int] = Field(
        default_factory=lambda: {
            "planner": 300,
            "generator": 300,
            # Synthesis runs after a tool batch — model digests tool output, often
            # 30+ KB. Needs significantly more headroom than a first-pass call.
            "synthesis": 1200,
            "evaluator": 300,
            "title": 60,
        },
        description="Per-stage timeout (seconds).",
    )
    tools_default: int = Field(
        default=300,
        ge=5,
        le=3600,
        description="Fallback timeout (seconds) for any individual tool call.",
    )
    tools: dict[str, int] = Field(
        default_factory=lambda: {
            "bash": 600,
            "task": 1800,
            "web_search": 45,
            "write_todos": 30,
        },
        description="Per-tool wall-clock timeout (seconds).",
    )
    # Tool result truncation: bound the size of ToolMessage content before it
    # enters the agent context. Per-tool override > default. Set to 0 to disable
    # truncation for a specific tool. Used by ToolResultTruncationMiddleware.
    tool_result_default_chars: int | None = Field(
        default=None,
        description="Default truncation cap for tool results (chars). None = no default cap (per-tool only).",
    )
    tool_result_caps: dict[str, int] = Field(
        default_factory=lambda: {
            "web_search": 12000,
            "bash": 8000,
            "ls": 4000,
            "read_file": 16000,
        },
        description="Per-tool truncation cap (chars). 0 disables truncation for that tool.",
    )
    # Adaptive: when a web_search ToolMessage was NOT summarized (web_search_summary
    # skipped/failed), apply this smaller cap instead of the regular `web_search`
    # cap. Synthesis stage drowns when fed multiple raw 12 KB excerpts after a
    # 3-way concurrent search — see thread-cd90decb audit. Set equal to
    # tool_result_caps["web_search"] to disable adaptive behavior.
    unsummarized_web_search_chars: int = Field(
        default=3500,
        ge=0,
        le=64000,
        description="Truncation cap for web_search results that lack a summary marker.",
    )

    def for_stage(self, stage: str | None) -> int:
        if stage and stage in self.stages:
            return int(self.stages[stage])
        return int(self.default)

    def for_tool(self, tool: str | None) -> int:
        if tool and tool in self.tools:
            return int(self.tools[tool])
        return int(self.tools_default)

    def truncation_cap_for(self, tool: str | None) -> int | None:
        """Resolve truncation cap for `tool`. Returns None when no cap applies."""
        if tool and tool in self.tool_result_caps:
            cap = int(self.tool_result_caps[tool])
            return None if cap <= 0 else cap
        if self.tool_result_default_chars is not None:
            cap = int(self.tool_result_default_chars)
            return None if cap <= 0 else cap
        return None


class RoutingConfig(BaseModel):
    """Stage-to-model routing map."""

    stages: dict[str, str] = Field(
        default_factory=dict,
        description="Map of stage name to model name.",
    )
    fallback: str | None = Field(
        default=None,
        description="Fallback model name when a stage mapping is missing or invalid.",
    )
    timeouts: RoutingTimeoutsConfig = Field(
        default_factory=RoutingTimeoutsConfig,
        description="Per-stage LLM call timeouts.",
    )


_routing_config: RoutingConfig = RoutingConfig()


def get_routing_config() -> RoutingConfig:
    """Get current routing configuration."""
    return _routing_config


def set_routing_config(config: RoutingConfig) -> None:
    """Set routing configuration."""
    global _routing_config
    _routing_config = config


def load_routing_config_from_dict(config_dict: dict) -> None:
    """Load routing configuration from dictionary."""
    global _routing_config
    _routing_config = RoutingConfig(**config_dict)
