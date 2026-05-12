# Important Files and Functions

## Autoresearch Control

### `backend/src/agents/middlewares/autoresearch_middleware.py`
- `_derive_topic(messages, explicit_topic)`
- `_derive_endpoint_goal(topic, context_lines)`
- `_handle_autoresearch(request, explicit_topic)`
- `wrap_model_call(request, handler)`
- `awrap_model_call(request, handler)`
- `after_agent(state, runtime)`

### `backend/src/control_plane/agents/autoresearch_agent.py`
- `start_objective(...)`
- `pause_objective(...)`
- `resume_objective(...)`
- `delete_objective(...)`
- `update_after_run(run)`
- `update_after_sufficiency(run, report)`
- `_upsert_daily_schedule(...)`
- `_derive_recommendations(run, objective)`
- `_write_progress_ledger(objective)`

### `backend/src/control_plane/models.py`
- `AutoresearchObjective`
- `ControlPlaneSnapshot.autoresearch_objectives`

### `backend/src/control_plane/service.py`
- `start_autoresearch_objective(...)`
- `pause_autoresearch_objective(...)`
- `resume_autoresearch_objective(objective_id)`
- `delete_autoresearch_objective(objective_id)`
- `get_autoresearch_progress_markdown(objective_id)`
- `record_workspace_activity(thread_id, message)`
- `has_recent_workspace_activity(hours)`
- `_resume_inactive_autoresearch_jobs()`

## Knowledge Vault Runtime

### `backend/src/control_plane/agents/knowledge_vault_agent.py`
- `execute(context)`
- `_execution_profile(context)`
- `_execute_discover(context, profile)`
- `_execute_ingest(context, profile)`
- `_execute_compile(context, profile)`
- `_execute_lint(context, profile)`
- `_execute_synthesis(context, profile)`
- `_execute_sufficiency(context, profile)`

### `backend/src/control_plane/vault_learning.py`
- `check_loop_guard(...)`
- `discover(urls, source, topic, max_results)`
- `enqueue_search_results(query, results)`
- `claim_search_queue_items(topic, max_items)`
- `clear_queued_search_results(reason)`
- `dedupe_recent_queries(query_text, topic_tags)`
- `write_query_note(...)`
- `expire_queries()`
- `ingest(urls, source, topic, queue_items)`
- `compile_incremental()`
- `compile_indexes()`
- `lint_vault(freshness_window_days)`
- `synthesize_knowledge_graph(objective_id, topic, graph_evidence)`
- `evaluate_sufficiency(objective_id, topic, min_score)`
- `get_action_items(limit)`
- `search(query, limit)`
- `get_run_summary()`
- `get_source(source_id)`
- `purge_objective(objective_id)`

### `backend/src/control_plane/vault_text_utils.py`
- shared text normalization/frontmatter/slug/token helpers used by vault manager

## API + Template Layer

### `backend/src/control_plane/services/templates.py`
- `builtin_templates()`
- defines both:
- `knowledge-vault-continuous`
- `knowledge-vault-autoresearch`

### `backend/src/gateway/routers/pipelines.py`
- autoresearch objective CRUD/start/pause/resume endpoints

### `backend/src/gateway/routers/vault.py`
- vault status/search/source/action-items/sufficiency/progress endpoints

## Search Tooling

### `backend/src/community/knowledge_vault_search/search.py`
- `VaultSearcher.search(query, categories, limit)`
- `_bm25_score(query_tokens, doc_tokens, avg_dl)`
- `_excerpt(body, query_tokens)`

### `backend/src/community/knowledge_vault_search/tool.py`
- `_get_searcher()`
- `query_knowledge_vault_tool(query, categories, limit)`

## Frontend Control Surfaces

### `frontend/src/app/workspace/vault/page.tsx`
- `VaultPage()`
- `handleCreateObjective()`
- progress markdown fetch + percent parsing effect

### `frontend/src/core/control-plane/api.ts`
- `fetchAutoresearchObjectives()`
- `startAutoresearchObjective(payload)`
- `pauseAutoresearchObjective(...)`
- `resumeAutoresearchObjective(...)`
- `deleteAutoresearchObjective(...)`
- `fetchVaultStatus()` / `searchVault()` / `fetchVaultActionItems()` / `evaluateVaultSufficiency()`

### `frontend/src/core/control-plane/hooks.ts`
- `useAutoresearchObjectives()`
- `useStartAutoresearchObjective()`
- `useDeleteAutoresearchObjective()`
- `useVaultStatus()`
- `useVaultSearch()`
- `useVaultActionItems()`
