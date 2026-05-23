# LightRAG Removal — File-by-File Changelog

> Records exactly which files were touched during the removal and what
> changed in each. Use alongside [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md)
> to reverse a specific edit.

## Deleted

| Path | Reason |
|---|---|
| `backend/src/community/lightrag/__init__.py` | Tool package gone. |
| `backend/src/community/lightrag/tool.py` | 109-line query wrapper. |
| `backend/src/community/lightrag/__pycache__/` | Build artifact. |

## Edited — backend

| Path | Change |
|---|---|
| `backend/src/community/registry.py` | Removed `"query_lightrag"` entry from `COMMUNITY_TOOL_REGISTRY`. |
| `backend/src/config/control_plane_config.py` | Removed nested `KnowledgeVaultConfig.LightRAGConfig` class and the `lightrag` field. |
| `backend/src/control_plane/service.py` | Removed `lightrag` entry from `_integration_service_catalog`, the `lightrag` block in `_resolve_integration_services`, and the `lightrag` branch in `_docker_keywords_for_service`. |
| `backend/src/control_plane/vault_learning.py` | Removed `graph_evidence` parameter from `synthesize_knowledge_graph` and dropped the `graph_payload`/`graph_evidence` keys from its report. |
| `backend/src/agents/middlewares/phase_tool_filter_middleware.py` | Removed `"query_lightrag"` from `_DRAFT_HIDDEN_TOOLS`; updated docstring. |
| `backend/src/agents/middlewares/plan_execution_gate_middleware.py` | Removed `"query_lightrag"` from `_SCOPE_GATED_TOOLS`. |
| `backend/src/agents/middlewares/execution_trace_middleware.py` | Removed `"query_lightrag"` from `_TRACEABLE_TOOL_NAMES`. |
| `backend/src/agents/middlewares/web_search_circuit_breaker_middleware.py` | Updated circuit-open message to drop the `query_lightrag` suggestion. |
| `backend/src/agents/middlewares/planner_middleware.py` | Removed `query_lightrag` from the planner schema docstring. |
| `backend/src/agents/lead_agent/prompt.py` | Removed item 3 from `<fetch_policy>` and the `query_lightrag` mention in `FETCH_POLICY_SECTION`. |
| `backend/CLAUDE.md` | Removed `lightrag/` from the community subpackage list. |

## Edited — frontend

| Path | Change |
|---|---|
| `frontend/src/core/control-plane/types.ts` | Removed `"lightrag"` from `IntegrationServiceId` union. |
| `frontend/src/app/workspace/integrations/page.tsx` | Removed `"lightrag"` from `orderedServiceIds`. |
| `frontend/src/app/page.tsx` | Removed `"lightrag"` from `serviceOrder`. |
| `frontend/src/components/workspace/messages/execution-trace-panel.tsx` | Removed the `query_lightrag` branch in the tool-label switch. |

## Edited — config + scripts

| Path | Change |
|---|---|
| `config.yaml` | Removed `tool_backends.lightrag` and `knowledge_vault.lightrag` blocks. |
| `scripts/local-stack.sh` | Removed all LightRAG and Infinity rerank env vars, `lightrag_compose`/`start_lightrag_compose`/`stop_lightrag_compose`/`start_lightrag_service`/`stop_lightrag_service`, the `start-lightrag` / `stop-lightrag` case arms, the usage text, the `start_stack`/`stop_stack` calls, and the aggregate banner lines. |
| `skills/knowledge-vault/SKILL.md` | Removed the "Graph Evidence Mode" section. |

## Edited — tests

| Path | Change |
|---|---|
| `backend/tests/test_community_tools_api.py` | Removed `"query_lightrag"` from registry-expected sets and from the `builtin_expected` set. |
| `backend/tests/test_phase_tool_filter_middleware.py` | Removed `"query_lightrag"` from the parametrized tool-name tuple. |
| `backend/tests/test_plan_execution_gate_middleware.py` | Removed `"query_lightrag"` from the parametrized tool-name tuple. |
| `backend/tests/test_integration_removal.py` | Updated `_resolve_integration_services` test to drop the `lightrag` SimpleNamespace mock and added new assertions that `lightrag` is no longer in the integration service catalog or in resolved services. |

## Untouched

These files still mention LightRAG as part of *historical analysis*.
Removing the mentions would falsify the record; they were intentionally
left in place:

- `docs/prompt-analysis/lead-agent-prompt-analysis-prompt-id-{1,4,6,15,17}.md`
- `docs/audit/README.md` (mentions LightRAG in a past trajectory example)
- `backend/docs/deerflow-analysis-and-improvements.md` (the RAG-row comparison)
