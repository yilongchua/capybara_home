# 02 — Subagent Prompts

Audit of every built-in subagent configuration plus the shared executor/registry/config.

## Inventory

| # | Subagent | File | Lines | Routing description | System prompt length |
|---|----------|------|-------|---------------------|----------------------|
| 1 | `general-purpose` | [backend/src/subagents/builtins/general_purpose.py](../../backend/src/subagents/builtins/general_purpose.py#L5-L46) | 5–46 | Complex, multi-step tasks needing exploration + action | ~200 words |
| 2 | `source-researcher` | [backend/src/subagents/builtins/source_researcher.py](../../backend/src/subagents/builtins/source_researcher.py#L5-L56) | 5–56 | One narrow live-source research objective | ~280 words |
| 3 | `bash-agent` | [backend/src/subagents/builtins/bash_agent.py](../../backend/src/subagents/builtins/bash_agent.py#L5-L45) | 5–45 | Run sequences of bash commands in an isolated context | ~160 words |
| 4 | `docs-explorer` | [backend/src/subagents/builtins/docs_explorer.py](../../backend/src/subagents/builtins/docs_explorer.py#L5-L59) | 5–59 | Local corpus (`.docs`) explorer | ~280 words |
| 5 | `synthesis-reviewer` | [backend/src/subagents/builtins/synthesis_reviewer.py](../../backend/src/subagents/builtins/synthesis_reviewer.py#L5-L54) | 5–54 | Final-pass quality reviewer | ~280 words |
| 6 | `vault-source-researcher` | [backend/src/subagents/builtins/vault_source_researcher.py](../../backend/src/subagents/builtins/vault_source_researcher.py#L9-L85) | 9–85 | Investigate one sub-question and persist to vault | ~350 words |
| 7 | `comparison-dimension-researcher` | [backend/src/subagents/builtins/comparison_dimension_researcher.py](../../backend/src/subagents/builtins/comparison_dimension_researcher.py#L5-L54) | 5–54 | One dimension across a fixed option set | ~310 words |
| 8 | `SubagentConfig` dataclass | [backend/src/subagents/config.py](../../backend/src/subagents/config.py#L1-L29) | 1–29 | Subagent configuration schema | n/a |
| 9 | Executor (recursion guard, tool filter) | [backend/src/subagents/executor.py](../../backend/src/subagents/executor.py#L154-L209) | 154–209 | Permission/recursion enforcement | n/a |
| 10 | Registry (lookups) | [backend/src/subagents/registry.py](../../backend/src/subagents/registry.py#L1-L52) | 1–52 | Listing and timeout overrides | n/a |

## Detailed findings

### 1. `general-purpose` — lines 5–46

| Field | Status |
|-------|--------|
| Description | Clear use cases, but missing "no clarification" hard rule |
| System prompt | Has typo `User workspace/ Output files`; cites non-standard citation format `[citation:Title](URL)` |

**Improvements**
- Standardise citation format to Markdown `[Title](URL)` to match other subagents.
- Fix the workspace typo.
- Add explicit constraint: *Do not ask for user confirmation — choose a reasonable default and proceed.*

### 2. `source-researcher` — lines 5–56

| Field | Status |
|-------|--------|
| Description | Strong: multi-topic explicitly rejected |
| Scope rule | Good (returns `failed` when multi-objective) |
| Output format | 7 numbered sections, clear |
| Threshold "3–5 useful sources" | "Useful" undefined |

**Improvements**
- Define "useful": *sources that directly answer the question with verifiable evidence; deduplicate near-duplicates.*
- Add a query budget: *after 3 distinct queries without sufficient evidence, stop and return `Source status: partial`.*
- Section 6 (retrieval failures) must always be present even on success, even if empty — improves transparency.

### 3. `bash-agent` — lines 5–45

| Field | Status |
|-------|--------|
| Description | Clear vs. parent `bash` tool |
| Destructive ops | Treated as advisory only |
| Output cap | Not specified |
| Typo | `User workspace/ Output files` |

**Improvements**
- Promote destructive-op caution to a hard rule: *never run `rm -rf`, `git reset --hard`, `--force`, or pipe-to-shell installers without an explicit confirmation request from the parent.*
- Add an output cap: *summarise output to <1000 tokens; preserve error messages verbatim.*
- Spell out parallelisation: *run in parallel only when outputs don't depend on each other; chain with `&&` when they do.*

### 4. `docs-explorer` — lines 5–59

| Field | Status |
|-------|--------|
| Corpus precedence | Good (`.docs` canonical, `.mounted` fallback) |
| Status enum | `no relevant hits` is vague |
| Passage length | Unbounded |

**Improvements**
- Replace status enum with four explicit values: `found`, `partial`, `missing` (dir absent), `empty` (dir present but irrelevant).
- Cap extracted passages at 50–200 words or use line ranges.
- Add: *if `.docs` is missing, report immediately — do not fall back to web search.*

### 5. `synthesis-reviewer` — lines 5–54

| Field | Status |
|-------|--------|
| Review checklist | Strong (6 dimensions) |
| Verdict thresholds | Undefined |
| "Proportionate" balance check | Vague |

**Improvements**
- Define thresholds:
  - `pass` — no issues found
  - `pass with caveats` — minor gaps that don't block presentation; enumerate them
  - `needs revision` — major coverage gap or unresolved contradiction
- Clarify "proportionate" to mean: roughly equal attention to each option, deviations explained.
- Add fix prioritisation: contradictions > coverage > staleness > citation.

### 6. `vault-source-researcher` — lines 9–85

| Field | Status |
|-------|--------|
| JSON output | Machine-parseable, clear |
| "Lightly normalised" title | Undefined |
| `Uncertainty` may be omitted | Inconsistent schema |

**Improvements**
- Specify title normalisation: *strip trailing punctuation, Title Case, ≤60 chars.*
- Always emit `uncertainty` (use `""` when none) so the JSON schema is stable.
- Explicit fail rule: if `save_to_knowledge_vault` returns `{"ok": false}`, set `status: "failed"` and put the error in `uncertainty`; do not retry.

### 7. `comparison-dimension-researcher` — lines 5–54

| Field | Status |
|-------|--------|
| Scope (single dimension) | Strong |
| Output parallelism | Required but format unspecified |
| "Knowledge-based estimate when safe" | Subjective judgement |
| Section 4 "Best and weakest" | Assumes a linear scale |

**Improvements**
- Specify a per-option field block: `metric`, `value/range`, `source` (URL or "knowledge-based"), `confidence`, `date/recency`. Use `—` for missing fields.
- Qualify safety: knowledge-based estimates only allowed when (a) no contradicting data exists, (b) clearly labelled, (c) reasoning briefly stated.
- Allow tradeoff framing in Section 4: *"Best on cost (Provider B) but weakest on latency. Best on latency (Provider A) but most expensive."*

### 8. `SubagentConfig` dataclass — config.py lines 1–29

| Field | Status |
|-------|--------|
| Schema | Minimal |
| `timeout_seconds=3600` default | Very generous |
| `disallowed_tools=["task"]` default | Good safety (no nesting) but undocumented |

**Improvements**
- Add `max_output_tokens` field to bound response size.
- Add `description_for_lead_agent: str` distinct from `system_prompt` (clearer semantics; loader uses `description` today).
- Document the `task` disallow as the core anti-recursion rule.
- Document timeout overrides loaded from `config.yaml` (see `registry.get_subagent_config`).

### 9. Executor recursion + tool filter — executor.py lines 154–209

| Field | Status |
|-------|--------|
| `task`-tool guard | Excellent error message |
| Trace logging | Comprehensive but logs only tool counts, not names |
| Timeout message | Not surfaced as part of result.error |

**Improvements**
- Log filtered tool names at INFO level for permission-issue triage.
- On timeout, set `result.error = f"Subagent '{config.name}' exceeded {timeout}s; did not complete"` so the lead agent can act on it.

### 10. Registry — registry.py lines 1–52

**Improvements**
- Add a docstring example showing how `subagents.timeout_overrides.<name>` in `config.yaml` adjusts the returned config.

## Cross-cutting observations

### A. Lead-agent routing tie-breaking

When more than one subagent could plausibly apply (e.g. `source-researcher` vs `comparison-dimension-researcher`), the lead agent has no tie-breaker. Add an inline routing table (in lead prompt or a short CLAUDE.md include):

| Intent | Preferred subagent |
|--------|--------------------|
| Single narrow fact-finding pass | `source-researcher` |
| Same dimension across N options | `comparison-dimension-researcher` |
| QA / coverage check on existing draft | `synthesis-reviewer` |
| One vault-ingest pass per sub-question | `vault-source-researcher` |
| Mixed exploration + action | `general-purpose` |
| Shell pipelines / build / test | `bash-agent` |
| Mounted corpus / uploads | `docs-explorer` |

### B. Output format consistency

Six subagents use 4–7 numbered prose sections; `vault-source-researcher` uses strict JSON. Pick one of:

1. **Status-first prose** for all: `## Status`, `## Key Findings`, `## Sources`, `## Confidence`, `## Limitations`.
2. **Strict JSON** for all (best for machine handoff; worst for human review).

Recommend (1) for human-reviewable subagents and (2) only for autoresearch-style pipelines.

### C. Citation format consistency

| Subagent | Format |
|----------|--------|
| general-purpose | `[citation:Title](URL)` |
| source-researcher | prose: title, URL, publisher, date |
| vault-source-researcher | `Title - URL (publisher, date)` |
| comparison-dimension-researcher | prose: citations, file paths, "knowledge-based" |

Adopt one canonical form across all: `[Title](URL) — Publisher, YYYY-MM-DD`.

### D. Working-directory boilerplate

6 of 7 subagents repeat the same `<working_directory>` block. Move to a shared prefix appended by the executor; the one exception (`vault-source-researcher` has no FS access) gets its own override.

### E. Missing hard constraints

Each subagent should grow a small `<constraints>` block with explicit hard rules. Suggested additions:

| Subagent | Hard rule |
|----------|-----------|
| source-researcher | "If task contains >3 topics, reject and ask parent to narrow." |
| bash-agent | "Never run rm -rf or `--force` ops without explicit parent confirmation." |
| docs-explorer | "If corpus empty, report immediately — do not call web search." |
| synthesis-reviewer | "Do not resolve contradictions yourself; surface them for the parent." |
| vault-source-researcher | "Do not retry save on failure; report error and stop." |
| comparison-dimension-researcher | "If <2 options, ask for more. If >10, recommend chunking." |

### F. Permission notes

`comparison-dimension-researcher` is granted `recall` but the prompt never mentions when to use it. Either document it in the system prompt or remove from the tool list.

`source-researcher` denies `write_file` but allows `bash` — a hostile or buggy prompt could write via shell. If file writes are genuinely forbidden, also block `bash` redirection.
