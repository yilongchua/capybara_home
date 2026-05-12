"""Tests for RoutingTimeoutsConfig and its config.yaml loader path."""

from __future__ import annotations

from src.config.routing_config import (
    RoutingConfig,
    RoutingTimeoutsConfig,
    get_routing_config,
    load_routing_config_from_dict,
)


def test_routing_timeouts_defaults():
    cfg = RoutingTimeoutsConfig()
    assert cfg.enabled is True
    assert cfg.default == 300
    # Sanity-check key stage defaults are present and synthesis gets extra headroom.
    assert cfg.for_stage("planner") == 300
    assert cfg.for_stage("generator") == 300
    assert cfg.for_stage("synthesis") == 1200
    assert cfg.for_stage("missing") == cfg.default


def test_routing_config_accepts_nested_timeouts_block():
    cfg = RoutingConfig(
        stages={"planner": "qwen3.6"},
        timeouts={"default": 240, "stages": {"planner": 60}},
    )
    assert cfg.stages == {"planner": "qwen3.6"}
    assert cfg.timeouts.for_stage("planner") == 60
    assert cfg.timeouts.default == 240


def test_load_routing_config_with_timeouts():
    payload = {
        "stages": {"planner": "qwen3.6"},
        "fallback": None,
        "timeouts": {
            "default": 200,
            "stages": {"planner": 75},
            "tools": {"web_search": 45},
        },
    }
    load_routing_config_from_dict(payload)
    cfg = get_routing_config()
    assert cfg.timeouts.for_stage("planner") == 75
    assert cfg.timeouts.for_stage("missing") == 200
    assert cfg.timeouts.for_tool("web_search") == 45
