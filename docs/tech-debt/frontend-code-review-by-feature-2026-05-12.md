# Frontend Code Review by Feature (Tech Debt)

Date: 2026-05-12
Scope: `frontend/`
Method: architecture + feature-path review, plus validation via `pnpm lint` and `pnpm typecheck`.

## Findings (ordered by severity)

### 1. [Critical] Path traversal risk in mock artifact file route
Feature: Mock/Static Mode Boundary, Artifact System

- `src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts:19`
- `src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts:20`
- `src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts:24`

Why this matters:
- The route resolves file paths from request params using `path.resolve(...)` after string replacement, but it does not enforce that the resolved path stays under `public/demo/threads/${threadId}`.
- Requests like `mnt/../../...` can potentially escape the intended directory.
- This endpoint also returns file bytes directly once the file exists.

Impact:
- Local file disclosure risk when mock mode is exposed.

Recommended fix:
- Build an explicit base dir and reject any normalized path outside it.
- Use `path.join(baseDir, relativePath)` with validation against traversal segments.
- Return sanitized download filenames (basename only).

### 2. [High] LangGraph client singleton ignores `isMock` after first initialization
Feature: Thread Lifecycle & Streaming Chat Engine, Mock/Static Mode Boundary

- `src/core/api/api-client.ts:142`
- `src/core/api/api-client.ts:143`
- `src/core/api/api-client.ts:144`

Why this matters:
- `getAPIClient(isMock?)` creates a single `_singleton` client once.
- If first call is non-mock, later mock calls still reuse non-mock base URL (or vice versa).
- This can silently route traffic to wrong backend, causing incorrect data source usage.

Impact:
- Cross-mode data bleed and hard-to-debug behavior in environments that mix real/mock threads.

Recommended fix:
- Maintain one client per mode key (`mock`/`real`) instead of a single global singleton.

### 3. [High] Artifact content loader does not check HTTP status
Feature: Artifact System

- `src/core/artifacts/loader.ts:21`
- `src/core/artifacts/loader.ts:22`
- `src/core/artifacts/loader.ts:23`

Why this matters:
- `loadArtifactContent` always returns `response.text()` without `response.ok` checks.
- 404/500 responses become rendered file content (for example, "File not found"), masking transport failures as valid artifact data.

Impact:
- Misleading UI states, poor operator visibility, and broken recovery logic.

Recommended fix:
- Throw typed errors on non-2xx and handle in UI with explicit error state.

### 4. [Medium] Download header leaks server absolute path
Feature: Mock/Static Mode Boundary, Artifact System

- `src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts:30`

Why this matters:
- `Content-Disposition` currently sets `filename` to full server path.
- This reveals internal filesystem structure.

Impact:
- Information disclosure and noisy UX (downloaded filename is path-like).

Recommended fix:
- Use `path.basename(artifactPath)` for the filename.

### 5. [Medium] Lint gate is failing in current frontend state
Feature: Engineering quality guardrail across all features

- `pnpm lint` exits with errors (import ordering and unnecessary type assertions across multiple files)

Why this matters:
- CI/local guardrail is red; style+consistency regressions can accumulate.
- In practice this blocks healthy merge flow and hides real issues in noisy lint output.

Impact:
- Reduced development velocity and weaker signal from static checks.

Recommended fix:
- Run `pnpm lint --fix`, then manually resolve remaining rules and keep lint green before new feature merges.

### 6. [Medium] No frontend test framework configured
Feature: Entire frontend platform

- `frontend/CLAUDE.md:23`

Why this matters:
- Critical flows (thread streaming, artifact rendering, mock/real switching, routing transitions) rely on runtime behavior but have no component/integration regression suite.

Impact:
- High probability of regressions escaping during refactors.

Recommended fix:
- Add at least a minimal test stack (Vitest + React Testing Library) and smoke tests for thread and artifact flows.

### 7. [Low] Static mode workspace redirect assumes demo thread directory exists
Feature: Application Shell & Routing, Mock/Static Mode Boundary

- `src/app/workspace/page.tsx:11`

Why this matters:
- `readdirSync` will throw if `public/demo/threads` is missing while static mode is enabled.

Impact:
- Runtime crash in misconfigured static deployments.

Recommended fix:
- Guard with existence check and fallback redirect.

## Feature-Level Review Notes

### Application Shell & Routing
- Overall route structure is clean and aligned to Next.js app router.
- Thread remount and new-thread generation logic is intentionally designed to prevent stale views.
- Debt: static-mode FS assumptions (finding #7).

### Thread Lifecycle & Streaming Chat Engine
- Strong handling for SSE dedup and run resume behavior.
- Debt: mode-sensitive singleton construction bug (finding #2).

### Message Rendering & Rich Output
- Rich markdown rendering pipeline is centralized and consistent.
- No critical rendering-blocking issues observed in reviewed files.

### Artifact System
- Good separation between URL resolution, loader, and UI hooks.
- Debt: missing HTTP error checks and mock-route path handling weaknesses (findings #1, #3, #4).

### Dreamy Workflow
- Feature breadth is strong; component and hook decomposition is good.
- Current lint failures include Dreamy-area files and should be cleaned before expanding feature scope (finding #5).

### Agents / Approvals / Vault / Integrations (Control Plane)
- Query-hook patterns and refresh domains are consistent.
- No critical correctness issue identified in sampled paths.

### Settings / i18n / Config
- Env schemas and local settings merge behavior are clear.
- Existing quality issue is mostly process-related (test/lint posture).

### Auth & Backend Boundary
- Better Auth route is wired, but broader auth hardening and enforcement posture should be reviewed separately from this frontend pass.

## Validation Commands Run
- `pnpm lint` -> failed (12 errors, 5 warnings)
- `pnpm typecheck` -> passed

## Suggested Remediation Sequence
1. Patch mock artifact route traversal + filename leak (findings #1 and #4).
2. Fix mode-aware API client singleton behavior (finding #2).
3. Add error-handling contract for artifact loader + UI fallback (finding #3).
4. Restore lint-green baseline (finding #5).
5. Add frontend smoke tests for thread/artifact/mock-mode critical paths (finding #6).
