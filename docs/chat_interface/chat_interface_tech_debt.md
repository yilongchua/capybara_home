# Chat Interface — Tech Debt Report

> **Date:** 2026-05-08
> **Scope:** All chat interfaces (main chat, dreamy, workspace)
> **Files Analyzed:** 30+ files across `frontend/src/components/workspace/`, `frontend/src/core/dreamy/`, `frontend/src/app/workspace/chats/`, `frontend/src/app/workspace/dreamy/`
> **Total Lines of Code:** ~8,500+ lines

---

## Executive Summary

The chat interface codebase has significant technical debt accumulated across three main areas: **file size** (three files exceed 800 lines), **hardcoded strings** (minimal i18n coverage), and **duplicate code** (steering logic, generation counter patterns, URL builders scattered across 15+ files). The most critical issues are the `input-box.tsx` (1020 lines) and `hooks.ts` useThreadStream (~850 lines) monoliths, which violate single-responsibility principles and make targeted changes risky.

### Severity Distribution

| Severity | Count | Examples |
|----------|-------|---------|
| **Critical** | 4 | Monolith files, race conditions, unsafe type casts |
| **High** | 12 | Hardcoded API paths, missing error boundaries, brittle string matching |
| **Medium** | 18 | Duplicate code, missing types, state synchronization bugs |
| **Low** | 20+ | Magic numbers, emoji in UI, missing loading/empty states |

---

## 1. Critical Issues (Fix Immediately)

### C-01: `input-box.tsx` — 1,020 lines, single-responsibility violation

**File:** `frontend/src/components/workspace/input-box.tsx`
**Lines:** 1020

This file handles model selection, mode switching, reasoning effort, privacy settings, auto-mode, folder mounting, follow-up suggestions, workflow prefix, and the entire input UI. It should be split into:

| Extracted Component | Responsibility |
|---------------------|---------------|
| `ModelSelectorPanel` | Model selection dropdown logic + UI |
| `ModeSelectorPanel` | Fast/pro mode switching |
| `ReasoningEffortSelector` | Reasoning effort dropdown |
| `PrivacyAndAutoModeMenu` | Privacy toggle + auto-mode |
| `FollowupSuggestions` | Follow-up suggestion chips (fetching + display) |
| `MountFolderDialog` | Folder mounting dialog logic + UI |

**Impact:** Any change to one feature risks breaking unrelated features. Code review is infeasible at this size.

---

### C-02: `hooks.ts` useThreadStream — ~850 lines, too many responsibilities

**File:** `frontend/src/core/threads/hooks.ts`
**Lines:** ~850 (of 987 total)

This single hook handles: message submission, file uploads, optimistic UI, trace events, task management, queue processing, custom event dispatching (6+ event types), and thread listing. Should be split into:

| Extracted Hook | Responsibility |
|----------------|---------------|
| `useThreadSubmission` | Message + file upload logic |
| `useTraceEvents` | Trace event collection and flushing |
| `useTaskManagement` | Subtask state updates |
| `useMessageQueue` | Queue processing logic |
| `useThreads` (standalone) | Thread listing + pagination |

**Impact:** The `onCustomEvent` callback alone (lines 290-524) handles at least 6 different event types, each 20-50 lines. This is unmaintainable.

---

### C-03: Race condition on auto-pin ref in `dreamy-box.tsx`

**File:** `frontend/src/components/workspace/dreamy/dreamy-box.tsx:39-46`

```tsx
// didAutoPinRef is set to true inside a useEffect, but if workflowJson changes rapidly
// the effect could fire again before the ref is set, causing a double-trigger.
```

**Fix:** Use `useRef` initialized to `false` and check/set atomically, or use a cleanup function in the effect.

---

### C-04: Unsafe `as Record<string, unknown>` casts throughout

**Files:**
- `chat-activity-panel.tsx:68` — `as Record<string, unknown>`
- `hooks.ts:68-73` — `asRecord` helper used throughout

**Impact:** Bypasses TypeScript type safety, could mask runtime bugs. Replace with proper discriminated unions or validation functions.

---

---

## 2. High Severity Issues (Fix This Sprint)

### H-01: Hardcoded API paths scattered across 15+ files

**Affected Files:**
| File | Lines | Path Pattern |
|------|-------|-------------|
| `use-checkpoint.ts` | 17 | `/api/threads/${threadId}/artifacts/mnt/user-data/outputs/checkpoint.json` |
| `use-dreamy-as-long-running-task.ts` | 14 | `/api/threads/${threadId}/dreamy/workflow` |
| `use-workflow-json.ts` | 15, 24 | Same `/dreamy/workflow` (duplicated) |
| `use-mounted-folder.ts` | 8, 17, 31 | `/dreamy/mount-folder` (GET/PUT/DELETE) |
| `use-mounted-folder-files.ts` | 20 | `/dreamy/mount-folder/files` |
| `use-progress.ts` | 10 | `/dreamy/executor/status` |
| `use-macos-file-actions.ts` | 15, 26, 37 | `/files/reveal`, `/files/open`, `/files/thumbnail` |
| `dreamy-progress-header.tsx` | 40, 46 | `/dreamy/executor/pause`, `/dreamy/executor/stop` |
| `dreamy-directory-tab.tsx` | 158, 163, 174, 185 | Multiple artifact URL paths |
| `input-box.tsx` | 469 | `/api/threads/${threadId}/suggestions` |
| `hooks.ts` | 262, 879 | `["threads", "search"]` query keys duplicated |

**Fix:** Create `frontend/src/core/dreamy/api.ts` with all endpoint builders. Example:
```ts
export const api = {
  dreamy: {
    workflow: (threadId: string) => `/api/threads/${threadId}/dreamy/workflow`,
    mountFolder: (threadId: string) => `/api/threads/${threadId}/dreamy/mount-folder`,
    executor: { status: (id) => `/api/threads/${id}/dreamy/executor/status`, pause: (id) => ..., stop: (id) => ... },
  },
};
```

---

### H-02: Missing i18n — 30+ hardcoded UI strings

**Affected Files & Strings:**
| File | Line(s) | Hardcoded String |
|------|---------|-----------------|
| `dreamy/page.tsx` | 23 | `"Dreamy -- Capybara"` |
| `dreamy/[thread_id]/page.tsx` | 81 | `"Dreamy -- Capybara"` |
| `dreamy/page.tsx` | 45 | `"Search Dreamy sessions..."` |
| `dreamy/page.tsx` | 52 | `"New Dreamy Session"` |
| `chats/[thread_id]/page.tsx` | 137 | `"Conversation finished"` |
| `chats/[thread_id]/page.tsx` | 352 | `"e.g. Be concise and focus on tradeoffs."` |
| `chats/[thread_id]/page.tsx` | 345 | `"Steer Next Turn"` |
| `input-box.tsx` | 304, 320 | `"Mounted: ${savedPath}"`, `"Mounted folder: ${savedPath}"` |
| `input-box.tsx` | 324 | `"Failed to mount folder"` |
| `dreamy-add-step-dialog.tsx` | 31, 38, 45, 52 | Tool descriptions |
| `dreamy-directory-tab.tsx` | 196-198, 214, 234, 245 | "No files yet", "Mounted Folder", etc. |
| `dreamy-progress-header.tsx` | 62, 70, 76 | "POC complete...", "Paused at row..." |
| `hooks.ts` | 631, 648, 653, 687, 691 | Multiple "Failed to..." messages |

**Fix:** Add all strings to `frontend/src/core/i18n/locales/en-US.ts` and `types.ts`. Use `t()` throughout.

---

### H-03: No error boundary for Dreamy subsystem

**Scope:** Entire dreamy feature tree (context provider + all components)

A crash in any renderer (e.g., `CsvPreview` on malformed CSV, or the naive CSV parser at `dreamy-file-renderers.tsx:171-196`) will unmount the entire dreamy panel.

**Fix:** Wrap `DreamyProvider` in an error boundary component that shows a recovery UI.

---

### H-04: Brittle live output detection via string matching

**File:** `dreamy-file-preview.tsx:164`
```tsx
const isLiveOutput = file.filename.includes("_results");
```

If the backend changes the naming convention, live refresh breaks silently.

**Fix:** Add a typed `is_live` or `output_type` flag from the backend API.

---

### H-05: Naive CSV parser that will corrupt data on edge cases

**File:** `dreamy-file-renderers.tsx:171-196`

The `parseDelimited` function handles basic quoted fields but does not handle:
- Escaped newlines within quotes (`"line1\nline2"`)
- Lines ending mid-quote
- Commas within quoted fields (partial support)

**Fix:** Use a library like `papaparse` or implement proper RFC 4180 parsing.

---

### H-06: `dreamy-directory-tab.tsx` — 296 lines, too many responsibilities

Fetches uploads, mounted folders, merged files, data source resolution, and renders three distinct sections. Should be split into:
- A data-fetching hook (`useDirectoryData`)
- A presentational component for mounted folder section
- A presentational component for uploaded/created files section

---

### H-07: `dreamy-file-renderers.tsx` — 382 lines, 10 renderer components

Each renderer is self-contained but the file mixes shared helpers (`LoadingState`, `ErrorState`, `resolveUrl`) with 10 distinct renderer exports. Consider splitting into per-renderer files or grouping by category (media vs. text).

---

### H-08: Unsafe type assertion on `thread.values.uploaded_files`

**File:** `dreamy-directory-tab.tsx:97-102`
```tsx
(thread.values.uploaded_files ?? []) as Array<...>
```

Silently trusts the runtime shape of `thread.values`. If the backend changes, this cast hides the error.

**Fix:** Add a runtime validation function or use a proper type guard.

---

---

## 3. Medium Severity Issues (Fix Next Sprint)

### M-01: Duplicate code — steering logic duplicated between chats and dreamy

**Files:**
- `chats/[thread_id]/page.tsx:50-78` (handleSteer + Dialog)
- `dreamy/[thread_id]/page.tsx:50-78` (handleSteer + window.prompt)

**Fix:** Extract to `useThreadSteering` hook. Also, dreamy uses `window.prompt` while chats uses a proper Dialog — unify to Dialog.

---

### M-02: Duplicate code — generation counter pattern in both layout files

**Files:**
- `chats/[thread_id]/layout.tsx:23-30`
- `dreamy/[thread_id]/layout.tsx:14-22`

Identical logic for forcing remounts when navigating to "new". Extract to `useThreadRemount` hook.

---

### M-03: Duplicate code — stable thread ID regex in 2 files

**Files:**
- `input-box.tsx:186` — `threadId.replace(/[^a-zA-Z0-9_-]/g, "_")`
- `chat-box.tsx:60` — same regex

**Fix:** Extract to `frontend/src/core/utils/strings.ts`:
```ts
export function sanitizeThreadId(id: string): string {
  return id.replace(/[^a-zA-Z0-9_-]/g, "_");
}
```

---

### M-04: `SelectedFile` type defined in component file instead of types.ts

**Files:**
- `dreamy-file-preview.tsx` — defines `SelectedFile` interface
- `dreamy-directory-tab.tsx:20` — imports it from the component file
- `dreamy-workflow-pane.tsx:21` — same

**Fix:** Move `SelectedFile` to `frontend/src/core/dreamy/types.ts`.

---

### M-05: `phase` typed as `string` instead of union type

**File:** `core/dreamy/hooks/use-dreamy-progress.ts:17`
```ts
phase: string;  // should be "design" | "poc" | "awaiting_approval" | "bulk" | ...
```

**Fix:** Define a proper union type:
```ts
export type DreamyPhase = "design" | "poc" | "awaiting_approval" | "bulk" | "done" | 
                          "running" | "paused" | "stopped" | "completed" | "failed";
```

---

### M-06: `DreamyStepEditor` — optimistic update without rollback

**File:** `dreamy-step-editor.tsx:39-57`

Calls `patchStep` (optimistic UI update) then `saveWorkflowJson` (server write). If the server write fails, there is no rollback. Optimistic state will be stale until next refetch.

**Fix:** Save the previous value before optimistic update, restore on failure.

---

### M-07: `DreamyStepEditor` — state sync overwrites concurrent user edits

**File:** `dreamy-step-editor.tsx:29-37`

The `useEffect` syncs local state from the step when it changes. If the user edits a field and then the backend updates the same step concurrently, local state is overwritten. No "dirty" flag or optimistic update guard.

**Fix:** Add a `isUserEditing` ref that blocks the sync effect during user input.

---

### M-08: `DreamyWorkflowPane` — local state lost on panel collapse

**File:** `dreamy-workflow-pane.tsx:37-39`

`activeTab` and `selectedFile` are local state. If the panel collapses (triggering remount), tab selection and file preview are lost.

**Fix:** Lift into `DreamyContext` or persist in URL params.

---

### M-09: Dual data sources for progress — confusing precedence

**File:** `core/dreamy/hooks/use-dreamy-progress.ts:40-42`

Chooses between `progress!.done` (executor), `checkpoint.completed.length`, and `execution_state.current_row_index`. The precedence logic is buried in a ternary chain. Two sources can be out of sync during transitions.

**Fix:** Define clear ownership: executor is source of truth for running state, checkpoint for completed state. Add a transition buffer.

---

### M-10: `useDreamyAsLongRunningTask` — phase-to-status mapping is lossy

**File:** `core/dreamy/hooks/use-dreamy-as-long-running-task.ts:20-27`

Maps `"poc"` and `"bulk"` both to `"running"`. The LRT consumer cannot distinguish between POC and bulk execution phases.

**Fix:** Return the raw phase alongside the status, or add a `subStatus` field.

---

### M-11: `useWorkflowJson` — double-read pattern (context + return value)

**File:** `core/dreamy/hooks/use-workflow-json.ts:46-50`

Sets `workflowJson` in context via `useEffect`, then also returns `data ?? null`. The caller (`DreamyWorkflowPane`) calls both `useWorkflowJson(threadId)` (which sets context) and `useDreamy()` (which reads context).

**Fix:** Have the hook simply return the value. Let callers use it directly without touching context.

---

### M-12: `chat-activity-panel.tsx` — 585 lines, should be split

**File:** `frontend/src/components/workspace/chats/chat-activity-panel.tsx`
**Lines:** 585

Mixes types, helpers, icon rendering, and main panel logic. Should split into:
- `timeline-helpers.ts` — `looksLikeFailure`, `getMessageTimestamp`, `preview`
- `timeline-item-row.tsx` — individual timeline item rendering
- `activity-panel-content.tsx` — main panel component

---

### M-13: `chats/[thread_id]/page.tsx` — 389 lines, too many responsibilities

**File:** `frontend/src/app/workspace/chats/[thread_id]/page.tsx`
**Lines:** 389

Handles thread stream setup, file upload handling, notification logic, steering dialog, context token management, and entire JSX layout. Should extract:
- `useThreadNotification` — notification logic
- `SteeringDialog` — steering dialog component (already partially extracted)
- Context token management → separate hook

---

### M-14: Commented-out code blocks (dead code)

**File:** `chats/[thread_id]/page.tsx:98-104, 206-218`

Commented-out "files tray" feature code. Should be removed or moved to a separate branch/file with a reference comment.

---

### M-15: `use-thread-chat.ts` — hydration mismatch risk

**File:** `frontend/src/components/workspace/chats/use-thread-chat.ts:24`

Calls `uuid()` inside a `useEffect`. If UUID generation is not deterministic across SSR/CSR, this causes hydration warnings.

---

### M-16: `use-chat-mode.ts` — dead code / no-op hook still imported and called

**File:** `frontend/src/components/workspace/chats/use-chat-mode.ts`
**Also imported in:** `chats/[thread_id]/page.tsx:54`, `index.ts`

The hook is a no-op with comment "skill mode is no longer supported". Should be removed entirely or marked deprecated with `console.warn`.

---

---

## 4. Low Severity Issues (Backlog)

### L-01: Magic numbers scattered throughout — should be named constants

| File | Line | Number | Suggested Constant Name |
|------|------|--------|------------------------|
| `use-checkpoint.ts` | 28 | `2000`, `30000` | `REFRESH_INTERVAL_ACTIVE`, `REFRESH_INTERVAL_IDLE` |
| `use-dreamy-as-long-running-task.ts` | 49 | `3000` | `REFRESH_INTERVAL_LRT` |
| `use-file-preview-content.ts` | 25 | `5 * 60 * 1000` | `FILE_PREVIEW_STALE_TIME` |
| `use-mounted-folder-files.ts` | 30-31 | `5_000`, `10_000`, `45_000` | (same as above) |
| `use-mounted-folder.ts` | 46-47 | `5_000`, `10_000`, `45_000` | (same as above) |
| `use-progress.ts` | 21 | `2000` | `REFRESH_INTERVAL_ACTIVE` |
| `use-workflow-json.ts` | 40 | `2000`, `30000` | (same as checkpoint) |
| `dreamy-file-renderers.tsx` | 169 | `500` | `CSV_ROW_LIMIT` |
| `dreamy-progress-header.tsx` | 16 | `60_000` | `MS_PER_MINUTE` |
| `chat-activity-panel.tsx` | 476, 528 | `500` | `TIMELINE_MAX_ITEMS` |
| `chat-activity-panel.tsx` | 104, 359 | `140`, `120` | `MESSAGE_PREVIEW_LIMIT` |
| `hooks.ts` | 731 | `1000` | `RECURSION_LIMIT` |
| `hooks.ts` | 862-863 | `50`, `"updated_at"`, `"desc"` | `DEFAULT_PAGE_SIZE`, etc. |
| `input-box.tsx` | 476 | `3` | `SUGGESTION_COUNT` |
| `input-box.tsx` | 490 | `.slice(0, 5)` | `MAX_SUGGESTIONS` |
| `input-box.tsx` | 924 | `-bottom-[17px]` | (pixel offset — should be CSS variable) |
| `input-box.tsx` | 529 | `z-3` | (non-standard Tailwind z-index) |

**Fix:** Create `frontend/src/core/dreamy/constants.ts`:
```ts
export const REFRESH_INTERVAL_ACTIVE = 2000;
export const REFRESH_INTERVAL_IDLE = 30000;
export const REFRESH_INTERVAL_LRT = 3000;
export const CSV_ROW_LIMIT = 500;
export const FILE_PREVIEW_STALE_TIME = 5 * 60 * 1000;
export const MS_PER_MINUTE = 60_000;
export const TIMELINE_MAX_ITEMS = 500;
export const MESSAGE_PREVIEW_LIMIT = 140;
export const RECURSION_LIMIT = 1000;
export const DEFAULT_PAGE_SIZE = 50;
export const SUGGESTION_COUNT = 3;
export const MAX_SUGGESTIONS = 5;
```

---

### L-02: Emoji used as UI content (not i18n-safe)

| File | Line | Emoji |
|------|------|-------|
| `dreamy-steps-list.tsx` | 24 | `✨` |
| `dreamy-progress-header.tsx` | 129 | `⚠` |

**Fix:** Replace with icon components from lucide-react.

---

### L-03: HTML preview has permissive sandbox

**File:** `dreamy-file-renderers.tsx:136`
```html
sandbox="allow-scripts allow-forms"
```

**Fix:** Consider adding stricter CSP or using an iframe with a dedicated backend CSP header.

---

### L-04: Image preview has no lazy loading

**File:** `dreamy-file-renderers.tsx:160`
```html
<img>  // missing loading="lazy"
```

**Fix:** Add `loading="lazy"` and an error fallback with placeholder.

---

### L-05: Missing loading states on page-level components

| File | Issue |
|------|-------|
| `chats/page.tsx` | No loading skeleton when `useThreads` is fetching |
| `chats/page.tsx` | No empty state when no threads exist |
| `dreamy/page.tsx` | Same — no loading or empty state |

---

### L-06: `isMock` hardcoded to `false` in dreamy page

**File:** `dreamy/[thread_id]/page.tsx:85`
```tsx
isMock: false  // should be explicit in type or derived from env
```

---

### L-07: Mode forced to "fast" in dreamy — undocumented restriction

**File:** `dreamy/[thread_id]/page.tsx:135-136`
```tsx
mode: "fast"  // dreamy threads cannot use "pro" mode — why?
```

**Fix:** If intentional, document in code or enforce at type level.

---

### L-08: `env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY` checked inline in 2 places

**File:** `chats/[thread_id]/page.tsx:331, 337`

Should be a derived constant or config value.

---

### L-09: `AgentThread` is a thin alias with no added value

**File:** `core/threads/types.ts`
```ts
export type AgentThread extends Thread<AgentThreadState> {}  // adds nothing
```

**Fix:** Remove the alias and use `Thread<AgentThreadState>` directly, unless there's a specific reason.

---

### L-10: `AgentThreadState extends Record<string, unknown>` — all field access is untyped

**File:** `core/threads/types.ts`

**Fix:** Define a proper interface for known state fields. Use `Record<string, unknown>` only for truly dynamic fields.

---

---

## 5. State Management Issues

### S-01: `DreamyContext` — state not persisted across remounts

**File:** `core/dreamy/context.tsx`

Holds `workflowJson`, `editingStepId`, `isPinned`, and `isPaneCollapsed` as plain React state. If the provider remounts (e.g., due to parent re-render or panel collapse), all state is lost. `editingStepId` being null on remount means the step editor closes unexpectedly when user navigates tabs.

---

### S-02: `input-box.tsx` — 12+ useState calls, 5 refs for stale-state avoidance

**File:** `input-box.tsx`

State variables: `modelOpen`, `modeOpen`, `reasoningOpen`, `privacyOpen`, `autoModeOpen`, `followups`, `followupsHidden`, `followupsLoading`, `isMountedFolderDialogOpen`, `mountPathInput`, etc.

Refs: `contextRef`, `onContextChangeRef`, `messagesRef`, `lastGeneratedForAiIdRef`, `wasStreamingRef`

**Fix:** Consolidate related state into useReducer where appropriate. Document why each ref is needed.

---

### S-03: `hooks.ts` useThreadStream — ~15 state variables, many refs

**File:** `core/threads/hooks.ts`

State: `messageQueue`, `queueRef`, `isSubmittingRef`, `isDequeuingRef`, `liveThinkingContent`, `optimisticMessages`, `prevMsgCountRef`, `syntheticSeqRef`, `currentRunIdRef`, `pendingTraceEventsRef`, `flushTimerRef`

**Fix:** Split into multiple hooks (see C-02). Each sub-hook should own its own state.

---

### S-04: `chat-box.tsx` — dual control of `activeTab`

**File:** `chat-box.tsx:66-101`

`activeTab` is controlled by both user interaction (`handleTabChange`) and side effects (lines 91-101 toggle based on `artifactsOpen`). This dual control is a source of potential bugs.

---

### S-05: `chat-box.tsx` — `isPanelCollapsed` mirrors panel state (source of truth problem)

**File:** `chat-box.tsx`

The component maintains its own copy of the panel's collapsed state, creating two sources of truth.

---

### S-06: `useMountedFolder` — manual query data manipulation is fragile

**File:** `core/dreamy/hooks/use-mounted-folder.ts:56-71`

Mutations manually call `queryClient.setQueryData`. If query keys change, these manual updates silently break. Consider using `invalidateQueries` or a more robust pattern with query factory.

---

## 6. File Size Analysis

### Files Exceeding Recommended Limits (>300 lines)

| Rank | File | Lines | Severity | Recommendation |
|------|------|-------|----------|---------------|
| 1 | `input-box.tsx` | **1,020** | Critical | Split into 6+ components (see C-01) |
| 2 | `hooks.ts` (useThreadStream) | **~850** | Critical | Split into 5 hooks (see C-02) |
| 3 | `prompt-input.tsx`* | **1,423** | Critical | (Referenced in file-map.md) Split textarea + popup logic |
| 4 | `chat-activity-panel.tsx` | **585** | High | Split helpers + components (see M-12) |
| 5 | `message-group.tsx`* | **517** | Medium | Extract tool call rendering |
| 6 | `message-list.tsx`* | **415** | Medium | Extract message grouping logic |
| 7 | `chats/[thread_id]/page.tsx` | **389** | High | Extract hooks + dialog (see M-13) |
| 8 | `dreamy-file-renderers.tsx` | **382** | High | Split per-renderer files (see H-07) |
| 9 | `message-list-item.tsx`* | **407** | Medium | Extract rendering helpers |
| 10 | `dreamy-directory-tab.tsx` | **296** | High | Split data fetching + presentation (see H-06) |
| 11 | `chat-box.tsx` | **232** | Medium | Extract artifact panel logic |
| 12 | `dreamy-file-preview.tsx` | **248** | Medium | Extract file type detection logic |
| 13 | `dreamy-workflow-pane.tsx` | **198** | Medium | Lift state to context (see M-08) |
| 14 | `dreamy-add-step-dialog.tsx` | **163** | Low | Minor cleanup |
| 15 | `dreamy/[thread_id]/page.tsx` | **146** | Medium | Extract steering hook (see M-01) |
| 16 | `dreamy-box.tsx` | **134** | Low | Fix race condition (see C-03) |
| 17 | `dreamy-step-editor.tsx` | **130** | Medium | Add rollback + dirty guard (see M-06, M-07) |
| 18 | `dreamy-progress-header.tsx` | **141** | Low | Extract constants (see L-01) |

_*Referenced in file-map.md, not fully analyzed in this review_

---

---

## 7. Prioritized Action Plan

### Phase 1: Quick Wins (1-2 days, no architectural changes)

| # | Action | Files | Effort |
|---|--------|-------|--------|
| 1.1 | Create `constants.ts` with all magic numbers | All dreamy hooks + components | 2h |
| 1.2 | Create `api.ts` with endpoint builders | All dreamy hooks + components | 3h |
| 1.3 | Move `SelectedFile` to `types.ts` | `dreamy-file-preview.tsx`, `dreamy-directory-tab.tsx`, `dreamy-workflow-pane.tsx` | 30m |
| 1.4 | Add typed union for `phase` in `DreamyProgress` | `use-dreamy-progress.ts` | 30m |
| 1.5 | Remove dead `useSpecificChatMode` hook + its imports | `use-chat-mode.ts`, `index.ts`, `[thread_id]/page.tsx` | 30m |
| 1.6 | Remove commented-out code blocks | `chats/[thread_id]/page.tsx` | 15m |
| 1.7 | Replace emoji with icon components | `dreamy-steps-list.tsx`, `dreamy-progress-header.tsx` | 30m |

### Phase 2: Structural Refactors (1-2 weeks)

| # | Action | Files | Effort |
|---|--------|-------|--------|
| 2.1 | Extract `useThreadSteering` hook (unify chats + dreamy) | Both `[thread_id]/page.tsx` files | 4h |
| 2.2 | Extract `useThreadRemount` hook (generation counter) | Both layout files | 2h |
| 2.3 | Extract `sanitizeThreadId` utility | `input-box.tsx`, `chat-box.tsx` | 30m |
| 2.4 | Add error boundary around DreamyProvider | `dreamy/[thread_id]/layout.tsx` | 3h |
| 2.5 | Add i18n keys for all hardcoded strings (dreamy) | All dreamy components | 6h |
| 2.6 | Add i18n keys for all hardcoded strings (chats) | Chat components + pages | 4h |
| 2.7 | Persist tab/file selection in URL params or context | `dreamy-workflow-pane.tsx` | 4h |
| 2.8 | Add rollback to `DreamyStepEditor` save handler | `dreamy-step-editor.tsx` | 2h |
| 2.9 | Add dirty guard to `DreamyStepEditor` sync effect | `dreamy-step-editor.tsx` | 2h |

### Phase 3: Major File Splits (2-4 weeks)

| # | Action | Source File | Target Files | Effort |
|---|--------|------------|--------------|--------|
| 3.1 | Split `input-box.tsx` | `input-box.tsx` (1020 lines) | 6 component files + 1 hook file | 2-3 days |
| 3.2 | Split `useThreadStream` hook | `hooks.ts` (987 lines) | 5 hook files | 2-3 days |
| 3.3 | Split `chat-activity-panel.tsx` | `chat-activity-panel.tsx` (585 lines) | helpers + 2 component files | 1 day |
| 3.4 | Split `dreamy-directory-tab.tsx` | `dreamy-directory-tab.tsx` (296 lines) | 1 hook + 3 component files | 1 day |
| 3.5 | Split `dreamy-file-renderers.tsx` | `dreamy-file-renderers.tsx` (382 lines) | 1 helpers file + per-renderer files | 1 day |
| 3.6 | Split `chats/[thread_id]/page.tsx` | `[thread_id]/page.tsx` (389 lines) | 1 hook + dialog component + page | 1 day |

### Phase 4: Robustness Improvements (backlog)

| # | Action | Effort |
|---|--------|--------|
| 4.1 | Replace naive CSV parser with papaparse or RFC 4180 implementation | 2h |
| 4.2 | Replace string-based `isLiveOutput` detection with typed backend flag | 1h |
| 4.3 | Replace `asRecord` / `as Record<string, unknown>` casts with proper type guards | 4h |
| 4.4 | Add loading + empty states to `chats/page.tsx` and `dreamy/page.tsx` | 2h |
| 4.5 | Fix race condition on auto-pin ref in `dreamy-box.tsx` | 1h |
| 4.6 | Define proper interface for `AgentThreadState` known fields | 2h |
| 4.7 | Add documentation for provider nesting order in layout files | 1h |
| 4.8 | Audit and fix potential circular dependency: `hooks.ts` → `traces` → components | 2h |

---

## 8. Cross-Cutting Concerns

### i18n Coverage Gap

Only a subset of UI strings use the `t()` translation function. The following areas are **not** internationalized:
- All dreamy-specific UI strings (progress messages, step descriptions, directory labels)
- Error/toast messages in `hooks.ts` and `input-box.tsx`
- Page titles for dreamy pages
- Placeholder text in forms

### Duplicate Patterns Inventory

| Pattern | Locations | Extraction Target |
|---------|-----------|------------------|
| Generation counter for remounts | `chats/[thread_id]/layout.tsx`, `dreamy/[thread_id]/layout.tsx` | `useThreadRemount` hook |
| Steering logic (handleSteer) | `chats/[thread_id]/page.tsx`, `dreamy/[thread_id]/page.tsx` | `useThreadSteering` hook |
| Stable thread ID sanitization | `input-box.tsx`, `chat-box.tsx` | `sanitizeThreadId()` utility |
| Thread list page structure | `chats/page.tsx`, `dreamy/page.tsx` | Shared `ThreadListPage` component |
| Manual queryClient.setQueryData | `use-mounted-folder.ts`, `use-mounted-folder-files.ts` | Query mutation helper |
| Refetch interval patterns | 6+ files with `2000`/`30000` values | `constants.ts` (Phase 1) |
| API endpoint string construction | 10+ files | `api.ts` (Phase 1) |

### Import Hygiene

- No truly unused imports found across the codebase (good hygiene).
- `SelectedFile` type imported from component files instead of `types.ts` (see M-04).
- Potential circular dependency risk: `hooks.ts` → `../traces` → components → `hooks.ts`.

---

## 9. Summary Statistics

| Metric | Value |
|--------|-------|
| Total files analyzed | 30+ |
| Total lines of code | ~8,500+ |
| Files > 300 lines | 18 |
| Files > 500 lines | 4 |
| Hardcoded API paths | 15+ instances across 10 files |
| Magic numbers (unnamed) | 20+ instances across 12 files |
| Hardcoded UI strings (no i18n) | 30+ instances across 15 files |
| Duplicate code blocks | 6 patterns across multiple files |
| Dead / no-op code | `use-chat-mode.ts` (6 lines) + commented blocks |
| Missing error boundaries | Dreamy subsystem (entire feature tree) |
| Unsafe type casts (`as`) | 5+ instances across 4 files |

---

## Appendix A: Full File Inventory Analyzed

### Chat Components
- `frontend/src/components/workspace/chat-ui/` (6 files)
- `frontend/src/components/workspace/chats/` (4 files)
- `frontend/src/components/workspace/input-box.tsx`

### Dreamy Components
- `frontend/src/components/workspace/dreamy/` (9 files)
- `frontend/src/core/dreamy/` (13 files: context, types, 11 hooks)

### Pages & Layouts
- `frontend/src/app/workspace/chats/` (3 files)
- `frontend/src/app/workspace/dreamy/` (3 files)

### Core
- `frontend/src/core/threads/hooks.ts`
- `frontend/src/core/threads/types.ts`

---

*Report generated: 2026-05-08*
