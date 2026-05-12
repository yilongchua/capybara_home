# Work Mode vs Plan+Work Mode Audit

Date: 2026-05-12  
Reference: `docs/lead_agent/pro-mode-audit-playbook.md`  
Threads audited:
- `chats/a270a57e-a9e4-4c80-9712-1ad648d13f8a`
- `chats/c04fbf42-2c11-4ee9-bec2-2b1b81a1d9e7`

## 1) Scope and Method
This audit follows the playbook workflow:
1. Confirm run context and mode from trajectory middleware events.
2. Build latency profile from trajectory events.
3. Correlate with Gateway/Nginx/LangGraph logs.
4. Separate expected polling noise from failure signals.
5. Compare output quality and operational behavior.

## 2) Mode Classification

### Thread `a270...` = Plan + Work mode
Evidence:
- Trajectory contains `planner_middleware` with `decision=plan_created` and `todo_count=4`.
- Plan artifact exists: `user-data/outputs/plans/plan-20260512-045846-comprehensive-ai-trends-report-generation.md`.
- Handoff artifacts exist under `.handoffs/`.

### Thread `c04...` = Work mode
Evidence:
- No `planner_middleware` events in trajectory.
- No plan artifact path under `user-data/outputs/plans/`.
- Direct recall + write_file execution pattern.

## 3) Performance Summary

| Metric | `a270...` (Plan+Work) | `c04...` (Work) |
|---|---:|---:|
| Trajectory events | 132 | 49 |
| Wall-clock run window | 12:58:16 to 13:04:50 (+08) | 12:48:57 to 12:54:18 (+08) |
| `before_agent -> before_model` | 0.008s | 0.008s |
| Model calls | 8 | 4 |
| Total model time | 335.022s | 319.615s |
| Max single model call | 182.118s | 136.970s |
| Median model call | 12.537s | 87.061s |
| Tool-call failures/timeouts | None in trajectory | None in trajectory |

Interpretation:
- Both runs are dominated by LLM latency, not tool latency.
- Plan+Work (`a270...`) did more orchestration steps and more model turns, but similar cumulative model time to Work mode.
- Work mode (`c04...`) was simpler but had fewer, heavier model calls.

## 4) Request/Traffic Profile (Lag/Noise)

### Thread `a270...`
- Status counts (nginx): `200=355`, `409=24`, `404=1`.
- High-volume endpoints:
  - `generation/jobs`: 111
  - `pipelines/runs`: 65
  - `threads/search`: 51
  - plan artifact fetch endpoint: 30
  - `POST /steer`: repeated 409 conflicts

Classification:
- `409` responses are consistent with steering conflicts while run state is active (expected contention signal, but noisy).
- No 5xx storm in gateway/nginx for this thread.

### Thread `c04...`
- Status counts (nginx): `200=243`, `404=1`.
- High-volume endpoints:
  - `generation/jobs`: 46
  - `pipelines/runs`: 26
  - `generation/completions`: 15

Classification:
- Very clean request profile.
- No contention pattern (no 409 series).

## 5) Error Correlation and Stability Signals

### Thread `a270...` notable issue
LangGraph shows repeated model backend failures during plan follow-up thread:
- repeated `HTTP 500` on `POST /v1/chat/completions`
- `Background Plan follow-up failed for thread a270...`
- memory update retries/failures (`Connection error`)

Interpretation:
- The primary response path completed, but asynchronous plan follow-up degraded reliability for this thread.
- This is a mode-linked operational risk: plan+work mode triggers extra follow-up paths that can fail even when final artifact is produced.

### Thread `c04...` notable issue
Trajectory shows summarization compaction fallback due to connection error:
- `summary_quality: fallback`
- `summary_error: Error generating summary: Connection error.`

Interpretation:
- Run still completed successfully.
- Summarization quality degraded but did not block output generation.

## 6) Output Quality Comparison

Artifacts:
- `a270...`: `ai-trends-report-may-2026.md` (~3801 words)
- `c04...`: `ai-trends-investment-report-2026.md` (~2768 words)

Assessment:
- `a270...` report is broader and longer, with stronger coverage depth.
- `c04...` report is tighter and more concise, with clearer investment framing.
- Both outputs are structurally usable, but `a270...` shows mild section duplication/numbering inconsistency in parts of the draft.

## 7) Findings (Mode Performance)

1. Plan+Work mode produced richer artifacts (plan + handoffs + longer report) but increased operational complexity and failure surface (follow-up 500s, steer 409 churn).
2. Work mode produced a clean operational trace with fewer backend-side anomalies and lower orchestration noise.
3. Core bottleneck in both modes is long model inference time, not tool execution.
4. For reliability-sensitive runs, work mode is currently more stable.
5. For higher-structure deliverables, plan+work mode is effective but should be hardened around async follow-up failure handling.

## 8) Recommended Actions

1. Add a guard/retry budget for async pro follow-up calls so repeated 500s are bounded and surfaced as a structured warning.
2. Debounce or suppress repeated `POST /steer` while thread state is locked/running to reduce 409 churn.
3. Add per-mode telemetry counters in run summary:
   - `planner_enabled`
   - `followup_attempts/success/failure`
   - `state_conflict_409_count`
4. Add model-phase percentile metrics by mode (`p50/p95` model call duration) to compare work vs plan+work over many runs.

## 9) Verdict
- **Best reliability in this sample:** `c04...` (Work mode)
- **Best structure/completeness in this sample:** `a270...` (Plan+Work mode)
- **Overall:** Plan+Work is higher capability but currently higher operational risk; Work mode is cleaner and steadier.
