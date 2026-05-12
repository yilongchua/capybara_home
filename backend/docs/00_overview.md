# Implementation Tracker — Lead Agent Design Study Bug Fixes

**Last updated:** 2026-05-10  
**Scope:** Backend middleware fixes identified in `docs/lead_agent/LEAD_AGENT_DESIGN_STUDY.md` (P3, P4, P5, P7, P9)  
**See also:** `docs/plan_work_mode/00_overview.md` for the Plan & Work Mode feature implementation tracker

---

## Summary

| Issue | Title | Status | Source files changed | Tests |
|-------|-------|--------|----------------------|-------|
| P3 | Title generation retry on timeout | ✅ Complete | `title_middleware.py` | 3 tests added |
| P4 | Todo reminder deduplication | ✅ Complete | `todo_dag_middleware.py` | 2 tests added |
| P5 | Pro follow-up failure surfacing | ✅ Complete | `pro_followup_middleware.py` | 4 tests added (new file) |
| P7 | Prevent recursive subagent delegation | ✅ Complete | `subagents/executor.py` | 2 tests added |
| P9 | Resume meta state missing fields | ✅ Complete | `thread_state.py`, `resume_state_middleware.py` | 4 tests added |

---

## P3 — Title Generation: Retry on LLM Timeout

**Status:** ✅ Complete  
**File:** `src/agents/middlewares/title_middleware.py`

### Problem
`_generate_title` previously returned a truncated fallback string on `TimeoutError`, masking the fact that a retry would have been worthwhile. The `_bg()` task had no retry path.

### Fix
- `_generate_title` now returns `None` specifically on `(asyncio.TimeoutError, TimeoutError)`, signalling the caller to retry.
- All other exceptions still return the fallback string (permanent failure).
- `_bg()` inside `aafter_model` checks for `None`; if so, sleeps 3 s then calls `_generate_title` once more.

### Key code (title_middleware.py:167-228)
```python
except (asyncio.TimeoutError, TimeoutError):
    logger.debug("Title LLM timed out; will retry once")
    return None  # signal to _bg() that a retry is worthwhile

async def _bg() -> None:
    title = await self._generate_title(state)
    if title is None:
        await asyncio.sleep(3.0)
        title = await self._generate_title(state)
```

### Tests — `tests/test_title_middleware_core_logic.py`
| Test | What it verifies |
|------|-----------------|
| `test_generate_title_returns_none_on_timeout` | `TimeoutError` → `None` return |
| `test_generate_title_returns_fallback_on_non_timeout_error` | Other errors → fallback string |
| `test_bg_task_retries_once_on_timeout` | `_bg()` calls `_generate_title` exactly twice |

---

## P4 — Todo DAG Middleware: Reminder Deduplication

**Status:** ✅ Complete  
**File:** `src/agents/middlewares/todo_dag_middleware.py`

### Problem
`before_model` unconditionally injected a `todo_reminder` `HumanMessage` every turn whenever the todo graph was active and no `write_todos` call was found in the message history. This stacked reminders in long conversations.

### Fix
`_build_reminder` now scans the last 6 messages (≈3 turns) for an existing `HumanMessage` with `name="todo_reminder"`. If one is found, it returns `None` (no injection). Old reminders outside the 6-message window allow a fresh injection.

### Key code (todo_dag_middleware.py:216-218)
```python
recent = messages[-6:] if len(messages) >= 6 else messages
if any(isinstance(m, HumanMessage) and getattr(m, "name", None) == "todo_reminder" for m in recent):
    return None
```

### Tests — `tests/test_todo_dag_middleware.py`
| Test | What it verifies |
|------|-----------------|
| `test_before_model_skips_reminder_when_recent_reminder_present` | Suppressed when reminder in last 6 msgs |
| `test_before_model_allows_reminder_when_no_recent_reminder` | Injected when reminder outside the 6-msg window |

---

## P5 — Pro Follow-up Middleware: Background Failure Surfacing

**Status:** ✅ Complete  
**File:** `src/agents/middlewares/pro_followup_middleware.py`

### Problem
Background daemon threads running the Pro follow-up LLM call could fail silently. No mechanism existed to inform the user that deepening had failed, since SSE writers are only valid inside an active LangGraph execution context.

### Fix
- Module-level `_failed_jobs: dict[str, tuple[str, str]]` and `_failed_jobs_lock` act as a cross-thread mailbox.
- `_run_background_followup` now accepts `job_id` and records `(job_id, str(exc))` in `_failed_jobs` on failure.
- `before_model` pops any failure for the current thread and emits a `background_followup_failed` SSE event via `get_stream_writer()`.

### Key code (pro_followup_middleware.py:24-107)
```python
_failed_jobs: dict[str, tuple[str, str]] = {}  # thread_id -> (job_id, error_msg)
_failed_jobs_lock = threading.Lock()

# In _run_background_followup:
except Exception as exc:
    with _failed_jobs_lock:
        _failed_jobs[thread_id] = (job_id, str(exc))

# In before_model:
with _failed_jobs_lock:
    failed = _failed_jobs.pop(thread_id, None)
if failed:
    writer({"type": "background_followup_failed", "job_id": failed_job_id, "error": error_msg})
```

### Tests — `tests/test_pro_followup_middleware.py` (new file)
| Test | What it verifies |
|------|-----------------|
| `test_run_background_followup_records_failure` | Exception populates `_failed_jobs` with correct job_id + error |
| `test_before_model_emits_sse_for_failed_job_and_clears_entry` | SSE emitted, entry removed after pop |
| `test_before_model_does_not_emit_when_no_failure` | No emission when no failure recorded |
| `test_failed_jobs_isolation_across_threads` | Thread-A failure not emitted for Thread-B |

---

## P7 — SubagentExecutor: Prevent Recursive Delegation

**Status:** ✅ Complete  
**File:** `src/subagents/executor.py`

### Problem
A misconfigured subagent could receive the `task` tool, enabling infinite recursive delegation. This wasn't caught at construction time.

### Fix
After `_filter_tools` is applied in `SubagentExecutor.__init__`, check whether `task` still appears in the filtered list. If so, raise `RuntimeError` immediately with a clear message pointing to `disallowed_tools`.

### Key code (executor.py:163-170)
```python
task_tool_names = [t.name for t in self.tools if t.name == "task"]
if task_tool_names:
    raise RuntimeError(
        f"Subagent '{config.name}' tool list contains 'task' — "
        "recursive delegation is not allowed. "
        "Add 'task' to disallowed_tools in SubagentConfig."
    )
```

### Tests — `tests/test_subagent_executor.py` (`TestTaskToolExclusion` class)
| Test | What it verifies |
|------|-----------------|
| `test_raises_when_task_tool_present` | `RuntimeError` raised when `task` tool in list |
| `test_no_raise_when_task_tool_absent` | No error when `task` excluded via `disallowed_tools` |

---

## P9 — ResumeMetaState: Missing Interrupt-Recovery Fields

**Status:** ✅ Complete  
**Files:** `src/agents/thread_state.py`, `src/agents/middlewares/resume_state_middleware.py`

### Problem
`ResumeMetaState` lacked three fields needed for accurate interrupt recovery: which todos were `in_progress` at interrupt time, retry attempt counts per tool call, and which subagent task IDs were still in flight.

### Fix

**Schema** (`thread_state.py:84-94`):
```python
class ResumeMetaState(TypedDict, total=False):
    ...
    in_progress_todo_ids: list[str]   # todos marked in_progress at interrupt time
    retry_counts: dict[str, int]      # tool_call_id -> attempt count from retry_meta
    running_subagent_ids: list[str]   # task IDs of deferred subagent calls in flight
```

**Population** (`resume_state_middleware.py`):
- `_extract_in_progress_todo_ids`: todos with `status == "in_progress"` from `todo_graph.nodes`
- `_extract_retry_counts`: copies `retry_meta.attempts_by_tool_call`
- `_extract_running_subagent_ids`: `deferred_task_calls` not in `{completed, failed, timed_out}` (includes `running` and `pending`)

### Tests — `tests/test_resume_state_middleware.py`
| Test | What it verifies |
|------|-----------------|
| `test_resume_state_tracks_in_progress_todo_ids` | Correctly lists in_progress todo IDs |
| `test_resume_state_tracks_retry_counts` | Copies attempts_by_tool_call from retry_meta |
| `test_resume_state_tracks_running_subagent_ids` | running+pending included; completed+failed excluded |
| `test_resume_state_empty_when_no_in_progress_todos` | Empty list when no in_progress todos |

---

## Notes

- CI runs tests externally via `.github/workflows/backend-unit-tests.yml` — do not run `pytest` locally in this repo.
- All fixes are backward-compatible: no existing state fields removed, no public API signatures changed.
- P5 uses `sys.modules` stub injection in tests to avoid pulling the full `src.client` dep tree.
