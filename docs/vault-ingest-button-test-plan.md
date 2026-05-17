# Knowledge Vault Ingest Button — Test Plan

Adds a manual ingest trigger so users can rebuild entities/concepts from
already-stored raw sources whenever the background pipeline has not produced
them (root cause for the observed "1215 sources but no concepts/entities" state
was older buggy ingest runs persisting empty `entity_refs` / `concept_refs`).

## Scope

- Backend: `VaultLearningManager.reprocess_existing_sources`
- Backend: `ControlPlaneService.start_vault_ingest_job` / `get_vault_ingest_status`
- Backend: `POST /api/vault/ingest/start`, `GET /api/vault/ingest/status`
- Frontend: vault page banner + "Run Ingest" button
- Logging: `logs/vault_ingest.log`

## Automated unit tests (added)

`backend/tests/test_vault_learning.py`

- `test_reprocess_existing_sources_backfills_entities_and_concepts` — ingests a
  source, wipes `entity_refs`/`concept_refs` from the manifest to simulate the
  legacy bug, runs `reprocess_existing_sources`, and asserts the manifest is
  rehydrated and compiled concept pages now exist.
- `test_reprocess_existing_sources_only_missing_skips_populated` — confirms
  `only_missing=True` (the default) leaves already-populated records alone so
  the button is safe to re-trigger.

`backend/tests/test_control_plane_api.py`

- `test_vault_ingest_endpoints_idle_then_start` — `/api/vault/ingest/status`
  starts at `idle`, `/api/vault/ingest/start` returns `accepted=True` with a
  job_id and log_path, and the status converges to a terminal state.
- `test_vault_ingest_start_rejects_when_already_running` — second start while a
  job is in-flight returns `accepted=False` and the friendly message.

## Manual QA

1. **Empty vault**
   - Open `/workspace/vault`.
   - Click **Run Ingest** → toast "Vault ingest started.", banner shows no
     progress label (total = 0), state returns to idle in <2 s.
2. **Backfill flow**
   - Pre-populate a few raw sources with empty refs (or use an existing
     installation whose manifest has them).
   - Click **Run Ingest** → banner shows `Source N/Total ingesting <title>…`,
     the spinner sits next to the button, and `logs/vault_ingest.log` is
     created with `vault_ingest_start` + per-item lines.
   - When done, switch to the **Knowledge** tab in the left panel — `Concepts`
     and `Entities` are no longer empty.
3. **Concurrency guard**
   - Click **Run Ingest** twice quickly → first invocation toasts "started",
     second toasts the already-running message and does not duplicate work.
4. **Refresh Cache still works**
   - With or without an ingest running, **Refresh Cache** continues to
     refresh the cached snapshot independently.
5. **Failure path**
   - Point `raw_path` of a manifest source at a non-existent file (manual edit
     of `manifest.json`), run the ingest, confirm the banner reports the
     `failed` count and `vault_ingest.log` records the warning. The job still
     finishes successfully (per-item failures do not abort the run).

## Logging assertions

After a run the file `logs/vault_ingest.log` should contain:

- One `vault_ingest_start` line with `job_id`, `force_reanalyze`, `log_path`.
- One `vault_ingest_item` line per processed source (`status=updated`,
  `skipped_no_raw`, `no_refs`, or `failed`).
- A terminal `vault_ingest_done` line with counts.

## Out of scope

- Re-fetching sources from the network (the button reuses the existing raw
  payload).
- Changing `cot_ingest_enabled` / `cot_min_chars` defaults.
- Queue-approval flow (`ensure_vault_queue_ingest_approval`) is left untouched.
