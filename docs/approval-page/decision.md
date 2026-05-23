# Decision: Option A — remove the UI, keep the backend

## What was chosen

Remove the `/workspace/approvals` page, its card component, the sidebar entry,
the breadcrumb mapping, and the three associated i18n keys. **Do not** touch
any backend route, service, model, hook, API helper, or workspace-refresh
domain.

## Why Option A and not B or C

Three options were on the table (see [removal-impact.md](removal-impact.md)
for the full breakdown):

- **A. Remove page only** — chosen.
- **B. Remove page + dead helpers** — also delete the no-op
  `ensure_vault_queue_ingest_approval` / `_auto_resolve_vault_queue_approvals`
  on the backend.
- **C. Full removal** — also delete the `ApprovalsService`, routes, model,
  hooks, types, refresh domain; migrate self-improver curation elsewhere.

Option A was preferred because:

1. **The UI is unambiguously dead.** The card was hardcoded for the
   websearch→KV ingest flow, which no longer produces approvals. The page
   also failed to render proposal approvals despite loading them, so users
   could not actually self-improver-review through this surface either.
2. **The backend is harmless to keep.** With no producers, the API serves
   empty lists and the expiry loop has nothing to expire. There is no
   performance or correctness cost to leaving it in place.
3. **Option B's "small cleanup" is genuinely small** but couples a UI-only
   change to a backend edit — easier to do as a separate followup once we
   confirm no test or callsite still references those no-ops.
4. **Option C is the right end state** but requires deciding where
   self-improver proposal review should live and ensuring no template ever
   sets `requires_approval=True`. That is a feature decision, not a cleanup.

## Why no endpoints were moved to the Scheduled Pipeline page

The user prompt asked whether the approval endpoints should be surfaced from
the Scheduled Pipeline page. The answer was **no migration required**, for
these reasons:

- The pipelines page (`frontend/src/app/workspace/pipelines/page.tsx`) renders
  **autoresearch objectives**, which do not create approvals. There is no
  `pending_approval` state to surface there today.
- The two backend approval producers that *could* light up — generic
  `requires_approval=True` pipeline templates and self-improver proposal
  curation — have no active templates / no producer wired in the current code.
- Adding a generic "Pending Approvals" panel to the pipelines page today would
  ship empty UI and create a maintenance burden for a feature that nothing
  currently produces.
- When a real producer is added, the approval-resolution UI should be
  **co-located with that producer's domain** (e.g. self-improver review next
  to the skill curation view, or pipeline-run approval as a button on the
  run row inside whatever page lists runs) — not on a separate "approvals"
  tab.

The hooks (`useApprovals`, `useResolveApproval`, etc.) and the API helpers
(`listApprovals`, `resolveApproval`, etc.) remain exported from
`@/core/control-plane`, so any future feature page can pull them in.

## Risks accepted by Option A

- **Dormant infrastructure can drift.** If someone adds a template with
  `requires_approval=True` while no resolution UI exists, the run will hang
  in `pending_approval` until `_expire_approvals()` auto-cancels it. Mitigation:
  none required for now (no current producer), but see [followups.md](followups.md).
- **Hooks/api exports are unused.** Lint will not flag them since they are
  named exports from a barrel. Tree-shaking removes them from the bundle.
  Acceptable.
