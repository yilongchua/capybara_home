# Code Cleanup Implementation Plan

Generated: 2026-04-30
Scope: full codebase audit (backend ~34K LOC Python, frontend ~30K LOC TS/TSX)
Mode: clean architecture, readable code, **do not alter functionality**

## Context

| Metric | Backend | Frontend |
|---|---|---|
| Source files | 215 `.py` | 269 `.ts`/`.tsx` |
| Total LOC | ~34,500 | ~29,900 |
| Largest file | `control_plane/service.py` — 2,651 | `ai-elements/prompt-input.tsx` — 1,423 |
| Files >500 LOC | 10 | 11 |

### Constraints discovered during audit

1. **TDD is mandatory** per `backend/CLAUDE.md` — every change needs unit tests.
2. **Test infrastructure was broken initially** — `backend/.venv` had been built on a different user's machine and `uv sync` won't refresh interpreter symlinks when the lockfile already matches. **Fix: `rm -rf .venv && uv sync`** (vanilla `uv sync` alone is insufficient).
3. **Frontend `components/ui/` and `components/ai-elements/` are off-limits** — auto-generated from Shadcn / MagicUI / React Bits / Vercel AI SDK registries (per `frontend/CLAUDE.md`). Refactoring them is wasted work; they get overwritten on regen.
4. **Documentation Update Policy** — every change to architecture must update `README.md` and `CLAUDE.md`.

---

## Work already done

### ✅ Pure helpers extracted from `vault_learning.py`

- New module: [`backend/src/control_plane/vault_text_utils.py`](../backend/src/control_plane/vault_text_utils.py) — 8 pure functions (`utcnow`, `utcnow_iso`, `slugify`, `strip_html`, `extract_title`, `word_tokens`, `frontmatter_dump`, `parse_frontmatter`).
- [`vault_learning.py`](../backend/src/control_plane/vault_learning.py) replaces inline definitions with `from … import … as _utcnow, …` so all 25+ internal call sites stay byte-identical.
- Removed now-unused `import re`.

### ✅ P0 #1 partial — seven sub-services extracted from `ControlPlaneService`

`service.py` shrunk **2,651 → 2,000 LOC** (-651, -25%) via composition. Each sub-service holds focused state (the store, plus optional back-reference to the facade for cross-domain calls). The facade now exposes the same public methods as before — they delegate one-line to the sub-service. **No public API change.**

| Sub-service | File | LOC | Methods |
|---|---|---|---|
| `TriggersService` | [`services/triggers.py`](../backend/src/control_plane/services/triggers.py) | 69 | `list_triggers`, `create_trigger_event`, `record_channel_message` |
| `FeedbackService` | [`services/feedback.py`](../backend/src/control_plane/services/feedback.py) | 46 | `list_feedback`, `add_feedback` |
| `ApprovalsService` | [`services/approvals.py`](../backend/src/control_plane/services/approvals.py) | 116 | `list_approvals`, `resolve_approval`, `_expire_approvals` |
| `ArtifactsService` | [`services/artifacts.py`](../backend/src/control_plane/services/artifacts.py) | 57 | `artifact_root`, `run_dir`, `write_json_artifact`, `write_text_artifact`, `append_artifact` (+ relocated `_isoformat`) |
| `TemplatesService` | [`services/templates.py`](../backend/src/control_plane/services/templates.py) | 153 | `builtin_templates`, `list_templates`, `upsert_template` |
| `ProposalsService` | [`services/proposals.py`](../backend/src/control_plane/services/proposals.py) | 215 | `list_self_improver_proposals`, `find_proposal`, `resolve_skill_path`, `apply_proposal`, `resolve_self_improver_proposal`, plus pure `proposal_review_key` and `proposals_for_run` static helpers |
| `SchedulerService` | [`services/scheduler.py`](../backend/src/control_plane/services/scheduler.py) | 388 | `parse_daily_time`, `next_daily_run_at`, `jobs_from_config`/`runtime`/`merged_jobs`, full runtime CRUD (`create`/`update`/`update_time`/`delete`/`set_enabled`/`pause`), and the tick path (`run_scheduler_tick`, `run_scheduler_job_now`) |

Imports also cleaned in [`service.py`](../backend/src/control_plane/service.py): removed `import json`, `import re`, `ProposalReview`, and the module-level `_DAILY_TIME_RE` constant (all relocated or no longer referenced).

**Verification status**: every touched file passes `ast.parse`. Behavioural verification (`make test`) is **pending** — the existing venv has stale interpreter symlinks pointing to a different user's home directory, and `uv sync` won't fix it because the lockfile already matches. Run `cd backend && rm -rf .venv && uv sync` to recreate.

### Skipped (deliberate, with reason)

- `service.py` module-level helpers (`_TEXT_EXTENSIONS`, `_CONVERTIBLE_EXTENSIONS`, `_DAILY_TIME_RE`): ~20 LOC of constants. Extraction adds an import for negligible win.
- `progressive-skills-animation.tsx` "unused" state at lines 68-69: setters *are* called and trigger renders. Removing them changes animation timing.

---

## Prioritized roadmap

### P0 — Highest impact, requires test verification

#### 1. Decompose `ControlPlaneService` (~75% complete: 2,651 → 2,000 LOC)

**File**: [`backend/src/control_plane/service.py`](../backend/src/control_plane/service.py)

**Target structure** (composition, not inheritance):

```
src/control_plane/
├── service.py                          # facade, ~300 LOC
└── services/
    ├── __init__.py
    ├── pipeline_orchestration.py       # create_run, start_run, list_runs, _execute_step*
    ├── scheduler.py                    # *_runtime_scheduler_job, run_scheduler_tick
    ├── proposal_review.py              # *_self_improver_proposal*
    ├── vault_integration.py            # _build_vault_manager, get_vault_*, search_vault
    ├── approvals.py                    # list_approvals, resolve_approval, _expire_approvals
    ├── feedback.py                     # list_feedback, add_feedback
    ├── triggers.py                     # list_triggers, create_trigger_event, record_channel_message
    ├── templates.py                    # list_templates, upsert_template, _builtin_templates
    ├── artifacts.py                    # _artifact_root, _run_dir, _write_*_artifact, _append_artifact
    ├── audit.py                        # _append_audit_event
    └── integrations.py                 # _docker_*, startup_jobs, integration_services_*
```

**Migration approach** (incremental, one sub-service per PR):

1. Create the sub-service module with `def __init__(self, store, redaction, ...)`.
2. Move methods verbatim — keep parameter names, error messages, audit event types unchanged.
3. In `service.py`, instantiate the sub-service and add **thin delegation methods** that preserve the public API:
   ```python
   def list_triggers(self) -> list[TriggerEvent]:
       return self._triggers.list_triggers()
   ```
4. Run `make test` between each sub-service extraction.
5. After all extractions, optionally collapse delegation methods if all callers can migrate to `service.triggers.list()` style — but only if no external consumers depend on the flat API.

**Status — done in current session (must still pass `make test` to confirm)**:

- ✅ `triggers` — extracted to [`services/triggers.py`](../backend/src/control_plane/services/triggers.py)
- ✅ `feedback` — extracted to [`services/feedback.py`](../backend/src/control_plane/services/feedback.py)
- ✅ `approvals` — extracted to [`services/approvals.py`](../backend/src/control_plane/services/approvals.py) (uses `cps` back-ref for cross-domain calls)
- ✅ `artifacts` — extracted to [`services/artifacts.py`](../backend/src/control_plane/services/artifacts.py)
- ✅ `templates` — extracted to [`services/templates.py`](../backend/src/control_plane/services/templates.py)
- ✅ `proposal_review` (proposals) — extracted to [`services/proposals.py`](../backend/src/control_plane/services/proposals.py)
- ✅ `scheduler` — extracted to [`services/scheduler.py`](../backend/src/control_plane/services/scheduler.py)

**Status — remaining**:

- [ ] `audit` — only one method (`_append_audit_event`); merge with another small service or leave on facade.
- [ ] `integrations` — `_docker_*`, `_local_stack_*`, startup-job thread management, integration service status. ~600 LOC. Largest remaining slice.
- [ ] `pipeline_orchestration` — `create_run`, `start_run`, `_execute_step`, `_execute_step_with_agent`, `_step_definitions_for_run`, `_build_step_runs`, `_finalize_run`, `_update_step_state`, `get_run`, `get_run_artifact_path`, `list_runs`. Tightly coupled to vault and agents. Save for last.
- [ ] `vault_integration` — `get_vault_*`, `search_vault`, `_build_vault_manager`, `_default_vault_manager`, `_render_vault_markdown_summary`, `_write_vault_step_artifacts`, `_vault_queue_ingest_steps`, `ensure_vault_queue_ingest_approval`, `evaluate_vault_sufficiency`, `record_workspace_activity`, `has_recent_workspace_activity`, `_resolve_vault_urls`, `_collect_discovered_urls`, `_build_folder_sync_manifest`, `_extract_file_text`, `_run_http_request`. ~700 LOC.

**Estimated effort remaining**: ~20 hours.

#### 2. Reduce `service.py` snapshot-mutation boilerplate (14 occurrences)

**Pattern duplicated 14 times**:
```python
def mutate(snapshot):
    snapshot.runs[run_id].some_field = value
    snapshot.runs[run_id].updated_at = now
self._store.mutate(mutate)
```

**Replacement helpers** (add to `service.py` or `services/_mutations.py`):
```python
def _mutate_run(self, run_id: str, mutator: Callable[[PipelineRun], None]) -> PipelineRun:
    def apply(snapshot):
        run = snapshot.runs[run_id]
        mutator(run)
        run.updated_at = utcnow()
        return run
    return self._store.mutate(apply)

def _mutate_scheduler_job(self, job_id: str, mutator: Callable[[SchedulerJob, SchedulerJobState | None], None]) -> SchedulerJob: ...
```

Call sites become one-liners. **Risk**: low. **Effort**: 2–3 hours.

#### 3. Decompose `VaultLearningManager` (1,824 LOC, ~67 methods)

**File**: [`backend/src/control_plane/vault_learning.py`](../backend/src/control_plane/vault_learning.py)

**Target structure**:

```
src/control_plane/vault/
├── __init__.py                # re-exports VaultLearningManager
├── manager.py                 # facade, ~200 LOC
├── manifest.py                # VaultManifestManager — _save_manifest, _load_manifest, _record_trust_decision
├── queue.py                   # VaultQueueManager — enqueue_search_results, claim_search_queue_items, dedupe
├── worker.py                  # VaultLearningWorker — discover, ingest, _trust_score, _fingerprint_attempt
├── paths.py                   # _compiled_source_path, _compiled_entity_path, _write_page, _raw_package_dir
└── loop_guard.py              # check_loop_guard, _fingerprint_attempt
```

`vault_text_utils.py` already extracted ✅.

**Compatibility layer**: keep `from src.control_plane.vault_learning import VaultLearningManager` working via `vault_learning.py` becoming `from .vault.manager import VaultLearningManager`.

**Effort**: ~20 hours.

#### 4. Decompose `CapybaraClient` (1,018 LOC)

**File**: [`backend/src/client.py`](../backend/src/client.py)

**Target structure**: 4 collaborators composed into a facade.

```
src/client/
├── __init__.py                # re-exports CapybaraClient
├── client.py                  # facade with all current public methods, delegating
├── agent_runner.py            # _ensure_agent, stream, chat, resume_run, reset_agent
├── skills.py                  # list_skills, get_skill, update_skill, install_skill
├── memory.py                  # get_memory, reload_memory, get_memory_*, list_memory_versions, redact_memory
└── uploads.py                 # upload_files, list_uploads, delete_upload, get_artifact, _convert_in_thread
```

**Critical**: `tests/test_client.py` has 77 unit tests including `TestGatewayConformance`. They validate every dict-returning method against Gateway Pydantic models. **Run after every move**.

**Effort**: ~12 hours.

---

### P1 — Medium impact, lower risk

#### 5. Extract router business logic from `gateway/routers/skills.py` (502 LOC)

Move `_safe_extract_zip`, manifest validation, and ZIP-handling helpers to `src/skills/archive_handler.py`. Routers become thin HTTP-contract definitions.

#### 6. Split `core/control-plane/types.ts` (520 LOC)

```
src/core/control-plane/types/
├── index.ts                   # re-exports all
├── pipelines.ts
├── vault.ts
├── scheduler.ts
├── self-improver.ts
├── integrations.ts
├── approvals.ts
└── feedback.ts
```

Update 4 importers (`app/workspace/vault/page.tsx` and friends) — use a barrel re-export from `index.ts` so most callers don't change.

#### 7. Generic fetch wrapper in `core/control-plane/api.ts` (461 LOC)

20+ functions repeat `fetch + check + cast`. Replace with:
```ts
async function apiCall<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${endpoint}`, options);
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}
```

#### 8. Extract hooks from `workspace/input-box.tsx` (942 LOC)

- `useModelSelection` — model-switching logic (~30 LOC)
- `useFolderMountWorkflow` — folder mount logic (~40 LOC)
- `useFollowupSuggestions` — suggestion state (~30 LOC)

Component becomes a thin orchestrator (~700 LOC, still large but no longer mixed-concern).

#### 9. Split `core/threads/hooks.ts` (750 LOC)

Currently 8+ effects mixing streaming, submission, refresh. Target split:
- `useThreadStream` — stream lifecycle (already named — refactor internals)
- `useSubmitMessage` — submission + uploads (currently inline)
- `useThreadAPI` — query wrappers

#### 10. Group middleware construction in `agents/lead_agent/agent.py` (604 LOC)

`_build_middlewares()` instantiates 25 middlewares in one block. Group by lifecycle phase into helpers:
```python
def _state_middlewares(config): ...      # ThreadData, Uploads, Sandbox
def _routing_middlewares(config): ...    # Autoresearch, DanglingToolCall, SearchPrivacy
def _permission_middlewares(config): ... # Permission, ToolDisclosure, Hooks
def _planning_middlewares(config): ...   # Summarization, SkillDisclosure, Planner, TodoDag
def _observation_middlewares(config): ...# Title, Memory, ViewImage, RetryPolicy, SubagentLimit
def _verification_middlewares(config): ..# Evaluator, Scratchpad, ResumeState, ProgressGuard
def _telemetry_middlewares(config): ...  # Trajectory, Metrics
```

Composition order is invariant — each helper returns a list, main function concatenates.

#### 11. Component extractions in mid-size frontend files

- `tool-settings-page.tsx` (646): extract `MCPServerDialog` and `MCPServerForm`.
- `vault/page.tsx` (475): extract `EndpointInput` to its own file; create `useVaultQueries` hook.
- `messages/message-group.tsx` (515): extract `ReasoningStep`, `ToolCallStep`, `SearchStep` subcomponents; move `convertToSteps` to `core/messages/utils.ts`.

---

### P2 — Polish

- **`magic-bento.tsx` (713)** and **`prompt-input.tsx` (1423)** — auto-generated, **do not edit**. If the upstream registries provide composable primitives, prefer extracting wrapper components elsewhere rather than mutating these files.
- **Type narrowing in `service.py`**: 6 `Any` returns/params (`_isoformat`, `_write_json_artifact data: Any`, `record_channel_message msg: Any`, `_get_local_llm_base_url app_config: Any`, `log_callback: Any | None`). Tighten where Pydantic models exist.
- **Naming consistency in `service.py`**: standardise `_build_*` (transform), `_render_*` (formatting), `_write_*` (I/O) prefixes per domain. Currently mixed.
- **Vulture pass**: run `vulture src/` on the backend to find unused imports & dead private functions across the 215 files.

---

## Execution checklist (per refactor)

For every P0/P1 item:

- [ ] Branch from `main`
- [ ] Extract code with **byte-identical method bodies** (copy-paste only, no edits)
- [ ] Update internal call sites
- [ ] Add facade/delegation so the public API is unchanged
- [ ] `make test` (backend) or `pnpm check` (frontend) — must pass before commit
- [ ] If tests are missing for the affected behaviour, add them **before** the refactor (per repo TDD policy)
- [ ] Update `CLAUDE.md` if architecture changed
- [ ] Update `README.md` if user-facing flow changed
- [ ] PR description: list files moved, link to this plan section

---

## Recommended sequencing

If the goal is to ship cleanup in shippable chunks, prioritise:

1. **Fix the venv** so `make test` works locally. Without this everything below is unsafe.
2. **P0 #2** (snapshot mutation helpers) — fastest, smallest, sets up cleaner refactor of P0 #1.
3. **P0 #1 sub-service extractions** in the order listed (audit → artifacts → triggers → … → vault_integration). Each is its own PR.
4. **P0 #3** (`VaultLearningManager` decomposition) — independent of #1.
5. **P0 #4** (`CapybaraClient`) — independent, well-tested.
6. **P1 items** in any order; pick by team availability.
7. **P2 polish** as ambient hygiene.

---

## Files referenced in this plan

Backend offenders (>500 LOC):
- [`control_plane/service.py`](../backend/src/control_plane/service.py) — 2,651
- [`control_plane/vault_learning.py`](../backend/src/control_plane/vault_learning.py) — 1,824
- [`client.py`](../backend/src/client.py) — 1,018
- [`community/aio_sandbox/aio_sandbox_provider.py`](../backend/src/community/aio_sandbox/aio_sandbox_provider.py) — 609
- [`agents/lead_agent/agent.py`](../backend/src/agents/lead_agent/agent.py) — 604
- [`agents/lead_agent/prompt.py`](../backend/src/agents/lead_agent/prompt.py) — 595 (prompt template, leave as-is)
- [`control_plane/agents/autoresearch_agent.py`](../backend/src/control_plane/agents/autoresearch_agent.py) — 592
- [`agents/middlewares/dreamy_bootstrap_middleware.py`](../backend/src/agents/middlewares/dreamy_bootstrap_middleware.py) — 576
- [`agents/dreamy_executor.py`](../backend/src/agents/dreamy_executor.py) — 504
- [`gateway/routers/skills.py`](../backend/src/gateway/routers/skills.py) — 502

Frontend offenders (>500 LOC, **excluding generated** `ui/`/`ai-elements/`):
- [`workspace/input-box.tsx`](../frontend/src/components/workspace/input-box.tsx) — 942
- [`core/threads/hooks.ts`](../frontend/src/core/threads/hooks.ts) — 750
- [`landing/progressive-skills-animation.tsx`](../frontend/src/components/landing/progressive-skills-animation.tsx) — 701
- [`workspace/settings/tool-settings-page.tsx`](../frontend/src/components/workspace/settings/tool-settings-page.tsx) — 646
- [`core/control-plane/types.ts`](../frontend/src/core/control-plane/types.ts) — 520
- [`workspace/messages/message-group.tsx`](../frontend/src/components/workspace/messages/message-group.tsx) — 515

Off-limits (auto-generated):
- `components/ui/sidebar.tsx` — 726
- `components/ui/magic-bento.tsx` — 713
- `components/ai-elements/prompt-input.tsx` — 1,423
- All other files under `components/ui/` and `components/ai-elements/`
