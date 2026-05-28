# DeerFlow → CapyHome: Comparative Analysis & Implementation Plan

## Core Objective

**Everything must be local.** CapyHome-home runs fully locally with local LM providers (llama.cpp, vLLM, Ollama, or any OpenAI-compatible endpoint). External integrations (SearXNG, Docker-based tools) are user-controlled via the Integrations tab — not bundled as fallbacks. All recommendations are scoped to this local-first constraint.

## Executive Summary

Both systems share the same DNA — LangGraph-based harness, middleware chains, LLM routing, persistent memory, skill injection. **CapyHome-home is considerably more feature-rich** in planning, evaluation, sandboxing, trajectory, and control-plane operations. DeerFlow's meaningful advantages that remain relevant for a local deployment are: **deferred tool discovery, per-agent personality injection, and optional content guardrails.**

> The four improvements already implemented (memory-summarization coupling, skill rescue, loop detection, todo exit enforcement) are confirmed live — they should **not** be re-implemented.

---

## Side-by-Side Comparison

| Dimension | CapyHome | DeerFlow | Gap |
|---|---|---|---|
| **Agent Runtime** | LangGraph + 25 middleware | LangGraph + 14 middleware | CapyHome ahead |
| **Middleware orchestration** | Topological sort, 25 layers | Ordered list, 14 layers | CapyHome ahead |
| **Tool loading** | All MCP tools loaded eagerly | Deferred registry + `tool_search` tool | **DeerFlow ahead** |
| **Planning** | PlannerMiddleware + DAG todos + sprint contracts | TodoMiddleware (flat list) | CapyHome ahead |
| **Evaluation** | EvaluatorMiddleware + deterministic pre-checks | None | CapyHome ahead |
| **Memory** | JSON + LLM extraction, debounced 30s, versioned | JSON + LLM extraction, debounced 2s, per-agent | Roughly equal |
| **Context summarization** | SummarizationMiddleware + memory flush hook | SummarizationMiddleware | CapyHome ahead |
| **Loop detection** | LoopDetectionMiddleware | LoopDetectionMiddleware | Roughly equal |
| **Per-agent personality** | Per-agent config.yaml only | Per-agent `SOUL.md` injected into prompt | **DeerFlow ahead** |
| **Skills** | Progressive disclosure, matcher, body injection | Static injection into prompt | CapyHome ahead |
| **Sandbox** | Abstract (local/docker/k8s), virtual paths | Abstract (local/docker) | CapyHome ahead |
| **RAG / Knowledge** | BM25 vault search + LightRAG + MCP | Community search APIs only | CapyHome ahead |
| **Web search** | SearXNG + crawl4ai (Docker `websearch` instance, full extraction pipeline) | External APIs (Exa, Tavily, etc.) | CapyHome ahead |
| **IM channels** | Slack + Telegram | None | CapyHome ahead |
| **Guardrails** | None | Optional GuardrailsMiddleware | **DeerFlow ahead** |
| **Subagents** | Executor + 3 concurrent + deferred queue | Executor + 3 concurrent | Roughly equal |
| **Trajectory/audit** | JSONL trajectory, MetricsMiddleware | None | CapyHome ahead |
| **Resume/checkpoints** | ResumeStateMiddleware + Command(resume) | LangGraph checkpointer only | CapyHome ahead |
| **Control plane** | Autoresearch scheduler, vault pipeline | None | CapyHome ahead |

---

## Gap Analysis: What DeerFlow Has That CapyHome Should Adopt

### Gap 1 — Deferred Tool Search *(High impact)*

**DeerFlow pattern:** Large MCP tool sets go into a `DeferredToolRegistry`. Only a lightweight `tool_search(query)` tool is exposed in the agent's live schema. When the agent needs a specific capability, it calls `tool_search`, gets back a ranked list of matching tool names, and the middleware activates those tools for subsequent calls.

**CapyHome problem:** All MCP tools are loaded eagerly and injected into the tool schema on every turn. As MCP servers grow (any number via `extensions_config.json`), the schema can balloon to thousands of tokens — especially damaging for local models that have smaller context windows and are more sensitive to schema noise than cloud models.

**Relevant files:**
- `src/tools/tools.py`
- `src/mcp/`
- `src/agents/lead_agent/agent.py`

---

### Gap 2 — Per-Agent SOUL.md Personality Injection *(Medium impact)*

**DeerFlow pattern:** Each named agent can have `agents/{agent_name}/SOUL.md` — a freeform markdown file injected verbatim into the system prompt after base instructions. Gives agents distinct voices, values, and behavioural constraints without modifying code.

**CapyHome problem:** Per-agent config exists (`agents/{name}/config.yaml`) but only controls model/tool selection. There is no mechanism to give an agent a distinct personality or behavioural framing beyond skills. For a local deployment with multiple specialised agents (research, coding, analysis), per-agent prompt tuning matters especially because local models respond more strongly to explicit role framing.

**Relevant files:**
- `src/agents/lead_agent/agent.py`
- `src/agents/lead_agent/prompt.py`

---

### Gap 3 — GuardrailsMiddleware *(Situational impact)*

**DeerFlow pattern:** Optional middleware positioned before the LLM call. Validates both input (user messages) and output (model response) against configurable policies. Can be backed by regex patterns, keyword lists, or a local LLM call for semantic validation — fully local.

**CapyHome problem:** No equivalent. `PermissionMiddleware` handles tool-call authorisation but does not validate the content of messages or model outputs. For local deployments serving multiple users or sensitive domains, local content policy enforcement adds a useful safety layer.

**Relevant files:**
- `src/agents/lead_agent/agent.py`
- `src/agents/middlewares/`

---

## Implementation Plan

### Priority 1 — Deferred Tool Search

**Effort:** Large (3–4 days)
**Impact:** High — directly reduces per-turn context usage as MCP footprint grows; critical for local models with constrained context windows

**Approach:**

1. Create `src/tools/deferred_registry.py` — a `DeferredToolRegistry` class that holds tools not yet activated for the current session.
2. Create `src/tools/builtins/tool_search.py` — `tool_search(query: str) -> list[ToolMatch]` using BM25 or simple token-overlap matching over tool names and descriptions. No embeddings, no external calls.
3. Create `src/agents/middlewares/deferred_tool_filter_middleware.py` — before LLM call, removes deferred tools from schema; after agent calls `tool_search`, marks matched tools as active for this session.
4. Extend `get_available_tools()` in `src/tools/tools.py`: add `deferred: bool` flag on tool config. Tools with this flag go into the registry rather than the live schema.
5. Add config toggle `tools.deferred_search_enabled: bool`.
6. Place `DeferredToolFilterMiddleware` between `ToolDisclosureMiddleware` and `HooksMiddleware` in the chain.

**Config change:**
```yaml
tools:
  deferred_search_enabled: true   # new top-level flag
  - name: my-mcp-tool
    use: ...
    group: mcp
    deferred: true                # new per-tool flag
```

**Tests:** `tests/test_deferred_tool_registry.py`, `tests/test_deferred_tool_filter_middleware.py`

---

### Priority 2 — Per-Agent SOUL.md

**Effort:** Small (0.5 day)
**Impact:** Medium — improves consistency and quality for specialised local agents; near-zero risk

**Approach:**

1. In `apply_prompt_template()` (`src/agents/lead_agent/prompt.py`): check for `agents/{agent_name}/SOUL.md` when `agent_name` is set in runtime config.
2. If found, append contents as a dedicated section after the base prompt and before skills.
3. No config toggle needed — file presence activates it automatically.

**Tests:** Extend `tests/test_prompt_template.py` with assertions for SOUL.md injection when file exists, and no injection when absent.

---

### Priority 3 — GuardrailsMiddleware

**Effort:** Medium (1 day)
**Impact:** Situational — valuable for multi-user or sensitive local deployments; off by default

**Approach:**

1. Create `src/agents/middlewares/guardrails_middleware.py` — `GuardrailsMiddleware` with `before_model()` (validates input messages) and `after_model()` (validates output).
2. Policy defined in `config.yaml`: regex patterns, keyword block lists, or a local LLM endpoint for semantic validation — all local, no external calls.
3. On violation: either log-and-warn (permissive mode) or inject an error message and halt (strict mode).
4. Place between `PermissionMiddleware` and `ToolDisclosureMiddleware` in the chain.
5. Disabled by default (`guardrails.enabled: false`).

**Tests:** `tests/test_guardrails_middleware.py`

---

## Implementation Sequence

```
Week 1
├── Priority 2: Per-agent SOUL.md     (0.5 day)
└── Priority 3: GuardrailsMiddleware  (1 day, optional)

Week 2–3
└── Priority 1: Deferred tool search  (3–4 days + integration tests)
```

Priority 2 is a quick win with no risk — ship it first. Priority 1 is the most impactful but requires careful integration with the existing MCP cache and `ToolDisclosureMiddleware`.

---

## Files Affected

| File | Type | Change |
|---|---|---|
| `src/agents/lead_agent/prompt.py` | Modify | SOUL.md loading and injection |
| `src/tools/tools.py` | Modify | Deferred flag filtering in `get_available_tools()` |
| `src/tools/deferred_registry.py` | **New** | Deferred tool registry |
| `src/tools/builtins/tool_search.py` | **New** | `tool_search` builtin tool |
| `src/agents/middlewares/deferred_tool_filter_middleware.py` | **New** | Schema filter + session activation |
| `src/agents/middlewares/guardrails_middleware.py` | **New** | Content guardrails (Priority 3) |
| `src/agents/lead_agent/agent.py` | Modify | Wire new middleware into registry |
| `config.yaml` | Modify | `deferred_search_enabled`, `guardrails` config keys |

---

## What NOT to Port from DeerFlow

| DeerFlow Feature | Reason to Skip |
|---|---|
| Claude OAuth credential discovery | No cloud LM connections — not applicable |
| Auto-thinking budget (80% of max_tokens) | Local models have no thinking budget constraints |
| Prompt cache block control | Local models do not use Anthropic cache control |
| Web search diversity (Exa, Tavily, Jina, DDGS) | CapyHome's `websearch` Docker instance (SearXNG + crawl4ai) is a more complete local extraction pipeline than any of DeerFlow's external API tools |
| `LoopDetectionMiddleware` | Already live |
| `TodoMiddleware` (flat list) | CapyHome's `TodoDagMiddleware` (DAG-based) is strictly more capable |
| Memory debounce (2s) | CapyHome's 30s is intentional to allow batching; 2s would thrash a local LLM |
| DeerFlow's model provider classes | CapyHome uses the langchain ecosystem which covers all local providers |
