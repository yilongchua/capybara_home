# Followups

Open items left behind by the Option A removal. None are urgent.

## 1. Decide the long-term fate of pipeline approval gating

The `requires_approval=True` path in
`backend/src/control_plane/service.py::create_run()` is wired but has no
template producer today.

Options:

- **Drop it.** Remove `requires_approval` from `PipelineTemplate` and
  `SchedulerJobConfig`, delete the `pending_approval` status branch, remove
  the `_expire_approvals` sweep tied to it. Cleanest but a real feature
  removal.
- **Keep it dormant.** Leave as-is. If a future producer needs gating, that
  feature must also ship a resolution UI in its own page.
- **Guard rail.** Add a unit assertion that no shipped template sets
  `requires_approval=True` so we don't silently regress while there is no
  resolution UI.

## 2. Move (or remove) self-improver proposal approvals

Endpoints under `/api/approvals/proposals/*` still work, but there is no UI
to consume them now. If/when self-improver proposal review is needed:

- Co-locate the UI with the self-improver / skill curation surface
  (skills tab? agent settings?) rather than reviving an "approvals" tab.
- The hooks `useProposalApprovals` and `useResolveProposalApproval` are
  ready to be imported anywhere from `@/core/control-plane`.

## 3. Delete the websearch→KV ingest no-ops

`backend/src/control_plane/service.py` still defines:

- `ensure_vault_queue_ingest_approval()` — always returns `None`.
- `_auto_resolve_vault_queue_approvals()` — called from `start_vault_ingest_job()`,
  matches nothing.

These are dead. Removing them is a small backend-only edit; do it next time
the file is touched, alongside any callsite cleanup. Keep the regression
test `test_vault_queue_no_longer_creates_approval` so the dead-path
guarantee survives the cleanup.

## 4. Workspace-refresh `"approvals"` domain

`frontend/src/core/workspace-refresh/index.ts` still publishes `"approvals"`
as a refresh domain, and several hooks (`useResolveApproval`,
`useApprovals`, etc.) still publish/subscribe to it. With no consumer page,
these publishes are no-ops. Safe to leave; remove only if/when the
`ApprovalsService` is removed entirely (Option C).

## 5. If/when Option C is taken

Order of operations to fully retire the system:

1. Confirm no template / scheduler job has `requires_approval=True`. Add a
   test that asserts this.
2. Migrate self-improver proposal review to a domain-specific UI (or remove
   it entirely if the workflow has been replaced).
3. Delete `backend/src/control_plane/services/approvals.py` and the
   `/api/approvals*` routes.
4. Delete `ApprovalRequest`, `pending_approval` status, and the
   `requires_approval` template field.
5. Delete the frontend hooks/api/types and the `"approvals"` refresh domain.
6. Update tests; remove `test_vault_queue_no_longer_creates_approval` and
   any approval-flow tests under `test_control_plane_api.py`.
