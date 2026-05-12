"""Tests for stage model router."""

from src.config.app_config import AppConfig
from src.config.model_config import ModelConfig
from src.config.routing_config import RoutingConfig
from src.config.sandbox_config import SandboxConfig
from src.models.router import ModelRouter


def _app_config() -> AppConfig:
    cfg = AppConfig(
        models=[
            ModelConfig(
                name="primary-120b",
                display_name="Primary",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="primary-120b",
                supports_thinking=True,
            ),
            ModelConfig(
                name="helper-local",
                display_name="Helper",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="helper-local",
                supports_thinking=False,
            ),
        ],
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
    )
    cfg.routing = RoutingConfig(
        stages={
            "planner": "primary-120b",
            "memory_extractor": "helper-local",
            "subagent_triage": "helper-local",
        },
        fallback="primary-120b",
    )
    return cfg


def test_generator_prefers_requested_model_when_valid():
    router = ModelRouter(app_config=_app_config())
    assert router.resolve("generator", requested_model="helper-local") == "helper-local"


def test_stage_mapping_uses_routing_table():
    router = ModelRouter(app_config=_app_config())
    assert router.resolve("memory_extractor", requested_model="primary-120b") == "helper-local"


def test_fallback_to_primary_when_stage_missing():
    router = ModelRouter(app_config=_app_config())
    assert router.resolve("unknown_stage", requested_model=None) == "primary-120b"


def test_endpoint_label_helper_when_stage_differs_from_generator():
    router = ModelRouter(app_config=_app_config())
    assert router.endpoint_label("subagent_triage", requested_model="primary-120b") == "helper"
