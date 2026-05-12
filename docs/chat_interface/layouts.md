# Chat Interface — Before & After Layouts

## Current Layout (Before)

```
┌─────────────────────────────────────────────────────────────┐
│  Thread Title                    [Artifacts]                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  User: Analyze the data in my project                       │
│                                                             │
│  Assistant: [markdown response]                             │
│    🔍 Searching for related info                            │
│    📄 Reading config.yaml                                   │
│                                                             │
│  User: What about the tests?                                │
│                                                             │
│  Assistant: [thinking...]                                   │
│    ● ● ●                                                    │  ← StreamingIndicator (3 dots)
│                                                             │
│  ┌──────────────────────────────────────┐                   │
│  │ ✓ Write unit tests for auth          │                   │
│  │   in_progress · 🔄                   │                   │  ← SubtaskCard with spinner
│  └──────────────────────────────────────┘                   │
│                                                             │
│  ┌──────────────────────────────────────────────┐           │
│  │ [📎] [Mount Folder] [Workflow] [⚡ Fast ▾]   │           │
│  │                     [🤖 Auto] [🔒⚡]         │           │
│  │                     [gpt-4 ▾]    [↑]        │           │  ← Input bar
│  └──────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────┘

Issues:
  - "..." gives no context about what's happening
  - Mount Folder is a full button taking horizontal space
  - Paperclip and Mount are separate (fragmented)
  - No way to reference files by name in messages
```

## Improved Layout (After)

```
┌─────────────────────────────────────────────────────────────┐
│  Thread Title                    [Artifacts]                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  User: Analyze the data in my project                       │
│                                                             │
│  Assistant: [markdown response]                             │
│    🔍 Searching for related info                            │
│    📄 Reading config.yaml                                   │
│                                                             │
│  User: What about the tests?                                │
│                                                             │
│  Assistant:                                                   │
│    ┌─────────────────────────────────────┐                  │
│    │ 🏃 Capybara is working on:          │                  │  ← CapybaraRunner
│    │    "Writing unit tests..."     ●    │                  │
│    └─────────────────────────────────────┘                  │
│                                                             │
│  ┌──────────────────────────────────────────┐               │
│  │ 📁 /Users/you/projects      [change]     │               │  ← MountFolderBadge
│  └──────────────────────────────────────────┘               │
│  ┌──────────────────────────────────────────────┐           │
│  │ [📎 ▾] [Workflow] [⚡ Fast ▾]               │           │
│  │                [🤖 Auto] [🔒⚡]             │           │
│  │                [gpt-4 ▾]     [↑]            │           │  ← Simplified input bar
│  └──────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────┘

When typing "Can you analyze @te":
  ┌──────────────────────────────────────────────┐           │
  │ Can you analyze @"test.txt"                  │           │
  │                    ┌─────────────────────┐   │           │  ← FileMentionPopup
  │                    │ 🔍 Search files...  │   │           │
  │                    ├─────────────────────┤   │           │
  │                    │ 📄 test.txt         │◄──┼─── selected│
  │                    │ 📄 todo-list.tsx    │   │           │
  │                    └─────────────────────┘   │           │
│  └──────────────────────────────────────────────┘           │

After selection: @"test.txt" is highlighted with green border
```

## Component Hierarchy (After)

```
ChatPage
├── ChatBox (resizable panels)
│   └── ChatPanel (main chat area)
│       ├── Header (thread title + artifacts)
│       ├── MessageList
│       │   ├── MessageListItem
│       │   │   └── CapybaraRunner (in Task loading state) ★ NEW
│       │   ├── MessageGroup (chain of thought)
│       │   └── SubtaskCard
│       │       └── CapybaraRunner (in_progress icon) ★ NEW
│       ├── StreamingIndicator → REPLACED BY CapybaraRunner ★
│       └── MountFolderBadge ★ NEW
│       └── InputBox
│           ├── AttachmentPopup ★ NEW (replaces paperclip + mount buttons)
│           │   ├── Attach Files → opens file dialog
│           │   └── Mount Folder → opens folder picker
│           ├── Workflow toggle
│           ├── Mode selector (Fast/Pro)
│           ├── Auto mode toggle
│           ├── Privacy & Autoresearch dropdown
│           └── ModelSelector
│           └── FileMentionInput ★ NEW (wraps PromptInputTextarea)
│               ├── PromptInputTextarea (transparent overlay for input)
│               ├── FileMentionBadge ★ NEW (highlighted mentions in overlay)
│               └── FileMentionPopup ★ NEW (@ mention dropdown)
└── ActivityPanel (right side)
```

## State Flow for @ Mentions

```
User types "@" in textarea
        │
        ▼
useFileMention detects "@" character
        │
        ├── Get cursor position in textarea
        ├── Trigger FileMentionPopup at cursor position
        │
FileMentionPopup opens
        │
        ├── Fetch files from useMountedFolderFiles(threadId)
        ├── Show Command popup with file list
        └── User can type to filter (e.g., "te" → shows test.txt)
        │
User selects file (Enter or click)
        │
        ├── useFileMention.selectFile(file)
        │   ├── Insert @"filename" at cursor position
        │   └── Close popup
        │
        ▼
FileMentionBadge renders in overlay layer
        │
        ├── Check if file exists in mounted folder files list
        │   ├── EXISTS → green border, subtle green bg, file icon
        │   └── NOT FOUND → orange/red tint, dashed border
        │
        ▼
User sends message
        │
        ├── Message text contains @"filename" mentions
        └── Backend parses @mentions to resolve file references
```

## Capybara Runner State Machine

```
                    ┌──────────────┐
                    │   IDLE       │  No activity, no animation
                    └──────┬───────┘
                           │ thread.isLoading becomes true
                           ▼
                    ┌──────────────┐
              ┌──── │  THINKING    │  Generic "thinking" state
              │     └──────┬───────┘
              │            │ First subagent/task detected
              │            ▼
              │     ┌──────────────┐
              │     │  EXECUTING   │  Show active task description
              │     └──────┬───────┘
              │            │ Task completes, more tasks remain
              │            ▼
              │     ┌──────────────┐
              │     │  EXECUTING   │  Update to next task description
              │     └──────┬───────┘
              │            │ All tasks complete, still streaming
              │            ▼
              │     ┌──────────────┐
              └─────│  STREAMING   │  Final response streaming
                    └──────┬───────┘
                           │ thread.isLoading becomes false
                           ▼
                    ┌──────────────┐
                    │   IDLE       │  Back to idle
                    └──────────────┘
```
