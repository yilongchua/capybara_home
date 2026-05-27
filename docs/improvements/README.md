# Prompt & Description Improvements — CapyHome

Comprehensive audit of every LLM-facing prompt, system message, tool description, and skill description across the CapyHome codebase, with concrete improvement suggestions for each.

## Scope

Anything that ends up in front of a model is in scope:

- Lead agent system prompt and its componentized sections
- Subagent system prompts and lead-agent-routing descriptions
- Tool descriptions (the strings the LLM reads to decide when to call a tool)
- Middleware-owned prompts (planner, evaluator, summarization, web search summary, dreamy bootstrap, etc.)
- Skill `SKILL.md` frontmatter descriptions (used for LLM-side routing)

## Files in this folder

| # | File | Coverage |
|---|------|----------|
| 1 | [01-lead-agent-prompts.md](01-lead-agent-prompts.md) | Lead agent system prompt sections, memory prompt, todo prompts, plan/dreamy mode sections |
| 2 | [02-subagent-prompts.md](02-subagent-prompts.md) | 7 built-in subagent configs + shared executor/registry |
| 3 | [03-tool-descriptions.md](03-tool-descriptions.md) | Built-in tools: `ask_user_for_clarification`, `present_files`, `recall`, `setup_agent`, `task`, `view_image`, `write_todos` |
| 4 | [04-middleware-prompts.md](04-middleware-prompts.md) | Planner, recursion pivot, plan evaluator, evaluator, summarization, web search summary, dreamy bootstrap |
| 5 | [05-skill-metadata.md](05-skill-metadata.md) | All 20 `SKILL.md` descriptions + parser/loader/curation |
| 6 | [06-summary-and-priorities.md](06-summary-and-priorities.md) | Cross-cutting findings, ranked priorities, suggested rollout order |
| 7 | [07-additional-llm-call-sites.md](07-additional-llm-call-sites.md) | Final sweep: control plane (vault, autoresearch), gateway routers, plan-execution gate, config-resident templates |

## How to read each file

Each file follows the same shape:

1. **Inventory table** — file path, line range, identifier, purpose, length.
2. **Per-item findings** — issues with quotes/snippets and concrete improvement suggestions.
3. **Cross-cutting notes** — patterns shared across the section.

File path and line numbers are always included so the source can be jumped to directly.

## Out of scope

- Frontend copy and UI strings (not LLM-facing).
- Logging / telemetry strings (not sent to a model).
- Config files that don't carry prompt content (covered only when they hold a `prompt_template`).
