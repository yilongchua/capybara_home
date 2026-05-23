# CapyHome — Agent Quick Reference

## Structure

Monorepo: `backend/` (Python/LangGraph/FastAPI) + `frontend/` (Next.js/React/TS).
Everything else: `docker/`, `skills/`, `scripts/`, `docs/`.

## Ports

| Service | Port |
|---|---|
| Nginx (unified entry) | 2026 |
| LangGraph server | 2024 |
| Gateway API (FastAPI) | 8001 |
| Frontend (Next.js) | 3000 |

## Commands

**From root** (full app):
```
make check          # Verify Node 22+, pnpm, uv, nginx
make config         # Bootstrap config.yaml + .env (NON-IDEMPOTENT — aborts if config.yaml exists)
make install        # `uv sync` in backend/ + `pnpm install` in frontend/
make dev            # Start all services (LangGraph + Gateway + Frontend + Nginx)
make stop           # Kill all services and clean sandbox containers
```

**Backend** (`backend/`):
```
make lint           # `uvx ruff check .`
make format         # `uvx ruff check . --fix && uvx ruff format .`
make test           # `PYTHONPATH=. uv run pytest tests/ -v`
make dev            # `uv run langgraph dev --no-browser --allow-blocking --no-reload`
make gateway        # `uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001`
```

**Frontend** (`frontend/`):
```
pnpm lint           # ESLint
pnpm typecheck      # `tsc --noEmit`
pnpm check          # lint + typecheck (BROKEN — `next lint` resolves to invalid dir; use the two above separately)
pnpm dev            # `next dev --turbo`
pnpm build          # `next build` (requires `BETTER_AUTH_SECRET` env var)
```

**CI order** (what `.github/workflows/` enforces):
- Backend: `make lint` → `make test`
- Frontend: `pnpm lint` → `pnpm typecheck`

## Config

- `config.yaml` — main app config (models, tools, sandbox, skills, memory, etc.). Values starting with `$` resolve as env vars.
- `extensions_config.json` — MCP servers and skill enable/disable state.
- Both live in project root. Precedence: explicit path > env var > `backend/` > project root.
- Generated from `config.example.yaml` / `extensions_config.example.json` via `make config`.

## Testing

- Backend: 39+ pytest files in `backend/tests/`. Run with `make test`.
- Frontend: **No test framework configured.**
- Some backend tests need a running backend (live integration tests in `test_client_live.py`).
- Regression tests: `test_docker_sandbox_mode_detection.py`, `test_provisioner_kubeconfig.py`.

## Gotchas

- `BETTER_AUTH_SECRET` is required for `pnpm build` (env validation). Set it or use `SKIP_ENV_VALIDATION=1` (still warns).
- `make config` is a one-time bootstrap — it refuses to overwrite existing config.
- Proxy env vars (`http_proxy`, `HTTPS_PROXY`, etc.) can silently break `pnpm install`. Unset them if registry access fails.
- `make dev` includes cleanup; if interrupted, run `make stop` first.
- No pre-commit hooks configured.
- `backend/` uses `uv` for Python package management; `frontend/` uses pnpm 10.26.2.
- Generated component dirs (`frontend/src/components/ui/`, `frontend/src/components/ai-elements/`) come from registries — don't edit manually.

## Existing Instruction Files

- `backend/CLAUDE.md` — comprehensive backend architecture, middleware chain, config schema, API docs.
- `frontend/CLAUDE.md` — frontend architecture, data flow, code style, env vars.
- `backend/AGENTS.md` — points to `backend/CLAUDE.md`.
- `frontend/AGENTS.md` — verbose architecture overview (low signal).
- `.github/copilot-instructions.md` — detailed onboarding guide (redundant with this file + CLAUDE.md).

## Code Style

- Backend: ruff, 240-char line length, double quotes, 4-space indent, Python 3.12+.
- Frontend: ESLint + TypeScript. Path alias `@/*` → `src/*`. Import ordering enforced. Use `cn()` for conditional Tailwind classes.
