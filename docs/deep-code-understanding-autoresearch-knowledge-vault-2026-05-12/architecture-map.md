# Architecture Map

## Core Components

- `backend/src/agents/middlewares/autoresearch_middleware.py`
- `backend/src/control_plane/agents/autoresearch_agent.py`
- `backend/src/control_plane/agents/knowledge_vault_agent.py`
- `backend/src/control_plane/vault_learning.py`
- `backend/src/control_plane/service.py`
- `backend/src/control_plane/services/templates.py`
- `backend/src/gateway/routers/pipelines.py`
- `backend/src/gateway/routers/vault.py`
- `backend/src/community/knowledge_vault_search/search.py`
- `backend/src/community/knowledge_vault_search/tool.py`
- `frontend/src/app/workspace/vault/page.tsx`
- `frontend/src/core/control-plane/api.ts`
- `frontend/src/core/control-plane/hooks.ts`

## Execution Graph (Autoresearch)

1. Chat input or API request triggers objective creation.
2. `ControlPlaneService.start_autoresearch_objective()` delegates to `AutoresearchOrchestratorAgent.start_objective()`.
3. Objective is created/updated in `snapshot.autoresearch_objectives`.
4. Bootstrap run starts with template `knowledge-vault-autoresearch`.
5. Step execution routes through `KnowledgeVaultAgent.execute()`:
- `vault_discover`
- `vault_ingest`
- `vault_compile`
- `vault_lint`
- `synthesize_knowledge_graph`
- `vault_sufficiency_evaluate`
6. Heavy storage and curation logic is handled by `VaultLearningManager`.
7. Run completion updates recommendations + scheduler state.
8. Objective ledger is written to markdown/json in `knowledge_vault/03_ops/autoresearch/objectives/<slug>/`.

## Data and Storage Model

Knowledge Vault root (default): `backend/.capybara-home/knowledge_vault` (via resolved configured paths)

- `00_schema/`: policy and schema docs
- `01_raw/`: raw source packages and fetched metadata
- `02_compiled/`: durable curated markdown pages (`sources/entities/concepts/syntheses/queries`)
- `03_ops/`: queues, reports, tasks, autoresearch objective trackers
- `.vault_state/manifest.json`: vault operational state, loop guard, coverage/sufficiency signals

## API Surface

Autoresearch endpoints (`pipelines.py`):
- `GET /api/pipelines/autoresearch`
- `GET /api/pipelines/autoresearch/{objective_id}`
- `POST /api/pipelines/autoresearch/start`
- `POST /api/pipelines/autoresearch/{objective_id}/pause`
- `POST /api/pipelines/autoresearch/{objective_id}/resume`
- `DELETE /api/pipelines/autoresearch/{objective_id}`

Vault endpoints (`vault.py`):
- `GET /api/vault/status`
- `GET /api/vault/search`
- `GET /api/vault/sources/{source_id}`
- `GET /api/vault/action-items`
- `POST /api/vault/sufficiency/evaluate`
- `GET /api/vault/objectives/{objective_id}/progress.md`

## Frontend Integration

`frontend/src/app/workspace/vault/page.tsx` is the main control surface:
- polls objectives + vault status every 20s
- starts objectives
- updates schedule time and enablement
- manually runs scheduler jobs
- deletes objectives
- fetches objective markdown progress and parses percent
