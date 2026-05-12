"""Tests for web_search timeout resolution and warning logic (Finding #2 regression guard).

Verifies that:
- HTTP timeout (effective_timeout_s) and routing timeout (routing_timeout_s) serve
  different roles and need not be equal.
- A warning fires only when HTTP timeout > routing timeout (the genuinely broken case).
- No warning when HTTP timeout <= routing timeout.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# _resolve_timeout_seconds is a pure function — import it directly.
from src.community.web_search.tools import _resolve_timeout_seconds


def _mock_routing(tool_timeout_s: int):
    """Return a mock routing config whose web_search tool timeout is `tool_timeout_s`."""
    config = MagicMock()
    config.timeouts.for_tool.return_value = tool_timeout_s
    return config


class TestResolveTimeoutSeconds:
    def test_defaults_to_routing_timeout_when_no_overrides(self):
        with patch("src.community.web_search.tools.get_routing_config", return_value=_mock_routing(45)):
            effective, routing, source = _resolve_timeout_seconds({}, None)
        assert effective == 45.0
        assert routing == 45
        assert source == "routing.timeouts.tools.web_search"

    def test_backend_timeout_overrides_routing(self):
        with patch("src.community.web_search.tools.get_routing_config", return_value=_mock_routing(45)):
            effective, routing, source = _resolve_timeout_seconds({}, 40.0)
        assert effective == 40.0
        assert routing == 45
        assert source == "tool_backends.websearch.timeout_seconds"

    def test_tool_extra_overrides_backend(self):
        with patch("src.community.web_search.tools.get_routing_config", return_value=_mock_routing(45)):
            effective, routing, source = _resolve_timeout_seconds({"timeout_seconds": 35}, 40.0)
        assert effective == 35.0
        assert source == "tools.web_search.timeout_seconds"


class TestWarningBehavior:
    def test_no_warning_when_http_timeout_less_than_routing(self, caplog):
        """HTTP 40s < routing 45s — valid configuration, no warning."""
        with patch("src.community.web_search.tools.get_routing_config", return_value=_mock_routing(45)):
            import logging
            with caplog.at_level(logging.WARNING, logger="src.community.web_search.tools"):
                _resolve_timeout_seconds({}, 40.0)
        assert not any("exceeds" in r.message for r in caplog.records)

    def test_no_warning_when_http_timeout_equals_routing(self, caplog):
        """HTTP 45s == routing 45s — equal is fine, no warning."""
        with patch("src.community.web_search.tools.get_routing_config", return_value=_mock_routing(45)):
            import logging
            with caplog.at_level(logging.WARNING, logger="src.community.web_search.tools"):
                _resolve_timeout_seconds({}, 45.0)
        assert not any("exceeds" in r.message for r in caplog.records)

    def test_warning_when_http_timeout_exceeds_routing(self, caplog):
        """HTTP 60s > routing 45s — HTTP client can never fire before middleware cancels."""
        with patch("src.community.web_search.tools.get_routing_config", return_value=_mock_routing(45)):
            import logging
            with caplog.at_level(logging.WARNING, logger="src.community.web_search.tools"):
                _resolve_timeout_seconds({}, 60.0)
        assert any("exceeds routing tool timeout" in r.message for r in caplog.records)

    def test_warning_message_names_source(self, caplog):
        """Warning message includes the config source so operators know where to fix."""
        with patch("src.community.web_search.tools.get_routing_config", return_value=_mock_routing(45)):
            import logging
            with caplog.at_level(logging.WARNING, logger="src.community.web_search.tools"):
                _resolve_timeout_seconds({}, 60.0)
        warning_messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("tool_backends.websearch.timeout_seconds" in m for m in warning_messages)

    def test_old_mismatch_pattern_no_longer_warns(self, caplog):
        """30s HTTP vs 45s routing was the original false-positive. Must be silent now."""
        with patch("src.community.web_search.tools.get_routing_config", return_value=_mock_routing(45)):
            import logging
            with caplog.at_level(logging.WARNING, logger="src.community.web_search.tools"):
                _resolve_timeout_seconds({}, 30.0)
        assert caplog.records == [], (
            "30s HTTP < 45s routing is valid; no warning should fire"
        )
