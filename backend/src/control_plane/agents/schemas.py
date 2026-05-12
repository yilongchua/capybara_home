from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.control_plane.models import PipelineRun, PipelineStepDefinition, PipelineStepRun, utcnow


@dataclass(frozen=True, slots=True)
class AgentExecutionContext:
    run_id: str
    run: PipelineRun
    step: PipelineStepRun
    definition: PipelineStepDefinition


class AgentExecutionReport(BaseModel):
    """Shared run/report envelope for step-level agent execution."""

    id: str
    run_id: str
    step_id: str
    step_kind: str
    run_template_name: str
    run_status: str
    run_created_at: datetime
    run_updated_at: datetime
    status: Literal["completed", "failed", "skipped"]
    note: str | None = None
    error: str | None = None
    resolved_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)
    details: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    output: dict[str, Any]
    report: AgentExecutionReport


class AgentExecutionError(RuntimeError):
    def __init__(self, message: str, *, report: AgentExecutionReport) -> None:
        super().__init__(message)
        self.report = report


class KnowledgeVaultExecutionProfile(BaseModel):
    mode: Literal["continuous", "autoresearch"]
    source: str
    topic_input_key: str
    stop_if_inactive: bool
    activity_window_hours: int
    model_config = ConfigDict(extra="allow")
