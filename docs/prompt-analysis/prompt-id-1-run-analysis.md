# Prompt ID 1 Run Analysis

## Scope

This report analyzes the prompt behavior observed in `prompt-tunning/prompt_id_1/` and the backend prompt definitions that shape those runs.

Primary files reviewed:

- `prompt-tunning/prompt_id_1/cycle_1_metadata.json`
- `prompt-tunning/prompt_id_1/cycle_2_metadata.json`
- `prompt-tunning/prompt_id_1/cycle_3_metadata.json`
- `prompt-tunning/prompt_id_1/cycle_*_promptlog_*.txt`
- `backend/src/agents/lead_agent/prompt.py`
- `backend/src/agents/memory/prompt.py`

Related prompt surfaces found during repository search:

- `backend/src/agents/lead_agent/todo_prompts.py`
- `backend/src/agents/middlewares/planner_middleware.py`
- `backend/src/agents/middlewares/plan_evaluator_middleware.py`
- `backend/src/agents/middlewares/evaluator_middleware.py`
- `backend/src/agents/middlewares/web_search_summary_middleware.py`
- `backend/src/security/search_masking.py`
- `backend/src/subagents/builtins/general_purpose.py`
- `backend/src/subagents/builtins/bash_agent.py`
- `backend/src/control_plane/prompts/vault_analyze.py`
- `backend/src/control_plane/prompts/vault_generate.py`

## Test Case

The analyzed user prompt was:

> I'm thinking of taking a 12 day trip to Greece with my partner in September. Can you make a realistic itinerary with places to stay, travel time between islands, and a rough budget?

The metadata labels this as an `easy` prompt, running in `work` mode with `auto_mode` enabled on `qwen3.6-local`.

## Executive Summary

The main issue is over-routing. A straightforward travel-planning request is being pushed through heavy orchestration paths: subagent delegation, repeated web search, knowledge-vault ingestion, and file artifact handling. This creates avoidable latency, search/tool failures, and hallucination risk before the model eventually produces an answer that is mostly based on general knowledge.

The prompt stack is capable, but the lead prompt currently overweights:

- subagent use for broad tasks,
- web search as the default first retrieval path,
- broad memory injection,
- multi-file artifact production,
- generic quality gates.

For this class of request, the target behavior should be: answer directly with light, bounded verification only where freshness matters.

## Observed Behavior Across Cycles

### Cycle 1

Cycle 1 completed in about two minutes, but the logs show several quality issues:

- `web_search` timed out repeatedly.
- The model fell back to general knowledge after tool failures.
- A large memory block was injected despite being unrelated to the Greece travel request.
- A `write_file` tool call failed because the required `description` argument was missing.
- The generated artifact hit a deterministic quality warning for missing `executive_summary`, which is a poor fit for a travel itinerary.

The final itinerary was useful, but it had unverified hotel names and overly confident current-pricing language.

### Cycle 2

Cycle 2 took much longer, around twenty minutes.

Notable issues:

- The agent performed multiple searches for hotel costs and logistics.
- Some results were low-value or unsuitable as evidence, including Facebook login-gated pages and generic booking aggregator pages.
- The model attempted to read `/app/output/.../result.md`, which was returned by the search package but was not accessible through the normal workspace file tool path.
- Search queries included stale year targeting, such as `September 2024`, despite the current date being 2026.

The final route was more reasonable in places, but the cost and accommodation recommendations still mixed current claims with weak source grounding.

### Cycle 3

Cycle 3 took the longest, roughly thirty-eight minutes.

Notable issues:

- A subagent was launched for an easy travel prompt and eventually timed out after the task timeout.
- The lead agent then tried direct web search, where some searches timed out and others returned zero results.
- The model then compiled an itinerary from training knowledge while also ingesting a synthetic `research-based itinerary planning` source into the knowledge vault.
- This created a misleading appearance of sourced research even when the final answer was primarily model knowledge.

The final response was coherent, but the workflow was too expensive and introduced unnecessary reliability risks.

## Prompt Inventory

### Lead Agent Prompt

File: `backend/src/agents/lead_agent/prompt.py`

This is the most important prompt surface. It controls:

- role identity,
- thinking style,
- clarification policy,
- skill loading,
- subagent orchestration,
- working directory behavior,
- fetch policy,
- response style,
- citations,
- critical reminders,
- Dreamy mode,
- Plan mode.

The lead prompt currently contains several strong instructions that can conflict for simple user requests:

- subagent mode says complex tasks should be decomposed and distributed;
- fetch policy says external web research should be attempted first for fresh information;
- working-directory guidance encourages final deliverables in files;
- response style asks for concise directness.

In the observed runs, the heavier instructions won.

### Memory Prompt

File: `backend/src/agents/memory/prompt.py`

The memory updater asks the model to retain detailed context, ongoing focus, history, and facts. This is useful for personalization, but the observed run shows two problems:

- broad memory can be injected even when unrelated to the current turn;
- assistant-generated trip outputs can become durable memory context unless the prompt strongly prevents one-off planning artifacts from being stored.

The memory format also includes high-detail sections such as `topOfMind` and `recentMonths`, which can dominate the system prompt if not relevance-filtered.

### Planner Prompt

File: `backend/src/agents/middlewares/planner_middleware.py`

The planner classifies trip planning as a complex domain and can produce todo DAGs. This is valid for some travel requests, but the observed request was simple enough to answer directly. The planner and work-mode classifications need a lighter category between trivial and complex.

### Subagent Prompts

Files:

- `backend/src/subagents/builtins/general_purpose.py`
- `backend/src/subagents/builtins/bash_agent.py`

The general-purpose subagent prompt is broad and autonomous. It is suitable for isolated research or code work, but not for a simple itinerary. In cycle 3, delegation became a failure path because the subagent timed out before the lead agent recovered.

### Evaluator And Quality Prompts

Files:

- `backend/src/agents/middlewares/plan_evaluator_middleware.py`
- `backend/src/agents/middlewares/evaluator_middleware.py`

The evaluator checks are generic. In the observed run, a travel artifact was warned for missing `executive_summary`, which is not a meaningful quality criterion for a user-facing itinerary.

### Search Prompts

Files:

- `backend/src/agents/middlewares/web_search_summary_middleware.py`
- `backend/src/security/search_masking.py`

The search summarization prompt is reasonable, but the lead prompt's fetch policy pushes the agent to search too early and too repeatedly. The search result handling also needs stronger instructions about source quality and inaccessible package paths.

## Root Causes

### 1. The Lead Prompt Lacks A Clear Complexity Ladder

The system distinguishes trivial and complex, but not enough middle ground exists for "answer directly with light verification." A travel itinerary is not trivial, but it also does not require subagents, todo DAGs, knowledge-vault writes, and multi-stage orchestration.

Recommended behavior:

- direct answer for simple consumer advice;
- one to three bounded searches for freshness-sensitive facts;
- planner for multi-step execution or deliverables;
- subagents only for separable, high-value independent work.

### 2. The Fetch Policy Is Too Search-First

The lead prompt says:

> `web_search` — external web research should be attempted first for fresh information

This makes sense for current events and high-stakes factual questions. It is too expensive for general trip planning. In the logs, search-first behavior caused repeated timeouts and low-value results.

Recommended behavior:

- use web search when freshness materially affects correctness;
- cap search attempts;
- stop after timeout/no-result patterns;
- answer from general knowledge with caveats when search is unavailable;
- do not keep retrying similar queries.

### 3. Subagent Instructions Are Too Salient

The subagent section is long, emphatic, and uses strong language like:

- `SUBAGENT MODE ACTIVE`
- `DECOMPOSE, DELEGATE, SYNTHESIZE`
- `Complex tasks should be decomposed`

This makes the model overuse `task` once a request seems broad. The observed travel request was broad but not operationally complex.

Recommended behavior:

- keep the hard concurrency rule;
- reduce the "preferred approach" language;
- add explicit examples of requests that should not use subagents, including simple travel plans, shopping advice, definitions, summaries, and ordinary recommendations;
- require a concrete reason before delegation.

### 4. Memory Injection Is Not Relevant Enough

Cycle 1 injected detailed unrelated memory about legal cases, Jira tickets, hardware, a Netherlands itinerary, and other projects. This increases token cost and may bias the answer.

Recommended behavior:

- pass the current user turn into memory recall;
- inject only topically relevant facts by default;
- keep broad user profile sections out unless the request needs personalization;
- distinguish durable preferences from transient tasks.

### 5. Memory Update Rules Are Too Permissive For One-Off Artifacts

The memory updater currently avoids upload events, but it does not strongly reject assistant-generated plans or temporary itineraries. A generated travel plan can become "current focus" even if it was only a one-off request.

Recommended behavior:

- do not store assistant-generated artifacts as user facts unless the user confirms adoption;
- do not store one-off travel/research explorations as current focus by default;
- only store travel plans when the user indicates commitment, booking, or ongoing planning.

### 6. Tool Schema Discipline Needs To Be Prompted More Compactly

The logs show `write_file` failed because `description` was missing. The schema already requires it, but the model still omitted it.

Recommended behavior:

- add a short tool-call checklist near the working-directory/tool guidance;
- emphasize required fields for file tools;
- for write operations, always include `description`, `path`, and `content`.

### 7. Search Artifact Paths Are Misleading

`web_search` returns package paths like `/app/output/.../result.md`. The model attempted to read one of these with `read_file`, causing a file-not-found error.

Recommended behavior:

- tell the model that search package paths are backend/container metadata unless explicitly mapped into the workspace;
- use the returned `results` content directly;
- do not call `read_file` on `/app/output/...` paths.

### 8. Quality Gates Are Not Domain-Aware

The itinerary artifact triggered a warning for missing `executive_summary`. That may be appropriate for reports, but not for itinerary markdown.

Recommended behavior:

Trip output checks should validate:

- route feasibility,
- number of nights equals trip length,
- island transfer durations are plausible,
- budget covers accommodation, transport, food, activities, local transit, and contingency,
- unverified names/prices are labeled as examples or estimates,
- assumptions are stated.

## Recommended Prompt Changes

### Lead Agent Prompt

Add a `request_complexity_ladder` section before subagent instructions:

```text
<request_complexity_ladder>
Default to the lightest workflow that can satisfy the user.

Direct answer:
- Use for advice, explanations, simple planning, ordinary recommendations, and consumer questions.
- Do not create todos, files, or subagents unless the user asks or the output would clearly benefit.

Light verification:
- Use 1-3 targeted searches only when current prices, schedules, availability, laws, or recent events materially affect correctness.
- If search times out or returns weak results, stop retrying and answer with clearly stated assumptions.

Planned work:
- Use planner/todos when the request requires multiple dependent implementation steps, artifact production, or explicit tracking.

Delegated work:
- Use subagents only when there are 2+ independent workstreams whose results can be synthesized.
- Do not use subagents for simple travel plans, routine recommendations, short explanations, or single-answer requests.
</request_complexity_ladder>
```

Revise fetch policy to:

```text
<fetch_policy>
Use retrieval only when it materially improves the answer.

Use web_search for:
- current prices, schedules, availability, laws, releases, or news;
- claims where stale knowledge would likely mislead the user.

Limits:
- Start with at most 1-3 targeted searches.
- If searches time out, return zero results, or produce low-quality pages twice, stop searching.
- Do not retry near-duplicate queries.
- Use returned result content directly; do not read /app/output package paths unless they are explicitly mapped into the workspace.

When search is unavailable:
- Continue from general knowledge if the request can still be answered.
- State assumptions and tell the user which details should be verified before acting.
</fetch_policy>
```

Add travel-specific guidance:

```text
<travel_planning_guidance>
For travel itineraries:
- If the user gives a month but no year, assume the next upcoming instance of that month relative to current_date and state the assumption.
- Prefer realistic route flow over maximizing famous stops.
- Include travel time, nights per location, local transport, and a budget range.
- Treat hotels, ferry schedules, and prices as examples unless verified by current search.
- Do not invent exact hotel recommendations; use neighborhoods or accommodation tiers when unverified.
- Mention what to verify before booking.
</travel_planning_guidance>
```

### Memory Prompt

Add rules to `MEMORY_UPDATE_PROMPT`:

```text
Do NOT store assistant-generated plans, reports, itineraries, or artifacts as durable user facts unless the user explicitly confirms they adopted, booked, saved, or will continue using them.

Do NOT treat one-off planning requests as long-term goals or top-of-mind priorities.

For travel planning, only record durable memory when the user expresses commitment, such as booked flights, fixed dates, chosen destinations, budget constraints, accessibility needs, or strong travel preferences.
```

Improve memory injection behavior in code and prompt:

- Pass `current_turn_text` into `format_memory_for_injection`.
- Prefer vector-recalled facts over broad profile sections.
- Only inject `topOfMind` and `recentMonths` when semantically relevant to the current turn.

### Subagent Prompt

Add explicit non-use cases:

```text
Do NOT use subagents for:
- routine travel itineraries;
- simple consumer recommendations;
- short summaries or explanations;
- a request that can be answered with one direct response plus optional caveats;
- cases where web search or a direct answer is faster than delegation.
```

Also reduce the salience of the current "preferred approach" wording. Keep the concurrency limit, but make delegation conditional rather than aspirational.

### Planner Prompt

Introduce a `moderate` output path or tighten the classifier so `trip plan` is not always complex. A normal itinerary should be handled as direct/light verification unless the user asks for bookings, files, comparisons across many destinations, or a detailed multi-document deliverable.

Suggested classification:

- trivial: greetings, definitions, calculations;
- moderate: direct answer requiring structure but no tool orchestration;
- complex: multi-step execution, code changes, legal analysis, multi-source research, large documents, or artifact-heavy work.

### Evaluator Prompt

Use domain-specific checks for travel output instead of generic report checks.

For trip plans, validate:

- all days/nights accounted for;
- route has plausible geography and transfer order;
- transfer durations are included and labeled as estimates when unverified;
- budget includes major categories;
- current facts are caveated if not verified;
- recommendations match stated traveler profile.

## Proposed Priority Order

1. Add the request-complexity ladder to the lead prompt.
2. Rewrite fetch policy with bounded search and graceful fallback.
3. Add travel-planning guidance.
4. Make memory injection relevance-based.
5. Tighten memory update rules for one-off artifacts.
6. Add tool-path and required-field discipline.
7. Reduce subagent prompt salience for moderate requests.
8. Make evaluator checks domain-aware.

## Expected Outcome

After these changes, the same Greece prompt should produce a useful answer in one short workflow:

1. State assumptions: September 2026, couple, mid-range unless otherwise specified.
2. Optionally run one to three focused searches for ferry/current cost sanity checks.
3. Stop searching if tools are slow or weak.
4. Provide a day-by-day itinerary with route, stays by neighborhood/tier, travel times, and budget.
5. Label prices as estimates and list items to verify before booking.

The agent should not launch subagents, write intermediate files, ingest synthetic sources, or inject unrelated memory for this request.

## Iterative Local Improvement Approach

The `prompt-tunning/` folder is too large to review file-by-file. Treat it as an evaluation corpus and improve the prompts by repeated, small cycles:

1. **Build a run inventory from metadata first.** Use `cycle_*_metadata.json` as the source of truth for prompt ID, difficulty, initial prompt, model, mode, status, start/end time, and response preview. This gives a fast map of which prompt IDs are slow, blank, timed out, over-tooled, or producing weak answers.
2. **Cluster failures by behavior, not by file.** Tag each cycle with symptoms such as `over_search`, `subagent_overuse`, `timeout`, `blank_response`, `unnecessary_file_artifact`, `memory_pollution`, `weak_grounding`, `bad_tool_schema`, `stale_date`, or `quality_gate_mismatch`.
3. **Sample logs only after clustering.** For each high-frequency symptom, inspect 2-4 representative prompt logs: one easy case, one hard/expert case, one improved cycle if available, and one regression. Avoid reading every log unless the symptom is rare or ambiguous.
4. **Map each symptom to the smallest prompt surface.** Prefer changing the lead prompt only when behavior spans many task types. Use planner/evaluator/search/memory/subagent prompts when the failure is localized to routing, quality checks, retrieval, memory, or delegation.
5. **Patch one behavioral rule at a time.** Each iteration should change one hypothesis, such as bounded search retries or subagent non-use cases. Do not bundle many prompt edits unless they are inseparable.
6. **Rerun a fixed benchmark slice locally.** Include at least one easy direct-answer prompt, one medium planning prompt, one current-events/research prompt, one artifact-producing prompt, and one expert/deep-research prompt. Keep the slice stable so changes are comparable.
7. **Score the rerun with a rubric.** Track latency, tool count, subagent count, search count, file writes, answer completeness, source grounding, caveat quality, and whether the final answer matched the user's requested format.
8. **Accept, adjust, or revert.** Keep a prompt change only if it improves the target symptom without creating regressions in harder tasks. If a change helps easy prompts but damages expert research, narrow the rule rather than making it global.

### Suggested Batch Triage Metrics

For every prompt ID and cycle, record:

- `duration_seconds`
- `difficulty`
- `status`
- `response_preview_empty`
- `model_timeout_seen`
- `web_search_count`
- `web_search_timeout_count`
- `subagent_count`
- `write_file_count`
- `read_file_count`
- `quality_warning_count`
- `memory_or_vault_mentions`
- `final_answer_mode`: direct answer, file artifact, summary of saved file, timeout recovery, or blank
- `primary_failure_label`
- `candidate_prompt_surface`

The first pass should answer: which failures are common across many prompt IDs, which are isolated to one domain, and which are caused by local tool/runtime instability rather than prompt wording.

### Improvement Backlog Template

Use this format for each issue before editing prompts:

```text
Issue:
Observed in:
Representative logs:
User impact:
Likely prompt surface:
Hypothesis:
Minimal prompt change:
Benchmark prompts to rerun:
Acceptance criteria:
Regression risk:
Decision after rerun:
```

### Reusable Iteration Prompt

Use this prompt locally for each improvement cycle:

```text
You are improving the Capybara Home prompt stack using the local `prompt-tunning/` evaluation corpus.

Objective:
Find the next highest-leverage prompt improvement that reduces bad orchestration behavior without hurting harder research tasks.

Context:
- The corpus has many `prompt_id_*` folders.
- Each folder contains `cycle_*_metadata.json` and many `cycle_*_promptlog_*.txt` files.
- Do not analyze every log individually.
- Start from metadata, cluster recurring symptoms, then inspect only representative logs.
- Existing analysis for prompt ID 1 is in `docs/prompt-analysis/prompt-id-1-run-analysis.md`.

Process:
1. Inventory all metadata files and summarize prompt IDs, difficulties, cycle counts, durations, statuses, and response previews.
2. Detect recurring symptoms using metadata plus targeted log searches:
   - overuse of web search
   - repeated web search timeouts
   - subagent use on easy or moderate tasks
   - model timeout or synthesis timeout
   - blank or missing final response
   - unnecessary file writing
   - weak source grounding or stale dates
   - memory/vault pollution
   - tool schema or path errors
   - evaluator/quality-gate mismatch
3. Pick one symptom cluster with the best impact-to-risk ratio.
4. Inspect 2-4 representative logs for that cluster. Include different difficulties or cycles when possible.
5. Identify the smallest prompt surface to change:
   - `backend/src/agents/lead_agent/prompt.py`
   - `backend/src/agents/memory/prompt.py`
   - `backend/src/agents/lead_agent/todo_prompts.py`
   - `backend/src/agents/middlewares/planner_middleware.py`
   - `backend/src/agents/middlewares/plan_evaluator_middleware.py`
   - `backend/src/agents/middlewares/evaluator_middleware.py`
   - `backend/src/agents/middlewares/web_search_summary_middleware.py`
   - `backend/src/subagents/builtins/general_purpose.py`
   - `backend/src/subagents/builtins/bash_agent.py`
6. Propose one minimal prompt change, with exact text to add/remove/replace.
7. Define a small benchmark rerun set and acceptance criteria.
8. Stop before applying code edits unless explicitly asked.

Output format:

## Cycle Goal
One sentence describing the target behavior to improve.

## Corpus Triage
Summarize counts and the main recurring symptoms. Do not list every file.

## Representative Evidence
List the small set of logs inspected and the specific behavior observed.

## Recommended Prompt Change
Name the file and provide exact replacement/addition text.

## Why This Is The Smallest Safe Change
Explain why this surface is preferred over broader prompt rewrites.

## Benchmark Rerun Plan
List the prompt IDs or prompt types to rerun and what to measure.

## Acceptance Criteria
State what must improve and what must not regress.
```

### First Three Iterations To Run

1. **Routing and delegation:** reduce subagent/planner usage for easy and moderate requests that can be answered directly.
2. **Search policy:** bound web search attempts, stop retry loops, and require caveats when current facts cannot be verified.
3. **Timeout recovery:** make deep-research tasks write and synthesize incrementally before the model hits the synthesis timeout.
