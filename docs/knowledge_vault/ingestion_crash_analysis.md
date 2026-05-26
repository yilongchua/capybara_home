# Knowledge Vault Ingestion — Architecture & Crash Analysis

## Overview

The vault ingestion has two phases, both running sequentially inside a daemon thread spawned by `start_vault_ingest_job()` (`service.py`).

```
HTTP POST /api/vault/ingest/start
        │
        ▼
start_vault_ingest_job()          daemon thread
        │
        ├─ Phase 0: requeue_all_claimed_items()   (rescue orphaned claims)
        ├─ Phase 0b: cleanup_orphan_compiled_files() (prune compiled orphans)
        │
        ├─ Phase 1: Queue Drain
        │   ├─ claim_search_queue_items(max_items=10_000)
        │   ├─ manager.ingest(queue_items=claimed_items)
        │   │   └─ for each item:
        │   │       ├─ reingest_if_changed()
        │   │       │   ├─ HTTP fetch / use pre_extracted_content
        │   │       │   ├─ _analyze_source()       ← LLM call #1
        │   │       │   ├─ _generate_source_sections() ← LLM call #2
        │   │       │   ├─ Write raw files to disk
        │   │       │   └─ Update manifest in-memory
        │   │       └─ (progress_callback updates job dict)
        │   ├─ compile_incremental()               ← writes compiled markdown
        │   └─ _mark_queue_items()                  ← queue status → "ingested"/"rejected"
        │
        └─ Phase 2: Source Reprocessing
            └─ reprocess_existing_sources(progress_callback=...)
                └─ for each source without entity/concept refs:
                    ├─ Read raw file
                    ├─ _analyze_source()            ← LLM call #1
                    └─ Write entity/concept ref pages
```

## LLM Calls Per Item

Each queue item in Phase 1 triggers **2 LLM calls** in `reingest_if_changed()`:

| Call | Method | Prompt | Purpose |
|---|---|---|---|
| #1 | `_analyze_source()` | `ANALYZE_SOURCE_PROMPT` | Extract entities, concepts, topic_tags, summary, key_claims |
| #2 | `_generate_source_sections()` | `GENERATE_PAGE_PROMPT` | Generate compiled page markdown content |

**For 182 items: 364 LLM calls** during Phase 1 alone.

If `cot_ingest_enabled` is off or content is below `cot_min_chars`, LLM calls are skipped and heuristic analysis is used instead.

## Embedding

**Embedding does NOT happen during the ingest pipeline.** Contrary to what the UI progress label might suggest:

1. `compile_incremental()` writes compiled markdown pages and updates the in-memory search index, but does NOT build or update the vector index.
2. `VaultVectorIndex.build()` — which splits compiled pages into chunks and calls the embedding endpoint — is called **lazily**:
   - On the first vector search query after ingestion
   - Via `load()` → `build()` if the metadata file is missing or config changed
   - No "182 embedding calls" batch during ingestion.

Embedding is deferred to query time, so a crash during ingestion does not waste embedding work.

## Crash Recovery

### Job Status (In-Memory)

`_vault_ingest_job` is a thread-local dict in `service.py` protected by `self._vault_ingest_lock`. **Not persisted.** On process crash, it is lost entirely — the next ingest starts fresh.

### Queue Lease Mechanism

When `claim_search_queue_items()` claims items:
- Sets `item["status"] = "claimed"`
- Stamps `item["claim_lease_until"]` = UTC now + 900s (default)
- In-memory, then saved via `_queue_txn()`

The lease prevents parallel runners from double-processing items. On crash, claimed items remain "claimed" with an active lease.

**Recovery**: Phase 0 of every ingest run calls `requeue_all_claimed_items()` which rescues items with **expired** leases back to `status="queued"`. Items with unexpired leases are left alone.

### Manifest Transaction

`_ingest_locked()` runs inside `_manifest_txn()` — a re-entrant lock-protected context manager:

- **On entry**: Reloads manifest from disk
- **On normal exit**: Calls `_save_manifest()` (writes to disk)
- **On exception/exit**: `_save_manifest()` is NOT called — manifest rollback

### Crash Scenarios

| Crash Point | Raw Files | Manifest Saved | Queue Status | Compiled Files | Recoverable? |
|---|---|---|---|---|---|
| Mid-queue-item loop (Phase 1) | ✅ Written | ❌ | "claimed" + lease active | ❌ | ✅ After lease expiry (15 min), items requeued → re-processed |
| After `compile_incremental()` | ✅ | ❌ | "claimed" + lease active | ✅ | ✅ Same as above. Compiled files orphaned (cleaned by Phase 0b on next run if sole runner) |
| After `_mark_queue_items()` | ✅ | ❌ | ✅ Marked "ingested"/"rejected" | ✅ | ⚠️ **Partial data loss** — queue items marked consumed but no manifest records. Lost forever on next run (queue items won't be re-queued). Window: ~1ms |
| After `_save_manifest()` | ✅ | ✅ | ✅ Marked | ✅ | ✅ **Fully recovered** |

### Re-Processing on First-Run Crash

On the **first ingestion** (no prior successful manifest):

1. Process crashes at item 50/182
2. Items 1-50 have raw files on disk (orphaned)
3. Manifest was never saved — no source records or hash_history exist
4. Queue items 1-50 remain "claimed" with active leases
5. Queue items 51-182 were never claimed
6. On re-run after lease expiry (or manual re-trigger):
   - `requeue_all_claimed_items()` rescues items 1-50 back to "queued"
   - **All 182 items** are claimed and re-processed
   - Content hash dedup (`effective_last_hash`) returns `None` (empty committed history) → no dedup
   - All 364 LLM calls re-execute from scratch
   - Old raw files (items 1-50) remain orphaned in timestamp-dated package dirs

**Yes, crash mid-first-run causes a full re-run of all items and all LLM calls.**

### Crash During Phase 2 (Reprocessing)

Phase 2 is more resilient:

- `_save_manifest()` is called every **25 updated sources** (`if updated % 25 == 0`)
- On crash, at most 24 sources of work are lost
- `reprocess_existing_sources()` re-scans manifest sources and re-processes only those still missing entity/concept refs

## Atomicity Boundary

The risky gap is between `_mark_queue_items()` and the outer `_save_manifest()` in `_manifest_txn`:

```
_ingest_locked()
  ├─ for each item: reingest_if_changed()  ← writes raw files, updates in-memory manifest
  ├─ compile_incremental()                  ← writes compiled files
  ├─ _mark_queue_items()                    ← SAVES queue to disk ("ingested")
  └─ [manifest txn exit] → _save_manifest() ← SAVES manifest to disk
```

If crash happens between `_mark_queue_items()` and `_save_manifest()`:
- Queue items are permanently "ingested" (won't be retried)
- But the manifest has no source records for them
- **The data is effectively lost** (raw files survive but are unlinked from the manifest)

This window is extremely narrow (~1ms), but it exists.

## Orphaned Files

`cleanup_orphan_compiled_files()` (Phase 0b) prunes compiled markdown pages unreachable from the manifest, but **does not** clean up:

- Orphaned raw package dirs (`03_ops/raw_sources/<source_id>/<timestamp>/`)
- Unreachable queue entries
- This is a minor storage leak on each crash.

## Summary

| Aspect | Behavior |
|---|---|
| LLM calls per item | 2 (`_analyze_source` + `_generate_source_sections`) |
| Total LLM calls for 182 items | 364 (if `cot_ingest_enabled`) |
| Embedding during ingest | ❌ Deferred to first query |
| Crash mid-first-run | All 182 re-processed, all 364 LLM calls re-made |
| Crash mid-subsequent-run | Only changed/new items re-processed (content hash dedup) |
| Queue lease expiry | 15 min default, rescued on next run |
| Risk window | `_mark_queue_items` ↔ `_save_manifest` (~1ms data loss risk) |
| Orphan cleanup | Compiled files only (Phase 0b). Raw dirs accumulate. |
