import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from src.config.benchmarks_config import BenchmarksConfig, load_benchmarks_config_from_dict
from src.config.checkpointer_config import CheckpointerConfig, load_checkpointer_config_from_dict
from src.config.control_plane_config import (
    ApprovalsConfig,
    CSVProfilesConfig,
    GenerationAsyncConfig,
    KnowledgeVaultConfig,
    PipelinesConfig,
    RedactionConfig,
    SchedulerConfig,
    ToolBackendsConfig,
)
from src.config.evaluator_config import EvaluatorConfig, load_evaluator_config_from_dict
from src.config.execution_trace_config import ExecutionTraceConfig, load_execution_trace_config_from_dict
from src.config.extensions_config import ExtensionsConfig
from src.config.handoffs_config import HandoffsConfig, load_handoffs_config_from_dict
from src.config.harness_config import load_harness_config_from_dict
from src.config.hooks_config import HooksConfig, load_hooks_config_from_dict
from src.config.loop_detection_config import LoopDetectionConfig, load_loop_detection_config_from_dict
from src.config.memory_config import load_memory_config_from_dict
from src.config.memory_versioning_config import MemoryVersioningConfig, load_memory_versioning_config_from_dict
from src.config.metrics_config import MetricsConfig, load_metrics_config_from_dict
from src.config.model_config import ModelConfig
from src.config.permissions_config import PermissionsConfig, load_permissions_config_from_dict
from src.config.planner_config import PlannerConfig, load_planner_config_from_dict
from src.config.prompt_config import PromptConfig, load_prompt_config_from_dict
from src.config.quality_gate_config import QualityGateConfig, load_quality_gate_config_from_dict
from src.config.question_generation_config import load_question_generation_config_from_dict
from src.config.recursion_pivot_config import RecursionPivotConfig, load_recursion_pivot_config_from_dict
from src.config.resume_config import ResumeConfig, load_resume_config_from_dict
from src.config.retry_config import RetryConfig, load_retry_config_from_dict
from src.config.routing_config import RoutingConfig, load_routing_config_from_dict
from src.config.sandbox_config import SandboxConfig
from src.config.scratchpad_config import ScratchpadConfig, load_scratchpad_config_from_dict
from src.config.skill_curation_config import SkillCurationConfig, load_skill_curation_config_from_dict
from src.config.skills_config import SkillsConfig
from src.config.sprint_contracts_config import SprintContractsConfig, load_sprint_contracts_config_from_dict
from src.config.subagents_config import SubagentsAppConfig, load_subagents_config_from_dict
from src.config.summarization_config import load_summarization_config_from_dict
from src.config.task_memory_config import TaskMemoryConfig, load_task_memory_config_from_dict
from src.config.title_config import load_title_config_from_dict
from src.config.todos_config import TodosConfig, load_todos_config_from_dict
from src.config.tool_config import ToolConfig, ToolGroupConfig
from src.config.tool_disclosure_config import ToolDisclosureConfig, load_tool_disclosure_config_from_dict
from src.config.trajectory_config import TrajectoryConfig, load_trajectory_config_from_dict
from src.config.web_search_summary_config import WebSearchSummaryConfig, load_web_search_summary_config_from_dict

load_dotenv()


class AppConfig(BaseModel):
    """Config for the CapyHome application"""

    models: list[ModelConfig] = Field(default_factory=list, description="Available models")
    sandbox: SandboxConfig = Field(description="Sandbox configuration")
    tools: list[ToolConfig] = Field(default_factory=list, description="Available tools")
    tool_groups: list[ToolGroupConfig] = Field(default_factory=list, description="Available tool groups")
    json_driven_tools: bool = Field(
        default=True,
        description="When true (default), built-in/sandbox tool descriptions are sourced from per-mode catalogs (internal_tools_plan.json / internal_tools_work.json). Set false to fall back to hard-coded BUILTIN_TOOLS.",
    )
    skills: SkillsConfig = Field(default_factory=SkillsConfig, description="Skills configuration")
    prompt: PromptConfig = Field(default_factory=PromptConfig, description="Prompt assembly configuration")
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig, description="Tool permission policy configuration")
    trajectory: TrajectoryConfig = Field(default_factory=TrajectoryConfig, description="Trajectory logging configuration")
    metrics: MetricsConfig = Field(default_factory=MetricsConfig, description="Runtime metrics configuration")
    execution_trace: ExecutionTraceConfig = Field(default_factory=ExecutionTraceConfig, description="Execution trace middleware configuration")
    subagents: SubagentsAppConfig = Field(default_factory=SubagentsAppConfig, description="Subagent timeout and concurrency policy")
    recursion_pivot: RecursionPivotConfig = Field(default_factory=RecursionPivotConfig, description="Recursion-budget evaluator pivot configuration")
    quality_gate: QualityGateConfig = Field(default_factory=QualityGateConfig, description="Report quality gate configuration")
    loop_detection: LoopDetectionConfig = Field(
        default_factory=LoopDetectionConfig,
        description="Loop-detection middleware safety thresholds",
    )
    todos: TodosConfig = Field(default_factory=TodosConfig, description="Todo DAG configuration")
    routing: RoutingConfig = Field(default_factory=RoutingConfig, description="Per-stage model routing configuration")
    planner: PlannerConfig = Field(default_factory=PlannerConfig, description="Planner middleware configuration")
    evaluator: EvaluatorConfig = Field(default_factory=EvaluatorConfig, description="Evaluator middleware configuration")
    sprint_contracts: SprintContractsConfig = Field(default_factory=SprintContractsConfig, description="Sprint contract configuration")
    handoffs: HandoffsConfig = Field(default_factory=HandoffsConfig, description="Handoff artifact configuration")
    hooks: HooksConfig = Field(default_factory=HooksConfig, description="Lifecycle hooks configuration")
    retry: RetryConfig = Field(default_factory=RetryConfig, description="Retry middleware configuration")
    resume: ResumeConfig = Field(default_factory=ResumeConfig, description="Resume behavior configuration")
    tool_disclosure: ToolDisclosureConfig = Field(default_factory=ToolDisclosureConfig, description="Phase-gated tool disclosure configuration")
    web_search_summary: WebSearchSummaryConfig = Field(
        default_factory=WebSearchSummaryConfig,
        description="Web-search summarization middleware configuration",
    )
    scratchpad: ScratchpadConfig = Field(default_factory=ScratchpadConfig, description="Scratchpad middleware configuration")
    task_memory: TaskMemoryConfig = Field(default_factory=TaskMemoryConfig, description="Task-scoped episodic memory configuration")
    memory_versioning: MemoryVersioningConfig = Field(default_factory=MemoryVersioningConfig, description="Versioned memory configuration")
    skill_curation: SkillCurationConfig = Field(default_factory=SkillCurationConfig, description="Skill auto-curation configuration")
    benchmarks: BenchmarksConfig = Field(default_factory=BenchmarksConfig, description="Benchmark calibration configuration")
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig, description="Extensions configuration (MCP servers and skills state)")
    pipelines: PipelinesConfig = Field(default_factory=PipelinesConfig, description="Pipeline control-plane configuration")
    approvals: ApprovalsConfig = Field(default_factory=ApprovalsConfig, description="Approval workflow configuration")
    redaction: RedactionConfig = Field(default_factory=RedactionConfig, description="Deterministic redaction configuration")
    csv_profiles: CSVProfilesConfig = Field(default_factory=CSVProfilesConfig, description="Reusable CSV analysis profiles")
    tool_backends: ToolBackendsConfig = Field(default_factory=ToolBackendsConfig, description="Local tool backend endpoints")
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig, description="Background scheduler configuration")
    generation: GenerationAsyncConfig = Field(default_factory=GenerationAsyncConfig, description="Asynchronous ComfyUI generation jobs")
    knowledge_vault: KnowledgeVaultConfig = Field(default_factory=KnowledgeVaultConfig, description="Knowledge vault ingestion/compile settings")
    model_config = ConfigDict(extra="allow", frozen=False)
    checkpointer: CheckpointerConfig | None = Field(default=None, description="Checkpointer configuration")

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path:
        """Resolve the config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `CAPYBARA_HOME_CONFIG_PATH` environment variable, use it.
        3. Otherwise, first check the `config.yaml` in the current directory, then fallback to `config.yaml` in the parent directory.
        """
        if config_path:
            path = Path(config_path)
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("CAPYBARA_HOME_CONFIG_PATH"):
            path = Path(os.getenv("CAPYBARA_HOME_CONFIG_PATH"))
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by environment variable `CAPYBARA_HOME_CONFIG_PATH` not found at {path}")
            return path
        else:
            # Check if the config.yaml is in the current directory
            path = Path(os.getcwd()) / "config.yaml"
            if not path.exists():
                # Check if the config.yaml is in the parent directory of CWD
                path = Path(os.getcwd()).parent / "config.yaml"
                if not path.exists():
                    raise FileNotFoundError("`config.yaml` file not found at the current directory nor its parent directory")
            return path

    @classmethod
    def from_file(cls, config_path: str | None = None) -> "AppConfig":
        """Load config from YAML file.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the config file.

        Returns:
            AppConfig: The loaded config.
        """
        resolved_path = cls.resolve_config_path(config_path)
        with open(resolved_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
        config_data = cls.resolve_env_variables(config_data)

        # Load title config if present
        if "title" in config_data:
            load_title_config_from_dict(config_data["title"])

        # Load summarization/compaction config.
        # `compaction` is a supported alias for `summarization` to make the
        # intent clearer in user-facing config. If both are present,
        # `summarization` wins.
        if "summarization" in config_data:
            load_summarization_config_from_dict(config_data["summarization"])
        elif "compaction" in config_data:
            load_summarization_config_from_dict(config_data["compaction"])

        # Load memory config if present
        if "memory" in config_data:
            load_memory_config_from_dict(config_data["memory"])

        # Load subagents config if present
        if "subagents" in config_data:
            load_subagents_config_from_dict(config_data["subagents"])

        # Load prompt config
        load_prompt_config_from_dict(config_data.get("prompt", {}))

        # Load permissions config
        load_permissions_config_from_dict(config_data.get("permissions", {}))

        # Load trajectory config
        load_trajectory_config_from_dict(config_data.get("trajectory", {}))

        # Load metrics config
        load_metrics_config_from_dict(config_data.get("metrics", {}))

        # Load execution trace config
        load_execution_trace_config_from_dict(config_data.get("execution_trace", {}))

        # Load harness kill-switch config (single toggle that drops the full
        # middleware chain back to the minimal plumbing subset — see
        # src/config/harness_config.py for contract).
        load_harness_config_from_dict(config_data.get("harness", {}))

        load_recursion_pivot_config_from_dict(config_data.get("recursion_pivot", {}))
        load_quality_gate_config_from_dict(config_data.get("quality_gate", {}))
        load_loop_detection_config_from_dict(config_data.get("loop_detection", {}))

        # Load question generation config
        load_question_generation_config_from_dict(config_data.get("question_generation", {}))

        # Load Phase B configs
        load_todos_config_from_dict(config_data.get("todos", {}))
        routing_data = config_data.get("routing", {})
        if isinstance(routing_data, dict):
            if "stages" in routing_data:
                load_routing_config_from_dict(routing_data)
            else:
                # Backward-compatible shorthand: stage keys declared directly under routing.
                # `timeouts` is a structured sibling — preserve it through the shorthand path.
                fallback = routing_data.get("fallback")
                timeouts = routing_data.get("timeouts")
                reserved = {"fallback", "timeouts"}
                stages = {k: v for k, v in routing_data.items() if k not in reserved}
                normalized_routing: dict = {"stages": stages, "fallback": fallback}
                if timeouts is not None:
                    normalized_routing["timeouts"] = timeouts
                config_data["routing"] = normalized_routing
                load_routing_config_from_dict(normalized_routing)
        else:
            load_routing_config_from_dict({})
        load_planner_config_from_dict(config_data.get("planner", {}))
        load_evaluator_config_from_dict(config_data.get("evaluator", {}))
        load_sprint_contracts_config_from_dict(config_data.get("sprint_contracts", {}))
        load_handoffs_config_from_dict(config_data.get("handoffs", {}))
        load_hooks_config_from_dict(config_data.get("hooks", {}))
        load_retry_config_from_dict(config_data.get("retry", {}))
        load_resume_config_from_dict(config_data.get("resume", {}))
        load_tool_disclosure_config_from_dict(config_data.get("tool_disclosure", {}))
        load_web_search_summary_config_from_dict(config_data.get("web_search_summary", {}))
        load_scratchpad_config_from_dict(config_data.get("scratchpad", {}))
        load_task_memory_config_from_dict(config_data.get("task_memory", {}))
        load_memory_versioning_config_from_dict(config_data.get("memory_versioning", {}))
        load_skill_curation_config_from_dict(config_data.get("skill_curation", {}))
        load_benchmarks_config_from_dict(config_data.get("benchmarks", {}))

        # Load checkpointer config if present
        if "checkpointer" in config_data:
            load_checkpointer_config_from_dict(config_data["checkpointer"])

        # Load extensions config separately (it's in a different file)
        extensions_config = ExtensionsConfig.from_file()
        config_data["extensions"] = extensions_config.model_dump()

        # Synthesize ModelConfig entries from user LLM endpoints and append to
        # the configured models list. The result is a single unified registry
        # that the agent runtime, /api/models, ModelRouter, and create_chat_model
        # all read from. Imported here to avoid a circular import at module load.
        from src.models.user_model_synthesis import synthesize_user_models

        user_models_as_configs = synthesize_user_models(extensions_config)
        existing_models = list(config_data.get("models") or [])
        # User models go first so they become the default (models[0]) when
        # config.yaml does not declare any model.
        config_data["models"] = [
            m.model_dump() for m in user_models_as_configs
        ] + existing_models

        result = cls.model_validate(config_data)
        return result

    @classmethod
    def resolve_env_variables(cls, config: Any) -> Any:
        """Recursively resolve environment variables in the config.

        Environment variables are resolved using the `os.getenv` function. Example: $OPENAI_API_KEY

        Args:
            config: The config to resolve environment variables in.

        Returns:
            The config with environment variables resolved.
        """
        if isinstance(config, str):
            if config.startswith("$"):
                env_value = os.getenv(config[1:])
                if env_value is None:
                    raise ValueError(f"Environment variable {config[1:]} not found for config value {config}")
                return env_value
            return config
        elif isinstance(config, dict):
            return {k: cls.resolve_env_variables(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [cls.resolve_env_variables(item) for item in config]
        return config

    def get_model_config(self, name: str) -> ModelConfig | None:
        """Get the model config by name.

        Args:
            name: The name of the model to get the config for.

        Returns:
            The model config if found, otherwise None.
        """
        # Fast-path exact lookup, then case-insensitive, then soft-match by
        # underlying `model:` id (for legacy thread state that stored a bare
        # model id like "qwen2.5:7b" before namespacing as "endpoint/qwen2.5:7b").
        model = next((model for model in self.models if model.name == name), None)
        if model is not None:
            return model
        lowered = name.lower()
        model = next((model for model in self.models if model.name.lower() == lowered), None)
        if model is not None:
            return model
        # Soft-match: bare id only — never match if caller already supplied a
        # namespaced "endpoint/model" form.
        if "/" not in name:
            model = next((model for model in self.models if model.model == name), None)
            if model is not None:
                return model
            model = next((model for model in self.models if model.model.lower() == lowered), None)
            if model is not None:
                return model
        return None

    def get_tool_config(self, name: str) -> ToolConfig | None:
        """Get the tool config by name.

        Args:
            name: The name of the tool to get the config for.

        Returns:
            The tool config if found, otherwise None.
        """
        return next((tool for tool in self.tools if tool.name == name), None)

    def get_tool_group_config(self, name: str) -> ToolGroupConfig | None:
        """Get the tool group config by name.

        Args:
            name: The name of the tool group to get the config for.

        Returns:
            The tool group config if found, otherwise None.
        """
        return next((group for group in self.tool_groups if group.name == name), None)


_app_config: AppConfig | None = None
_extensions_mtime_at_load: float | None = None


def _current_extensions_mtime() -> float | None:
    # Lazy import keeps app_config free of cycles at module load.
    from src.models.user_model_synthesis import extensions_config_mtime

    return extensions_config_mtime()


def get_app_config() -> AppConfig:
    """Get the CapyHome config instance.

    Returns a cached singleton instance. Use `reload_app_config()` to reload
    from file, or `reset_app_config()` to clear the cache.

    If `extensions_config.json` has been modified since the cached config was
    loaded, the cache is invalidated so user-added LLM endpoints surface
    without requiring a process restart (relevant when the gateway writes new
    endpoints but the LangGraph server holds a separate cached singleton).
    """
    global _app_config, _extensions_mtime_at_load
    if _app_config is not None:
        current_mtime = _current_extensions_mtime()
        if current_mtime is not None and current_mtime != _extensions_mtime_at_load:
            _app_config = None
    if _app_config is None:
        _app_config = AppConfig.from_file()
        _extensions_mtime_at_load = _current_extensions_mtime()
    return _app_config


def reload_app_config(config_path: str | None = None) -> AppConfig:
    """Reload the config from file and update the cached instance.

    This is useful when the config file has been modified and you want
    to pick up the changes without restarting the application.

    Args:
        config_path: Optional path to config file. If not provided,
                     uses the default resolution strategy.

    Returns:
        The newly loaded AppConfig instance.
    """
    global _app_config, _extensions_mtime_at_load
    _app_config = AppConfig.from_file(config_path)
    _extensions_mtime_at_load = _current_extensions_mtime()
    return _app_config


def reset_app_config() -> None:
    """Reset the cached config instance.

    This clears the singleton cache, causing the next call to
    `get_app_config()` to reload from file. Useful for testing
    or when switching between different configurations.
    """
    global _app_config, _extensions_mtime_at_load
    _app_config = None
    _extensions_mtime_at_load = None


def set_app_config(config: AppConfig) -> None:
    """Set a custom config instance.

    This allows injecting a custom or mock config for testing purposes.

    Args:
        config: The AppConfig instance to use.
    """
    global _app_config
    _app_config = config
