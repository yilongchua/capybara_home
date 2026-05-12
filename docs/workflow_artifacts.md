# Workflow Artifacts (workflow_*.md)

## Overview

Workflow artifacts are a proposed artifact system for complex user requests that require strict, step-by-step execution with middleware-level adherence. Unlike `plan.md` which generates todos and lets the agent execute them in a ReAct loop, workflow artifacts enforce **strict sequential execution** where each step must complete before the next begins.

## When to Create a Workflow Artifact

A workflow artifact is created when:
- The user request is complex enough to require structured multi-step execution
- Steps have strict ordering dependencies (not just a DAG, but enforced sequence)
- Errors during execution should trigger workflow adaptation (not just retry the same step)

## Naming Convention

```
workflow_{request_id}.md        # By request ID
workflow_{timestamp}.md         # By timestamp (e.g., workflow_20260510_143022.md)
workflow_{topic}.md             # By topic (e.g., workflow_migrate-database.md)
```

The `...` in the filename refers to a **single user request** that triggered the workflow. One request = one workflow file.

## Workflow vs Plan: Key Differences

| Aspect | plan.md (plan mode) | workflow_*.md (proposed) |
|---|---|---|
| **Execution model** | ReAct loop with todo DAG — agent can interleave thinking and doing | Strict sequential steps — each step must complete before next begins |
| **Adherence level** | Agent follows todos loosely (can reorder, skip, combine) | Middleware-level enforcement — steps are injected as hard constraints |
| **Error handling** | Agent retries or adapts within ReAct loop | Model can **modify/expand the workflow file** for next iteration |
| **Flexibility** | High — agent has autonomy within todo structure | Low during execution, but adaptive on error |
| **Use case** | General multi-step tasks (coding, research) | Complex workflows with strict dependencies (deployments, migrations, audits) |

## Workflow File Format

```markdown
---
workflow_version: 1
request_id: <thread_or_request_identifier>
title: "Short description of the workflow"
created_at: 2026-05-10T14:30:22Z
status: active | completed | aborted | adapted
---

# Title

> Summary of what this workflow aims to achieve and why it was triggered.

## Steps

### Step 1: Initialize environment
- **Type**: setup
- **Status**: pending | running | completed | failed | skipped
- **Description**: Set up the target environment, verify prerequisites
- **Dependencies**: none
- **Error policy**: abort — cannot proceed without clean environment

### Step 2: Migrate database schema
- **Type**: execution
- **Status**: pending | running | completed | failed | skipped
- **Description**: Run migration scripts from v1 to v2
- **Dependencies**: [Step 1]
- **Error policy**: adapt — if migration fails, modify workflow to add rollback step

### Step 3: Run integration tests
- **Type**: verification
- **Status**: pending | running | completed | failed | skipped
- **Description**: Execute integration test suite against migrated schema
- **Dependencies**: [Step 2]
- **Error policy**: abort — tests must pass before proceeding

### Step 4: Deploy to staging
- **Type**: deployment
- **Status**: pending | running | completed | failed | skipped
- **Description**: Deploy updated service to staging environment
- **Dependencies**: [Step 3]
- **Error policy**: adapt — if deploy fails, add diagnostic step before retry

## Adaptation Log

| Timestamp | Step Modified | Change Reason | Changes Made |
|---|---|---|---|
| 2026-05-10T14:35:00Z | Step 2 | Migration timeout | Added `--timeout=300` flag, inserted pre-check step before migration |
```

## Execution Model

### Phase 1: Workflow Generation (Plan Mode)

When a complex request is detected, the planner generates a workflow artifact instead of (or in addition to) a plan:

```
User request → PlannerMiddleware detects complexity → Generates workflow_*.md
  → Writes to {outputs_path}/workflow_{request_id}.md
  → Writes to {workspace_path}/.handoffs/workflow_{request_id}.md (for handoff)
  → Populates ThreadState.workflow field
```

### Phase 2: Strict Execution (Work Mode)

A proposed `WorkflowMiddleware` would enforce step-by-step execution:

```python
# Pseudocode for proposed WorkflowMiddleware
class WorkflowMiddleware(BaseMiddleware):
    def before_model(self, state):
        workflow = state.workflow
        current_step = self._find_next_ready_step(workflow)

        if not current_step:
            return state  # All steps complete

        # Inject step as hard instruction — agent MUST execute this step
        state.messages.append(
            HumanMessage(content=f"WORKFLOW_STEP: Execute '{current_step.title}'")
        )

        # Mark step as running
        self._update_step_status(workflow, current_step.id, "running")

    def after_agent(self, state):
        # Check if step completed successfully
        step_result = self._evaluate_step_completion(state)

        if step_result.success:
            self._update_step_status(workflow, current_step.id, "completed")
        else:
            # KEY DIFFERENCE: model can modify the workflow on error
            adapted_workflow = self._allow_workflow_adaptation(state, step_result.error)
            if adapted_workflow:
                self._write_updated_workflow(adapted_workflow)  # Overwrites workflow_*.md
            else:
                self._update_step_status(workflow, current_step.id, "failed")
```

### Phase 3: Workflow Adaptation (Error-Driven)

When an error occurs during execution, the model is allowed to:
1. **Modify existing steps** — change parameters, add error handling
2. **Insert new steps** — add diagnostic or recovery steps
3. **Skip steps** — if a step becomes irrelevant due to error state
4. **Abort the workflow** — if recovery is not possible

The adapted workflow is written back to disk, and execution continues from the modified state. This is the key differentiator from plan mode: **the workflow itself evolves during execution**.

## ThreadState Fields (Proposed)

```python
# thread_state.py additions

class WorkflowState(TypedDict):
    workflow_id: str              # Matches filename without extension
    title: str                    # Human-readable title
    steps: list[WorkflowStep]     # Ordered list of steps
    status: str                   # "active" | "completed" | "aborted" | "adapted"
    current_step_index: int       # Which step is currently executing
    adaptation_count: int         # How many times the workflow was modified

class WorkflowStep(TypedDict):
    id: str                       # Step identifier (e.g., "step-1")
    title: str                    # Short step name
    type: str                     # "setup" | "execution" | "verification" | "deployment"
    status: str                   # "pending" | "running" | "completed" | "failed" | "skipped"
    description: str              # Detailed instructions for the step
    dependencies: list[str]       # IDs of prerequisite steps
    error_policy: str             # "abort" | "adapt" — what to do on failure
```

## Frontend Integration

A `WorkflowViewer` component would render the workflow artifact:

```tsx
// frontend/src/components/workspace/artifacts/workflow-viewer.tsx
// Similar to PlanViewer but with:
// - Strict step ordering visualization (not a DAG)
// - Real-time step status updates via SSE
// - Adaptation log display (shows what changed and why)
// - "Adapt Workflow" button for manual intervention
```

SSE events:
- `workflow_started` — workflow artifact created and execution begins
- `step_started` / `step_completed` / `step_failed` — per-step lifecycle
- `workflow_adapted` — workflow was modified due to error (includes diff)
- `workflow_completed` / `workflow_aborted` — final state

## Configuration

```yaml
# config.yaml additions
workflows:
  enabled: true                  # Toggle workflow artifact system on/off
  max_steps: 20                  # Max steps before requiring manual review
  adaptation_enabled: true       # Allow model to modify workflow on error
  max_adaptations: 5             # Max times a workflow can be adapted before aborting
  auto_create_threshold: complex # When to auto-create workflows: "simple" | "moderate" | "complex"
```

## Relationship to Existing Systems

### vs Plan Mode
- Plan mode creates `plan.md` with a todo DAG — agent has flexibility in execution order
- Workflow mode creates `workflow_*.md` with strict sequential steps — agent has minimal flexibility
- Plan mode can **escalate to** workflow mode if complexity is detected mid-execution

### vs Dreamy Mode
- Dreamy's `workflow.json` is for **data processing pipelines** (batch extraction, enrichment)
- Proposed workflow_*.md is for **general complex user requests** (deployments, migrations, audits)
- Dreamy workflow is JSON + machine-executed by `DreamyExecutor`
- Proposed workflow is Markdown + enforced by a middleware layer

### vs Todo DAG
- Todo DAG (`todo_graph` state) allows parallel execution of independent steps
- Workflow enforces strict sequential order (or at most, minimal parallelism within a step)
- Todo DAG has no error-driven adaptation mechanism
- Workflow explicitly supports adaptation via model-modified workflow file

## Implementation Priority

| Component | Status | Notes |
|---|---|---|
| ThreadState fields | Proposed | Needs to be added to `thread_state.py` |
| WorkflowMiddleware | Proposed | New middleware, similar structure to `WorkModeMiddleware` |
| `_render_workflow_md()` | Proposed | Template function, similar to `_render_plan_md()` in planner middleware |
| `WorkflowViewer` component | Proposed | Frontend component, similar to `PlanViewer` |
| SSE events | Proposed | `workflow_started`, `step_*`, `workflow_adapted` |
| Adaptation logic | Proposed | Core differentiator — model modifies workflow on error |

## Example: When to Use Workflow vs Plan

**Use plan.md (plan mode):**
- "Build a todo app with React and Firebase" — steps can be parallelized, agent has flexibility
- "Research the best database for our use case" — research steps can be reordered

**Use workflow_*.md (workflow mode):**
- "Migrate our production database from PostgreSQL 14 to 16 with zero downtime" — strict sequence: backup → test migration → cutover → verify
- "Audit our security configuration across 5 cloud providers" — each provider must be fully audited before moving to the next
- "Deploy v2.3.1 to staging, run tests, then deploy to production" — deployment pipelines require strict adherence
