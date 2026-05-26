# Dreamy — Frontend File Inventory

Every frontend path Dreamy owned or modified.

## Whole-File (re-create these in full)

### `frontend/src/components/workspace/dreamy/`

The dreamy workspace pane. 16 files at removal time:

| File | Purpose |
|---|---|
| `dreamy-workflow-pane.tsx` | Root pane component — composes header, steps list, editor, file preview. |
| `dreamy-box.tsx` | Main Dreamy tab UI container, wraps the pane with surface-level controls. |
| `dreamy-add-step-dialog.tsx` | Modal dialog for adding a workflow step. |
| `dreamy-step-editor.tsx` | Per-step editor (instructions, outputs, dependencies). |
| `dreamy-steps-list.tsx` | List view of the workflow steps with selection / reorder UX. |
| `dreamy-progress-header.tsx` | Progress bar / phase banner / current-row indicator. |
| `dreamy-directory-tab.tsx` | Mounted-folder directory browser. |
| `dreamy-file-preview.tsx` | File preview panel (delegates to renderer files below). |
| `dreamy-file-renderers.tsx` | Dispatch table mapping file kind → renderer. |
| `file-preview-csv.tsx` | CSV renderer (table). |
| `file-preview-text.tsx` | Text / code renderer. |
| `file-preview-document.tsx` | Document renderer (PDF / DOCX). |
| `file-preview-media.tsx` | Image / media renderer. |
| `file-preview-shared.tsx` | Shared layout helpers for previews. |
| `directory-file-row.tsx` | Row in the directory browser. |
| `use-directory-data.ts` | React hook backing the directory tab. |

### `frontend/src/core/dreamy/`

The data-layer module for Dreamy. At removal time:

| File | Purpose |
|---|---|
| `api.ts` | Typed fetch client. Exposes `api.threads.dreamy.workflow(threadId)`, `mountFolder(threadId)`, `analyse(threadId)`, `analyseStatus(threadId)`, `repoOverviewRefresh(threadId)`, `repoOverviewRefreshStatus(threadId, jobId)`, `publishDocs(threadId)`. |
| `context.tsx` | `DreamyProvider` React context — owns `dreamyActive`, `onActivateDreamy`, `onDeactivateDreamy`. Consumed by `InputBox` and by the Dreamy pane. |
| `constants.ts` | Default poll intervals, phase strings, query-key prefixes. |
| `error-boundary.tsx` | React error boundary scoped to the Dreamy pane. |
| `types.ts` | TypeScript shapes for `WorkflowJson`, `DreamyIntent`, `MountFolderConfig`, `AnalyseStatus`, `RepoOverviewRefreshJob`. |
| `hooks/use-workflow-json.ts` | Polls + caches `workflow.json` for the open thread. |
| `hooks/use-checkpoint.ts` | Mark-done / advance-step UX. |
| `hooks/use-progress.ts` | Aggregated phase + progress derivation. |
| `hooks/use-dreamy-progress.ts` | Per-row progress widget binding. |
| `hooks/use-file-preview-content.ts` | Lazy-loaded file content for the preview panel. |
| `hooks/use-folder-picker.ts` | Native folder picker integration. |
| `hooks/use-macos-file-actions.ts` | macOS Quick Look / Reveal in Finder actions. |
| `hooks/use-mounted-folder.ts` | Query `<thread>/dreamy/mount-folder`. |
| `hooks/use-mounted-folder-files.ts` | Query mounted-folder listing. |
| `hooks/use-step-highlight.ts` | Step syntax highlighting (for inline code in instructions). |

### `frontend/src/app/workspace/dreamy/`

Next.js route:

| File | Purpose |
|---|---|
| `[thread_id]/page.tsx` | Renders the workflow pane for a thread. |
| `[thread_id]/layout.tsx` | Wraps in `<DreamyProvider>` and applies the Dreamy chrome. |
| `page.tsx` (root) | Dreamy landing page (if present at the time of reinstatement). |

## Surgical Edits (re-add these lines to surviving files)

### `frontend/src/components/workspace/input-box.tsx`

```tsx
// Props on the component (near the top of the props destructure block, L227-L230)
dreamy,
dreamyActive,
onActivateDreamy,
onDeactivateDreamy,

// Type signature (L241-L242, L268-L269)
dreamy?: boolean;
dreamyActive?: boolean;
// ...
onActivateDreamy?: () => Promise<void> | void;
onDeactivateDreamy?: () => Promise<void> | void;

// API calls — use the same prefix everywhere (L329, L342, L363, L632, L816, L870)
`${getBackendBaseURL()}${api.threads.dreamy.analyseStatus(threadId)}`
`dreamy.repo_overview_refresh_job.${threadId}`
`${getBackendBaseURL()}${api.threads.dreamy.repoOverviewRefreshStatus(threadId, normalized)}`
`${getBackendBaseURL()}${api.threads.dreamy.mountFolder(createdThreadId)}`
`${getBackendBaseURL()}${api.threads.dreamy.analyse(threadId)}`
`${getBackendBaseURL()}${api.threads.dreamy.publishDocs(threadId)}`

// The activation flag derived in the body (L514)
const isDreamyThread = [dreamy, dreamyActive].some(Boolean);

// Set on the outgoing run payload (L1234)
dreamy: isDreamyThread,

// Effect deps that depend on dreamy state (L1259)
}, [context.model_name, disabled, isDreamyThread, isMock, status, threadId, lastMessageId]);

// Hide Plan-mode affordance when dreamy is active (L1341, L1360)
{!dreamy && ( ... )}
{!dreamy && isPlanMode ? ( ... ) : null}

// Slash-command dispatch (executeSlashCommand) — restore the "dreamy" and
// "dreamy-exit" branches per docs/slash_commands/dreamy/dreamy.md and dreamy-exit.md.
```

### `frontend/src/app/workspace/chats/[thread_id]/layout.tsx`

```tsx
// L8 — import
import { DreamyProvider } from "@/core/dreamy/context";

// L27 — wrap children
<DreamyProvider>{children}</DreamyProvider>
```

### `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/layout.tsx`

```tsx
// L21 — same wrapper for agent-scoped chats
<DreamyProvider>{children}</DreamyProvider>
```

### `frontend/src/core/threads/slash-commands.ts`

```ts
// At removal time these were ALREADY absent from this file's SUPPORTED_COMMANDS,
// but historically they belonged here. To reinstate the slash-menu affordance:
export type SlashCommandName =
  | "compact"
  | "recover"
  | "handoff"
  | "new"
  | "mount"
  | "analyse"
  | "publishdocs"
  | "rename"
  | "dreamy"
  | "dreamy-exit";

export const SUPPORTED_COMMANDS: ReadonlySet<SlashCommandName> = new Set([
  // existing,
  "dreamy",
  "dreamy-exit",
]);
```

### `frontend/src/core/threads/types.ts`

```ts
// L100-L101 inside ThreadStateValues
dreamy_mode?: boolean;
dreamy_intent?: {
  shape: string;
  intent_class: string;
  confidence: number;
  extracted_fields: string[];
  inferred_goal: string;
  workflow_requested: boolean;
};

// L134 inside RunCreatePayload (or equivalent)
dreamy_mode?: boolean;
```

### `frontend/src/core/threads/hooks.ts`

```ts
// L15 — api import
import { api } from "@/core/dreamy/api";

// L1116-L1138 inside the state-stream reducer:
// Forward dreamy_mode / dreamy_intent from LangGraph state deltas into the local cache
if (
  "dreamy_mode" in update ||
  "dreamy_intent" in update
) {
  cache.update(...prev, {
    ...("dreamy_mode" in update ? { dreamy_mode: Boolean(update.dreamy_mode) } : {}),
    ...("dreamy_intent" in update
      ? { dreamy_intent: update.dreamy_intent }
      : {}),
  });
}
```

### `frontend/src/core/threads/utils.ts`

```ts
// L5
const DREAMY_TITLE_PREFIX = "✨ ";

// L11-L16
export function isDreamyThread(thread: AgentThread) {
  if (thread.values?.dreamy_mode) {
    return true;
  }
  const title = thread.title ?? "";
  return title.startsWith(DREAMY_TITLE_PREFIX);
}
```

### `frontend/src/core/workspace-refresh/index.ts`

```ts
// L25 — add the dreamy refresh event variant
export type WorkspaceRefreshEvent =
  | `artifacts:${string}`
  | `dreamy:${string}`
  | ...;
```

### `frontend/src/components/workspace/chat-ui/mount-folder-badge.tsx`

```tsx
// L54, L58 — react-query keys (kept the "dreamy-" prefix historically)
queryKey: ["dreamy-mounted-folder", threadId],
queryKey: ["dreamy-mounted-folder-files", threadId],
```

> If Dreamy is permanently retired, renaming these to `["mounted-folder", threadId]` and `["mounted-folder-files", threadId]` is fine — they refer to a now-general feature. Only restore the `dreamy-` prefix if you want to preserve cache-key compatibility with stored state.

### `frontend/src/components/workspace/artifacts/context.tsx`

```tsx
// L49 — comment only, no functional dependency
// Auto-closing on every agent file write breaks the dreamy sidebar experience.
```

### `frontend/src/core/i18n/locales/types.ts` and `en-US.ts`

```ts
// types.ts L146, L502-L503
dreamy: string;          // nav entry
dreamy: { ... };         // pane copy bundle

// en-US.ts L187, L570
dreamy: "Dreamy",
dreamy: { ... },         // pane copy
```

## Surface-Level Wiring Checklist

The single biggest historical failure was inconsistent activation surfaces. When reinstating Dreamy, **every chat surface that renders `<InputBox>`** must:

1. Be wrapped in `<DreamyProvider>` (currently `app/workspace/chats/[thread_id]/layout.tsx` and `app/workspace/agents/.../layout.tsx`; the dedicated Dreamy route already does this).
2. Pass concrete implementations for `onActivateDreamy` and `onDeactivateDreamy` to `<InputBox>`, OR
3. Hide the `/dreamy` and `/dreamy-exit` slash-menu entries on that surface so users can't dead-end on a "not available" toast.

The "not available on this chat surface yet" toast in the old code is a code smell — never ship a slash command that can hit it.
