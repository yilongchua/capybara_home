---
name: dreamy-workflow
description: >
  Active in Dreamy mode — batch-workflow execution environment. Activated only when
  the user explicitly invokes /workflow. Follow the 5-phase protocol: (1) Present
  inferred steps to user for confirmation, (2) User edits if needed, (3) POC on
  rows 1–3 with per-row timing, (4) Mandatory approval gate via ask_clarification,
  (5) Execute steps as a strict sequential executor per row.
  NEVER call task(). NEVER create workflow.json without /workflow invocation.
workflow: true
---

# Dreamy Workflow Skill

## Hard Rules (always active in this mode)

- **NO SUBAGENTS**: Never call `task()`. Disabled in Dreamy mode.
- **ONE ROW PER TOOL CALL — no batching ever**: Each bash or tool invocation
  receives the data for exactly ONE row. Never write a script that loops, iterates,
  or processes multiple rows inside a single tool call. Speed is irrelevant — the
  invariant is strict repetition of the same action, one item at a time.
- **workflow.json is the execution contract**: Once it exists, follow `steps` in
  exact order for every row. Do not invent, skip, reorder, or merge steps.
- **write_row before advancing**: For each row, all steps must complete AND
  `write_result.py` must succeed BEFORE calling `checkpoint.py --mark-done`.
  Never advance `current_row_index` without a committed write.
- **Gated design**: Do NOT create workflow.json unless the user's message started
  with `/workflow`. Without it, ask what they want done per row before doing anything.
- **Approval gate is mandatory**: After POC (rows 1–3), ALWAYS call `ask_clarification`
  with `clarification_type="risk_confirmation"`. Never proceed to row-by-row execution without confirmation.
- **execution_state is live state**: Update `current_row_index` and `current_step_id`
  in workflow.json after EVERY individual row — not at the end of a batch.

---

## workflow.json v2 Schema

```json
{
  "version": "2",
  "thread_id": "<uuid>",
  "created_at": "<ISO-8601>",
  "data_source": {
    "type": "inline|file",
    "filename": "tasks.txt",
    "total_rows": 13,
    "fields": ["Vessel Name", "IMO Number", "Vessel Type"],
    "sample_rows": [{ "Vessel Name": "...", "IMO Number": "...", "Vessel Type": "..." }]
  },
  "steps": [
    {
      "id": "step-1",
      "action": "tool_call",
      "tool": "get_vessel_particulars",
      "description": "Fetch vessel details from Equasis using IMO Number",
      "input_fields": ["IMO Number"],
      "output_fields": ["Flag", "Gross Tonnage", "Year Built", "Owner"],
      "on_no_result": "skip"
    },
    {
      "id": "step-2",
      "action": "write_row",
      "description": "Write fetched details back to the output file",
      "input_fields": ["Flag", "Gross Tonnage", "Year Built", "Owner"],
      "output_fields": []
    }
  ],
  "execution_state": {
    "phase": "design|poc|awaiting_approval|bulk|done",
    "current_row_index": 0,
    "current_step_id": null,
    "total_rows": 13,
    "poc_results": [],
    "seconds_per_row_estimate": null,
    "estimated_completion_iso": null,
    "started_at": null
  }
}
```

**Step action types:**

| action | Semantics |
|--------|-----------|
| `tool_call` | Call `tool` with `input_fields` from the row; store results in `output_fields` |
| `write_row` | Write accumulated `output_fields` to the output file for the current row |
| `conditional` | Evaluate `condition`; branch to `on_true_step_id` / `on_false_step_id` |

---

## Phase 0 — Present Steps to User

The bootstrap middleware has already:
- Detected the structured data from the message body or uploaded file
- Called the LLM once to infer `steps` from the schema
- Written `workflow.json` v2 to `/mnt/user-data/outputs/workflow.json`

Your job: read `workflow.json` and present the steps to the user as a clear table:

| Step | Action | Tool | Input Fields | Output Fields |
|------|--------|------|-------------|---------------|
| step-1 | tool_call | get_vessel_particulars | IMO Number | Flag, Gross Tonnage, Year Built |
| step-2 | write_row | — | Flag, Gross Tonnage, Year Built | — |

Ask the user to confirm or edit the steps before proceeding to POC.
Keep `execution_state.phase = "design"` until the user says to proceed.

---

## Phase 1 — Design (User Edits)

If the user wants to edit steps, update `workflow.json` using `str_replace_based_edit`.
Each edit must keep the v2 schema valid.

When the user confirms the steps, write:
```python
data['execution_state']['phase'] = 'poc'
```
Then proceed to Phase 2.

---

## Phase 2 — POC (Rows 1–3)

Initialize checkpoint:
```bash
python /mnt/skills/batch-workflow/scripts/checkpoint.py \
  --file /mnt/user-data/outputs/checkpoint.json \
  --init --total <total_rows>
```

For each of rows 0, 1, 2 (or fewer if `total_rows < 3`):

1. Note wall-clock time before starting the row
2. For each step in `workflow.steps` (in order):
   a. Write `execution_state.current_step_id = step.id` to `workflow.json`
   b. Execute the step:
      - `action=tool_call`: call `step.tool` with `step.input_fields` from the row
      - `action=write_row`: call `write_result.py` with accumulated output data
      - `action=conditional`: evaluate `condition`; branch accordingly
   c. If tool returns empty and `step.on_no_result = "skip"`: mark `no_result`, move to next row
3. Note elapsed seconds after all steps complete for the row
4. Append to `execution_state.poc_results`:
   ```json
   {"row_index": 0, "status": "found|no_result|error", "seconds": 28}
   ```
5. Call `checkpoint.py --mark-done <row_index>`

After all POC rows, write:
```python
import json, statistics
data = json.load(open('/mnt/user-data/outputs/workflow.json'))
seconds_list = [r['seconds'] for r in data['execution_state']['poc_results'] if r.get('seconds')]
avg = round(statistics.mean(seconds_list)) if seconds_list else 30
data['execution_state']['phase'] = 'poc'          # middleware flips to awaiting_approval
data['execution_state']['current_row_index'] = <completed_count>
data['execution_state']['seconds_per_row_estimate'] = avg
json.dump(data, open('/mnt/user-data/outputs/workflow.json', 'w'), indent=2)
```

Present POC results as a table:

| Row | Key Output | Status | Time |
|-----|-----------|--------|------|
| 1 | ... | found | 28s |
| 2 | ... | found | 31s |
| 3 | ... | no_result | 22s |

Then immediately call `ask_clarification` (do not wait for the middleware to remind you).

---

## Phase 3 — Approval Gate

ALWAYS call `ask_clarification` after POC. Never skip this step.

```python
remaining = total_rows - completed_poc_rows
est_minutes = round(seconds_per_row_estimate * remaining / 60, 1)
ask_clarification(
    question=(
        f"POC complete for rows 1–{completed_poc_rows}.\n\n"
        f"**Results:**\n{poc_table_markdown}\n\n"
        f"**Remaining rows:** {remaining}\n"
        f"**Estimated time:** ~{est_minutes} minutes "
        f"({seconds_per_row_estimate}s per row)\n\n"
        "Proceed with row-by-row execution for all remaining rows?"
    ),
    clarification_type="risk_confirmation",
    options=["Yes, proceed", "No, cancel"],
)
```

On user confirmation, write to `workflow.json`:
```python
data['execution_state']['phase'] = 'bulk'
data['execution_state']['current_row_index'] = <completed_poc_rows>
data['execution_state']['current_step_id'] = steps[0]['id']
data['execution_state']['started_at'] = datetime.now(timezone.utc).isoformat()
# compute estimated_completion_iso from now + remaining * seconds_per_row
```

---

## Phase 4 — Full Run (Executor Contract)

You are a **strict executor**, not a planner. Repeat the same workflow for every row.
Never deviate from `workflow.steps`. Never batch.

### The Row Loop

Process one row at a time, advancing only after a completed write + checkpoint:

```
row_index = current_row_index   ← read from workflow.json

REPEAT until row_index == total_rows:

  ── Step loop (one step at a time) ──────────────────────────────────
  accumulated = {}   ← in-memory output fields for this row

  for step in workflow.steps:

    1. Write to workflow.json:
         execution_state.current_step_id = step.id

    2. Execute EXACTLY for THIS row's data (no loops, no batches):

       action=tool_call:
         • Extract step.input_fields values from this row only
         • Call step.tool with those values (one call, one row)
         • Store result values in accumulated[step.output_fields]
         • If empty and on_no_result="skip": goto NO_RESULT

       action=write_row:
         • Call write_result.py with accumulated output fields
         • This MUST succeed before advancing

       action=conditional:
         • Evaluate step.condition against this row's data
         • Route to on_true_step_id or on_false_step_id accordingly

  ── Row commit ──────────────────────────────────────────────────────
  3. call checkpoint.py --mark-done <row_index>
  4. Write to workflow.json:
       execution_state.current_row_index = row_index + 1
       execution_state.current_step_id = null

  row_index += 1
  continue to next row

  ── No-result branch ────────────────────────────────────────────────
  NO_RESULT:
    call write_result.py --status no_result
    call checkpoint.py --mark-done <row_index>
    write execution_state.current_row_index = row_index + 1
    row_index += 1
    continue

  ── Error branch ────────────────────────────────────────────────────
  ERROR (after 2 retries):
    call write_result.py --status error --error-msg "<reason>"
    call checkpoint.py --mark-done <row_index>
    write execution_state.current_row_index = row_index + 1
    row_index += 1
    continue
```

### What "one row per tool call" means in practice

```bash
# ✅ CORRECT — one row's values passed as arguments
python script.py --a "7" --op "+" --b "6"

# ❌ WRONG — script reads the whole file and loops internally
python script.py --input /mnt/user-data/outputs/starting_point.csv
```

If using bash for computation, the command receives only THIS row's field values, not the file path. The file path is only valid in `load_tasks.py` at initialisation and `write_result.py` for output.

### After all rows

Write to workflow.json:
```python
data['execution_state']['phase'] = 'done'
data['execution_state']['current_step_id'] = None
```

Call `present_files` with the output file.

---

## Context Anchoring (Long Runs)

For runs with many rows (hundreds to tens of thousands), the system automatically injects
a `dreamy_anchor` system_reminder before the first model call of each new row. This anchor:

- Is read fresh from `workflow.json` on disk — always authoritative even after context compression
- Contains the current phase, row index, active step, and output file path
- Repeats the no-batch rule

**If you see a `dreamy_anchor` message, trust it as the execution state.** It supersedes
any stale row counts or file paths from earlier in the conversation history.

```
<system_reminder>
DREAMY EXECUTOR — phase=bulk, row 247 of 30000
current_step_id: step-1
Output file: /mnt/user-data/outputs/leads_results.csv (do NOT modify the source file)
RULES: (1) One tool/bash call = exactly ONE row's data ...
</system_reminder>
```

---

## No-Result Handling

- Do NOT write placeholder text ("N/A", "—", "not found") to output columns
- Call `write_result.py --status no_result` — only `_status` column is updated
- Continue immediately to the next row

---

## Resume Pattern

If the run is interrupted, check the checkpoint:
```bash
python /mnt/skills/batch-workflow/scripts/load_tasks.py \
  --input /mnt/user-data/uploads/tasks.txt \
  --checkpoint /mnt/user-data/outputs/checkpoint.json
```

Read `resume_index` and restart row-by-row execution from that row.

---

## Script Reference

```
load_tasks.py
  --input <path>              Excel/CSV/JSON/text file
  [--checkpoint <path>]       Existing checkpoint for resume detection
  → stdout JSON: {total, fields, samples, resume_index}

write_result.py
  --output <path>             Output file (.xlsx or .json)
  --task-id <id>              Row index (1-based)
  --data '<json>'             Result data as JSON object (omit for no-result)
  [--status found|no_result|error]
  [--error-msg "<text>"]

checkpoint.py
  --file <path>
  --init --total <N>          Initialise for N rows
  --mark-done <row_index>     Mark one row complete
  --status                    Print progress summary
```

All scripts are at `/mnt/skills/batch-workflow/scripts/`.
