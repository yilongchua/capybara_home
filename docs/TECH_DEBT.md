# Technical Debt

This document tracks known backend agent-system debt that should stay visible when a finding is intentionally deferred or only partially reduced.

## Lead Agent, Subagents, Memory, and Context

### Subagent Timeout Cancellation

- **Status:** Open
- **Risk:** A timed-out subagent still runs in a Python worker thread until the underlying call returns. The parent reports timeout, but orphan work can continue to consume tools, mutate shared sandbox files, or update the task result holder later.
- **Current mitigation:** Timeout is surfaced to the caller and background task cleanup avoids deleting running entries prematurely.
- **Needed fix:** Move subagent execution to a cancellable process/async task boundary, or add cooperative cancellation propagation through the agent stream and tool layer.

### Complete Custom-Agent Tool Boundary

- **Status:** Partially reduced
- **Risk:** Subagents now receive the parent custom agent's configured `tool_groups` when loading config-defined tools, and runtime permission middleware runs inside subagents. Built-in and MCP tools are still assembled by `get_available_tools()` outside the `tool_groups` filter, so a stricter future policy may need explicit built-in/MCP group metadata.
- **Current mitigation:** Parent `tool_groups` are forwarded to subagent tool loading, recursive `task` remains disabled, init-time permission filtering removes obvious deny/ask tools, and `PermissionMiddleware` enforces arg-sensitive rules during subagent tool calls.
- **Needed fix:** Extend tool metadata so `tool_groups` can constrain built-ins and MCP tools consistently, then add end-to-end custom-agent delegation tests for each tool source.

### Memory Write Ordering Across Processes

- **Status:** Partially reduced
- **Risk:** In-process debounced and immediate memory updates are serialized per memory scope. Separate Python processes can still perform concurrent read-modify-write cycles against the same memory file and vector index.
- **Current mitigation:** `MemoryUpdateQueue` uses per-scope locks for debounced and summarization-triggered updates in a single backend process, and vector rows are pruned when facts are removed or evicted.
- **Needed fix:** Add file-level or SQLite-backed optimistic concurrency around memory updates, and make the updater retry on SHA/version conflicts instead of silently dropping work.
