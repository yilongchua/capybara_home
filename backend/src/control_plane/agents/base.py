from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.control_plane.agents.schemas import (
    AgentExecutionContext,
    AgentExecutionReport,
    AgentExecutionResult,
)
from src.control_plane.models import utcnow

if TYPE_CHECKING:
    from src.control_plane.service import ControlPlaneService


class BaseControlPlaneAgent:
    agent_id = "base"

    def __init__(self, service: ControlPlaneService) -> None:
        self._service = service

    def supports(self, kind: str) -> bool:
        return kind in self.supported_kinds()

    @classmethod
    def supported_kinds(cls) -> set[str]:
        return set()

    def execute(self, context: AgentExecutionContext) -> AgentExecutionResult:
        raise NotImplementedError

    def _report(
        self,
        context: AgentExecutionContext,
        *,
        status: str,
        note: str | None = None,
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AgentExecutionReport:
        return AgentExecutionReport(
            id=f"{context.run_id}:{context.step.step_id}",
            run_id=context.run_id,
            step_id=context.step.step_id,
            step_kind=context.definition.kind,
            run_template_name=context.run.template_name,
            run_status=context.run.status,
            run_created_at=context.run.created_at,
            run_updated_at=context.run.updated_at,
            status=status,
            note=note,
            error=error,
            resolved_at=None,
            updated_at=utcnow(),
            details={"agent_id": self.agent_id, **(details or {})},
        )

    def _result(
        self,
        context: AgentExecutionContext,
        *,
        output: dict[str, Any],
        status: str = "completed",
        note: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AgentExecutionResult:
        report = self._report(context, status=status, note=note, details=details)
        return AgentExecutionResult(output={**output, "agent_report": report.model_dump(mode="json")}, report=report)

    def build_failure_report(
        self,
        context: AgentExecutionContext,
        *,
        error: str,
        note: str,
    ) -> AgentExecutionReport:
        return self._report(context, status="failed", error=error, note=note)
