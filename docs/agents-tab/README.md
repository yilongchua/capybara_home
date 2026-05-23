# Agents Tab — Reference for Future Re-implementation

> **Status:** Removed from the workspace sidebar on 2026-05-23. Routes, components, hooks, and the backend API still exist — only the nav link was deleted (`frontend/src/components/workspace/workspace-nav-chat-list.tsx`).
>
> **Why this doc exists:** the Agents feature is non-trivial — it spans a gallery UI, a two-step bootstrap flow (name → conversational SOUL.md authoring), a custom-agent chat surface, a CRUD REST API, a `setup_agent` tool that writes files to disk inside an agent run, and lead-agent runtime branches that swap prompt/tool-group/SOUL depending on whether a custom agent is active. This file captures every load-bearing detail so the tab can be brought back later without re-discovering the architecture.

---

## 1. What "Agents" means in Capybara Home

A **custom agent** is a per-user named persona that sits on top of the same Lead Agent runtime. It is **not** a separate LangGraph graph — it is a triple of:

1. A YAML config (`config.yaml`)
2. A SOUL.md file (personality + behavioural guardrails injected into the system prompt)
3. An optional `tool_groups` whitelist that narrows the lead agent's tool catalogue

When a chat thread is started with `agent_name=<name>`, the lead agent factory (`make_lead_agent` in `backend/src/agents/lead_agent/agent.py`) loads that agent's config, resolves a (possibly overridden) model, restricts tools to the agent's groups, and injects the agent's SOUL.md into the system prompt. Everything else (sandbox, memory, middlewares, sub-agents) is identical to a default lead-agent run.

Custom agents are stored under the per-install Capybara Home data dir:

```
{base_dir}/agents/{agent-name-lowercase}/
    config.yaml          # name, description, model?, tool_groups?
    SOUL.md              # personality / behaviour
    memory.json          # per-agent memory (written by MemoryMiddleware)
```

`base_dir` is whatever `get_paths().base_dir` resolves to (defaults to `backend/.capybara-home`). The path helpers live in `backend/src/config/paths.py`:

- `paths.agents_dir` → `{base_dir}/agents`
- `paths.agent_dir(name)` → `{base_dir}/agents/{name.lower()}`
- `paths.agent_memory_file(name)` → `{base_dir}/agents/{name}/memory.json`
- `paths.user_md_file` → `{base_dir}/USER.md` (global cross-agent profile)

Agent names must match `^[A-Za-z0-9-]+$` and are stored lowercase. The same regex is enforced on the frontend (`NAME_RE` in [new/page.tsx](../../frontend/src/app/workspace/agents/new/page.tsx)) and the backend (`AGENT_NAME_PATTERN` in [agents.py](../../backend/src/gateway/routers/agents.py) and [agents_config.py](../../backend/src/config/agents_config.py)).

---

## 2. Backend surface

### 2.1 REST API — `backend/src/gateway/routers/agents.py`

Mounted at `/api` and proxied by nginx. Tag: `agents`.

| Method | Path | Purpose | Notes |
|---|---|---|---|
| `GET` | `/api/agents` | List all custom agents | Returns `{agents: AgentResponse[]}` **without** `soul` |
| `GET` | `/api/agents/check?name=<name>` | Validate + availability check | `{available: bool, name: string}` — must run **before** `/agents/{name}` because of FastAPI path ordering |
| `GET` | `/api/agents/{name}` | Full agent (incl. SOUL.md) | 404 if missing |
| `POST` | `/api/agents` | Create agent | 409 if exists, 422 if name invalid, rolls back the directory on any failure |
| `PUT` | `/api/agents/{name}` | Update description / model / tool_groups / SOUL | Partial — any field `None` is a no-op |
| `DELETE` | `/api/agents/{name}` | `shutil.rmtree` the directory | 204 on success, 404 if missing |
| `GET` | `/api/user-profile` | Read global `USER.md` | Returns `{content: string | null}` |
| `PUT` | `/api/user-profile` | Write global `USER.md` | Creates `base_dir` if absent |

`AgentResponse` / `AgentCreateRequest` / `AgentUpdateRequest` are the source of truth for field types. **`soul` is intentionally omitted from list responses** to keep the gallery payload small — only `GET /{name}` returns it.

Edge cases the router handles (don't lose these on re-impl):

- `_validate_agent_name` raises 422 with a human-readable message including the regex.
- `_normalize_agent_name` lowercases — the on-disk dir name is always lowercase even if the user typed mixed case.
- `create_agent_endpoint` writes `config.yaml` and `SOUL.md` separately; if either write fails it `shutil.rmtree`s the half-created dir.
- `update_agent` re-loads the saved config after writing so the response reflects the merged-on-disk state (avoids drift if YAML round-tripping changes anything).
- The check endpoint hits the filesystem directly via `agent_dir.exists()` — there is no in-memory cache.

### 2.2 Config loaders — `backend/src/config/agents_config.py`

- `AgentConfig` (pydantic): `name`, `description`, `model | None`, `tool_groups | None`.
- `load_agent_config(name) -> AgentConfig | None` — returns `None` when `name is None`. Strips unknown YAML fields before passing to pydantic (legacy `prompt_file` etc. are silently dropped).
- `load_agent_soul(name) -> str | None` — reads `{agent_dir}/SOUL.md`, returns `None` when missing/empty. **If `name` is `None`, it reads `{base_dir}/SOUL.md`** (the default-agent SOUL).
- `list_custom_agents() -> list[AgentConfig]` — scans `paths.agents_dir`, skips dirs without `config.yaml`, logs warnings on broken entries instead of raising.

### 2.3 Lead-agent runtime integration — `backend/src/agents/lead_agent/agent.py`

The lead-agent factory reads `agent_name` from `config.configurable` and branches on it:

```python
agent_name = cfg.get("agent_name")
agent_config = load_agent_config(agent_name) if not is_bootstrap else None
```

Three downstream effects:

1. **Model resolution** (`_resolve_generator_model`): if the agent config sets `model`, it becomes the fallback when no `model_name` was passed in `configurable`. Routing config (`generator` stage) still applies on top.
2. **Tool restriction** (`get_available_tools(... groups=agent_config.tool_groups ...)`): if `tool_groups` is set, the agent only sees tools whose `group` matches one of those names. `None` means "all groups".
3. **System prompt** (`apply_prompt_template(..., agent_name=...)`): `prompt_cache.py` reads `{agent_dir}/SOUL.md` and injects it. The cache key includes `agent_name`, and `_is_stale` watches the SOUL.md mtime so editing the file mid-process invalidates the cached prompt.
4. **Memory isolation** (`MemoryMiddleware(agent_name=ctx.agent_name)`): each agent gets its own `memory.json` under `{agent_dir}/memory.json`. Memory does not leak between custom agents.
5. **Trace metadata** (`_inject_trace_metadata`): `agent_name` is added to LangSmith metadata as `"default"` when unset. Useful for filtering traces in observability tools.

### 2.4 Bootstrap mode + the `setup_agent` tool

Creating a new agent from the UI does **not** call `POST /api/agents` directly. Instead, the frontend:

1. Calls `GET /api/agents/check` to validate the name and confirm it's free.
2. Spins up a fresh thread with `configurable.is_bootstrap = true` and `agent_name = <name>`.
3. Sends a templated first user turn (`t.agents.nameStepBootstrapMessage`) telling the agent its name and asking it to bootstrap its SOUL.

The lead agent then enters the `params.is_bootstrap` branch:

- Skill catalogue is restricted to the single skill named `"bootstrap"` (so the model focuses on personality authoring instead of trying to use unrelated skills).
- Tools include the standard catalogue **plus** `setup_agent` (defined in `backend/src/tools/builtins/setup_agent_tool.py`).
- When the model decides the SOUL is ready, it calls `setup_agent(soul=..., description=...)` which:
  - Resolves `agent_name` from `runtime.context`.
  - Creates `{paths.agent_dir(name)}` and writes `config.yaml` (name + description) and `SOUL.md`.
  - Returns a `Command` that updates state with `created_agent_name` so the frontend can detect completion via `onToolEnd`.
  - Rolls back (`shutil.rmtree`) the agent directory if anything throws.

The frontend listens for `onToolEnd({ name: "setup_agent" })`, calls `getAgent(agentName)`, and on success swaps the input box for a success card with "Start chatting" and "Back to Gallery" buttons. **This is the only way custom agents are created today — the gallery's `New Agent` button routes to this conversational flow rather than a form.**

A `bootstrap` skill must exist for the bootstrap prompt to make sense — search the skills/public directory if revisiting. (The `setup_agent` tool itself is registered unconditionally in `src/tools/builtins/__init__.py`.)

### 2.5 Per-agent memory

`MemoryMiddleware(agent_name=...)` writes to `{agent_dir}/memory.json` instead of the global `memory.json` when `agent_name` is non-null. Otherwise everything else (debounced queue, fact extraction LLM call, query-relevant injection) is identical to the global flow described in `backend/CLAUDE.md` → "Memory System".

`USER.md` (at `{base_dir}/USER.md`) is a global cross-agent user profile written through `/api/user-profile`. It is currently **not** wired through the UI — the routes exist but the frontend exposes no editor. Worth restoring alongside the Agents tab if user profiles become relevant again.

---

## 3. Frontend surface

### 3.1 Routes

```
/workspace/agents                              → AgentGallery
/workspace/agents/new                          → NewAgentPage (2-step: name → bootstrap chat)
/workspace/agents/{agent_name}/chats/{thread_id}  → AgentChatPage (custom-agent chat)
/workspace/agents/{agent_name}/chats/new       → blank AgentChatPage (creates thread on first send)
```

All routes are App-Router client components ("use client").

### 3.2 Data layer — `frontend/src/core/agents/`

- [types.ts](../../frontend/src/core/agents/types.ts) — `Agent`, `CreateAgentRequest`, `UpdateAgentRequest`. Note `soul` is optional on `Agent` (only populated by `GET /agents/{name}`).
- [api.ts](../../frontend/src/core/agents/api.ts) — thin `fetch` wrappers around the 6 REST endpoints. Throws `Error(detail)` so React Query surfaces backend error messages directly.
- [hooks.ts](../../frontend/src/core/agents/hooks.ts):
  - `useAgents()` — `useWorkspaceRefreshQuery(["agents"])`. Refresh domain = `"agents"`, so any mutation publishing that domain auto-refetches.
  - `useAgent(name)` — single-agent fetch, disabled when `name` is falsy.
  - `useCreateAgent / useUpdateAgent / useDeleteAgent` — all invalidate `["agents"]` and `publishWorkspaceRefresh(["agents"], { source: "agents" })` on success.

The workspace-refresh subsystem (see `frontend/src/core/workspace-refresh.ts`) is what lets a `setup_agent` tool result inside a thread cause the gallery to re-render after backgrounded creation. Keep this wiring if re-implementing.

### 3.3 Components

| Component | Path | Role |
|---|---|---|
| `AgentGallery` | [agent-gallery.tsx](../../frontend/src/components/workspace/agents/agent-gallery.tsx) | Grid of `AgentCard`s + empty state + "New Agent" CTA. Loading spinner shown via `t.common.loading`. |
| `AgentCard` | [agent-card.tsx](../../frontend/src/components/workspace/agents/agent-card.tsx) | Single agent tile: name, model badge, description, tool_groups badges, "Chat" CTA, delete dialog. |
| `AgentWelcome` | [agent-welcome.tsx](../../frontend/src/components/workspace/agent-welcome.tsx) | Hero block shown above the input box when starting a new agent chat. |
| `NewAgentPage` | [new/page.tsx](../../frontend/src/app/workspace/agents/new/page.tsx) | Two-step flow: name form → bootstrap chat. Uses a stable `useMemo(() => uuid())` thread id so all bootstrap turns share one thread. |
| `AgentChatPage` | [[agent_name]/chats/[thread_id]/page.tsx](../../frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx) | Full chat experience scoped to a custom agent. Same provider stack as the default chat: `SubtasksProvider`, `ActivityProvider`, `ExecutionTraceProvider`, `DirectoryProvider`, `PromptInputProvider`, `DreamyProvider`. |
| Layout | [[agent_name]/chats/[thread_id]/layout.tsx](../../frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx) | Provides those contexts to nested routes. |

`AgentChatPage` mirrors the default chat page almost exactly — diff highlights:

- Calls `useAgent(agentName)` for the header pill (`{agent?.name ?? agentName}`).
- Adds `agent_name: agentName` into every `sendMessage` call's `context`.
- Routes `newChatHref` to `/workspace/agents/{agentName}/chats/new` instead of `/workspace/chats/new`.
- Same plan-mode / work-mode / "execute plan" intent matching as the default chat.

### 3.4 The 2-step new-agent flow (in detail)

`step === "name"` form:

1. User types a name; client-side regex `NAME_RE = /^[A-Za-z0-9-]+$/`.
2. On Enter / Continue → `checkAgentName(trimmed)`.
3. On `{available: false}` → show `t.agents.nameStepAlreadyExistsError`.
4. On success → set `agentName`, switch to `step === "chat"`, and immediately `sendMessage(threadId, { text: t.agents.nameStepBootstrapMessage.replace("{name}", trimmed) }, { is_bootstrap: true, mode: "work" })`.

`step === "chat"`:

- `useThreadStream({ threadId, context: { mode: "work", is_bootstrap: true } })`
- `onToolEnd({ name })`: if `name === "setup_agent"`, refetch the agent via `getAgent(agentName)`. The success card replaces the input box once `agent` is populated.
- Manual chat turns also pass `{ agent_name: agentName }` so the lead agent sees them on subsequent bootstraps.

Failure modes the current implementation tolerates silently:

- `getAgent` after `setup_agent`: catches and ignores ("agent write may not be flushed yet"). Could be tightened with a retry loop.
- Bootstrap thread is never persisted as a "real" chat in the sidebar (no entry in `useThreads()`), because it uses a fresh UUID and never matches `/workspace/chats/{id}`.

### 3.5 i18n keys

All UI strings live under `t.agents.*` in [en-US.ts](../../frontend/src/core/i18n/locales/en-US.ts) (and mirrored in `types.ts`):

```
agents.title / description / newAgent / emptyTitle / emptyDescription / chat / delete /
deleteConfirm / deleteSuccess / newChat / createPageTitle / createPageSubtitle /
nameStepTitle / nameStepHint / nameStepPlaceholder / nameStepContinue /
nameStepInvalidError / nameStepAlreadyExistsError / nameStepCheckError /
nameStepBootstrapMessage(name) / agentCreated / startChatting / backToGallery
```

Plus `t.sidebar.agents` (currently unused after the nav removal). `nameStepBootstrapMessage` is a `(name: string) => string`-shape template that substitutes `{name}` via string-replace, not interpolation, so keep the literal `{name}` placeholder in any new locale.

### 3.6 Sidebar nav (the removed bit)

The Agents link lived in [workspace-nav-chat-list.tsx](../../frontend/src/components/workspace/workspace-nav-chat-list.tsx) as a `SidebarMenuItem` with the `BotIcon` and `t.sidebar.agents` label, active when `pathname.startsWith("/workspace/agents")`. Restoring it = re-adding that menu item; everything else still works.

---

## 4. Data flow — creating + using a custom agent end-to-end

```
┌─ User clicks "New Agent" in sidebar gallery
│
├─ /workspace/agents/new (step=name)
│     ↓ name + GET /api/agents/check
│     ↓ (available)
│
├─ step=chat, threadId = uuid()
│   useThreadStream({ context: { is_bootstrap: true, mode: "work" } })
│   sendMessage(threadId, { text: bootstrapMessage }, { agent_name })
│       │
│       ▼ LangGraph runs make_lead_agent(config)
│         _extract_runtime_params → is_bootstrap=true, agent_name="foo"
│         (skills restricted to "bootstrap", tools += setup_agent)
│         model authors SOUL, calls setup_agent(soul=..., description=...)
│             │
│             ▼ Writes {base_dir}/agents/foo/{config.yaml, SOUL.md}
│             ▼ Returns Command(update={created_agent_name})
│
├─ onToolEnd("setup_agent") in frontend → getAgent("foo") → setAgent(...)
│   Success card → "Start chatting" → router.push(/workspace/agents/foo/chats/new)
│
└─ /workspace/agents/foo/chats/new (AgentChatPage)
    useThreadStream({ context: { agent_name: "foo", ...settings.context } })
    sendMessage(...)
       ▼ LangGraph runs make_lead_agent(config)
         is_bootstrap=false, agent_name="foo"
         agent_config = load_agent_config("foo")  → tool_groups, model
         apply_prompt_template(agent_name="foo")   → injects SOUL.md
         MemoryMiddleware(agent_name="foo")        → reads/writes per-agent memory.json
```

---

## 5. If you re-add the Agents tab later — checklist

1. **Sidebar** — re-add the `SidebarMenuItem` block in `workspace-nav-chat-list.tsx` (the import of `BotIcon` also needs to come back). Decide where it sits in the tab order — previously between Chats (now also removed) and Scheduled Pipeline.
2. **Routes** — already present under `frontend/src/app/workspace/agents/**`; no work needed unless you want to redesign the gallery or the bootstrap flow.
3. **API + tools** — fully intact. `setup_agent` is still registered in `src/tools/builtins/__init__.py` and will still be exported via `get_available_tools` in bootstrap mode.
4. **Edit-agent UI** — there is **no edit screen today**, only create + delete. `PUT /api/agents/{name}` and `useUpdateAgent` exist but nothing calls them from the gallery. Consider adding an editor that lets users tweak `description`, `model`, `tool_groups`, and `SOUL.md` directly — the backend is ready for it.
5. **USER.md profile** — `/api/user-profile` is wired backend-only. If the Agents tab grows into a "personas + profile" surface, this is the obvious place to host it.
6. **Bootstrap skill** — verify the public `bootstrap` skill still exists in `skills/public/`; without it, `apply_prompt_template(available_skills={"bootstrap"})` will produce an empty skill section and the model won't have any authoring guidance.
7. **Bootstrap thread cleanup** — bootstrap threads currently live in LangGraph state forever (they're never listed in the sidebar because they use a fresh UUID, but they consume storage). Consider deleting the thread after `setup_agent` succeeds if storage cost matters.
8. **Onboarding** — `t.agents.nameStepBootstrapMessage` uses `{name}` literal-replace, not `(name) => ...`. Type definition in `types.ts` matches.
9. **Trace correlation** — `_inject_trace_metadata` writes `agent_name: "default"` when unset, but `"foo"` when the custom-agent path runs. Useful for LangSmith dashboards.
10. **Tool-group narrowing edge case** — if a custom agent's `tool_groups` list excludes a group that contains a tool the prompt template assumes (e.g. memory tools, subagent `task`), the agent will silently lose that capability. Worth surfacing in the editor UI with warnings.

---

## 6. Files touched by the Agents feature (single source of truth)

**Frontend**
- `frontend/src/app/workspace/agents/page.tsx`
- `frontend/src/app/workspace/agents/new/page.tsx`
- `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`
- `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/layout.tsx`
- `frontend/src/components/workspace/agents/agent-gallery.tsx`
- `frontend/src/components/workspace/agents/agent-card.tsx`
- `frontend/src/components/workspace/agent-welcome.tsx`
- `frontend/src/components/workspace/workspace-nav-chat-list.tsx` *(nav link removed — restore here)*
- `frontend/src/core/agents/{api,hooks,types,index}.ts`
- `frontend/src/core/i18n/locales/en-US.ts` (and `types.ts`, `zh-CN.ts`) — `t.agents.*` and `t.sidebar.agents`

**Backend**
- `backend/src/gateway/routers/agents.py` (REST API)
- `backend/src/gateway/app.py` (`app.include_router(agents.router)` near "Agents API is mounted at /api/agents")
- `backend/src/config/agents_config.py` (`AgentConfig`, `load_agent_config`, `load_agent_soul`, `list_custom_agents`)
- `backend/src/config/paths.py` (`agents_dir`, `agent_dir`, `agent_memory_file`, `user_md_file`)
- `backend/src/agents/lead_agent/agent.py` (runtime branching on `agent_name` / `is_bootstrap`)
- `backend/src/agents/lead_agent/prompt_cache.py` (SOUL.md mtime-watch, `agent_name` in cache key)
- `backend/src/tools/builtins/setup_agent_tool.py` (`setup_agent` tool)
- `backend/src/tools/builtins/__init__.py` (registers `setup_agent`)
- `backend/src/agents/memory/*` (`MemoryMiddleware(agent_name=...)` path)

**Skills**
- `skills/public/bootstrap/` (referenced by `apply_prompt_template(available_skills={"bootstrap"})`)

---

## 7. Open questions / known gaps to address on re-impl

- **No edit screen.** `useUpdateAgent` exists but is uncalled. Required if users want to evolve their personas.
- **No SOUL preview.** The success card hides the actual SOUL.md the model wrote; users currently can't see or edit it from the UI.
- **No "duplicate agent" flow.** Forking a successful persona requires editing files on disk.
- **No agent search / tagging.** Gallery is a flat grid.
- **No agent-scoped chat history view.** `/workspace/chats` lists threads but doesn't filter by `agent_name`. Threads have `agent_name` in their runtime context but no first-class persistent field on the thread record.
- **No agent export/import.** Useful for sharing personas across installs.
- **Bootstrap skill is implicit.** No frontend signalling if `bootstrap` skill is missing or disabled.

These are good targets for the next iteration.
