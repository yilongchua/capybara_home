# 07 — Additional LLM Call Sites

Final-sweep coverage of every remaining LLM call site that wasn't in docs 01–05: control plane (vault, autoresearch), gateway routers, plan-execution gate, config-resident templates, and the dreamy repo-overview job.

## Discovery method

`grep -rn "ainvoke\|\.invoke(\|ChatAnthropic\|chat_completion\|messages\.create\|llm\.invoke\|model\.invoke" backend/src --include="*.py"` returns 34 invocation sites. Docs 01–04 already cover the lead agent, all subagents, and 8 middleware call sites. This document covers the remaining sites and their prompts.

## Inventory

| # | Call site | Prompt source | File | Lines |
|---|-----------|---------------|------|-------|
| 1 | `plan_execution_gate_middleware._classify(...)` | `_CLASSIFIER_PROMPT_TEMPLATE` | [backend/src/agents/middlewares/plan_execution_gate_middleware.py](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L106-L191) | 106–115 (prompt), 191 (call) |
| 2 | `suggestions` router | inline prompt | [backend/src/gateway/routers/suggestions.py](../../backend/src/gateway/routers/suggestions.py#L99-L114) | 99–114 |
| 3 | Dreamy repo-overview job — system prompt | inline `SystemMessage` | [backend/src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py#L615-L621) | 615–621 |
| 4 | Dreamy repo-overview job — user prompt | `_build_repo_overview_refresh_prompt()` | [backend/src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py#L541-L564) | 541–564 |
| 5 | Question-generation config template | `prompt_template` default | [backend/src/config/question_generation_config.py](../../backend/src/config/question_generation_config.py#L38-L45) | 38–45 |
| 6 | Title-generation config template | `prompt_template` default | [backend/src/config/title_config.py](../../backend/src/config/title_config.py#L30) | 30 |
| 7 | Vault learning (control plane) | (per agent surveyed) | [backend/src/control_plane/vault_learning.py](../../backend/src/control_plane/vault_learning.py#L900-L905) | ~900–905 |
| 8 | Autoresearch generator | `GENERATOR_PROMPT` | [backend/src/control_plane/autoresearch_loop/generator.py](../../backend/src/control_plane/autoresearch_loop/generator.py#L47-L89) | 47–89 |
| 9 | Autoresearch reflector | `REFLECTOR_PROMPT` | [backend/src/control_plane/autoresearch_loop/reflector.py](../../backend/src/control_plane/autoresearch_loop/reflector.py#L19-L53) | 19–53 |
| 10 | Autoresearch researcher dispatch | `_build_task_prompt()` | [backend/src/control_plane/autoresearch_loop/researcher.py](../../backend/src/control_plane/autoresearch_loop/researcher.py#L34-L42) | 34–42 |
| 11 | Autoresearch LLM wrapper | (delegates to caller's prompt) | [backend/src/control_plane/autoresearch_loop/llm.py](../../backend/src/control_plane/autoresearch_loop/llm.py#L60-L72) | 60–72 |
| 12 | Vault source analysis | `ANALYZE_SOURCE_PROMPT` | [backend/src/control_plane/prompts/vault_analyze.py](../../backend/src/control_plane/prompts/vault_analyze.py#L1-L45) | 1–45 |
| 13 | Vault page generation | `GENERATE_PAGE_PROMPT` | [backend/src/control_plane/prompts/vault_generate.py](../../backend/src/control_plane/prompts/vault_generate.py#L1-L27) | 1–27 |
| 14 | Memory updater LLM call | `MEMORY_UPDATE_PROMPT` (already covered in [01](01-lead-agent-prompts.md)) | [backend/src/agents/memory/updater.py](../../backend/src/agents/memory/updater.py#L260-L271) | 260–271 |

## Detailed findings

### 1. `_CLASSIFIER_PROMPT_TEMPLATE` — plan_execution_gate_middleware.py 106–115

**What it does**: Classifies whether a search call during Plan Mode is *scope-clarifying* or *content-gathering*.

**Issues**
- Forces a one-word answer (`scope` or `content`). No way to express mixed intent.
- Real queries often blend both (e.g., *"which sources cover X"*).
- Uses Python `repr()` for the query — leaks quoting artifacts into the prompt.

**Improvements**
- Allow three values: `scope`, `content`, `mixed` (and default `mixed` toward the safer behaviour — block content but let scope through).
- Show 2 borderline examples and the correct label for each.
- Quote the query naturally: `with query: "..."` instead of `{query!r}`.
- Optionally request a one-line rationale and parse `scope` / `content` from the first word.

### 2. Suggestions router inline prompt — gateway/routers/suggestions.py 99–114

**What it does**: HTTP endpoint that generates N follow-up suggestion questions.

**Issues**
- "EXACTLY N" can fail when the model produces fewer; the endpoint then errors out.
- No diversity guidance — easy to get N near-duplicate variants.
- Duplicated logic with `question_generation_config.py` (item #5 below) — drift risk.

**Improvements**
- Switch to "UP TO N" and accept partial responses.
- Add: *"Vary topic and depth — no near-duplicates."*
- Add: *"Do not echo the user's last turn verbatim."*
- Consolidate with the middleware template (see cross-cutting).

### 3. Dreamy repo-overview system prompt — gateway/routers/dreamy.py 615–621

**Current**: One sentence — `"You are an expert software architect and reviewer. Generate a detailed, practical repository analysis report in markdown only."`

**Issues**
- No grounding in the actual repo structure.
- No format spec, no required sections.
- Relies entirely on the human message to provide structure.

**Improvements**
- Expand to ~5 lines covering audience (engineer unfamiliar with codebase), required sections (Executive summary → Architecture → Critical files → Execution flow → Risks → Recommended reading order), and source-grounding rule (cite paths from the mirrored docs; do not invent).
- Explicitly forbid inventing file paths.

### 4. Dreamy repo-overview user prompt — gateway/routers/dreamy.py 541–564

**What it does**: Stitches `index.md`, `directory_tree.md`, `file_catalog.md`, `failed_files.md` from the mounted mirror into one analysis prompt.

**Issues**
- `file_catalog.md` can balloon to >100 KB; the prompt has no truncation strategy.
- No handling for missing mirrors beyond inserting `(missing)`.
- The base constant `_REPO_OVERVIEW_PROMPT` itself is vague ("all critical files", "main features").

**Improvements**
- Cap each section block (e.g., `file_catalog.md` first 10k chars + tail truncation marker).
- Treat missing mirrors as hard skips with explicit acknowledgement in output: *"unable to analyse \<section> because mirror is missing."*
- Tighten `_REPO_OVERVIEW_PROMPT` with concrete asks per section (target lengths, what counts as "critical").

### 5. Question-generation config template — config/question_generation_config.py 38–45

**Current**:
```
Given the following conversation exchange, generate {count} concise follow-up
questions a user might want to ask next. Focus on natural continuations,
clarifications, or deeper dives.

User: {user_message}
Assistant: {assistant_response}

Return ONLY the questions as a numbered list (1. ... 2. ... etc.), one per line,
no extra commentary.
```

**Issues**
- Three suggested modes ("natural continuations / clarifications / deeper dives") with no prioritisation.
- Numbered text output is harder to parse than JSON.
- Effectively duplicates the suggestions router (item #2).

**Improvements**
- Merge with the suggestions endpoint (single template imported from one location).
- Switch to JSON array output: `{"questions": ["...", "..."]}`.
- Prioritise: *"Prefer follow-ups that deepen understanding over rephrasings."*
- Cap each question: ≤15 words.

### 6. Title-generation config template — config/title_config.py line 30

**Current**:
```
Generate a concise title (max {max_words} words) for this conversation.
User: {user_msg}
Assistant: {assistant_msg}

Return ONLY the title, no quotes, no explanation.
```

**Issues**
- "No quotes" suggests a recurring past failure but isn't reinforced with positive examples.
- No anti-generic-title rule (titles like "Conversation" or "Help" leak through otherwise).
- No character limit.

**Improvements**
- Add 3 example outputs (specific, descriptive titles).
- Forbid generic titles: *"Avoid 'Conversation', 'Question', 'Help', 'Discussion' — be specific to the content."*
- Add a character cap alongside the word cap (e.g., ≤60 chars).
- Document the `✨` Dreamy prefix is applied externally — don't add emoji.

### 7. Vault learning — control_plane/vault_learning.py ~900–905

**What it does**: Calls the model with an analysis/curation prompt as part of the vault learning loop. The prompt is constructed locally; see surrounding helper.

**Action**
- Audit the exact prompt around line 905 with the file open in the editor.
- Ensure it includes the same entity/concept rules as `ANALYZE_SOURCE_PROMPT` (item #12) — divergence is a maintenance risk.

### 8. `GENERATOR_PROMPT` — autoresearch_loop/generator.py 47–89

**What it does**: Proposes up to N new sub-questions per loop iteration, prioritising empty coverage clusters and pushing depth levels L1 → L2 → L3.

**Issues**
- 12 clusters × 3 levels is a lot of structure; no examples of well-formed questions per cluster/level.
- "Phrased the way a human would type it" is subjective.
- Skips with judgement-based fallback ("skip nonsensical clusters for abstract topics") but provides no examples.

**Improvements**
- Append a small "good vs. bad" examples block:
  ```
  GOOD: "how does prompt caching work in claude api"
  BAD:  "Could you please elaborate on the mechanisms of prompt caching?"
  ```
- Provide 1 example question per (cluster, level) pair as a static reference, or at least per cluster.
- Use novelty score (recency of last answered question in the cluster) alongside depth to break ties.
- Add a fallback: *"If all clusters are sufficiently covered, return an empty array."*

### 9. `REFLECTOR_PROMPT` — autoresearch_loop/reflector.py 19–53

**What it does**: Proposes follow-up questions motivated by previously answered ones; emits an overall reflection.

**Issues**
- "Directly motivated by one finding" can miss cross-finding intersections.
- "Novelty" left undefined.
- No fallback when no genuine follow-ups exist.

**Improvements**
- Allow `parent_id` to be a list to support cross-finding follow-ups.
- Define a novelty scale: `high` (contradicts prior), `medium` (significantly extends), `low` (confirms / clarifies).
- Fallback: *"If no genuine follow-ups, return `{ "followups": [], "reflection": "research fully addressed the topic" }`.*

### 10. `_build_task_prompt()` — autoresearch_loop/researcher.py 34–42

**What it does**: Brief dispatch prompt for the `vault-source-researcher` subagent.

**Issues**
- "Save exactly once" is a hard constraint that conflicts with multi-facet findings.
- No success criterion definition.
- Relies entirely on the subagent's own system prompt for the rest.

**Improvements**
- Allow multiple saves *under the same topic* when a single sub-question yields multiple independent insights: *"Save each independent insight as its own vault entry under the same `topic`."*
- Define success: *"You've answered if your vault entry contains a clear `## Answer` section that addresses the sub-question."*
- Reference the JSON output schema explicitly so the dispatch prompt and subagent prompt stay aligned.

### 11. `autoresearch_loop/llm.py` 60–72

**What it does**: Thin model-invocation wrapper used by generator / reflector / researcher. No prompt of its own.

**Issues**
- No timeout / retry policy here means each upstream caller must handle it.

**Improvements**
- Add a default timeout and one-retry policy with exponential backoff at this wrapper level so individual prompts don't have to.

### 12. `ANALYZE_SOURCE_PROMPT` — control_plane/prompts/vault_analyze.py 1–45

**What it does**: Extracts structured analysis (summary, claims, entities, concepts, tags, open questions, gap queries, synthesis refs) from an ingested source.

**Issues**
- Entity rules are strict and prescriptive, but the boundary with `concepts` is fuzzy ("crystals" = concept, "Black Tourmaline" = entity).
- "Prefer multi-word proper nouns" tension with the brevity ask.
- No examples for the *current* domain — examples lean spiritual/lifestyle, which biases generalisation.

**Improvements**
- Add 2–3 domain-neutral examples and explicitly mark entity vs. concept side-by-side.
- Cap entity rule conflict resolution: *"If a term qualifies as both, put it under `entities` only."*
- Define `synthesis_refs` more concretely: *"Cross-source topic slugs this source would link to under a wikilink. Use existing vault topics when possible."*
- Add a `language` field to the output so downstream processing knows the source language.

### 13. `GENERATE_PAGE_PROMPT` — control_plane/prompts/vault_generate.py 1–27

**What it does**: Renders an analysed source into Obsidian-compatible Markdown.

**Issues**
- "Obsidian-compatible" undefined.
- Both the full source text *and* the analysis JSON are passed — duplicated tokens.
- `review_items` semantics undefined.

**Improvements**
- Define "Obsidian-compatible" with concrete syntax: headers (`##`, `###`), bulleted lists (`-`), wikilinks (`[[...]]`), code fences for code.
- Drop the source text — the analysis JSON already extracted what's needed.
- Define `review_items` explicitly: *"Items that need human follow-up — uncertain claims, missing citations, outdated info."*
- Add an output target length (e.g., `summary_markdown` 100–200 words).

### 14. Memory updater LLM call — agents/memory/updater.py 260–271

**Status**: Uses `MEMORY_UPDATE_PROMPT` already audited in [01-lead-agent-prompts.md](01-lead-agent-prompts.md) (lines 18–123 of `agents/memory/prompt.py`).

**Wrapper concerns** (line 271)
- Single `model.invoke(prompt)` with no timeout or retry — a slow model call blocks memory updates indefinitely.

**Improvements**
- Add `asyncio.wait_for` (or sync equivalent) with the timeout already used by `summarization_middleware`.
- On timeout, skip the memory update for this turn rather than failing the whole flow.

## Cross-cutting observations

### A. Question-generation duplication

`gateway/routers/suggestions.py` and `config/question_generation_config.py` independently define essentially the same prompt. Pick one source of truth (the config) and have the router call into the same generator. This appears as item #2 + item #5 above.

### B. Vault analysis vs. vault learning divergence

`control_plane/prompts/vault_analyze.py` defines the canonical entity/concept rules, but `control_plane/vault_learning.py` also calls the model with an analysis-like prompt (line 905). Confirm both paths share rules or consolidate.

### C. Token-bloat hotspots

- `dreamy.py` repo-overview user prompt embeds the full `file_catalog.md` and `directory_tree.md`.
- `vault_generate.py` embeds the full source text *and* the analysis JSON.

Both are easy wins: truncate the catalog with a tail marker; drop the source text from the page generator.

### D. Missing timeouts / retries

The non-middleware LLM calls (memory updater, vault analyze, vault generate, autoresearch generator/reflector/researcher) all call `model.invoke` directly with no shared timeout/retry policy. Add a thin wrapper in `autoresearch_loop/llm.py` (and consider reusing it across the control plane) so each caller doesn't reinvent timeout handling.

### E. Output format inconsistency

| Caller | Output | Notes |
|--------|--------|-------|
| Plan-execution-gate classifier | one word | Brittle for mixed intent |
| Suggestions router | numbered list | Hard to parse |
| Question-generation middleware | numbered list | Same |
| Title middleware | bare string | Susceptible to quoting / emoji |
| Dreamy repo overview | Markdown | OK |
| Vault analyze / generate | strict JSON | Best practice |
| Autoresearch generator / reflector | strict JSON | Best practice |
| Autoresearch researcher | JSON via subagent | Best practice |
| Memory updater | strict JSON | Best practice |

Migrate the four non-JSON callers toward strict JSON (or single-line bare string with explicit anti-quoting examples for title).

### F. Hard rules vs. soft hints

`ANALYZE_SOURCE_PROMPT` has explicit stoplists ("DO NOT include 'your', 'their', 'this'..."), which work well. Apply the same pattern to other prompts that have known failure modes:

- `title` template: stoplist generic titles.
- `suggestions`: stoplist near-duplicate phrasings.
- `vault_generate`: stoplist preamble like "Here is your..." / code fences.
