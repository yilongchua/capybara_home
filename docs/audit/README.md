# Chat Audit Guide

How to reconstruct what an agent actually did during a single chat thread —
what it was asked, what it planned, which model/tool calls it made, and what
it produced — by reading the on-disk artifacts the backend already writes.

All examples below use a real thread as the reference:

- **Reference thread id:** `fa33b3bb-8994-4529-8944-05e63cfcb40e`
- **Topic:** crystal practices research (prompt #16 from
  [prompt-tunning/test_prompt.py](../../prompt-tunning/test_prompt.py))

You can swap that id for any other thread and the layout is identical.

---

## 1. Where the artifacts live

Every chat is sandboxed under `backend/.capybara-home/threads/{thread_id}/`.
For the reference thread:

```
backend/.capybara-home/threads/fa33b3bb-8994-4529-8944-05e63cfcb40e/
├── logs/
│   └── trajectory/
│       └── trajectory-1779458558-run-e7d64f5272.jsonl   # per-run event log
└── user-data/
    ├── workspace/
    │   ├── plan.md                                       # latest plan state
    │   ├── plans/                                        # versioned plan snapshots
    │   │   └── plan-20260522-140345-crystal-practices-research-and-safety-plan.md
    │   └── .prompts/                                     # captured LLM prompts
    │       └── 20260522T140238_783072Z_lead_agent_prompt_tuning.txt
    │       └── ... (one file per model call)
    └── outputs/                                          # files produced for the user
```

Supporting global stores (shared across threads):

| Path | What it holds |
|---|---|
| `backend/.capybara-home/checkpoints.db` | LangGraph SQLite checkpointer — full state per turn |
| `backend/.capybara-home/memory.json` | Global memory facts injected into prompts |
| `prompt-tunning/prompt_id_*/cycle_*_metadata.json` | Per-run metadata when the run was driven by `test_prompt.py` (chat_url, model, response_preview, copied prompt logs) |

Folder layout is created by `ThreadDataMiddleware`; the `.prompts/` capture is
gated by the `CAPYBARA_PROMPT_LOGGING_ENABLED=1` env var that `test_prompt.py`
sets in
[prompt-tunning/test_prompt.py:59](../../prompt-tunning/test_prompt.py#L59).

---

## 2. The audit checklist

For a single chat, an audit should answer:

1. **What was asked?** — initial user prompt and any follow-ups.
2. **What did the agent plan?** — plan.md and the dated plan snapshot.
3. **What ran?** — every `model_call_*` and `tool_call_*` event, in order.
4. **What did the model see?** — the rendered system prompt + messages sent
   for each model call.
5. **What did it produce?** — files written under `user-data/outputs/` and any
   `present_files` tool calls.
6. **Did anything go wrong?** — timeouts, retries, failed middleware events.
7. **What context was injected?** — which memory facts and skills appeared in
   the system prompt for that turn.

---

## 3. Step-by-step walkthrough (reference thread)

### 3.1 Locate the thread

```bash
THREAD=fa33b3bb-8994-4529-8944-05e63cfcb40e
TDIR="backend/.capybara-home/threads/$THREAD"
ls "$TDIR"
```

### 3.2 Read the original ask

The submitted prompt is preserved verbatim inside the first captured prompt
file's `messages[]` (and, for `test_prompt.py` runs, in
`prompt-tunning/prompt_id_*/cycle_*_metadata.json` under `initial_prompt`).

For this thread it is the "deeper read on crystals" prompt — prompt #16 in
[prompt-tunning/test_prompt.py:112-114](../../prompt-tunning/test_prompt.py#L112-L114).

### 3.3 Read the plan

```bash
cat "$TDIR/user-data/workspace/plan.md"
ls "$TDIR/user-data/workspace/plans/"
```

`plan.md` is overwritten as the plan evolves; `plans/` keeps timestamped
snapshots. For the reference thread, the snapshot is
`plan-20260522-140345-crystal-practices-research-and-safety-plan.md` —
status `draft`, 7 todos, awaiting Execute Plan approval.

### 3.4 Replay the run from the trajectory

The trajectory JSONL is the canonical event log. One run = one file:

```bash
TRAJ="$TDIR/logs/trajectory/trajectory-1779458558-run-e7d64f5272.jsonl"
```

Each line is `{ts, run_id, thread_id, event, payload}`. The events the
trajectory middleware emits are:

| Event | Meaning |
|---|---|
| `before_agent` / `after_agent` | Agent invocation boundary |
| `before_model` / `after_model` | Each LangGraph model node entry/exit |
| `model_call_start` / `model_call_end` | Underlying LLM HTTP call |
| `tool_call_start` / `tool_call_end` | Tool invocations (with `tool` name) |
| `tool_call_timeout` | A tool hit its per-call timeout |
| `middleware_event` | Free-form payloads from individual middlewares |

Quick aggregations for the reference thread:

```bash
# event counts
awk -F'"event":' '{print $2}' "$TRAJ" | awk -F'"' '{print $2}' | sort | uniq -c

# tools used
grep -o '"tool": "[^"]*"' "$TRAJ" | sort -u
```

For `fa33b3bb-...` this yields 6 model calls, 7 tool calls (one of which timed
out), and the tools touched were `query_knowledge_vault`, `query_lightrag`,
`web_search`, `write_todos`.

A timeline view (`ts` is unix epoch seconds, sort by it):

```bash
jq -c '{ts, event, tool: (.payload.tool // null)}' "$TRAJ" | sort
```

### 3.5 Inspect what the model actually saw

Every model call writes a JSON file under `user-data/workspace/.prompts/`
named `{utc_ts}_lead_agent_{purpose}.txt`. The reference thread has 10 such
captures from the prompt-tuning run.

```bash
ls "$TDIR/user-data/workspace/.prompts/"
jq '{timestamp_utc, model_name, invocation_params, messages: (.messages|length)}' \
  "$TDIR/user-data/workspace/.prompts/20260522T140238_783072Z_lead_agent_prompt_tuning.txt"
```

Each file contains:

- `timestamp_utc`, `actor`, `purpose`, `thread_id`
- `model_name` + `invocation_params` (provider, model id, temperature, etc.)
- the full `messages[]` exactly as sent to the LLM, including the system
  prompt with injected memory/skills and the `<memory>` block

This is the artifact to use when the question is "did the model see what we
think it saw?" — e.g. checking that a memory fact got injected, or that a
skill body was loaded.

### 3.6 Check produced files

```bash
ls "$TDIR/user-data/outputs/"
```

Empty for the reference thread — the plan was never executed past draft, so
no outputs were produced. A completed plan would show files here, typically
mirrored by `present_files` tool calls in the trajectory.

### 3.7 Check for failures

```bash
grep -E '"event":"(tool_call_timeout|tool_call_failed|after_model)"' "$TRAJ" | head
```

The reference thread has one `tool_call_timeout` line — useful as a flag
even when the final response looked fine.

### 3.8 Cross-reference checkpointer state (optional)

For deeper audits you can dump per-turn state from the SQLite checkpointer:

```bash
sqlite3 backend/.capybara-home/checkpoints.db \
  "SELECT thread_id, checkpoint_id, type, length(checkpoint) \
     FROM checkpoints WHERE thread_id='$THREAD' ORDER BY checkpoint_id;"
```

Each row is a serialized `ThreadState` (schema:
[backend/src/agents/thread_state.py](../../backend/src/agents/thread_state.py)).
This is the source of truth for `messages`, `todos`, `plan`, `artifacts`,
`uploaded_files`, etc. at every step.

### 3.9 Cross-reference the driver metadata (only for `test_prompt.py` runs)

When a thread was launched by `prompt-tunning/test_prompt.py`, its driver
metadata lives in `prompt-tunning/prompt_id_{N}/cycle_{C}_metadata.json` and
includes `thread_id`, `chat_url`, `run_config`, `response_preview`, and
references to copied prompt logs. Grep across them by thread id:

```bash
grep -rl "$THREAD" prompt-tunning/ 2>/dev/null
```

The reference thread predates per-thread driver metadata, so this returns
nothing — but it's the right starting point for newer runs.

---

## 4. One-shot audit script

For repeatable audits, the following snippet prints the full picture for any
thread id:

```bash
audit_thread() {
  local thread="$1"
  local tdir="backend/.capybara-home/threads/$thread"
  echo "== Thread $thread =="
  echo "-- plan --"
  [ -f "$tdir/user-data/workspace/plan.md" ] && head -20 "$tdir/user-data/workspace/plan.md"
  echo "-- captured prompts --"
  ls "$tdir/user-data/workspace/.prompts/" 2>/dev/null
  echo "-- outputs --"
  ls "$tdir/user-data/outputs/" 2>/dev/null
  echo "-- trajectories --"
  for traj in "$tdir"/logs/trajectory/*.jsonl; do
    [ -f "$traj" ] || continue
    echo "  $traj"
    awk -F'"event":' '{print $2}' "$traj" | awk -F'"' '{print $2}' | sort | uniq -c | sed 's/^/    /'
    grep -o '"tool": "[^"]*"' "$traj" | sort -u | sed 's/^/    used /'
  done
}

audit_thread fa33b3bb-8994-4529-8944-05e63cfcb40e
```

---

## 5. What to flag in a review

When auditing for quality/regressions, look for:

- **Plan never advanced past `draft`** — gate failed or user never approved
  (the reference thread is in this state).
- **`tool_call_timeout` events** — usually point at a slow external tool
  (knowledge vault, web search) and may correlate with degraded answers.
- **Repeated model calls with near-identical messages** — possible
  `LoopDetectionMiddleware` miss; check `middleware_event` payloads.
- **Memory facts injected that don't match the user turn** — see
  `<memory>` block inside the captured prompt; if irrelevant facts appear,
  `injection_relevance_threshold` may need tightening
  ([backend/CLAUDE.md](../../backend/CLAUDE.md) → Memory System).
- **No `present_files` despite outputs** — files written but not surfaced to
  the user; check `WriteFileArtifactMiddleware` events.
- **Subagent runs hidden from the timeline** — verify `task_*` events in the
  trajectory and that `subagent_type` / `group_id` payload fields are set.

---

## 6. Related references

- ThreadState schema:
  [backend/src/agents/thread_state.py](../../backend/src/agents/thread_state.py)
- Lead agent + middleware order:
  [backend/src/agents/lead_agent/agent.py](../../backend/src/agents/lead_agent/agent.py)
- Trajectory middleware (writes the JSONL):
  see `TrajectoryMiddleware` in
  [backend/src/agents/lead_agent/agent.py](../../backend/src/agents/lead_agent/agent.py)
- Path layout helpers:
  [backend/src/config/paths.py](../../backend/src/config/paths.py)
- Prompt-tuning driver that produced the reference thread:
  [prompt-tunning/test_prompt.py](../../prompt-tunning/test_prompt.py)
