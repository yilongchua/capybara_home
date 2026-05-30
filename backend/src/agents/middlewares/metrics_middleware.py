"""Lightweight runtime metrics middleware."""

from __future__ import annotations

import logging
from collections import Counter
from threading import Lock
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.config.metrics_config import get_metrics_config

logger = logging.getLogger(__name__)

_METRICS_LOCK = Lock()
_COUNTERS: Counter[str] = Counter()


def _counter_key(name: str, labels: dict[str, Any]) -> str:
    ordered_labels = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    return f"{name}|{ordered_labels}"


def increment_metric(name: str, labels: dict[str, Any], value: int = 1) -> None:
    """Increment an internal counter metric.

    Metrics are advisory — a label-typing bug or corrupted counter must not
    propagate into the agent loop. Any failure is logged once and swallowed.
    """
    if value == 0:
        return
    try:
        with _METRICS_LOCK:
            _COUNTERS[_counter_key(name, labels)] += value
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("increment_metric failed for %s: %s", name, exc)


def get_metrics_snapshot() -> dict[str, int]:
    """Get a snapshot of all in-memory metrics (for tests/diagnostics)."""
    with _METRICS_LOCK:
        return dict(_COUNTERS)


def render_metrics_prometheus() -> str:
    """Render counters in Prometheus text exposition format.

    Intentionally minimal: no HELP/TYPE lines, no histograms. Gateways can serve
    this directly on a /metrics route until a dedicated exporter lands.
    """
    with _METRICS_LOCK:
        items = sorted(_COUNTERS.items())
    lines: list[str] = []
    for key, value in items:
        name, _, label_part = key.partition("|")
        metric_name = name.replace(".", "_").replace("-", "_")
        if label_part:
            quoted = ",".join(
                f'{kv.split("=", 1)[0]}="{kv.split("=", 1)[1]}"'
                for kv in label_part.split(",")
                if "=" in kv
            )
            lines.append(f"{metric_name}{{{quoted}}} {value}")
        else:
            lines.append(f"{metric_name} {value}")
    return "\n".join(lines) + ("\n" if lines else "")


def reset_metrics_snapshot() -> None:
    """Reset in-memory metrics (for tests)."""
    with _METRICS_LOCK:
        _COUNTERS.clear()


class MetricsMiddleware(AgentMiddleware[AgentState]):
    """Collect runtime counters with stage/endpoint labels."""

    @staticmethod
    def _endpoint(runtime: Runtime) -> str:
        context = getattr(runtime, "context", None) or {}
        return str(context.get("endpoint") or "primary")

    @staticmethod
    def _base_labels(runtime: Runtime) -> dict[str, Any]:
        # `thread_id` is intentionally NOT included as a counter label: every
        # distinct thread would mint a new label key for every metric × tool ×
        # endpoint combination, with no eviction. Long-running deployments
        # accumulate one bucket per thread forever (classic Prometheus
        # high-cardinality anti-pattern). If per-thread metrics are needed
        # downstream, expose them via a separate per-run scratchpad cleared in
        # `after_agent`, not as a global counter label.
        return {
            "endpoint": MetricsMiddleware._endpoint(runtime),
        }

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        if not get_metrics_config().enabled:
            return None
        increment_metric("work_agent.before_model", self._base_labels(runtime))
        return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        if not get_metrics_config().enabled:
            return None
        increment_metric("work_agent.after_model", self._base_labels(runtime))
        return None

    @override
    def wrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        if not get_metrics_config().enabled:
            return handler(request)
        labels = self._base_labels(request.runtime)
        increment_metric("work_agent.model_call.start", labels)
        result = handler(request)
        increment_metric("work_agent.model_call.end", labels)
        return result

    @override
    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        if not get_metrics_config().enabled:
            return await handler(request)
        labels = self._base_labels(request.runtime)
        increment_metric("work_agent.model_call.start", labels)
        result = await handler(request)
        increment_metric("work_agent.model_call.end", labels)
        return result

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        if not get_metrics_config().enabled:
            return handler(request)
        labels = {
            **self._base_labels(request.runtime),
            "tool": request.tool_call.get("name") or "unknown",
        }
        increment_metric("work_agent.tool_call.start", labels)
        result = handler(request)
        increment_metric("work_agent.tool_call.end", labels)
        return result

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        if not get_metrics_config().enabled:
            return await handler(request)
        labels = {
            **self._base_labels(request.runtime),
            "tool": request.tool_call.get("name") or "unknown",
        }
        increment_metric("work_agent.tool_call.start", labels)
        result = await handler(request)
        increment_metric("work_agent.tool_call.end", labels)
        return result
