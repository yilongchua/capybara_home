# 06 — Summary and Priorities

Cross-cutting findings across the lead agent, subagents, tools, middleware, and skills, with a recommended rollout order.

## Recurring patterns

### A. Undefined adjectives

Every layer overuses adjectives without anchoring them. Each one should grow a one-line signal:

| Adjective | Where it appears | Suggested anchor |
|-----------|------------------|------------------|
| "complex" | lead prompt, todo prompts | involves unknowns, multi-step (≥3 steps), or error recovery |
| "stuck" | recursion pivot | same tool with similar args ≥3× without output change |
| "stale" | evaluator | file timestamp older than the last status transition |
| "substantive" | evaluator | references the deliverable + acknowledges open items |
| "low-value" | summarization | acknowledgements, false starts, retries that didn't change state |
| "key information" | web search summary | data points, dates, names, prices, verifiable claims |
| "genuine blocker" | plan evaluator | circular dep, synthesis with no inputs, unsatisfiable gate |
| "durable" | memory | persistent patterns, expertise, values, long-term goals |
| "naturally splits" | subagent dispatch | 2+ independent streams, each expected >30s |
| "useful source" | source-researcher | directly answers the question with verifiable evidence |

### B. Missing failure modes

Almost no prompt specifies what to do when its preconditions fail:

| Layer | Failure unaddressed | Recommended addition |
|-------|--------------------|----------------------|
| Lead | `web_search` timeout | state limitation; proceed with reasoning or decline |
| Lead | subagent timeout | narrow scope, retry once; on 2nd failure synthesise partial |
| Subagent | save failure (vault) | report and stop; do not retry |
| Subagent | empty corpus | report immediately; do not fall back to web |
| Plan Mode | user rejects approval | freeze state; never resume implicitly |
| Recursion pivot | unable to decide | default `KEEP` |
| Summarization | over-budget output | drop sections in fixed order (Files → Open Items → Goal last) |

### C. Missing examples in structured-output prompts

Every prompt that asks for JSON / enums / verdicts would benefit from one positive and one negative example. Highest priority:

- `PLANNER_SYSTEM_PROMPT` (only the trivial path is shown)
- `_PLAN_EVAL_PROMPT` (`revised_todos` shape never demonstrated)
- `_EVALUATOR_PROMPT_TEMPLATE` (no pass/fail example)
- `MEMORY_UPDATE_PROMPT` (JSON shape implied, never shown)
- Dreamy step-inference (no example steps array)

### D. Placeholder hygiene

| Placeholder | File | Status |
|-------------|------|--------|
| `{subagent_thinking}` | lead_agent/prompt.py 174–181 | Never defined |
| `{subagent_reminder}` | lead_agent/prompt.py 267–278 | Never defined |
| `{n}` in batching example | lead_agent/prompt.py 8–49 | Hard limit or example value? Ambiguous |
| `{max_steps}`, `{max_clarifications}` | planner_middleware.py 203–332 | Injected via `str.replace` — injection-vulnerable |
| `{workspace_path}` (would-be) | evaluator_middleware.py 19–32 | Currently hard-coded |
| `{plan_paths}` (would-be) | evaluator_middleware.py 19–32 | Currently hard-coded |

### E. Citation format drift

| Layer | Format observed |
|-------|------------------|
| Lead `CITATIONS_SECTION` | `[citation:Title](URL)` |
| general-purpose subagent | `[citation:Title](URL)` |
| source-researcher | prose: title, URL, publisher, date |
| vault-source-researcher | `Title - URL (publisher, date)` |
| comparison-dimension-researcher | prose: "citations, file paths, or 'knowledge-based' label" |
| web search summary | not specified |

Standardise to one canonical form: `[Title](URL) — Publisher, YYYY-MM-DD`.

### F. Cross-skill / cross-subagent boundaries

Boundaries are implicit and the LLM has to infer them. Add explicit "use X instead when …" pointers:

- `source-researcher` vs `comparison-dimension-researcher`
- `synthesis-reviewer` vs `general-purpose`
- `excel-modeling` vs `data-analysis`
- `chart-visualization` vs `data-analysis`
- `consulting-analysis` vs `deep-research`
- `knowledge-vault` vs `deep-research`

## Suggested rollout order

Prioritised by *blast radius × ease of fix*.

### Wave 1 — high-impact, low-effort (1–2 days)

1. **Fix injection in `PLANNER_SYSTEM_PROMPT`** — switch `str.replace` to `string.Template` (planner_middleware.py ~line 785).
2. **Standardise citation format** to `[Title](URL) — Publisher, Date` across lead prompt, all subagents, and summary middlewares.
3. **Resolve undefined placeholders** in lead prompt (`{subagent_thinking}`, `{subagent_reminder}`, `{n}`).
4. **Reconcile / dedupe** `LEGACY_SYSTEM_PROMPT_TEMPLATE` against componentized sections — delete one.
5. **Fix typo** `User workspace/ Output files` in all subagent prompts.

### Wave 2 — clarity uplift (3–5 days)

6. **Anchor adjectives** (table in section A above) — add a one-line signal next to each.
7. **Add failure-mode lines** (section B) to every prompt that has a known unhappy path.
8. **Add `Returns:` and one example call** to every tool description.
9. **Expand under-described tools**: `recall`, `setup_agent`, `write_todos` (see [03-tool-descriptions.md](03-tool-descriptions.md)).
10. **Rewrite weak skill descriptions**: `excel-modeling`, `chart-visualization`, `image/video/podcast/ppt-generation`, `github-deep-research`, `knowledge-vault`, `consulting-analysis` (see [05-skill-metadata.md](05-skill-metadata.md)).

### Wave 3 — structural improvements (1–2 weeks)

11. **Componentize the lead prompt fully** — delete `LEGACY_SYSTEM_PROMPT_TEMPLATE` once parity is confirmed.
12. **Add a routing table** to the lead prompt (subagent + skill tie-breakers, section F).
13. **Add `<constraints>` blocks** to every subagent system prompt (hard rules per [02-subagent-prompts.md](02-subagent-prompts.md)).
14. **Standardise subagent output format** — pick prose-with-status sections for human-reviewable subagents; JSON only for pipeline subagents.
15. **Extend skill frontmatter** with `when_not_to_use` and `triggers` fields; add a load-time lint.

### Wave 4 — runtime safety (parallel with Wave 3)

16. **Subagent timeout error surfacing** — set `result.error` with a clear message (executor.py).
17. **Filtered-tool logging** at INFO level in subagent executor.
18. **Plan-mode `write_todos` validation** — surface error codes in the tool description so the LLM can self-correct.
19. **Audit config-resident prompts** (`config/question_generation_config.py`, `config/title_config.py`) for the same patterns flagged here.
20. **Audit autoresearch prompts** in `control_plane/autoresearch_loop/` — completed in [07-additional-llm-call-sites.md](07-additional-llm-call-sites.md).
21. **Consolidate duplicate question-generation prompts** between `gateway/routers/suggestions.py` and `config/question_generation_config.py` (see [07](07-additional-llm-call-sites.md) §A).
22. **Add shared LLM-call wrapper** with timeout + 1-retry for control-plane callers (see [07](07-additional-llm-call-sites.md) §D).
23. **Truncate token-bloat hotspots** in `dreamy.py` repo overview and `vault_generate.py` (see [07](07-additional-llm-call-sites.md) §C).

## How to use these docs

- Each per-area document ([01](01-lead-agent-prompts.md)–[05](05-skill-metadata.md)) lists every prompt with file path and line numbers so you can jump straight to source.
- This summary is the "where to start" guide — read it first, pick a wave, then open the per-area doc for the exact rewrite suggestions.
- The improvement suggestions are deliberately concrete (proposed wording, schema additions, decision rules) so they can be lifted directly into PRs.
