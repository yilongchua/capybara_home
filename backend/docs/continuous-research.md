# Autoresearch — Agentic Learning Loop

Autoresearch is a continuous, self-driving knowledge accumulation system. Users
declare a broad **topic** and **objective**; CapyHome then anticipates the
questions a curious human would ask about that topic and pre-fills the vault
before the user ever searches.

## Mental model

> **Autoresearch is a vault warmer, not a research pipeline.**
> The unit of work is a *question*, not a *source*. "Done" means
> *novelty has decayed* — the system can no longer produce useful new
> questions — not *some sufficiency score crossed a threshold*.

## One iteration

```
load ledger + taxonomy + coverage
        │
        ▼
┌────────────────────────────────┐
│ Generator (LLM call 1)         │  proposes N sub-questions
└────────────────────────────────┘    across uncovered clusters
        │
        ▼
┌────────────────────────────────┐
│ Dedup                          │  Jaccard vs. ledger + vault search
└────────────────────────────────┘    duplicates collapse, novel survive
        │
        ▼
┌────────────────────────────────┐
│ vault-source-researcher        │  one subagent per surviving question
│ (subagent fanout, sequential)  │    saves a vault entry via
└────────────────────────────────┘    save_to_knowledge_vault
        │
        ▼
┌────────────────────────────────┐
│ Reflector (LLM call 2)         │  reads new answers → emits follow-ups
└────────────────────────────────┘
        │
        ▼
ledger updated · novelty rate computed · stop signalled if saturated
```

One scheduled run = one iteration. The scheduler tick fires the pipeline
template `knowledge-vault-autoresearch-loop` (one step, kind
`autoresearch_loop_iteration`), which calls
`src/control_plane/autoresearch_loop/loop.py:run_one_iteration`.

## Question taxonomy

12 clusters × 3 depth levels. The generator is asked to fill **breadth**
(empty clusters at L1) before drilling **depth** (L2, then L3).

Stored at `{vault_root}/00_schema/QUESTION_TAXONOMY.json` and seeded from
`src/control_plane/autoresearch_loop/taxonomy.py:DEFAULT_TAXONOMY` on first
vault initialisation. Users can edit the JSON file directly to add, remove,
or rename clusters — `load_taxonomy()` falls back to the defaults if the
file is malformed.

The clusters are:

| ID | Cluster | Lens |
|----|---------|------|
| 1 | Definition & Identity | What X is and how it is bounded |
| 2 | Composition & Structure | What X is made of |
| 3 | Process & Method | How X is made / done / used |
| 4 | Origin & History | Where X came from |
| 5 | Geography & Location | Where X is found or practiced |
| 6 | Quality & Evaluation | How to tell good X from bad X |
| 7 | Comparison & Contrast | How X relates to neighbours |
| 8 | Practical Application | Real-world uses |
| 9 | Risks & Pitfalls | What can go wrong |
| 10 | Cultural & Social Context | How X fits into people's lives |
| 11 | Tools & Resources | What you need |
| 12 | People & Authorities | Who knows about X |

## Question ledger

The ledger lives at `{vault_root}/03_ops/autoresearch/objectives/{slug}/`:
- `ledger.json` — structured nodes (TodoNode-shaped: id, content, status,
  depends_on, cluster, level, asked_by, novelty, loop_iteration,
  vault_entries, duplicate_of, researcher_summary)
- `ledger.md` — human-readable mirror with iteration summaries and
  cluster-coverage hint

Statuses: `pending`, `in_progress`, `answered`, `duplicate`, `rejected`,
`blocked`.

## Stop criteria

Single signal: **novelty decay**.

```
novelty_rate = (1 − duplicate_fraction) over last N generator-emitted questions
stop if (1 − novelty_rate) >= novelty_decay_threshold
```

Defaults (`config.yaml` → `knowledge_vault`):
- `autoresearch_novelty_decay_threshold: 0.7`
- `autoresearch_novelty_window: 10`
- `autoresearch_max_questions_per_iteration: 8`
- `autoresearch_max_researcher_fanout: 3`
- `autoresearch_dedup_similarity_threshold: 0.85`

The objective is only eligible to stop after `autoresearch_novelty_window`
generator questions exist — earlier iterations always continue.

## Lifecycle

1. **Start** — `service.start_autoresearch_objective(topic, endpoint_goal, …)`
   creates an `AutoresearchObjective`, fires a bootstrap run.
2. **Bootstrap completes** — `update_after_run` reads `iteration_summary` from
   the step output, creates the daily scheduler job (default 02:00 UTC).
3. **Daily iteration** — scheduler fires the loop template, one iteration runs.
4. **Stop** — when `iteration_summary.stop == True`, the orchestrator flips
   status to `completed_endpoint` and disables the scheduler job.
5. **Pause / Resume / Delete** — user actions toggle the scheduler job and
   objective status; delete cascades vault purge.

## Key files

| Path | Purpose |
|------|---------|
| `src/control_plane/autoresearch_loop/loop.py` | One-iteration driver |
| `src/control_plane/autoresearch_loop/generator.py` | LLM call 1: propose questions |
| `src/control_plane/autoresearch_loop/dedup.py` | Jaccard + vault search dedup |
| `src/control_plane/autoresearch_loop/researcher.py` | Dispatch to `vault-source-researcher` |
| `src/control_plane/autoresearch_loop/reflector.py` | LLM call 2: propose follow-ups |
| `src/control_plane/autoresearch_loop/stop_criteria.py` | Novelty-decay stop |
| `src/control_plane/autoresearch_loop/ledger.py` | Question ledger persistence |
| `src/control_plane/autoresearch_loop/taxonomy.py` | 12-cluster taxonomy loader |
| `src/control_plane/agents/autoresearch_agent.py` | Objective lifecycle owner |
| `src/subagents/builtins/vault_source_researcher.py` | Subagent that writes to vault |

## Configuration knobs (`KnowledgeVaultConfig`)

| Field | Default | Purpose |
|-------|--------:|---------|
| `autoresearch_max_questions_per_iteration` | 8 | Generator cap |
| `autoresearch_max_researcher_fanout` | 3 | Concurrent researchers per iteration (currently serial) |
| `autoresearch_novelty_decay_threshold` | 0.7 | Duplicate fraction that triggers stop |
| `autoresearch_novelty_window` | 10 | Recent-question window for novelty rate |
| `autoresearch_dedup_similarity_threshold` | 0.85 | Jaccard cutoff for duplicates |
| `autoresearch_objective_similarity_threshold` | 0.35 | Anti-drift floor (reserved) |
| `cot_model` | `""` | Optional override model for the generator + reflector LLM calls |

## Migration from the legacy template

The old template-based pipeline
(`knowledge-vault-autoresearch` with discover/ingest/compile/lint/synthesize/
sufficiency steps) and the sufficiency-based completion logic have been
removed. On first startup after upgrade, the control plane purges:
- Any `AutoresearchObjective` still pinned to the old template id.
- Any scheduler jobs that point at the old template id.
- The legacy template definition itself.

There is no opt-in path; users restart their objectives with `/autoresearch`
or via the Knowledge Vault tab.
