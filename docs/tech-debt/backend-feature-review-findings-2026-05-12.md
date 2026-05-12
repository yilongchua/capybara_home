# Backend Feature-Based Code Review (Tech Debt)

Date: 2026-05-12  
Scope: `backend/src`  
Method: feature-first static review of runtime, API, sandbox, subagents, memory, and extensions paths.

## Critical Findings

### 1) Host-level sandbox escape risk in local provider
- Severity: Critical
- Feature: Sandbox & File Operations
- Evidence:
  - `subprocess.run(..., shell=True)` executes arbitrary command text directly ([local_sandbox.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/sandbox/local/local_sandbox.py#L152)).
  - File operations (`read_file`, `write_file`, `update_file`) accept resolved host paths with no thread-root boundary check ([local_sandbox.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/sandbox/local/local_sandbox.py#L180)).
- Risk:
  - In local mode, any successful prompt/tool invocation can read/write outside thread directories and execute host commands with process permissions.
- Recommended remediation:
  - Enforce an allowlist root boundary (`workspace/uploads/outputs/skills`) before command/file access.
  - Add explicit denylist for sensitive host paths.
  - Consider removing `shell=True` (or hard-gating dangerous shell usage by policy).

### 2) Mounted-folder path can expose arbitrary host directories
- Severity: Critical
- Feature: Dreamy Mounted Folder + Artifacts
- Evidence:
  - API accepts any existing absolute directory path and persists it as mount root ([dreamy.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/gateway/routers/dreamy.py#L148)).
  - Mounted file listing returns host `full_path` values ([dreamy.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/gateway/routers/dreamy.py#L136)).
  - Artifact resolution trusts configured mount root and serves files under it ([artifacts.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/gateway/routers/artifacts.py#L170)).
- Risk:
  - Sensitive host data can be browsed and surfaced through API once mounted.
- Recommended remediation:
  - Restrict mount root to configured safe bases.
  - Remove `full_path` from API response.
  - Add authorization checks and audit logging for mount changes.

### 3) Upload endpoint is vulnerable to memory/resource exhaustion
- Severity: High
- Feature: Upload Lifecycle
- Evidence:
  - Entire file is loaded into memory (`content = await file.read()`) before write ([uploads.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/gateway/routers/uploads.py#L115)).
  - No explicit file size/count/type limits in router.
- Risk:
  - Large or multiple uploads can exhaust worker memory and degrade service.
- Recommended remediation:
  - Stream to disk in chunks.
  - Enforce per-file and per-request limits.
  - Add conversion worker isolation and timeout caps for heavy formats.

### 4) Subagent timeout does not guarantee execution stop
- Severity: High
- Feature: Subagent Delegation
- Evidence:
  - Timeout sets status and calls `execution_future.cancel()` with best-effort note ([executor.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/subagents/executor.py#L422)).
- Risk:
  - Timed-out tasks may continue running in background pool, causing hidden resource contention and side effects.
- Recommended remediation:
  - Move subagent execution to killable process boundary (not thread-only).
  - Add cooperative cancellation token checks inside long-running execution loops.

### 5) Artifact HTML is served inline without isolation controls
- Severity: High
- Feature: Artifact Serving
- Evidence:
  - HTML artifacts are returned with `HTMLResponse(content=...)` ([artifacts.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/gateway/routers/artifacts.py#L191)).
- Risk:
  - Stored XSS risk if untrusted/generated HTML is opened in authenticated UI context.
- Recommended remediation:
  - Default to download for HTML, or serve from isolated origin/sandboxed iframe with strict CSP.

## Medium Findings

### 6) Skill state updates are non-atomic and race-prone
- Severity: Medium
- Feature: Skills Management
- Evidence:
  - Direct overwrite via `open(config_path, "w")` + `json.dump` ([skills.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/gateway/routers/skills.py#L348)).
- Risk:
  - Concurrent writes may corrupt `extensions_config.json` or lose changes.
- Recommended remediation:
  - Use atomic temp-file + replace strategy and process-level lock.

### 7) Env var resolution skips string items inside lists
- Severity: Medium
- Feature: Extensions/MCP Config
- Evidence:
  - List handling only recursively resolves dict entries; string list items are untouched ([extensions_config.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/config/extensions_config.py#L185)).
- Risk:
  - `$VAR` placeholders in list fields (e.g., args/header fragments) silently remain unresolved, causing misconfiguration drift.
- Recommended remediation:
  - Resolve list items recursively for both dict and string values.

### 8) Memory queue uses `print` and swallows update failures
- Severity: Medium
- Feature: Memory Pipeline
- Evidence:
  - Operational events emitted via `print(...)` instead of structured logs ([queue.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/agents/memory/queue.py#L69)).
  - Per-thread update exceptions are caught and only printed ([queue.py](/Users/ryan_chua/Desktop/capybara-home/backend/src/agents/memory/queue.py#L133)).
- Risk:
  - Production observability is weak; failures are easy to miss and not consistently monitored.
- Recommended remediation:
  - Replace `print` with leveled logger events + metric counters for success/failure/retry.
  - Add dead-letter queue or retry envelope with capped backoff.

## Low / Structural Tech Debt

### 9) Broad exception swallowing across critical paths
- Severity: Low
- Feature: Cross-cutting Reliability
- Evidence:
  - Numerous `except Exception` blocks in gateway/channel/control-plane/middleware modules (example patterns across `gateway/app.py`, `channels/*`, `control_plane/*`).
- Risk:
  - Root-cause visibility and deterministic error behavior degrade over time.
- Recommended remediation:
  - Standardize typed exceptions and structured error responses.
  - Reserve broad catches for explicit safety boundaries with enriched context.

## Feature Coverage Summary
- Reviewed critical backend features: runtime orchestration, sandbox/tooling, gateway artifacts/uploads/skills/runs, dreamy mount flow, subagent execution, memory queue, MCP/extensions loading.
- Highest-risk areas cluster around: sandbox trust boundaries, mounted folder exposure, and cancellation/resource control for long-running delegated tasks.
