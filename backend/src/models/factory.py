import logging
from urllib.parse import urlparse

from langchain.chat_models import BaseChatModel

from src.config import get_app_config, get_tracing_config, is_tracing_enabled
from src.models.prompt_logging import PromptLoggingCallback
from src.reflection import resolve_class

logger = logging.getLogger(__name__)


def _normalize_base_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip().rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def _enforce_local_llm_policy(config, model_config, model_settings_from_config: dict, kwargs: dict) -> None:
    """Optionally enforce that all model calls use a local OpenAI-compatible backend."""
    policy = config.model_extra.get("local_llm_policy", {}) if config.model_extra else {}
    if not isinstance(policy, dict) or not bool(policy.get("enabled", False)):
        return

    allowed_base_urls_raw = policy.get(
        "allowed_base_urls",
        [
            "http://localhost:1234/v1",
            "http://192.168.1.22:1234/v1",
        ],
    )
    if not isinstance(allowed_base_urls_raw, list) or len(allowed_base_urls_raw) == 0:
        raise ValueError("local_llm_policy.enabled=true requires a non-empty local_llm_policy.allowed_base_urls list.")

    allowed_base_urls = {_normalize_base_url(str(url)) for url in allowed_base_urls_raw}

    if model_config.use != "langchain_openai:ChatOpenAI":
        raise ValueError(
            "local_llm_policy is enabled, but configured model provider is not OpenAI-compatible. "
            f"Expected 'langchain_openai:ChatOpenAI', got '{model_config.use}'."
        )

    base_url = kwargs.get("base_url") or kwargs.get("api_base") or model_settings_from_config.get("base_url") or model_settings_from_config.get("api_base")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError(
            "local_llm_policy is enabled, but model base URL is missing. "
            f"Allowed base URLs: {sorted(allowed_base_urls)}"
        )

    normalized_base_url = _normalize_base_url(base_url)
    if normalized_base_url not in allowed_base_urls:
        raise ValueError(
            "local_llm_policy rejected model base URL "
            f"'{base_url}'. Allowed: {sorted(allowed_base_urls)}"
        )


def create_chat_model(name: str | None = None, thinking_enabled: bool = False, **kwargs) -> BaseChatModel:
    """Create a chat model instance from the config.

    Args:
        name: The name of the model to create. If None, the first model in the config will be used.

    Returns:
        A chat model instance.
    """
    config = get_app_config()
    if name is None:
        name = config.models[0].name
    model_config = config.get_model_config(name)
    if model_config is None:
        raise ValueError(f"Model {name} not found in config") from None
    model_class = resolve_class(model_config.use, BaseChatModel)
    model_settings_from_config = model_config.model_dump(
        exclude_none=True,
        exclude={
            "use",
            "name",
            "display_name",
            "description",
            "supports_thinking",
            "supports_reasoning_effort",
            "when_thinking_enabled",
            "thinking",
            "supports_vision",
        },
    )
    # Internal markers (e.g. user-endpoint synthesis tag) must not flow to the
    # underlying chat-model constructor.
    for k in [key for key in model_settings_from_config if key.startswith("__")]:
        model_settings_from_config.pop(k, None)
    # Compute effective when_thinking_enabled by merging in the `thinking` shortcut field.
    # The `thinking` shortcut is equivalent to setting when_thinking_enabled["thinking"].
    has_thinking_settings = (model_config.when_thinking_enabled is not None) or (model_config.thinking is not None)
    effective_wte: dict = dict(model_config.when_thinking_enabled) if model_config.when_thinking_enabled else {}
    if model_config.thinking is not None:
        merged_thinking = {**(effective_wte.get("thinking") or {}), **model_config.thinking}
        effective_wte = {**effective_wte, "thinking": merged_thinking}
    if thinking_enabled and has_thinking_settings:
        if not model_config.supports_thinking:
            raise ValueError(f"Model {name} does not support thinking. Set `supports_thinking` to true in the `config.yaml` to enable thinking.") from None
        if effective_wte:
            model_settings_from_config.update(effective_wte)
    if not thinking_enabled and has_thinking_settings:
        if effective_wte.get("extra_body", {}).get("thinking", {}).get("type"):
            # OpenAI-compatible gateway: thinking is nested under extra_body
            kwargs.update({"extra_body": {"thinking": {"type": "disabled"}}})
            kwargs.update({"reasoning_effort": "minimal"})
        elif effective_wte.get("thinking", {}).get("type"):
            # Native langchain_anthropic: thinking is a direct constructor parameter
            kwargs.update({"thinking": {"type": "disabled"}})
    if not model_config.supports_reasoning_effort and "reasoning_effort" in kwargs:
        del kwargs["reasoning_effort"]

    # 'endpoints' is a Capybara-specific list of base URLs for round-robin load
    # balancing across multiple local inference backends. It is not a recognised
    # ChatOpenAI constructor kwarg; pop it here and derive base_url from it so it
    # never reaches AsyncCompletions.create().
    endpoints = model_settings_from_config.pop("endpoints", None)
    if isinstance(endpoints, list) and endpoints:
        import random as _random
        model_settings_from_config["base_url"] = _random.choice(endpoints)

    _enforce_local_llm_policy(config, model_config, model_settings_from_config, kwargs)

    # Merge kwargs on top of model_settings_from_config so that caller-provided
    # values (e.g. base_url) take precedence over the config dump, avoiding
    # "multiple values for keyword argument" errors.
    merged = {**model_settings_from_config, **kwargs}
    model_instance = model_class(**merged)

    if thinking_enabled and model_config.supports_thinking:
        try:
            from src.agents.thinking_stream import ThinkingStreamCallback

            existing_callbacks = list(model_instance.callbacks or [])
            model_instance.callbacks = [*existing_callbacks, ThinkingStreamCallback()]
        except Exception as e:
            logger.debug("Could not attach ThinkingStreamCallback: %s", e)

    try:
        existing_callbacks = list(model_instance.callbacks or [])
        model_instance.callbacks = [*existing_callbacks, PromptLoggingCallback()]
    except Exception as e:
        logger.debug("Could not attach PromptLoggingCallback: %s", e)

    if is_tracing_enabled():
        try:
            from langchain_core.tracers.langchain import LangChainTracer

            tracing_config = get_tracing_config()
            tracer = LangChainTracer(
                project_name=tracing_config.project,
            )
            existing_callbacks = model_instance.callbacks or []
            model_instance.callbacks = [*existing_callbacks, tracer]
            logger.debug(f"LangSmith tracing attached to model '{name}' (project='{tracing_config.project}')")
        except Exception as e:
            logger.warning(f"Failed to attach LangSmith tracing to model '{name}': {e}")
    return model_instance
