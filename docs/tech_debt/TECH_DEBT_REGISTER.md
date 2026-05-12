# Tech Debt Register

This register tracks high-impact technical debt across backend, frontend, and delivery workflows.

## Completed in this pass

- [x] Added frontend CI checks on pull requests (`pnpm check`).
- [x] Fixed backend lint blockers in new search/crawl community tools.
- [x] Added gateway component-level health reporting to surface degraded startup/runtime states.

## Active high-priority debt

1. Control-plane service decomposition
- Scope: `backend/src/control_plane/service.py`
- Problem: very high complexity and mixed responsibilities.
- Target: split into domain services (scheduler, approvals, integrations, vault, self-improver).
- Status: planned.

2. Async hot path blocking I/O
- Scope: generation + selected community tools + local sandbox utilities.
- Problem: synchronous network/process calls in async-adjacent paths.
- Target: progressively migrate to async I/O (`httpx.AsyncClient`, async subprocess where applicable).
- Status: planned.

3. Exception granularity
- Scope: gateway startup, control-plane, channels, community adapters.
- Problem: broad `except Exception` patterns reduce diagnosability.
- Target: typed exception handling and clearer degraded-state contracts.
- Status: in progress.

4. Frontend modularity
- Scope: oversized composite modules (`prompt-input`, stream hooks, large API client files).
- Problem: high coupling and difficult testability.
- Target: split by feature boundaries and isolate side effects.
- Status: planned.

5. Frontend test coverage
- Scope: application-facing UI and interaction paths.
- Problem: very limited test footprint.
- Target: add unit tests for hooks/components and critical integration flows.
- Status: planned.

## Next execution batches

1. Extract first control-plane slice (scheduler + runtime-job management) behind a dedicated service module.
2. Introduce shared frontend API request helper and migrate control-plane endpoints.
3. Add focused tests for gateway health/degraded behavior and first frontend hook coverage set.
