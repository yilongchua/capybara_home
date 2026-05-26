# 05 — Skill Metadata

Audit of every `SKILL.md` frontmatter description (the field the lead agent uses for routing) plus the skill loader / parser / curator.

## Inventory (20 skills)

| # | Skill | File | Lines | Approx. words | Routing quality |
|---|-------|------|-------|---------------|-----------------|
| 1 | batch-workflow | [skills/batch-workflow/SKILL.md](../../skills/batch-workflow/SKILL.md#L1-L20) | 1–~20 frontmatter | ~180 | ★★★★★ |
| 2 | bootstrap | [skills/bootstrap/SKILL.md](../../skills/bootstrap/SKILL.md#L1-L20) | 1–~20 | ~100 | ★★★★☆ |
| 3 | chart-visualization | [skills/chart-visualization/SKILL.md](../../skills/chart-visualization/SKILL.md#L1-L20) | 1–~20 | ~70 | ★★★☆☆ |
| 4 | consulting-analysis | [skills/consulting-analysis/SKILL.md](../../skills/consulting-analysis/SKILL.md#L1-L20) | 1–~20 | ~100 | ★★★☆☆ |
| 5 | data-analysis | [skills/data-analysis/SKILL.md](../../skills/data-analysis/SKILL.md#L1-L20) | 1–~20 | ~70 | ★★★★☆ |
| 6 | deep-research | [skills/deep-research/SKILL.md](../../skills/deep-research/SKILL.md#L1-L20) | 1–~20 | ~90 | ★★★★★ |
| 7 | dreamy-workflow | [skills/dreamy-workflow/SKILL.md](../../skills/dreamy-workflow/SKILL.md#L1-L20) | 1–~20 | ~80 | ★★★★★ |
| 8 | excel-modeling | [skills/excel-modeling/SKILL.md](../../skills/excel-modeling/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★☆☆☆ |
| 9 | find-skills | [skills/find-skills/SKILL.md](../../skills/find-skills/SKILL.md#L1-L20) | 1–~20 | ~80 | ★★★★★ |
| 10 | frontend-design | [skills/frontend-design/SKILL.md](../../skills/frontend-design/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★★★☆ |
| 11 | github-deep-research | [skills/github-deep-research/SKILL.md](../../skills/github-deep-research/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★★☆☆ |
| 12 | image-generation | [skills/image-generation/SKILL.md](../../skills/image-generation/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★★☆☆ |
| 13 | knowledge-vault | [skills/knowledge-vault/SKILL.md](../../skills/knowledge-vault/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★★☆☆ |
| 14 | pdf-pro | [skills/pdf-pro/SKILL.md](../../skills/pdf-pro/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★★★☆ |
| 15 | podcast-generation | [skills/podcast-generation/SKILL.md](../../skills/podcast-generation/SKILL.md#L1-L20) | 1–~20 | ~60 | ★★★☆☆ |
| 16 | ppt-generation | [skills/ppt-generation/SKILL.md](../../skills/ppt-generation/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★★☆☆ |
| 17 | skill-creator | [skills/skill-creator/SKILL.md](../../skills/skill-creator/SKILL.md#L1-L20) | 1–~20 | ~60 | ★★★★☆ |
| 18 | surprise-me | [skills/surprise-me/SKILL.md](../../skills/surprise-me/SKILL.md#L1-L20) | 1–~20 | ~50 | ★★★★☆ |
| 19 | video-generation | [skills/video-generation/SKILL.md](../../skills/video-generation/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★★☆☆ |
| 20 | web-design-guidelines | [skills/web-design-guidelines/SKILL.md](../../skills/web-design-guidelines/SKILL.md#L1-L20) | 1–~20 | ~40 | ★★★★☆ |

## Skill loader / parser / curator

| Module | File | Lines | Notes |
|--------|------|-------|-------|
| Parser | [backend/src/skills/parser.py](../../backend/src/skills/parser.py#L1-L74) | 1–74 | Extracts frontmatter — no validation of description quality |
| Loader | [backend/src/skills/loader.py](../../backend/src/skills/loader.py#L22-L110) | 22–110 | Walks `skills/{public,custom}`; silent on malformed YAML |
| Skill dataclass | [backend/src/skills/types.py](../../backend/src/skills/types.py#L1-L63) | 1–63 | No constraints on `description` length |
| Auto-curation | [backend/src/skills/curation.py](../../backend/src/skills/curation.py#L69-L102) | 69–102 | Generates stub descriptions ("Auto-curated helper for frequent `<tool>` workflows") |

## Findings — high-impact

### excel-modeling (★★☆☆☆)

**Issues**
- Only ~40 words; "formula-heavy" is technical jargon.
- Overlap with `data-analysis` not addressed.
- No "when NOT to use" guidance.

**Suggested rewrite**
```
Use when building or refactoring Excel financial models — formula validation,
workbook inspection, color-coded styling, or LibreOffice-based recalculation.
NOT for SQL-style analysis, pivot tables, or aggregation over CSV/XLSX —
use `data-analysis` for those.
```

### github-deep-research (★★★☆☆)

**Issues**
- Only 2 user-language triggers; body mentions "competitive analysis" and "timeline reconstruction" but the description doesn't.

**Suggested rewrite**
```
Multi-round deep research on GitHub repositories — comprehensive analysis,
timeline reconstruction, competitive intelligence, or in-depth investigation
of open-source projects.
```

### image-generation / video-generation / podcast-generation / ppt-generation

All four rely on the single verb pattern *generate / create / produce*. Add content-type and downstream-use triggers:

- **image-generation**: character designs, scene compositions, product mockups, UI elements, concept art — also use within presentation/article flows when imagery is needed.
- **video-generation**: animated scenes, visual explanations, motion sequences, product demos — also include in content-generation workflows.
- **podcast-generation**: convert articles / research reports / documentation / blog posts into audio.
- **ppt-generation**: visual storytelling, multi-slide content, executive summaries with imagery — include user-facing language ("turn this into a deck").

### chart-visualization (★★★☆☆)

**Issues**
- Generic "visualize data" framing.
- No content/domain examples.
- No "when NOT to use" pointing to `data-analysis` for upstream SQL work.

**Suggested rewrite**
```
Use when turning data into visuals — time-series trends, market or product
comparisons, sales funnels, hierarchies, distributions. Intelligently selects
chart type per dataset shape. NOT for exploratory SQL/CSV analysis — start
with `data-analysis` and pass the cleaned result here.
```

### knowledge-vault (★★★☆☆)

**Issues**
- Niche framing ("ingest articles into Obsidian-compatible vault") doesn't surface user-facing intents.
- Boundary with `deep-research` unclear.

**Suggested rewrite**
```
Use when building a personal knowledge base — ingest articles, keep source
notes current, or compile synthesis/index pages for continuous learning.
For one-time research with no persistence, use `deep-research` instead.
```

### consulting-analysis (★★★☆☆)

**Issues**
- Two-phase flow (analysis framework → report) is invisible in the frontmatter.
- Boundary with `deep-research` and `data-analysis` unclear.

**Suggested rewrite**
```
Use when producing consulting-grade analyses with structured frameworks
(market analysis, competitive intelligence, consumer insights, financial).
Phase 1 = framework + workplan; Phase 2 = synthesis into a final report.
For preliminary topic discovery use `deep-research` first.
```

## Findings — medium-impact

### bootstrap (★★★★☆)

- Add an explicit "NOT for editing an existing SOUL.md in place" clarification; the skill regenerates rather than patches.

### frontend-design / web-design-guidelines / pdf-pro / skill-creator / surprise-me

- All solid; minor polish — add one "NOT for ..." line each to anchor the boundary versus adjacent skills (`frontend-design` vs `web-design-guidelines`, `pdf-pro` vs `data-analysis`, etc.).

## Findings — loader/parser layer

### Parser (`backend/src/skills/parser.py` lines 1–74)

**Issues**
- Accepts descriptions of any length.
- No keyword presence check (no warning if frontmatter omits trigger phrases).
- Malformed YAML returns `None` with console warning only.

**Improvements**
- Add description length warnings (<60 words → log a warning, ≥250 → log a warning).
- Add a soft check for at least one trigger phrase (`when ...`, `Use this skill when ...`).
- Surface YAML parse failures via the curation flow (so authors notice).

### Loader (`backend/src/skills/loader.py` lines 22–110)

**Improvements**
- Emit a single structured warning if any enabled skill fails parse-time validation.
- Add a CLI sanity command: `python -m skills.lint` that prints rating-style output.

### Skill dataclass (`backend/src/skills/types.py` lines 1–63)

**Improvements**
- Add an optional `when_not_to_use: str | None` field so anti-trigger guidance gets a structured home (currently lives only in prose body).
- Add `triggers: list[str] | None` for explicit keyword lists used by retrieval / fuzzy routing in the future.

### Curation (`backend/src/skills/curation.py` lines 69–102)

**Issues**
- Auto-generated frontmatter says only *"Auto-curated helper for frequent `<tool>` workflows"* — guaranteed to be a low-quality routing description.

**Improvements**
- Pull the most common natural-language user prompts that triggered the tool sequence and inject 2–3 example triggers.
- Mark these proposals as `draft: true` in frontmatter; require human review before publishing.

## Cross-cutting recommendations

1. **Standardise frontmatter shape** with at least:
   ```yaml
   ---
   name: …
   description: >-
     One paragraph (60–120 words) covering when to use, with 2–3 user-language triggers.
   when_not_to_use: |
     - Pointer to adjacent skills (e.g. "Use `data-analysis` for SQL exploration.")
   triggers:
     - "explicit phrase 1"
     - "explicit phrase 2"
   workflow: false
   ---
   ```
2. **Lint at load time** — warn on missing trigger keywords, missing `when_not_to_use`, descriptions <60 words.
3. **Fix the "generate / create / produce" cliché** in the four content-generation skills with content-type triggers.
4. **Disambiguate adjacent skills** explicitly: `excel-modeling` ↔ `data-analysis`; `chart-visualization` ↔ `data-analysis`; `consulting-analysis` ↔ `deep-research`; `knowledge-vault` ↔ `deep-research`; `frontend-design` ↔ `web-design-guidelines`.
5. **Upgrade auto-curated skills** with usage-derived triggers before they are surfaced to the lead agent.
