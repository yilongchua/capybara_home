"""Self-improver proposal review sub-service.

Owns:
- Listing self-improver proposals across pipeline runs.
- Resolving proposals (approve / reject) and applying skill-file additions.
- Skill-path resolution for proposals (with safety checks against the skills
  root) and SKILL.md markdown validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.config import get_app_config
from src.control_plane.models import PipelineRun, ProposalReview, utcnow
from src.control_plane.store import ControlPlaneStore

if TYPE_CHECKING:
    from src.control_plane.service import ControlPlaneService


class ProposalsService:
    def __init__(self, store: ControlPlaneStore, control_plane: ControlPlaneService) -> None:
        self._store = store
        self._cps = control_plane

    @staticmethod
    def proposal_review_key(run_id: str, proposal_id: str) -> str:
        return f"{run_id}:{proposal_id}"

    @staticmethod
    def proposals_for_run(run: PipelineRun) -> list[dict[str, Any]]:
        proposals: list[dict[str, Any]] = []
        for step in run.steps:
            if step.kind != "self_improver_draft":
                continue
            output = step.output if isinstance(step.output, dict) else {}
            report = output.get("report")
            if not isinstance(report, dict):
                continue
            raw = report.get("proposals")
            if not isinstance(raw, list):
                continue
            for entry in raw:
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    proposals.append(entry)
        return proposals

    def list_self_improver_proposals(self) -> list[dict[str, Any]]:
        snapshot = self._store.read()
        items: list[dict[str, Any]] = []

        for run in snapshot.runs.values():
            proposals = self.proposals_for_run(run)
            if not proposals:
                continue

            for proposal in proposals:
                proposal_id = str(proposal.get("id", "")).strip()
                if not proposal_id:
                    continue
                key = self.proposal_review_key(run.id, proposal_id)
                review = snapshot.proposal_reviews.get(key)
                items.append(
                    {
                        "id": key,
                        "run_id": run.id,
                        "proposal_id": proposal_id,
                        "run_template_name": run.template_name,
                        "run_status": run.status,
                        "run_created_at": run.created_at,
                        "run_updated_at": run.updated_at,
                        "status": review.status if review else "pending",
                        "note": review.note if review else None,
                        "error": review.error if review else None,
                        "resolved_at": review.resolved_at if review else None,
                        "updated_at": review.updated_at if review else None,
                        "applied_path": review.applied_path if review else None,
                        "proposal": proposal,
                    }
                )

        items.sort(key=lambda item: item["run_updated_at"], reverse=True)
        items.sort(key=lambda item: item["status"] != "pending")
        return items

    def find_proposal(
        self,
        *,
        run: PipelineRun,
        proposal_id: str,
    ) -> dict[str, Any]:
        for proposal in self.proposals_for_run(run):
            if str(proposal.get("id")) == proposal_id:
                return proposal
        raise ValueError(f"Proposal not found: {proposal_id}")

    def resolve_skill_path(self, proposal: dict[str, Any]) -> Path:
        raw_skill_path = proposal.get("skill_path")
        if not isinstance(raw_skill_path, str) or not raw_skill_path.strip():
            raise ValueError("Proposal is missing a valid skill_path.")

        skills_root = get_app_config().skills.get_skills_path().resolve()
        candidate = Path(raw_skill_path.strip()).expanduser()
        if not candidate.is_absolute():
            candidate = (skills_root / candidate).resolve()
        else:
            candidate = candidate.resolve()

        if skills_root not in candidate.parents:
            raise ValueError("Skill path is outside the allowed skills directory.")
        if candidate.name != "SKILL.md":
            raise ValueError("Only SKILL.md files can be modified by proposal apply.")
        if not candidate.exists() or not candidate.is_file():
            raise ValueError(f"Skill file does not exist: {candidate}")
        return candidate

    def apply_proposal(self, proposal: dict[str, Any]) -> str:
        addition = proposal.get("recommended_addition")
        if not isinstance(addition, str) or not addition.strip():
            raise ValueError("Proposal is missing recommended_addition.")
        skill_file = self.resolve_skill_path(proposal)

        original = skill_file.read_text(encoding="utf-8")
        block = addition.strip()
        if block in original:
            return str(skill_file)

        updated = f"{original.rstrip()}\n\n{block}\n"
        precheck = self._cps._validate_skill_markdown(updated)
        if not precheck.get("frontmatter_ok") or not precheck.get("parse_ok"):
            issues = precheck.get("issues") or []
            raise ValueError(f"Updated SKILL.md failed validation: {'; '.join(issues)}")

        skill_file.write_text(updated, encoding="utf-8")
        post_write = skill_file.read_text(encoding="utf-8")
        postcheck = self._cps._validate_skill_markdown(post_write)
        if not postcheck.get("frontmatter_ok") or not postcheck.get("parse_ok"):
            skill_file.write_text(original, encoding="utf-8")
            issues = postcheck.get("issues") or []
            raise ValueError(
                f"Applied SKILL.md failed validation and was rolled back: {'; '.join(issues)}"
            )
        return str(skill_file)

    def resolve_self_improver_proposal(
        self,
        *,
        run_id: str,
        proposal_id: str,
        approve: bool,
        note: str | None = None,
    ) -> dict[str, Any]:
        run = self._cps.get_run(run_id)
        proposal = self.find_proposal(run=run, proposal_id=proposal_id)
        review_key = self.proposal_review_key(run_id, proposal_id)

        snapshot = self._store.read()
        existing = snapshot.proposal_reviews.get(review_key)
        if existing is not None and existing.status in {"applied", "rejected", "apply_failed"}:
            raise ValueError(f"Proposal is already resolved with status '{existing.status}'.")

        now = utcnow()
        status = "rejected"
        error: str | None = None
        applied_path: str | None = None
        if approve:
            try:
                applied_path = self.apply_proposal(proposal)
                status = "applied"
            except Exception as exc:
                status = "apply_failed"
                error = str(exc)

        review = ProposalReview(
            run_id=run_id,
            proposal_id=proposal_id,
            status=status,
            note=note,
            error=error,
            updated_at=now,
            resolved_at=now,
            applied_path=applied_path,
        )

        def mutate(snapshot):
            snapshot.proposal_reviews[review_key] = review

        self._store.mutate(mutate)
        self._cps._append_audit_event(
            "proposal_resolved",
            f"Proposal {proposal_id} for run {run_id} resolved as {status}.",
            metadata={
                "run_id": run_id,
                "proposal_id": proposal_id,
                "status": status,
                "approved": approve,
                "applied_path": applied_path,
                "error": error,
            },
        )

        return {
            "id": review_key,
            "run_id": run_id,
            "proposal_id": proposal_id,
            "status": status,
            "note": note,
            "error": error,
            "resolved_at": now,
            "updated_at": now,
            "applied_path": applied_path,
            "proposal": proposal,
        }
