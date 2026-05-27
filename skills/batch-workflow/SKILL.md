---
name: batch-workflow
description: >
  Use this skill when the user has a large list of tasks that all follow the same
  process template but operate on different data — for example: read every question
  from a file and create a detailed research report per question, enrich every row
  of an Excel using a scraping tool and write back findings, or run the same analysis
  on each item in a dataset. Each task follows the same workflow but the data differs,
  forming an intentional batch loop. Also use when some tasks require LLM reasoning
  in the middle (comparisons, yes/no decisions, cross-referencing another file).
  Trigger on: process each row, for every item in this list, batch task, loop over
  all questions, generate per-item output, bulk workflow, row-by-row analysis,
  for each entry do X, process all records, repeat this for each.
workflow: true
---

# Batch Workflow Skill

## Overview

This skill guides the agent through processing a large list of tasks where each task
follows the same workflow template but operates on different data. It handles:

- **Per-task progress visibility** — the user sees each task being worked on
- **No-result handling** — if a task returns empty data, output columns are left blank
- **Inline reasoning** — LLM can compare, decide, and write findings (e.g. yes/no)
- **Resume support** — interrupted runs restart from the last completed task
- **Flexible task sources** — Excel rows, text files, CSV, JSON arrays
- **Complex per-task workflows** — Pro-mode research, multi-step analysis via subagents

## Core Concepts

| Term | Meaning |
|------|---------|
| **Task List** | Source of work: Excel file, text file, CSV, JSON array |
| **Task** | One unit of work: one row, one question, one identifier |
| **Workflow Template** | The steps to run per task (tool calls + reasoning) |
| **Result** | Output per task: filled Excel cells, a report file, a JSON entry |
| **Checkpoint** | Progress file tracking which tasks are done (enables resume) |

## Workflow

### Phase 0 — Analyze Task List

```bash
python /mnt/skills/public/batch-workflow/scripts/load_tasks.py \
  --input /mnt/user-data/uploads/<file> \
  [--checkpoint /mnt/user-data/workspace/checkpoint.json]
```

Parse the JSON output to understand:
- Total task count and field names
- First 3 sample tasks
- Resume index (if a prior checkpoint exists — skip to that row)

### Phase 1 — Design the Workflow Template

Before running the POC, state the template explicitly:

1. **Data source**: which tool/MCP to call per task (or which column to read)
2. **Reasoning steps**: any comparisons, decisions, or cross-references needed
3. **Output shape**: column names to write (for Excel) or file name pattern (for reports)
4. **No-result rule**: if the data source returns empty/null → leave output blank,
   mark status as `no_result` — do NOT write placeholder text
5. **Decision rule** (if applicable): comparison condition → write "YES" / "NO" /
   "UNKNOWN" to a dedicated decision column

### Phase 2 — POC (First 3 Tasks)

Process tasks 1–3 using the designed template.

- **Simple tasks** (scraping → write value): call the tool directly and write results
- **Complex tasks** (research reports, multi-step analysis): spawn a subagent per
  task via the `task` tool — the subagent handles the full workflow and writes its
  output file, then returns a brief summary

Present POC results as a formatted table:

| Task ID | Key output field | Status |
|---------|-----------------|--------|
| 1 | ... | found / no_result / error |
| 2 | ... | found |
| 3 | ... | no_result |

### Phase 3 — Approval Gate

Call `ask_user_for_clarification` with `clarification_type: "risk_confirmation"` showing:
- The POC results table
- Total remaining tasks
- Estimated total time (task count × avg seconds per task)
- Confirmation of no-result and error handling rules

Wait for explicit user approval before proceeding.

### Phase 4 — Bulk Processing

After approval, process all remaining tasks using the same template from Phase 1.

#### Option A — Simple tasks (direct tool calls)

For each task:

```
1. Read task data from source
2. Call tool/MCP with task identifier
3. If result is empty → call write_result.py with --status no_result (skips data columns)
4. If result found → call write_result.py with --data '{...}'
5. If reasoning needed → apply comparison logic, write YES/NO/UNKNOWN
6. Call checkpoint.py --mark-done <task_id>
```

Because `workflow: true` is set in this skill's frontmatter, the frequency-based
loop detection (Layer 2) is disabled for this thread. The hash-based detection
(Layer 1) remains active and still catches genuine stuck loops.

#### Option B — Complex tasks (subagent delegation)

For tasks requiring full Pro-mode research or multi-step reasoning, spawn one subagent
per task:

```
task(
  prompt="<task data and full workflow instructions>",
  subagent_type="general-purpose"
)
```

The subagent writes its own output files and returns a brief status summary. The main
agent updates the checkpoint after each subagent returns, then moves to the next task.
Subagents run sequentially (one at a time) to avoid output file conflicts.

### Phase 5 — Deliver Results

For Excel output: call `present_files` with the enriched output file path.
For report files: call `present_files` listing all generated report files.

---

## No-Result Handling

When a task produces no data (empty API response, no matches, HTTP 404, etc.):

- **Do NOT** write placeholder text or "N/A" to output columns
- Call `write_result.py --status no_result` — this only updates the `_status` column
- Continue immediately to the next task

## Reasoning / Decision Steps

If the workflow requires a binary decision (e.g. cross-reference with a reference file):

1. Load the reference data **once** before the loop starts (not per task)
2. Per task: after fetching data, run the comparison
3. Write `"YES"` / `"NO"` / `"UNKNOWN"` (if reference data is missing) to the
   decision column

## Error Handling

| Condition | Action |
|-----------|--------|
| Tool/API returns empty | Write nothing; status = `no_result` |
| Tool/API error (timeout, 5xx) | Retry up to 2×; if still failing, status = `error`, write error reason to `_error` column |
| Reasoning cannot decide | Write `"UNKNOWN"` to decision column |
| Fatal error (auth failure, file missing) | Stop; report to user before restarting |

## Resume Pattern

If the run is interrupted:

```bash
python /mnt/skills/public/batch-workflow/scripts/load_tasks.py \
  --input /mnt/user-data/uploads/<file> \
  --checkpoint /mnt/user-data/workspace/checkpoint.json
```

Read `resume_index` from the output. Restart bulk processing with
`--start-task <resume_index>`. Tasks already marked done in the checkpoint are
skipped automatically by `write_result.py`.

---

## Script Reference

```
load_tasks.py
  --input <path>              Excel/CSV/JSON/text file
  [--checkpoint <path>]       Existing checkpoint JSON for resume detection
  → stdout JSON: {total, fields, samples: [...first 3...], resume_index}

write_result.py
  --output <path>             Output Excel/JSON file path
  --task-id <id>              Row number or task identifier
  --data '<json>'             Result data as JSON object (omit for no-result)
  [--status found|no_result|error]
  [--error-msg "<text>"]
  → writes result to correct row/entry; saves after every call

checkpoint.py
  --file <path>               Checkpoint JSON file path
  --mark-done <task_id>       Mark one task as completed
  → updates checkpoint file

checkpoint.py
  --file <path>
  --status                    Print human-readable progress summary
  → stdout: "Completed: 47 / 580 (8.1%)"
```

## Environment

Python dependencies used by scripts (all present in `backend/pyproject.toml`):
- `openpyxl` — Excel read/write
- `pandas` — CSV/JSON parsing (optional, falls back to stdlib csv)
- Standard library: `json`, `csv`, `argparse`, `pathlib`, `datetime`
