# Changes applied for Option A

All edits are frontend-only. Backend was deliberately untouched.

## Deletions

- `frontend/src/app/workspace/approvals/` — entire route directory removed
  (was `page.tsx`).
- `frontend/src/components/workspace/approvals/` — entire component directory
  removed (was `approval-card.tsx`).

## Edits

### `frontend/src/components/workspace/workspace-nav-chat-list.tsx`

- Removed the `<SidebarMenuItem>` block that linked to `/workspace/approvals`.
- Removed `CheckCheckIcon` from the `lucide-react` import (was only used by
  that menu item).

### `frontend/src/components/workspace/workspace-container.tsx`

- Removed the `if (segment === "approvals") return t.breadcrumb.approvals;`
  case from `nameOfSegment()`.

### `frontend/src/core/i18n/locales/en-US.ts`

- Removed `sidebar.approvals` (under the `sidebar` section).
- Removed `breadcrumb.approvals` (under the `breadcrumb` section).
- Removed `pages.approvals` (under the `pages` section).

### `frontend/src/core/i18n/locales/types.ts`

- Removed the matching `approvals: string;` type field from each of the
  `sidebar`, `breadcrumb`, and `pages` interface blocks.

## Files intentionally NOT changed

- `frontend/src/core/control-plane/hooks.ts` — `useApprovals`,
  `useResolveApproval`, `useProposalApprovals`, `useResolveProposalApproval`
  remain exported.
- `frontend/src/core/control-plane/api.ts` — `listApprovals`,
  `resolveApproval`, `listProposalApprovals`, `resolveProposalApproval`
  remain.
- `frontend/src/core/control-plane/types.ts` — approval types remain.
- `frontend/src/core/workspace-refresh/` — the `"approvals"` refresh domain
  remains.
- Entire `backend/` tree — untouched.

## Verification

- `pnpm typecheck` passes after the changes.
- `grep -rn "t\.sidebar\.approvals\|t\.breadcrumb\.approvals\|t\.pages\.approvals\|/workspace/approvals" frontend/src --include="*.ts" --include="*.tsx"`
  returns no matches — there are no orphan references to the removed keys or
  the deleted route.
- `pnpm lint` produces only pre-existing errors in unrelated files (no new
  errors introduced by this change).
