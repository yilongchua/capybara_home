"""Unified extensions configuration for MCP servers and skills."""

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class McpOAuthConfig(BaseModel):
    """OAuth configuration for an MCP server (HTTP/SSE transports)."""

    enabled: bool = Field(default=True, description="Whether OAuth token injection is enabled")
    token_url: str = Field(description="OAuth token endpoint URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(
        default="client_credentials",
        description="OAuth grant type",
    )
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token (for refresh_token grant)")
    scope: str | None = Field(default=None, description="OAuth scope")
    audience: str | None = Field(default=None, description="OAuth audience (provider-specific)")
    token_field: str = Field(default="access_token", description="Field name containing access token in token response")
    token_type_field: str = Field(default="token_type", description="Field name containing token type in token response")
    expires_in_field: str = Field(default="expires_in", description="Field name containing expiry (seconds) in token response")
    default_token_type: str = Field(default="Bearer", description="Default token type when missing in token response")
    refresh_skew_seconds: int = Field(default=60, description="Refresh token this many seconds before expiry")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="Additional form params sent to token endpoint")
    model_config = ConfigDict(extra="allow")


class McpServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    type: str = Field(default="stdio", description="Transport type: 'stdio', 'sse', or 'http'")
    command: str | None = Field(default=None, description="Command to execute to start the MCP server (for stdio type)")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to the command (for stdio type)")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for the MCP server")
    url: str | None = Field(default=None, description="URL of the MCP server (for sse or http type)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers to send (for sse or http type)")
    oauth: McpOAuthConfig | None = Field(default=None, description="OAuth configuration (for sse or http type)")
    description: str = Field(default="", description="Human-readable description of what this MCP server provides")
    excluded_tools: list[str] = Field(default_factory=list, description="Tool names to exclude from this server's tool list")
    model_config = ConfigDict(extra="allow")


class SkillStateConfig(BaseModel):
    """Configuration for a single skill's state."""

    enabled: bool = Field(default=True, description="Whether this skill is enabled")


class CommunityToolStateConfig(BaseModel):
    """Enabled/disabled override for a community tool."""

    enabled: bool = Field(default=True, description="Whether this community tool is enabled")


class UserLlmEndpointConfig(BaseModel):
    """A single user-added LLM endpoint."""

    enabled: bool = Field(default=True, description="Whether this endpoint is active")
    provider: str = Field(..., description="Provider type: 'ollama', 'lm-studio', or 'custom'")
    display_name: str = Field(..., description="Human-readable name for this endpoint")
    base_url: str = Field(..., description="Base URL of the OpenAI-compatible endpoint")
    api_key: str = Field(default="", description="Optional API key")
    models: list[str] = Field(default_factory=list, description="Discovered model IDs")
    default_model: str = Field(default="", description="Default model to use")
    supports_thinking: bool = Field(default=False, description="Whether models on this endpoint support thinking")
    supports_vision: bool = Field(default=False, description="Whether models on this endpoint support vision")


class ExtensionsConfig(BaseModel):
    """Unified configuration for MCP servers and skills."""

    mcp_servers: dict[str, McpServerConfig] = Field(
        default_factory=dict,
        description="Map of MCP server name to configuration",
        alias="mcpServers",
    )
    skills: dict[str, SkillStateConfig] = Field(
        default_factory=dict,
        description="Map of skill name to state configuration",
    )
    community_tools: dict[str, CommunityToolStateConfig] = Field(
        default_factory=dict,
        description="Map of community tool name to enabled/disabled override",
        alias="communityTools",
    )
    user_models: dict[str, UserLlmEndpointConfig] = Field(
        default_factory=dict,
        description="Map of user-added LLM endpoint name to configuration",
        alias="userModels",
    )
    user_embedding_models: dict[str, UserLlmEndpointConfig] = Field(
        default_factory=dict,
        description="Map of user-added embedding-model endpoint name to configuration",
        alias="userEmbeddingModels",
    )
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        """Resolve the extensions config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `CAPYBARA_HOME_EXTENSIONS_CONFIG_PATH` environment variable, use it.
        3. Otherwise, check for `extensions_config.json` in the current directory, then in the parent directory.
        4. For backward compatibility, also check for `mcp_config.json` if `extensions_config.json` is not found.
        5. If not found, return None (extensions are optional).

        Args:
            config_path: Optional path to extensions config file.

        Returns:
            Path to the extensions config file if found, otherwise None.
        """
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("CAPYBARA_HOME_EXTENSIONS_CONFIG_PATH"):
            path = Path(os.getenv("CAPYBARA_HOME_EXTENSIONS_CONFIG_PATH"))
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by environment variable `CAPYBARA_HOME_EXTENSIONS_CONFIG_PATH` not found at {path}")
            return path
        else:
            # Check if the extensions_config.json is in the current directory
            path = Path(os.getcwd()) / "extensions_config.json"
            if path.exists():
                return path

            # Check if the extensions_config.json is in the parent directory of CWD
            path = Path(os.getcwd()).parent / "extensions_config.json"
            if path.exists():
                return path

            # Backward compatibility: check for mcp_config.json
            path = Path(os.getcwd()) / "mcp_config.json"
            if path.exists():
                return path

            path = Path(os.getcwd()).parent / "mcp_config.json"
            if path.exists():
                return path

            # Extensions are optional, so return None if not found
            return None

    @classmethod
    def from_file(cls, config_path: str | None = None) -> "ExtensionsConfig":
        """Load extensions config from JSON file.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the extensions config file.

        Returns:
            ExtensionsConfig: The loaded config, or empty config if file not found.
        """
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
            # Return empty config if extensions config file is not found
            return cls(mcp_servers={}, skills={})

        try:
            with open(resolved_path, encoding="utf-8") as f:
                config_data = json.load(f)
            cls.resolve_env_variables(config_data)
            return cls.model_validate(config_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Extensions config file at {resolved_path} is not valid JSON: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to load extensions config from {resolved_path}: {e}") from e

    @classmethod
    def resolve_env_variables(cls, config: dict[str, Any]) -> dict[str, Any]:
        """Recursively resolve environment variables in the config.

        Environment variables are resolved using the `os.getenv` function. Example: $OPENAI_API_KEY

        Args:
            config: The config to resolve environment variables in.

        Returns:
            The config with environment variables resolved.
        """
        for key, value in config.items():
            if isinstance(value, str):
                if value.startswith("$"):
                    env_value = os.getenv(value[1:])
                    if env_value is None:
                        # Unresolved placeholder — store empty string so downstream
                        # consumers (e.g. MCP servers) don't receive the literal "$VAR"
                        # token as an actual environment value.
                        config[key] = ""
                    else:
                        config[key] = env_value
                else:
                    config[key] = value
            elif isinstance(value, dict):
                config[key] = cls.resolve_env_variables(value)
            elif isinstance(value, list):
                config[key] = [cls.resolve_env_variables(item) if isinstance(item, dict) else item for item in value]
        return config

    def get_enabled_mcp_servers(self) -> dict[str, McpServerConfig]:
        """Get only the enabled MCP servers.

        Returns:
            Dictionary of enabled MCP servers.
        """
        return {name: config for name, config in self.mcp_servers.items() if config.enabled}

    def is_skill_enabled(self, skill_name: str, skill_category: str) -> bool:
        """Check if a skill is enabled.

        Args:
            skill_name: Name of the skill
            skill_category: Category of the skill

        Returns:
            True if enabled, False otherwise
        """
        skill_config = self.skills.get(skill_name)
        if skill_config is None:
            # Default to enable for public & custom skill
            return skill_category in ("public", "custom")
        return skill_config.enabled


_extensions_config: ExtensionsConfig | None = None
_extensions_mtime_at_load: float | None = None


def _current_extensions_mtime() -> float | None:
    """Best-effort mtime of the active extensions_config.json, or None if absent."""
    try:
        path = ExtensionsConfig.resolve_config_path()
    except FileNotFoundError:
        return None
    if path is None:
        return None
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def get_extensions_config() -> ExtensionsConfig:
    """Get the extensions config instance.

    Returns a cached singleton instance. The cache is invalidated when the
    on-disk extensions_config.json mtime changes, so endpoints written by any
    path (onboarding PUT, first-time wizard, manual edit, separate process)
    surface without a Gateway restart.
    """
    global _extensions_config, _extensions_mtime_at_load
    if _extensions_config is not None:
        current_mtime = _current_extensions_mtime()
        if current_mtime is not None and current_mtime != _extensions_mtime_at_load:
            _extensions_config = None
    if _extensions_config is None:
        _extensions_config = ExtensionsConfig.from_file()
        _extensions_mtime_at_load = _current_extensions_mtime()
    return _extensions_config


def reload_extensions_config(config_path: str | None = None) -> ExtensionsConfig:
    """Reload the extensions config from file and update the cached instance.

    This is useful when the config file has been modified and you want
    to pick up the changes without restarting the application.

    Args:
        config_path: Optional path to extensions config file. If not provided,
                     uses the default resolution strategy.

    Returns:
        The newly loaded ExtensionsConfig instance.
    """
    global _extensions_config, _extensions_mtime_at_load
    _extensions_config = ExtensionsConfig.from_file(config_path)
    _extensions_mtime_at_load = _current_extensions_mtime()
    return _extensions_config


def reset_extensions_config() -> None:
    """Reset the cached extensions config instance.

    This clears the singleton cache, causing the next call to
    `get_extensions_config()` to reload from file. Useful for testing
    or when switching between different configurations.
    """
    global _extensions_config, _extensions_mtime_at_load
    _extensions_config = None
    _extensions_mtime_at_load = None


def set_extensions_config(config: ExtensionsConfig) -> None:
    """Set a custom extensions config instance.

    This allows injecting a custom or mock config for testing purposes.

    Args:
        config: The ExtensionsConfig instance to use.
    """
    global _extensions_config
    _extensions_config = config
