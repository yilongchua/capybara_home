# Autoresearch Deep Dive

## Triggering Paths

### 1) Chat middleware path

File: `backend/src/agents/middlewares/autoresearch_middleware.py`

- `wrap_model_call()` and `awrap_model_call()` detect:
- `autoresearch`
- `autoresearch - <topic>`
- `_derive_topic()` extracts topic from explicit input or recent human context.
- `_derive_endpoint_goal()` builds a default endpoint goal from topic + recent context lines.
- `_handle_autoresearch()` records workspace activity, validates template availability, then starts objective.
- `after_agent()` records non-autoresearch user activity for inactivity-gating logic.

### 2) API path

File: `backend/src/gateway/routers/pipelines.py`

`POST /api/pipelines/autoresearch/start` calls service start with:
- `topic`
- `endpoint_goal`
- `thread_id`
- `objective_id`
- `daily_time`
- `bootstrap`
- `summary`

## Objective Lifecycle Orchestration

File: `backend/src/control_plane/agents/autoresearch_agent.py`

### Creation / restart
- `start_objective()` validates topic + endpoint goal, checks template existence, then:
- creates new `AutoresearchObjective`, or
- restarts existing one and resumes scheduler job.
- Starts bootstrap run (`forced_plan_mode`, `subagents_enabled`, `long_running_visible`).
- Writes progress ledger files (`progress.md`, `progress.json`).

### Pause / resume
- `pause_objective()` sets status `paused_denied`, disables scheduler job.
- `resume_objective()` sets status `active`, re-enables scheduler job.

### Completion and endpoint handling
- `update_after_sufficiency()` consumes sufficiency report.
- If decision is `sufficient` and no blockers:
- marks objective `completed_endpoint`
- sets pause reason `endpoint_reached`
- disables scheduler job
- rewrites progress ledger.

### Run post-processing
- `update_after_run()` derives `recommended_tasks` + `recommended_queries` from step reports.
- First successful run creates/upserts daily schedule via `_upsert_daily_schedule()`.

### Cleanup
- `delete_objective()`:
- removes matching runtime scheduler jobs
- calls vault purge (`VaultLearningManager.purge_objective()`)
- removes objective from snapshot
- appends audit event
- returns deleted payload with removed scheduler job IDs.

## Objective State Model

File: `backend/src/control_plane/models.py`

`AutoresearchObjective` stores:
- user-facing identifiers (`objective_id`, `topic`, `endpoint_goal`)
- status (`active`, `paused_denied`, `completed_endpoint`)
- schedule fields (`scheduler_job_id`, `schedule_daily_time`)
- latest run + sufficiency metadata
- recommendations
- milestone history
- progress ledger paths

## Scheduler + Activity Behavior

File: `backend/src/control_plane/service.py`

- `record_workspace_activity()` logs workspace trigger events.
- `has_recent_workspace_activity(hours=24)` powers inactivity gating.
- `_resume_inactive_autoresearch_jobs()` re-enables disabled active objective jobs when fresh workspace activity appears.

Behavioral intent:
- skip vault discover/ingest when workspace inactive
- do not permanently disable schedules for inactivity skip
- keep long-running objective alive until endpoint reached or manual intervention
