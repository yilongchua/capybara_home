# Chat Implementation Analysis & Design

> **Purpose**: Documents the current chat message flow, architecture, and detailed implementation plan for (1) steering-based message injection and (2) queue-based message sending.

---

## 1. Architecture Overview

```
User → PromptInput → useThreadStream.sendMessage() → thread.submit() → LangGraph Server (port 2024)
                                                    ↓
                                            Middleware Chain (~30 middlewares)
                                                    ↓
                                            SSE Stream → Frontend rendering
```

### Key Files Reference

| Layer | File | Role |
|---|---|---|
| **Frontend submit** | `frontend/src/core/threads/hooks.ts:529-718` | `sendMessage()` → optimistic UI → file upload → `thread.submit()` |
| **Frontend page** | `frontend/src/app/workspace/chats/[thread_id]/page.tsx:103-140` | Wires `useThreadStream` → `handleSubmit` → `InputBox onSubmit` |
| **LangGraph SDK** | LangChain's `useStream` hook (external) + `frontend/src/core/api/api-client.ts` | SSE connection management, multi-consumer tee dedup |
| **Agent factory** | `backend/src/agents/lead_agent/agent.py:667-755` | `make_lead_agent()` builds middleware chain in topological order |
| **Middleware registry** | `backend/src/agents/lead_agent/agent.py:442-541` | `_build_middleware_registry()` — 30+ middleware specs with `after`/`before` DAG |
| **Middleware sorting** | `backend/src/agents/lead_agent/agent.py:235-278` | `_topological_sort_middleware_specs()` — Kahn's algorithm for deterministic ordering |
| **State schema** | `backend/src/agents/thread_state.py:162-193` | `ThreadState` extends LangChain `AgentState` with 25+ custom fields |
| **Gateway app** | `backend/src/gateway/app.py:1-370` | FastAPI gateway — mounts routers, CORS, API key auth, lifespan |
| **Gateway routers** | `backend/src/gateway/routers/__init__.py` | Imports all router modules (approvals, artifacts, runs, uploads, etc.) |
| **Gateway pattern** | `backend/src/gateway/routers/runs.py:1-85` | Example router — Pydantic models, LangGraph SDK client proxy |

---

## 2. Current Message Flow (Step by Step)

1. **User types** → `PromptInput` component (`frontend/src/components/ai-elements/prompt-input.tsx`)
2. **Optimistic messages created** (`hooks.ts:551-569`) — human msg + AI "uploading" placeholder shown immediately
3. **Files uploaded** (`hooks.ts:577-657`) → gateway `/api/threads/{id}/uploads`
4. **Thread submitted** (`hooks.ts:672-694`) → `thread.submit({messages: [{type: "human", ...}]}, config)`
5. **Middleware chain runs** (~30 middlewares in topological order, see `LEAD_AGENT_DESIGN_STUDY.md:491-524`)
6. **Model executes** → tool calls → more model turns until terminal answer
7. **SSE stream** → frontend processes `onCustomEvent`, `onUpdateEvent`, `onLangChainEvent`
8. **Messages rendered** → `MessageList` component (`frontend/src/components/workspace/messages/message-list.tsx`) groups by type

---

## 3. Current State: No Queuing, No Steering Injection

### Queuing
Does not exist. Each `thread.submit()` is an independent LangGraph submission. Messages are NOT queued — the user must wait for a run to complete before sending another (the UI simply doesn't allow it).

### Steering/Injection
No dedicated injection mechanism exists. Middlewares can only inject via:
- `before_model()` returning state updates (merged into ThreadState)
- Custom SSE events via `get_stream_writer()` from `langgraph.config`
- Prompt injection via `apply_prompt_template()` in `backend/src/agents/lead_agent/prompt.py`

---

## 4. Objective 1: Message Injection via Steering (Middleware)

### Where It Would Fit
A new middleware in the chain, positioned early — after `ThreadDataMiddleware` (step 1), before `UploadsMiddleware` (step 7 in the registry at `agent.py:474`).

### Design Options

**A) Steering middleware (Recommended)**
- Extend `ThreadState` with a `steering_context: str | None` field
- New `SteeringMiddleware.before_model()` reads this field and injects it as a system message
- Gateway endpoint `POST /api/threads/{id}/steer` writes to it via LangGraph SDK `update_state`
- Cleanest because it uses the existing middleware pattern and LangGraph state model

**B) External API endpoint with shared store**
- A gateway endpoint that writes to a shared state (Redis/SQLite)
- Middleware polls the store and injects changes into state
- More complex, introduces external dependency

**C) Custom SSE event handler**
- Frontend sends steering events via a separate SSE/WebSocket channel
- Backend middleware picks them up and injects into state
- Requires new transport layer

### Recommended Approach: Option A — Steering Middleware

#### 4A.1 Backend Changes

**File: `backend/src/agents/thread_state.py`** (line ~192, add after existing fields)

```python
# Steering / injection support
steering_context: NotRequired[str | None]  # External steering message injected before model call
```

**File: `backend/src/agents/middlewares/steering_middleware.py`** (new file)

```python
"""SteeringMiddleware — injects external steering context into the agent run."""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage


class SteeringMiddleware(AgentMiddleware):
    """Reads ThreadState.steering_context and injects it as a SystemMessage.

    Position in chain: after thread_data, before uploads.
    The steering context is cleared after injection so it only fires once per turn.
    """

    def before_model(self, state, runtime):
        steering = state.get("steering_context")
        if not steering or not steering.strip():
            return None
        # Inject as a system message at the front of the conversation
        return {
            "messages": [SystemMessage(content=steering.strip())],
            "steering_context": None,  # Clear after injection
        }
```

**File: `backend/src/agents/lead_agent/agent.py`** (in `_build_middleware_registry`, add after line 468)

```python
MiddlewareSpec("steering", lambda: SteeringMiddleware(), after={"thread_data"}),
```

**File: `backend/src/gateway/routers/steering.py`** (new file)

```python
"""Steering API — allows external systems to inject steering context into a thread."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["steering"])


def _langgraph_url() -> str:
    import os
    return os.getenv("CAPYBARA_LANGGRAPH_URL") or os.getenv("LANGGRAPH_URL") or "http://localhost:2024"


class SteerRequest(BaseModel):
    """Request body for steering a thread."""
    message: str = Field(..., description="Steering instruction to inject into the agent run.")


class SteerResponse(BaseModel):
    """Response body for steering."""
    thread_id: str
    acknowledged: bool


@router.post(
    "/threads/{thread_id}/steer",
    response_model=SteerResponse,
    summary="Inject steering context",
    description="Inject a steering message into the thread state. This will be injected "
                "as a SystemMessage before the next model call via SteeringMiddleware.",
)
async def steer_thread(thread_id: str, request: SteerRequest) -> SteerResponse:
    """Inject steering context into a thread's state."""
    try:
        from langgraph_sdk import get_client

        client = get_client(url=_langgraph_url())
        # Update the thread state with the steering context.
        # The SteeringMiddleware will pick it up on the next before_model() call.
        await client.threads.update_state(thread_id, {
            "values": {"steering_context": request.message},
        })
        return SteerResponse(thread_id=thread_id, acknowledged=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to steer thread: {exc}") from exc
```

**File: `backend/src/gateway/routers/__init__.py`** (add import)

```python
from . import approvals, artifacts, feedback, generation, integrations, mcp, models, pipelines, runs, skills, suggestions, steering, triggers, uploads, vault

__all__ = [
    "approvals", "artifacts", "feedback", "generation", "integrations", "mcp",
    "models", "pipelines", "runs", "skills", "suggestions", "steering",
    "triggers", "uploads", "vault",
]
```

**File: `backend/src/gateway/app.py`** (in the mount section, add)

```python
app.include_router(steering.router)
```

#### 4A.2 Frontend Changes (Optional — for UI-based steering)

**File: `frontend/src/app/workspace/chats/[thread_id]/page.tsx`** (add steer API call)

```typescript
// Add after existing imports
import { useMutation, useQueryClient } from "@tanstack/react-query";

// New mutation for steering
const queryClient = useQueryClient();
const steerMutation = useMutation({
  mutationFn: async (message: string) => {
    const res = await fetch(`/api/threads/${threadId}/steer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!res.ok) throw new Error("Failed to send steering message");
    return res.json();
  },
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
  },
});

// Expose via a function that the steering input component can call
```

---

## 5. Objective 2: Queue-Based Message Sending

### Where It Would Fit
Frontend queue management in `useThreadStream`. The `onFinish` callback already exists at `hooks.ts:496-501`.

### Design Options

**A) Frontend-only queue (Recommended)**
- `useThreadStream` maintains a `messageQueue: PromptInputMessage[]` state array
- After `onFinish`, the next queued message auto-submits
- Simple, no backend changes needed
- UI shows a queue indicator with count

**B) Backend queue**
- New endpoint `POST /api/threads/{id}/submit-queued` adds to a Redis/SQLite queue
- Background worker submits runs as they complete
- More robust but significantly more complex

**C) Hybrid**
- Frontend queues messages and polls for run completion, then auto-submits next
- Uses existing `thread.submit()` but wraps it in a queue manager hook

### Recommended Approach: Option A — Frontend-Only Queue

#### 5A. Changes to `frontend/src/core/threads/hooks.ts`

**Add queue state and logic (around line 77, after existing refs):**

```typescript
// Message queue for sequential submission
const [messageQueue, setMessageQueue] = useState<PromptInputMessage[]>([]);
const isSubmittingRef = useRef(false);

// Extend ThreadStreamOptions to accept queue callback
export type ThreadStreamOptions = {
  threadId?: string | null | undefined;
  context: LocalSettings["context"];
  isMock?: boolean;
  onStart?: (threadId: string) => void;
  onFinish?: (state: AgentThreadState) => void;
  onToolEnd?: (event: ToolEndEvent) => void;
  onContextTokens?: (event: { tokenCount: number; messageCount?: number }) => void;
  onCompaction?: (event: { messagesCompressed?: number; messagesKept?: number }) => void;
  onQueueChange?: (queueLength: number) => void;  // New callback for UI updates
};
```

**Add queue management functions (before the return statement, around line 720):**

```typescript
// Enqueue a message for sequential submission
const enqueueMessage = useCallback(
  (message: PromptInputMessage) => {
    setMessageQueue((prev) => [...prev, message]);
    listeners.current.onQueueChange?.(messageQueue.length + 1);
  },
  [messageQueue.length],
);

// Clear all queued messages
const clearQueue = useCallback(() => {
  setMessageQueue([]);
  listeners.current.onQueueChange?.(0);
}, []);

// Process queue: submit next message when run is complete
const processQueue = useCallback(async () => {
  if (messageQueue.length === 0) {
    isSubmittingRef.current = false;
    return;
  }

  const [nextMessage, ...rest] = messageQueue;
  setMessageQueue(rest);
  listeners.current.onQueueChange?.(rest.length);

  try {
    await sendMessage(threadIdRef.current!, nextMessage, context);
  } catch (error) {
    console.error("Failed to send queued message:", error);
    // Put the failed message back at the front of the queue
    setMessageQueue((prev) => [nextMessage, ...prev]);
    listeners.current.onQueueChange?.(messageQueue.length);
  }
}, [messageQueue, sendMessage, threadIdRef, context]);

// Hook into onFinish to trigger queue processing
// Modify the existing onFinish callback (line 496) to also call processQueue:
onFinish(state) {
  listeners.current.onFinish?.(state.values);
  void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
  if (threadIdRef.current) {
    publishThreadRefresh(threadIdRef.current);
  }
  // Process next queued message after a short delay
  setTimeout(() => processQueue(), 500);
},
```

**Update `sendMessage` to support queue mode (around line 529):**

```typescript
const sendMessage = useCallback(
  async (
    threadId: string,
    message: PromptInputMessage,
    extraContext?: Record<string, unknown>,
    _options?: SendMessageOptions & { queued?: boolean },  // Add queued flag
  ) => {
    // If queued mode, add to queue instead of submitting immediately
    if (_options?.queued) {
      enqueueMessage(message);
      return;
    }
    // ... existing implementation unchanged
```

#### 5B. Changes to `frontend/src/app/workspace/chats/[thread_id]/page.tsx`

**Add queue state and UI indicator (around line 103):**

```typescript
const [queueLength, setQueueLength] = useState(0);

// Wire up queue change callback
const [thread, sendMessage, liveThinkingContent] = useThreadStream({
  threadId: isNewThread ? undefined : threadId,
  context: settings.context,
  isMock,
  onContextTokens: ({ tokenCount }) => onContextTokens(tokenCount),
  onCompaction: onCompaction,
  onQueueChange: setQueueLength,  // New callback
  onStart: () => { ... },
  onFinish: (state) => { ... },
});

// Modified submit handler with queue support
const handleSubmit = useCallback(
  (message: PromptInputMessage, options?: InputBoxSubmitOptions & { queued?: boolean }) => {
    void sendMessage(threadId, message, undefined, options);
  },
  [sendMessage, threadId],
);

// Clear queue handler
const handleClearQueue = useCallback(() => {
  // Access clearQueue from the hook or manage locally
  setQueueLength(0);
}, []);
```

**Add queue indicator UI in the header (around line 193):**

```tsx
{queueLength > 0 && (
  <span
    className="text-muted-foreground rounded bg-blue-500/10 px-2 py-0.5 text-xs font-normal cursor-pointer hover:bg-blue-500/20"
    title={`${queueLength} message${queueLength > 1 ? 's' : ''} in queue. Click to clear.`}
    onClick={handleClearQueue}
  >
    {queueLength} queued
  </span>
)}
```

#### 5C. Changes to `frontend/src/components/ai-elements/prompt-input.tsx` (Optional — for queue toggle)

Add a "queue" toggle button in the prompt input toolbar that, when enabled, queues messages instead of submitting immediately:

```tsx
// New prop to support queue mode
interface PromptInputProps {
  // ... existing props
  onQueueToggle?: (queued: boolean) => void;
}
```

---

## 6. Complete File Change Summary

### Backend Files to Create/Modify

| # | File | Action | What Changes |
|---|---|---|---|
| 1 | `backend/src/agents/thread_state.py` | **Modify** (line ~192) | Add `steering_context: NotRequired[str \| None]` field |
| 2 | `backend/src/agents/middlewares/steering_middleware.py` | **Create** (new file) | New `SteeringMiddleware` — reads `steering_context`, injects SystemMessage, clears field |
| 3 | `backend/src/agents/lead_agent/agent.py` | **Modify** (line ~468, in `_build_middleware_registry`) | Add `MiddlewareSpec("steering", ...)` after `"thread_data"` |
| 4 | `backend/src/gateway/routers/steering.py` | **Create** (new file) | New `POST /api/threads/{id}/steer` endpoint using LangGraph SDK `update_state` |
| 5 | `backend/src/gateway/routers/__init__.py` | **Modify** (line 1) | Add `steering` to imports and `__all__` |
| 6 | `backend/src/gateway/app.py` | **Modify** (in router mount section) | Add `app.include_router(steering.router)` |

### Frontend Files to Create/Modify

| # | File | Action | What Changes |
|---|---|---|---|
| 1 | `frontend/src/core/threads/hooks.ts` | **Modify** (line ~32, ~77, ~496, ~529) | Add `messageQueue` state, `enqueueMessage`, `clearQueue`, `processQueue`; extend `ThreadStreamOptions` with `onQueueChange`; modify `sendMessage` to accept `{ queued: true }`; hook into `onFinish` for auto-dequeue |
| 2 | `frontend/src/app/workspace/chats/[thread_id]/page.tsx` | **Modify** (line ~103, ~193) | Add `queueLength` state; wire `onQueueChange`; add queue indicator in header with clear button |
| 3 | `frontend/src/components/ai-elements/prompt-input.tsx` | **Modify** (optional) | Add queue toggle button to toolbar row |

---

## 7. Middleware Chain Position (Steering)

The new `steering` middleware slot in the topological order:

```
 #  Middleware                        Key activation condition / position
 ──  ──────────────────────────────── ─────────────────────────────────────────
  1  ThreadDataMiddleware              Always — creates thread data dirs
  2  SteeringMiddleware (NEW)          Always — injects steering_context as SystemMessage, then clears
  3  DreamyWatchdogMiddleware          If dreamy_mode
  4  UploadsMiddleware                 Always — injects newly uploaded files
  ... (remaining middlewares unchanged)
```

Position rationale: Steering must run after `thread_data` (which sets up paths) but before `uploads` and all other middlewares, so the steering content appears at the front of the conversation context before any other injections.

---

## 8. Implementation Order & Dependencies

```
Phase 1 — Steering (backend-first, no frontend dependency)
  [S1] Add steering_context to ThreadState
  [S2] Create SteeringMiddleware
  [S3] Register in middleware registry (agent.py)
  [S4] Create gateway steering endpoint
  [S5] Wire into gateway app.py

Phase 2 — Queue (frontend-only, no backend dependency)
  [Q1] Add queue state + logic to useThreadStream (hooks.ts)
  [Q2] Wire onQueueChange callback in chat page
  [Q3] Add queue indicator UI in header
  [Q4] (Optional) Add queue toggle to PromptInput

Phase 3 — Integration (both features together)
  [I1] Add steering input component to chat page
  [I2] Wire steering mutation to /api/threads/{id}/steer endpoint
  [I3] End-to-end testing: steer during active run, verify injection
```

---

## 9. Testing Checklist

### Steering Tests (Backend)

| Test | How to Verify |
|---|---|
| SteeringMiddleware injects SystemMessage | Unit test: call `before_model()` with `steering_context` set → verify returned state contains a `SystemMessage` and `steering_context: None` |
| SteeringMiddleware is no-op when empty | Unit test: call with `steering_context = None` → returns `None` |
| Steering clears after injection | Unit test: call `before_model()` twice with same context → first call injects, second returns None |
| Gateway endpoint updates state | Integration test: `POST /api/threads/{id}/steer` → verify LangGraph state has `steering_context` set |
| Middleware runs in correct position | Verify topological sort places "steering" after "thread_data" and before "uploads" in `agent.py` |

### Queue Tests (Frontend)

| Test | How to Verify |
|---|---|
| Messages queue when `{ queued: true }` | Submit with `queued: true` → verify `messageQueue.length === 1`, no `thread.submit()` called |
| Queue auto-submits on run finish | Submit queued message → wait for `onFinish` → verify next queued message auto-submits after 500ms |
| Failed messages return to queue | Submit queued message that fails → verify it's back at front of queue |
| Clear queue removes all pending | Call `clearQueue()` → verify `messageQueue.length === 0` |
| UI shows queue count | Queue 3 messages → verify "3 queued" badge appears in header |
| Clicking badge clears queue | Click "3 queued" → verify all messages removed, no submissions in progress |

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Steering context persists across turns if middleware fails | Low | Medium | Middleware clears `steering_context` in the same return dict — LangGraph applies atomically. Add logging on injection. |
| Queue grows unbounded during long sessions | Medium | Low | Cap queue at N messages (e.g., 20). Show warning when approaching cap. |
| Queue auto-submit races with a new manual submission | Low | Medium | Check `isSubmittingRef` before dequeue; if a fresh run just started, stop the queue processor. |
| Steering endpoint called on non-existent thread | Medium | Low | LangGraph SDK `update_state` will return 404 for missing threads — gateway returns 502 as-is. |
| Steering message too large for context window | Low | High | Add a max length check on the gateway endpoint (e.g., 4000 chars). Truncate with warning. |
