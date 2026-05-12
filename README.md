# Capybara Home

An open-source **super agent harness** that orchestrates sub-agents, persistent memory, and sandboxed execution environments to perform complex, multi-step tasks — powered by extensible skills.

## Architecture

```
                         Nginx (2026)
                     Reverse Proxy / Unified Entry
                    /            |             \
          LangGraph (2024)   Gateway (8001)   Frontend (3000)
          Agent Runtime      REST API          Next.js UI
               |                |
        Middleware Registry   17 Route Modules
               |
          Lead Agent (LLM)
         /      |       \
    Sandbox   MCP     Sub-Agents
    Tools    Tools    (parallel)
```

| Layer | Stack |
|---|---|
| **Backend** | Python 3.12, LangGraph 1.0.6, LangChain, FastAPI |
| **Frontend** | Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4 |
| **LLMs** | OpenAI, Anthropic, Google Gemini, DeepSeek, local llama.cpp |
| **Infrastructure** | Docker, Kubernetes, Nginx, GitHub Actions |
| **Channels** | Slack, Telegram |

## Quick Start

### Configuration

```bash
git clone https://github.com/capybara-home/capybara-home.git
cd capybara-home
make config
```

Edit `config.yaml` — define at least one model:

```yaml
models:
  - name: gpt-4
    display_name: GPT-4
    use: langchain_openai:ChatOpenAI
    model: gpt-4
    api_key: $OPENAI_API_KEY
    max_tokens: 4096
    temperature: 0.7
```

Set API keys in `.env`:

```bash
OPENAI_API_KEY=your-key
```

### Docker (Recommended)

```bash
make docker-init     # Pull sandbox image (first time only)
make docker-start    # Start all services
```

Access: **http://localhost:2026**

### Local Development

```bash
make check           # Verify Node.js 22+, pnpm, uv, nginx
make install         # Install all dependencies
make dev             # Start all services with hot-reload
```

Access: **http://localhost:2026**

### Local Research Stack

Start a fully local research stack (SearXNG + Onyx + crawl4ai):

```bash
make local-stack-start
make local-stack-status
```

## Core Features

### Skills (18 Built-in)

Skills are structured capability modules (Markdown files with YAML frontmatter) that define workflows and best practices. Loaded progressively — only when the task needs them.

| Category | Skills |
|---|---|
| **Research** | deep-research, github-deep-research, find-skills |
| **Generation** | ppt-generation, podcast-generation, video-generation, pdf-pro |
| **Data** | data-analysis, excel-modeling, chart-visualization, consulting-analysis |
| **Design** | frontend-design, web-design-guidelines, bootstrap |
| **Media** | image-generation |
| **Meta** | skill-creator, knowledge-vault, surprise-me |

Custom skills go in `skills/custom/` (gitignored).

### Sub-Agent Delegation

The lead agent spawns sub-agents for parallel execution. Each sub-agent gets its own scoped context, tools, and termination conditions.

- Max 3 concurrent sub-agents per turn
- 15-minute timeout per task
- Built-in agents: `general-purpose`, `bash`

### Sandboxed Execution

Each task runs in an isolated environment with a full filesystem:

```
/mnt/user-data/
  uploads/       # User files
  workspace/     # Agent working directory
  outputs/       # Final deliverables
```

Three sandbox modes: **Local**, **Docker**, **Kubernetes** (via provisioner).

### Persistent Memory

LLM-powered fact extraction across sessions. Stores user context, preferences, and accumulated knowledge locally in `.capybara-home/memory.json`.

- Configurable confidence threshold (default: 0.7)
- Max 100 facts, debounced updates (30s)
- Top 15 facts injected into system prompt per interaction

### MCP Integration

Configurable MCP servers extend tool capabilities:

- Lazy-loaded (tools initialized on first use)
- Cache invalidation via file mtime
- OAuth support (`client_credentials`, `refresh_token`)
- Transports: stdio, SSE, HTTP

### IM Channels

Receive tasks from messaging apps. Channels auto-start when configured.

| Channel | Transport |
|---------|-----------|
| Telegram | Bot API (long-polling) |
| Slack | Socket Mode |

### Context Engineering

- **Isolated sub-agent context** — sub-agents can't see each other's state
- **Automatic summarization** — context reduction at configurable token limits
- **Adaptive polling** — workspace polling uses event-driven refresh with slower idle fallback intervals to reduce noisy background requests
- **Plan mode** — DAG todo tracking + Planner/Generator/Evaluator loop (Pro mode defaults)
- **Handoff artifacts** — planner/evaluator write `plan.md`, `sprint_contract.md`, `report.md` under thread workspace
- **Hooks + retries** — command hooks (`SessionStart`/`PreToolUse`/`PostToolUse`/`FileChanged`) and per-tool retry policy
- **Trajectory replay** — JSONL trajectories can be replay-checked via eval fixtures
- **Resumable runs** — resume paused/interrupted runs via Gateway API and embedded client helper
- **Phase-gated tools + scratchpad** — optional tool allow-lists by phase plus `.handoffs/scratchpad.md`
- **Versioned memory + redact** — append-only memory versions with auditable redact mutations

### Embedded Python Client

```python
from src.client import CapybaraClient

client = CapybaraClient()
response = client.chat("Analyze this paper", thread_id="my-thread")

for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])

# Resume from existing checkpointed thread state
result = client.resume_run(thread_id="my-thread", run_id="run-123")
```

## Project Structure

```
capybara-home/
  backend/
    src/
      agents/          # LangGraph agent + middleware registry chain
      gateway/         # FastAPI REST API (16 routers)
      sandbox/         # Execution environment (local/docker/k8s)
      subagents/       # Parallel task delegation
      tools/           # Tool registry + built-ins
      mcp/             # MCP integration + OAuth
      models/          # LLM factory (thinking/vision support)
      skills/          # Skill discovery + loading
      config/          # Configuration system
      community/       # Community tools (searxng, onyx, crawl4ai, etc.)
      channels/        # IM integrations (slack, telegram)
      client.py        # Embedded Python client
    tests/             # 39 test files (pytest)
    docs/              # Backend documentation
  frontend/
    src/
      app/             # Next.js App Router
      components/      # UI (shadcn), workspace, landing, AI elements
      core/            # Business logic (threads, API, artifacts, i18n, memory, skills, MCP)
      hooks/           # Shared React hooks
      styles/          # Tailwind CSS 4 + theming
  skills/
    public/            # 18 built-in skills
    custom/            # User skills (gitignored)
  docker/              # Docker compose + nginx configs
  scripts/             # Dev/ops scripts
  docs/                # Project documentation
```

## Configuration

| File | Purpose |
|------|---------|
| `config.yaml` | Models, tools, sandbox, memory, channels, summarization, prompt/permissions/trajectory/metrics/progress_guard + phase-B blocks (`todos`, `routing`, `planner`, `evaluator`, `sprint_contracts`, `handoffs`, `hooks`, `retry`) + phase-C blocks (`resume`, `tool_disclosure`, `scratchpad`, `task_memory`, `memory_versioning`, `skill_curation`, `benchmarks`) |
| `extensions_config.json` | MCP servers, skill enable/disable |
| `.env` | API keys, endpoints, feature flags |

Control-plane API optimization:
- `GET /api/pipelines/runs` supports optional `thread_id`, `status`, and `limit` query params for narrowed run lists.

Generated from examples via `make config`.

## Development

```bash
make dev             # Start all services (hot-reload)
make stop            # Stop all services

# Backend only (from backend/)
make test            # Run pytest suite
make lint            # Ruff linting
make format          # Ruff formatting

# Frontend only (from frontend/)
pnpm check           # Lint + typecheck
pnpm dev             # Dev server with Turbopack
```

### Docker

```bash
make docker-init     # Build/pull images
make docker-start    # Start services
make docker-stop     # Stop services
make docker-logs     # View logs
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, workflow, and guidelines.

## License

[MIT License](./LICENSE)
