# Chat Interface — File Map

Quick reference for all files involved in the chat interface improvements.

## Existing Files (Read-Only Reference)

### Core Chat Components
```
frontend/src/components/workspace/chats/
├── chat-box.tsx                    # ChatBox wrapper with resizable panels (artifacts + activity)
├── chat-activity-panel.tsx         # Activity panel content
├── use-thread-chat.ts              # Thread ID management hook
└── use-chat-mode.ts                # Chat mode hook (no-op)

frontend/src/components/workspace/messages/
├── message-list.tsx                # MessageList — groups & renders messages (415 lines)
├── message-list-item.tsx           # MessageListItem — single message rendering (407 lines)
├── message-group.tsx               # MessageGroup — chain of thought / tool calls (517 lines)
├── subtask-card.tsx                # SubtaskCard — subagent task display (219 lines)
├── execution-trace-panel.tsx       # Execution trace visualization
├── markdown-content.tsx            # Markdown rendering wrapper
├── artifact-link.tsx               # Artifact file link component
├── skeleton.tsx                    # Loading skeletons
├── context.ts                      # ThreadContext provider
└── index.ts                        # Re-exports MessageList

frontend/src/components/workspace/
├── input-box.tsx                   # InputBox — main chat input (973 lines) ★ KEY FILE
├── streaming-indicator.tsx         # Three bouncing dots animation (34 lines) ★ REPLACE
├── todo-list.tsx                   # Todo list above input bar
├── thread-title.tsx                # Thread title display
└── tooltip.tsx                     # Tooltip component

frontend/src/components/ai-elements/
├── prompt-input.tsx                # PromptInput — reusable input component (1423 lines)
├── task.tsx                        # Task collapsible component
├── chain-of-thought.tsx            # ChainOfThought accordion
├── shimmer.tsx                     # Shimmer text animation ★ USE FOR HIGHLIGHTING
└── conversation.tsx                # Conversation wrapper

frontend/src/core/
├── threads/types.ts                # AgentThreadState, AgentThreadContext types
├── threads/hooks.ts                # useThreadStream hook
├── dreamy/hooks/use-mounted-folder.ts       # useMountedFolder / useSaveMountedFolder
├── dreamy/hooks/use-mounted-folder-files.ts # useMountedFolderFiles ★ USE FOR @ MENTIONS
├── dreamy/hooks/use-folder-picker.ts        # useFolderPicker hook
└── i18n/locales/types.ts           # Translations interface ★ ADD chatUI keys
```

### Pages (Layout Integration Points)
```
frontend/src/app/workspace/chats/[thread_id]/page.tsx    # Main chat page ★ ADD MountFolderBadge
frontend/src/app/workspace/dreamy/[thread_id]/page.tsx   # Dreamy chat page ★ ADD MountFolderBadge
```

### UI Components (Available for Reuse)
```
frontend/src/components/ui/command.tsx        # Command popup ★ USE FOR @ MENTIONS
frontend/src/components/ui/dropdown-menu.tsx  # Dropdown menu ★ USE FOR ATTACHMENT POPUP
frontend/src/components/ui/dialog.tsx         # Dialog modal
frontend/src/components/ui/button.tsx         # Button component
frontend/src/components/ui/badge.tsx          # Badge component
```

## New Files (To Be Created)

### Phase 1: Capybara Runner
```
frontend/src/components/workspace/chat-ui/
└── capybara-runner.tsx          # Running capybara animation component

frontend/src/hooks/
└── use-current-task-description.ts  # Hook to derive active task from thread state
```

### Phase 2: Attachment Popup + Mount Badge
```
frontend/src/components/workspace/chat-ui/
├── attachment-popup.tsx         # Unified paperclip+mount popup button
└── mount-folder-badge.tsx       # Mount folder indicator pill (above input bar)
```

### Phase 3: @ File Mentions
```
frontend/src/components/workspace/chat-ui/
├── file-mention-input.tsx       # @ mention-aware textarea wrapper
├── file-mention-popup.tsx       # Command popup for file selection
└── file-mention-badge.tsx       # Highlighted mention rendering badge

frontend/src/hooks/
└── use-file-mention.ts          # @ mention detection and insertion hook
```

## Modification Map

### Files to MODIFY (not just read)

| File | What to Change | Phase |
|------|---------------|-------|
| `input-box.tsx` | Replace paperclip + mount buttons with AttachmentPopup; replace PromptInputTextarea with FileMentionInput | 2, 3 |
| `message-list.tsx` | Replace `<StreamingIndicator>` with `<CapybaraRunner>` at line 401 | 1 |
| `message-list-item.tsx` | Replace `<Loader>` in Task element with `<CapybaraRunner>` at line 177 | 1 |
| `subtask-card.tsx` | Replace `<Loader2Icon>` with `<CapybaraRunner>` at line 85 | 1 |
| `chats/[thread_id]/page.tsx` | Add `<MountFolderBadge>` above InputBox | 2 |
| `dreamy/[thread_id]/page.tsx` | Add `<MountFolderBadge>` above InputBox | 2 |
| `i18n/locales/types.ts` | Add `chatUI` section to Translations interface | 1, 2, 3 |
| `i18n/locales/en-US.ts` | Add English translations for chatUI keys | 1, 2, 3 |

### Files to READ (understand before modifying)

| File | Why Read It |
|------|-------------|
| `prompt-input.tsx` | Understand PromptInputTextarea props and behavior before wrapping it |
| `message-group.tsx` | Understand how tool calls are extracted for task description |
| `dreamy/hooks/use-mounted-folder-files.ts` | Understand MountedFolderFile type for @ popup |
| `core/tools/presentation.ts` | Understand resolveToolIconKey for task icons |
| `core/messages/utils.ts` | Understand hasToolCalls, explainLastToolCall utilities |
