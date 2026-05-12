# Chat Interface — Test Plan

Manual + static-check verification for the four chat-interface improvements. Frontend has no test runner configured (`pnpm test` is not defined), so verification relies on `pnpm check` (lint + typecheck) plus structured manual UI checks.

## Pre-flight

- [ ] `cd frontend && pnpm check` exits 0
- [ ] `pnpm dev` starts on port 3000
- [ ] Backend reachable (`make dev` from project root, or backend `make gateway` + `make dev`)
- [ ] Open `/workspace/chats/new` and `/workspace/dreamy/new` in browser

## Phase 1 — CapybaraRunner (already shipped)

| # | Scenario | Expected |
|---|----------|----------|
| 1.1 | Send a message that triggers tool use | Loading row at end of message list shows `Capybara -- <icon> <task description>…` instead of three bouncing dots |
| 1.2 | While streaming with no active subtask | Renders `Capybara -- <Brain icon> thinking…` (animated dots) |
| 1.3 | Subagent task in progress | Subtask card shows mini CapybaraRunner with shimmer |
| 1.4 | File upload mock-AI message | Task element header renders CapybaraRunner with the file label |
| 1.5 | Animation perf | Task switcher icon updates within 1 frame when `taskDescription` changes; no console warnings |

## Phase 2A — AttachmentPopup

| # | Scenario | Expected |
|---|----------|----------|
| 2A.1 | Open input bar | Single paperclip+chevron button (no separate Mount Folder button) |
| 2A.2 | Click paperclip+chevron | Dropdown shows two items: **Attach Files**, **Mount Folder** |
| 2A.3 | Select "Attach Files" | Native file picker opens; selected files appear as chips above the textarea |
| 2A.4 | Select "Mount Folder" on macOS/Linux with picker | Native folder picker opens; on success, toast `Mounted: <path>` appears |
| 2A.5 | Select "Mount Folder" when picker unavailable | Manual-path Dialog opens with input; pressing Enter mounts |
| 2A.6 | While `isPicking` is true | "Mount Folder" item shows "Picking…" label and is disabled |
| 2A.7 | Keyboard | Open with Tab+Enter; arrow keys + Enter pick an item |
| 2A.8 | Tooltip | Hover the trigger shows "Attach files or mount a folder" |
| 2A.9 | i18n | Strings come from `t.chatUI.attachmentPopup.*` (no hard-coded English) |

## Phase 2B — MountFolderBadge

| # | Scenario | Expected |
|---|----------|----------|
| 2B.1 | Open chat with no mounted folder | No badge rendered (component returns null) |
| 2B.2 | Mount a folder | Badge appears above the input bar at top-left, shows truncated path with `📁` icon |
| 2B.3 | Hover the path text | Tooltip shows the full mounted path |
| 2B.4 | Click "Change" | Folder picker opens; selecting a different folder updates badge text and shows toast |
| 2B.5 | "Change" while picker pending | Refresh icon animates (`animate-spin`); button disabled |
| 2B.6 | Path truncation | Paths longer than 36 chars render as `head…tail` |
| 2B.7 | Both pages | Badge appears on `/workspace/chats/[id]` AND `/workspace/dreamy/[id]` |
| 2B.8 | New thread | Badge hidden when `isNewThread` (no thread to fetch from yet) |
| 2B.9 | Layout | Badge does NOT overlap the TodoList when both are visible |

## Phase 3 — File Mention `@`

| # | Scenario | Expected |
|---|----------|----------|
| 3.1 | Type `@` at start of textarea (folder mounted, files exist) | Popup opens above the textarea with file list |
| 3.2 | Type `@te` after `Read ` (with space before `@`) | Popup filters files by `te` |
| 3.3 | `email@x.com` (no boundary) | Popup does NOT open — `@` not preceded by whitespace |
| 3.4 | `@<space>` | Popup closes (whitespace breaks the mention) |
| 3.5 | Arrow Down / Up while popup open | Selection moves within Command list, NOT cursor in textarea |
| 3.6 | Enter while popup open | Inserts `@<filename> ` at cursor; closes popup; cursor lands after the inserted text |
| 3.7 | Tab while popup open | Same behavior as Enter (accepts highlighted file) |
| 3.8 | Escape while popup open | Closes popup; cursor stays put; same `@` does not re-open |
| 3.9 | Continue typing after Escape | Popup re-opens once cursor moves past the dismissed `@` location |
| 3.10 | No folder mounted | Popup empty state: "Mount a folder to reference files" |
| 3.11 | Folder mounted but empty | Popup empty state: "No files found" |
| 3.12 | Click outside popup | Popup closes; textarea retains its value |
| 3.13 | Submit form with mention text | Message sent contains literal `@<filename>` text (backend handles it as plain text for v1) |
| 3.14 | Existing chat features still work | Paperclip, mode selector, model selector, Enter-to-submit, Backspace-removes-attachment all unchanged |

## Phase 4 — Cleanup & Regression

| # | Scenario | Expected |
|---|----------|----------|
| 4.1 | `streaming-indicator.tsx` no longer imported | `grep -r "StreamingIndicator" frontend/src` returns no matches; file deleted |
| 4.2 | All four flows in dreamy mode | AttachmentPopup, MountFolderBadge, @-mentions, CapybaraRunner all work in `/workspace/dreamy/[id]` |
| 4.3 | Page reload during streaming | CapybaraRunner re-attaches to in-flight run with the right task description |
| 4.4 | Theme switch (light/dark) | All new components respect theme variables (`bg-background`, `text-muted-foreground`, etc.) |

## Static Checks

- [ ] `pnpm typecheck` passes
- [ ] `pnpm lint` passes (or only warns on pre-existing issues, not the new files)
- [ ] No new ESLint disable comments without justification
- [ ] All new files live under `frontend/src/components/workspace/chat-ui/` per the plan

## Known Limitations / Not in Scope

- Layered overlay highlighting of `@mentions` (Phase 3 v2 — adds visual green/red feedback for existing-vs-missing files). Skipped in this iteration to ship value first.
- Unmount endpoint — backend `dreamy.py` only exposes `GET` and `PUT` for `mount-folder`, no DELETE. Badge offers "Change" only.
- i18n: only `en-US` locale exists in `core/i18n/locales/`; no translations to add for other languages.
- Backend tests — no backend code was changed in these phases; no `pytest` runs needed.
