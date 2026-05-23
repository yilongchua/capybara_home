# Approvals: Impact Analysis (pre-removal snapshot)

This is the analysis that was performed before deleting `/workspace/approvals`.
It captures the state of the codebase at the time of the decision so future
contributors can understand why the UI was removed but the backend kept.

## The approvals system surfaces three distinct flows

1. **Vault queue ingestion approvals** — `approval_kind:
   "knowledge_vault_queue_ingest"`. Was the human-in-the-loop gate between
   websearch results landing in the vault queue and being ingested.

   **State at removal: already dead.**
   - `ControlPlaneService.ensure_vault_queue_ingest_approval()` in
     `backend/src/control_plane/service.py` is a no-op (returns `None`).
   - `ControlPlaneService._auto_resolve_vault_queue_approvals()` still exists
     but matches nothing because nothing creates these anymore.
   - Test `test_vault_queue_no_longer_creates_approval` in
     `backend/tests/test_control_plane_api.py` (~L317-L351) enforces this.
   - Websearch ingestion is now handled directly inside the knowledge vault
     flow (`manager.enqueue_search_results()` → `start_vault_ingest_job()`,
     no approval hop).

2. **Pipeline run gating** — generic `ApprovalRequest` created in
   `ControlPlaneService.create_run()` when `requires_approval=True` on the
   template (or `SchedulerJobConfig.requires_approval` on a scheduled job).
   Run sits in `pending_approval` until `POST /api/approvals/{id}/resolve`.

   **State at removal: infrastructure present, no active producer.**
   No template in the repo sets `requires_approval=True` today, but the code
   path is wired end-to-end (creation, resolve, auto-expire).

3. **Self-improver proposal approvals** — `/api/approvals/proposals` +
   `/api/approvals/proposals/{run_id}/{proposal_id}/resolve`. The skill
   curation review queue.

   **State at removal: infrastructure present, queue currently empty in
   typical use.**

## Why the UI is dead even though the backend isn't

The page `/workspace/approvals` consumed `useApprovals` and rendered each
pending item via `ApprovalCard`. The card had a **hardcoded title**:

```ts
const displayTitle = `Websearch→KV Ingest${itemCount != null ? ` - ${itemCount} items` : ""}`;
```

— i.e. the card was specifically designed for the now-dead vault-queue
ingestion approvals (flow #1). Its `metadata` reads
(`queued_item_count`, `sample_titles`) only match that approval kind.

Flow #2 (pipeline gating) and flow #3 (proposal approvals) would have
rendered as a generic "Websearch→KV Ingest" card with no meaningful content
even if they had producers — and proposal approvals are loaded by the page
via `useProposalApprovals` but **never rendered** (the JSX iterates only
`pendingApprovals`, not `proposals`). So the page already failed to surface
two of the three approval kinds.

In short: removing the page removes nothing that any current code path was
relying on. Future flows that need a human-in-the-loop UI should build a
purpose-built surface (and likely live inside the feature that needs them —
e.g. inside the Scheduled Pipeline page — not in a generic approvals tab).

## Frontend surface (pre-removal)

| Item | File | Status |
|------|------|--------|
| Page | `frontend/src/app/workspace/approvals/page.tsx` | DEAD |
| Card component | `frontend/src/components/workspace/approvals/approval-card.tsx` | DEAD (only used by page) |
| Sidebar item | `frontend/src/components/workspace/workspace-nav-chat-list.tsx` (the `<SidebarMenuItem>` with `CheckCheckIcon`) | DEAD |
| Breadcrumb mapping | `frontend/src/components/workspace/workspace-container.tsx` `nameOfSegment()` | DEAD |
| i18n keys `sidebar.approvals`, `breadcrumb.approvals`, `pages.approvals` | `frontend/src/core/i18n/locales/en-US.ts` + matching `types.ts` | DEAD |
| `useApprovals`, `useResolveApproval`, `useProposalApprovals`, `useResolveProposalApproval` | `frontend/src/core/control-plane/hooks.ts` | KEEP — exported, may be reused by a future producer-specific UI |
| `listApprovals`, `resolveApproval`, `listProposalApprovals`, `resolveProposalApproval` | `frontend/src/core/control-plane/api.ts` | KEEP — see above |
| `ApprovalRequest`, `ResolveApprovalRequest`, `ProposalApprovalItem` types | `frontend/src/core/control-plane/types.ts` | KEEP — referenced by hooks/api |
| Workspace-refresh `"approvals"` domain | `frontend/src/core/workspace-refresh/index.ts` | KEEP — published from several hooks |

## Backend surface (untouched by this change)

| Item | File | Status |
|------|------|--------|
| Routes `GET /api/approvals`, `POST /api/approvals/{id}/resolve`, `GET /api/approvals/proposals`, `POST /api/approvals/proposals/{run_id}/{proposal_id}/resolve` | `backend/src/gateway/routers/approvals.py` | KEEP |
| `ApprovalsService` (list/resolve/expire) | `backend/src/control_plane/services/approvals.py` | KEEP |
| `ApprovalRequest` model + `pending_approval` pipeline status | `backend/src/control_plane/models.py` | KEEP |
| Approval creation in `create_run()` and the `start_run()` gate | `backend/src/control_plane/service.py` | KEEP |
| `_expire_approvals()` periodic sweep | `backend/src/control_plane/services/approvals.py` | KEEP |
| Tests under `backend/tests/test_control_plane_api.py` | — | KEEP |
| Dead-but-still-present `ensure_vault_queue_ingest_approval()` + `_auto_resolve_vault_queue_approvals()` no-ops | `backend/src/control_plane/service.py` | KEEP for now, see followups |

## Cross-feature coupling notes

- **Plan-mode approval gate** (`plan_execution_gate_middleware.py`) is *not*
  this system — it uses agent-side clarification + `goto=END`, not
  `ApprovalRequest`.
- **Dreamy `awaiting_approval` phase** is a workflow phase label inside the
  dreamy middleware, *not* a backend approval row.
- No LangGraph `interrupt()` is wired into the approval flow.
- Vault ingestion no longer routes through approvals; see the deleted
  `backend/src/security/search_masking.py` and `search_privacy_middleware.py`
  for context on the prior pipeline.
