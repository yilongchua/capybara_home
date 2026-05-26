# Dreamy — Backend File Inventory

Every backend path Dreamy owned or modified, with the action needed to (a) recreate it or (b) edit the surviving file when reinstating Dreamy.

> **Convention:** "Whole-file" = file existed solely for Dreamy and can be recreated verbatim. "Surgical edit" = file has non-Dreamy responsibilities; the listed lines are the ones to add back.

## Whole-File (re-create these in full)

### `backend/src/agents/middlewares/dreamy_intent_middleware.py`

Strips `/dreamy` and `/workflow` prefixes from the latest human turn, classifies workflow-design intent, handles `/dreamy-exit`. The full file content is reproduced below as it was at removal time:

```python
from __future__ import annotations

import re
from typing import NotRequired, TypedDict, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event


class DreamyIntent(TypedDict):
    shape: str
    intent_class: str
    confidence: float
    extracted_fields: list[str]
    inferred_goal: str
    workflow_requested: bool


class DreamyIntentState(AgentState):
    dreamy_mode: NotRequired[bool]
    dreamy_intent: NotRequired[DreamyIntent]


class DreamyIntentMiddleware(AgentMiddleware[DreamyIntentState]):
    """Detect Dreamy workflow-design intent from explicit commands or follow-up prompts."""

    state_schema = DreamyIntentState

    _CSV_SPLIT_RE = re.compile(r"\s*,\s*")

    @staticmethod
    def _strip_workflow_command(text: str) -> str:
        stripped = text.lstrip()
        if stripped.startswith("/dreamy"):
            remainder = stripped[len("/dreamy"):]
            if remainder.startswith("\n"):
                remainder = remainder[1:]
            return remainder.lstrip()
        if not stripped.startswith("/workflow"):
            return text
        remainder = stripped[len("/workflow"):]
        if remainder.startswith("\n"):
            remainder = remainder[1:]
        return remainder.lstrip()

    @staticmethod
    def _is_dreamy_mode(runtime: Runtime) -> bool:
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return False
        return bool(context.get("dreamy_mode", False))

    # ... (full body matches the version shipped pre-removal — see git history if exact bytes are needed)
```

> **Re-creation note:** A copy of the complete file is in the repository's git history. To reinstate, restore the file at commit `pre-dreamy-removal`. The classifier itself is small (~150 LOC) and easy to re-derive from the schema in `DreamyIntent`.

### `backend/src/agents/middlewares/dreamy_watchdog_middleware.py`

`DreamyWatchdogMiddleware`. Bounded-time watchdog. Reads `DreamyTimeoutConfig` (see below). Cancels or flags Dreamy runs that exceed `total_run_timeout_seconds`, `idle_timeout_seconds`, etc. Hooks `before_agent` and `after_model`. ~12.5 KB.

### `backend/src/agents/middlewares/dreamy_bootstrap_middleware.py`

`DreamyBootstrapMiddleware`. One-shot bootstrap for a Dreamy thread. Inspects `dreamy_mount.json`, detects the data source (mounted folder, CSV, inline), and may shell out to a `load_tasks.py` helper (subprocess, bounded by `DreamyTimeoutConfig.bootstrap_subprocess_timeout`). Emits the initial `workflow.json` skeleton if missing. ~28.7 KB — the heaviest of the five.

### `backend/src/agents/middlewares/dreamy_poc_middleware.py`

`DreamyPocMiddleware`. Proof-of-concept phase. Runs the workflow against a small sample so the user can approve before bulk execution. Sets `execution_state.phase = "awaiting_approval"` and surfaces `poc_results`. ~7.9 KB.

### `backend/src/agents/middlewares/dreamy_execution_middleware.py`

`DreamyExecutionMiddleware`. Bulk-execution driver. Reads `execution_state.current_row_index` / `current_step_id`, executes one step per turn, writes state back atomically, and invokes `checkpoint.py --mark-done` after each completed row. ~9 KB.

### `backend/src/agents/memory/dreamy_state_preservation_hook.py`

Module-level functions (not a class) plugged into `CapyHomeSummarizationMiddleware.before_summarization`:

- `dreamy_state_preservation_hook(event)` — snapshot the last 5 messages whose `name == "dreamy_anchor"`, the current `dreamy_intent`, and persist to `<thread_dir>/dreamy_resumption.json`.
- `load_dreamy_resumption(thread_id)` — read back the snapshot.

Hook contract:

```python
def dreamy_state_preservation_hook(event) -> None:
    context = event.runtime.context if hasattr(event, "runtime") else {}
    if not context.get("dreamy_mode"):
        return
    # ... persist anchor messages + dreamy_intent ...
```

Wired in `_create_summarization_middleware`:

```python
hooks = [memory_flush_hook] if get_memory_config().enabled else []
if dreamy_mode:
    hooks.append(dreamy_state_preservation_hook)
```

### `backend/src/gateway/routers/dreamy.py`

The whole gateway router. ~1668 LOC. Owns:

- `workflow.json` GET/PATCH (with in-memory v1→v2 migration via `_maybe_migrate_v1`).
- Mount-folder GET/POST (`<user-data>/dreamy_mount.json`).
- `/analyse` (deterministic markdown mirror generation under `.docs/` + analysis manifests under `.analyse/`).
- `/analyse/repo-overview-refresh` (model-driven `repo_overview.md` refresh, with a persistent job ledger at `<user-data>/repo_overview_refresh_jobs.json` and an `initialize_repo_overview_refresh_jobs()` startup recovery routine).
- `/publishdocs` (copy `.docs` back into `<mounted_folder>/.docs/`).

Constants worth noting:

- `_REPO_OVERVIEW_PROMPT` — the system prompt for the overview refresh.
- `_REPO_OVERVIEW_MODEL_TIMEOUT_SECONDS = 45.0`
- `_REPO_OVERVIEW_REFRESH_MAX_ATTEMPTS = 3`
- `_REPO_OVERVIEW_REFRESH_BACKOFF_SECONDS = 2.0`
- `_TEXT_EXTENSIONS` — the whitelist for "is this text" before falling back to mime/UTF-8 sniffing.
- `_MOUNT_LIST_DEFAULT_LIMIT = 2000`, `_MOUNT_LIST_HARD_LIMIT = 10000`.

### `backend/src/config/dreamy_timeout_config.py`

```python
from pydantic import BaseModel, Field

class DreamyTimeoutConfig(BaseModel):
    """Controls for long-running dreamy threads and stuck-run recovery."""
    enabled: bool = Field(default=True, description="Whether dreamy timeout controls are active.")
    # ... idle_timeout_seconds, total_run_timeout_seconds, watchdog_poll_interval_seconds,
    #     bootstrap_subprocess_timeout, etc.

_dreamy_timeout_config: DreamyTimeoutConfig = DreamyTimeoutConfig()

def get_dreamy_timeout_config() -> DreamyTimeoutConfig: ...
def set_dreamy_timeout_config(config: DreamyTimeoutConfig) -> None: ...
def load_dreamy_timeout_config_from_dict(config_dict: dict) -> None: ...
```

### `backend/tests/test_dreamy_bootstrap_middleware.py`
### `backend/tests/test_dreamy_intent_middleware.py`
### `backend/tests/test_dreamy_mount_folder_router.py`
### `backend/tests/test_dreamy_repo_overview_refresh.py`

Tests live alongside the implementation files they cover. Restore with the rest of the Dreamy code.

## Surgical Edits (re-add these lines to surviving files)

### `backend/src/agents/lead_agent/agent.py`

```python
# L12  — memory hook import
from src.agents.memory.dreamy_state_preservation_hook import dreamy_state_preservation_hook

# L18-L22 — middleware imports
from src.agents.middlewares.dreamy_bootstrap_middleware import DreamyBootstrapMiddleware
from src.agents.middlewares.dreamy_execution_middleware import DreamyExecutionMiddleware
from src.agents.middlewares.dreamy_intent_middleware import DreamyIntentMiddleware
from src.agents.middlewares.dreamy_poc_middleware import DreamyPocMiddleware
from src.agents.middlewares.dreamy_watchdog_middleware import DreamyWatchdogMiddleware

# L223 — signature
def _create_summarization_middleware(*, mode: str = "", dreamy_mode: bool = False) -> CapyHomeSummarizationMiddleware | None:

# L232 — pick the dreamy summarization profile when active
normalized_mode = "dreamy" if dreamy_mode else mode

# L277-L278 — append the preservation hook
if dreamy_mode:
    hooks.append(dreamy_state_preservation_hook)

# L548 (top of _build_middlewares)
dreamy_mode = bool(cfg.get("dreamy_mode", False))

# L554 — force-disable subagents in dreamy mode
subagent_enabled=False if dreamy_mode else cfg.get("subagent_enabled", False),

# L569-L573 — middleware specs (insert after `steering`, before `uploads`)
MiddlewareSpec("dreamy_watchdog",   lambda: DreamyWatchdogMiddleware(),    after={"thread_data"}),
MiddlewareSpec("dreamy_intent",     lambda: DreamyIntentMiddleware(),      after={"thread_data", "dreamy_watchdog"}),
MiddlewareSpec("dreamy_bootstrap",  lambda: DreamyBootstrapMiddleware(),   after={"thread_data", "dreamy_intent", "dreamy_watchdog"}),
MiddlewareSpec("dreamy_poc",        lambda: DreamyPocMiddleware(),         after={"dreamy_bootstrap", "thread_data", "dreamy_watchdog"}),
MiddlewareSpec("dreamy_execution",  lambda: DreamyExecutionMiddleware(),   after={"dreamy_poc", "thread_data", "sandbox", "dreamy_watchdog"}),

# L576 — `sandbox` needs to wait for dreamy_intent and dreamy_bootstrap
MiddlewareSpec("sandbox", lambda: SandboxMiddleware(), after={"thread_data", "dreamy_intent", "dreamy_bootstrap"}),

# L588 — pass dreamy_mode into summarization
MiddlewareSpec("summarization", lambda: _create_summarization_middleware(mode=mode, dreamy_mode=dreamy_mode), after={"dangling_tool_call"}),

# L710 — same flag inside _extract_runtime_params
dreamy_mode = bool(cfg.get("dreamy_mode", False))

# L721 — propagate subagent override
subagent_enabled=False if dreamy_mode else cfg.get("subagent_enabled", False),

# L788 — make_lead_agent: re-read the flag
dreamy_mode = bool((config.get("configurable") or {}).get("dreamy_mode", False))

# L866 — pass through to prompt template
dreamy_mode=dreamy_mode,
```

### `backend/src/agents/lead_agent/prompt.py`

```python
# L501-L530 — the DREAMY_MODE_SECTION constant (the rulebook the model reads)
DREAMY_MODE_SECTION = """<dreamy_mode>
You are running in **Dreamy mode** — a batch-workflow execution environment.

**Immediate action required:** Load the dreamy-workflow skill now:
```
read_file /mnt/skills/dreamy-workflow/SKILL.md
```

**Hard constraints in this mode:**
- NEVER call the `task()` tool — it is disabled and will be rejected.
- All row processing must be sequential and inline.
- When Dreamy mode has just been enabled and workflow.json does not yet exist, treat the
  user's next substantive workflow request as workflow-design input even without a slash prefix.
- If the user has not actually described the row-by-row job yet, ask what should happen per row
  before creating workflow.json.
- Once workflow.json v2 exists at /mnt/user-data/workspace/workflow.json, it is your
  **executor contract**:
  - Read execution_state.current_row_index and current_step_id at the start of each turn.
  - Execute exactly the step at current_step_id for the row at current_row_index.
  - After completing a step, update execution_state.current_step_id to the next step id
    (null if the row is complete), and increment current_row_index when all steps for a row finish.
  - Write execution_state back to workflow.json after every step.
  - Do NOT invent steps not listed in `steps`. Do NOT skip steps.
- When execution_state.phase is "awaiting_approval", you MUST call ask_clarification
  (clarification_type="risk_confirmation") showing the POC results, remaining row count,
  and estimated time. Do not process any more rows until the user explicitly confirms.
- When execution_state.phase is "bulk", execute the current step for the current row,
  update execution_state, call checkpoint.py --mark-done after each row completes,
  and continue until phase is "done".
</dreamy_mode>"""

# L617 — apply_prompt_template signature
dreamy_mode: bool = False,

# L636-L637 — conditional append
if dreamy_mode:
    return prompt + "\n\n" + DREAMY_MODE_SECTION
```

### `backend/src/agents/thread_state.py`

```python
# L157-L163
class DreamyIntentState(TypedDict):
    shape: str
    intent_class: str
    confidence: float
    extracted_fields: list[str]
    inferred_goal: str
    workflow_requested: bool

# L256-L257 (inside ThreadState)
dreamy_mode: NotRequired[bool]
dreamy_intent: NotRequired[DreamyIntentState]
```

### `backend/src/gateway/app.py`

```python
# L19 — add `dreamy,` to the router import block
from src.gateway.routers import (
    ...,
    dreamy,
    ...,
)

# L113-L119 — lifespan startup hook
try:
    await dreamy.initialize_repo_overview_refresh_jobs()
    _mark_component_status(app, "dreamy_repo_overview_recovery", status="running")
except Exception as exc:
    logger.exception("Dreamy repo overview refresh recovery failed")
    _mark_component_status(app, "dreamy_repo_overview_recovery", status="failed", error=str(exc))

# L379 — mount the router
app.include_router(dreamy.router)
```

### `backend/src/config/__init__.py`

```python
# L3
from .dreamy_timeout_config import DreamyTimeoutConfig, get_dreamy_timeout_config

# L35-L36 (inside __all__)
"DreamyTimeoutConfig",
"get_dreamy_timeout_config",
```

### `backend/src/config/app_config.py`

```python
# L21
from src.config.dreamy_timeout_config import DreamyTimeoutConfig, load_dreamy_timeout_config_from_dict

# L74-L76 (inside AppConfig)
dreamy_timeout: DreamyTimeoutConfig = Field(
    default_factory=DreamyTimeoutConfig,
    description="Dreamy runtime timeout and watchdog configuration",
)

# L199-L200 (inside the load function)
# Load dreamy timeout/watchdog config
load_dreamy_timeout_config_from_dict(config_data.get("dreamy_timeout", {}))
```

### `backend/src/config/summarization_config.py`

```python
# L58 — doc string mentions dreamy as a valid mode-override key
description="Optional per-mode overrides keyed by mode name: work, plan, dreamy. Legacy aliases fast/pro are also recognized.",
```

### `backend/src/config/question_generation_config.py`

```python
# L13-L15
enabled_in_dreamy: bool = Field(
    default=False,
    description="Whether to generate follow-up questions in dreamy mode. Requires enabled=true.",
)
```

### `config.yaml` and `config.example.yaml`

Three blocks (full content lives in the repo's pre-removal commit):

1. **`summarization.modes.dreamy:`** — per-mode summarization overrides (around config.yaml L256).
2. **`question_generation.enabled_in_dreamy: false`** (around config.yaml L280).
3. **Top-level `dreamy_timeout:`** block (around config.yaml L397) — feeds `DreamyTimeoutConfig`.

### `skills/dreamy-workflow/SKILL.md`

The progressive-disclosure skill loaded by the model on entering Dreamy mode (referenced explicitly in `DREAMY_MODE_SECTION`). Keep the skill alongside the rest of the public skills under `skills/dreamy-workflow/`.
