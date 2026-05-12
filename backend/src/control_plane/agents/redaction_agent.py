from __future__ import annotations

from src.control_plane.agents.base import BaseControlPlaneAgent
from src.control_plane.agents.schemas import AgentExecutionContext, AgentExecutionResult


class RedactionAgent(BaseControlPlaneAgent):
    agent_id = "redaction"

    @classmethod
    def supported_kinds(cls) -> set[str]:
        return {"redact_text"}

    def execute(self, context: AgentExecutionContext) -> AgentExecutionResult:
        text = str(
            context.definition.config.get("text")
            or context.run.inputs.get(context.definition.config.get("input_key", "text"), "")
        )
        redacted = self._service._redaction.redact_text(text)
        artifact = self._service._write_text_artifact(
            context.run_id,
            f"{context.step.step_id}-redacted.txt",
            redacted,
        )
        self._service._append_artifact(context.run_id, artifact)
        return self._result(
            context,
            output={"redacted_text": redacted, "artifact_path": artifact},
            details={
                "graph": ["load_input", "redact_text", "write_artifact"],
                "raw_length": len(text),
                "redacted_length": len(redacted),
            },
        )
