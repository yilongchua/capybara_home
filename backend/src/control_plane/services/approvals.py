"""Approval request sub-service.

Owns approval listing, resolution, and expiry. Cross-domain operations
(audit logging, vault manager, run lifecycle) are routed back through the
facade ``ControlPlaneService`` so semantics match the original monolith.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.config import get_app_config
from src.control_plane.models import ApprovalRequest, PipelineRun, utcnow
from src.control_plane.store import ControlPlaneStore

if TYPE_CHECKING:
    from src.control_plane.service import ControlPlaneService

logger = logging.getLogger(__name__)


class ApprovalsService:
    def __init__(self, store: ControlPlaneStore, control_plane: ControlPlaneService) -> None:
        self._store = store
        self._cps = control_plane

    def list_approvals(self) -> list[ApprovalRequest]:
        self._expire_approvals()
        snapshot = self._store.read()
        return sorted(
            snapshot.approvals.values(),
            key=lambda item: (item.status == "pending", item.requested_at),
            reverse=True,
        )

    def resolve_approval(
        self,
        approval_id: str,
        *,
        approve: bool,
        note: str | None = None,
        auto_start: bool = True,
    ) -> PipelineRun:
        config = get_app_config().approvals
        if (not approve) and config.require_resolution_note_on_reject and not note:
            raise ValueError("A resolution note is required when rejecting this approval.")

        now = utcnow()
        approval_metadata: dict[str, Any] = {}

        def mutate(snapshot):
            approval = snapshot.approvals.get(approval_id)
            if approval is None:
                raise ValueError(f"Unknown approval request: {approval_id}")
            if approval.status != "pending":
                raise ValueError(f"Approval is already {approval.status}.")
            approval_metadata.update(approval.metadata)

            approval.status = "approved" if approve else "rejected"
            approval.resolved_at = now
            approval.resolution_note = note

            run = snapshot.runs[approval.pipeline_run_id]
            run.status = "approved" if approve else "rejected"
            run.updated_at = now
            if not approve and note:
                run.alerts.append(note)
            return run

        run = self._store.mutate(mutate)
        self._cps._append_audit_event(
            "approval_resolved",
            f"Approval {approval_id} {'approved' if approve else 'rejected'}.",
            metadata={"approval_id": approval_id, "run_id": run.id, "approved": approve},
        )
        if (not approve) and str(approval_metadata.get("approval_kind") or "") == "knowledge_vault_queue_ingest":
            manager = self._cps._default_vault_manager()
            cleared_count = manager.clear_queued_search_results(reason="rejected_by_user")
            self._cps._append_audit_event(
                "vault_queue_cleared_on_reject",
                f"Cleared {cleared_count} queued vault item(s) after rejection.",
                metadata={"approval_id": approval_id, "run_id": run.id, "cleared_count": cleared_count},
            )
        if approve and auto_start:
            return self._cps.start_run(run.id)
        return run

    def _expire_approvals(self) -> None:
        config = get_app_config().approvals
        if not config.enabled:
            return

        deadline = utcnow() - timedelta(minutes=config.auto_expire_minutes)

        def expire(snapshot):
            for approval in snapshot.approvals.values():
                if approval.status != "pending":
                    continue
                if approval.requested_at <= deadline:
                    approval.status = "expired"
                    approval.resolved_at = utcnow()
                    approval.resolution_note = "Expired automatically."
                    run = snapshot.runs.get(approval.pipeline_run_id)
                    if run and run.status == "pending_approval":
                        run.status = "cancelled"
                        run.updated_at = utcnow()
                        run.alerts.append("Approval expired before execution.")

        self._store.mutate(expire)
