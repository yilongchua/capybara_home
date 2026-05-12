# Custom Agents

Custom agents let you run the lead agent with a distinct personality, model, and tool scope — without modifying any code. Each agent is a directory under `.capybara-home/agents/{name}/`.

## Directory Structure

```
backend/.capybara-home/agents/
├── example/                  # Template to copy from
│   ├── config.yaml           # Required — agent metadata and overrides
│   └── SOUL.md               # Optional — personality and behavioural framing
└── autoresearch/             # Built-in autoresearch companion agent
    ├── config.yaml
    └── SOUL.md
```

## config.yaml

Every agent directory must contain a `config.yaml`:

```yaml
name: my-agent
description: "One-line description shown in the agent list."
# model: null              # Optional — inherits global default when omitted
# tool_groups: null        # Optional — inherits all groups when omitted
```

**Fields:**

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Must match the directory name (lowercase, alphanumeric + hyphens) |
| `description` | string | `""` | Shown in the agent picker UI |
| `model` | string or null | null | Override the LLM for this agent, e.g. `"llama3-70b"` |
| `tool_groups` | list or null | null | Restrict tools to specific groups, e.g. `["bash", "file:read", "web"]` |

## SOUL.md

`SOUL.md` is an optional markdown file that is injected verbatim into the system prompt, **after base instructions and before skills**. It defines the agent's:

- Personality and communication style
- Domain focus and research methodology
- Behavioural guardrails and stop conditions
- Any domain-specific workflow steps

**What to put in SOUL.md:**
- Framing: "You are a X agent whose purpose is Y"
- Methodology: step-by-step research or execution approach
- Standards: evidence requirements, output format, confidence thresholds
- Boundaries: what the agent will not do or claim

**What NOT to put in SOUL.md:**
- Tool instructions — use Skills for that (SOUL.md does not know which tools are available)
- Restatements of base prompt rules (clarification policy, output paths, etc.)
- Configuration — that belongs in `config.yaml`

## How SOUL.md is Loaded

```
apply_prompt_template()
    └── get_agent_soul(agent_name)
            └── load_agent_soul(agent_name)
                    └── reads .capybara-home/agents/{name}/SOUL.md
                            → wrapped in <soul>...</soul> tags
                            → inserted between <role> and <thinking_style>
```

When `agent_name` is `None` (the default agent), the loader checks `.capybara-home/SOUL.md` instead — this acts as a global personality override for all unnamed sessions.

## Activating a Custom Agent

Pass `agent_name` in the LangGraph `config.configurable`:

```python
config = {
    "configurable": {
        "thread_id": "my-thread",
        "agent_name": "autoresearch",   # matches .capybara-home/agents/autoresearch/
        "is_plan_mode": True,
        "subagent_enabled": True,
    }
}
```

Or set it in the frontend thread settings if supported by the UI.

## Creating a New Agent

1. Copy the `example/` directory:
   ```bash
   cp -r backend/.capybara-home/agents/example backend/.capybara-home/agents/my-agent
   ```

2. Edit `config.yaml` — update `name` and `description`.

3. Edit `SOUL.md` — write the agent's personality and methodology.

4. No restart required — the agent is resolved at request time.

## Built-in Agents

### `autoresearch`

Companion agent for interactive autoresearch sessions. Designed to be used alongside the automated Knowledge Vault pipeline.

**Workflow:**
1. Reads the objective's `progress.md` to identify topic, endpoint goal, and coverage gaps
2. Decomposes the endpoint goal into verifiable sub-claims
3. Searches to raise low-confidence sub-claims first
4. Writes new evidence to `knowledge_vault/01_raw/{objective_id}/`
5. Generates targeted next queries and writes them back to the progress ledger
6. Stops when all sub-claims reach sufficient confidence or the endpoint is met

**Activate via:**
```python
{"configurable": {"agent_name": "autoresearch", "subagent_enabled": True}}
```

> Note: The automated Knowledge Vault pipeline (scheduler, discover/ingest/compile/lint/sufficiency steps) runs independently via the control plane and does not use this agent's SOUL.md. This agent is for **interactive research sessions** in the chat UI.

## Notes

- Agent directories live in `.capybara-home/agents/` which is gitignored — they are user data, not repo content.
- Agent name validation: must match `^[A-Za-z0-9-]+$`.
- If `model` is set in `config.yaml` but not found in `config.yaml` model list, the global default is used.
- Per-agent memory is stored separately at `.capybara-home/agents/{name}/memory.json`.
