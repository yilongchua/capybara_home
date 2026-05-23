# LightRAG — Verbatim Source Archive

> This document preserves every LightRAG-related source artifact that was
> deleted or edited during removal. Restoring LightRAG should start by
> copying these snippets back into the listed file paths.

---

## 1. The tool module

### `backend/src/community/lightrag/__init__.py`

```python
from .tool import query_lightrag_tool

__all__ = ["query_lightrag_tool"]
```

### `backend/src/community/lightrag/tool.py`

```python
"""LightRAG internal query tool for objective-driven graph evidence retrieval."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from langchain.tools import tool

from src.config import get_app_config

logger = logging.getLogger(__name__)


def _lightrag_config() -> dict[str, Any]:
    cfg = get_app_config().knowledge_vault.lightrag
    return {
        "enabled": bool(getattr(cfg, "enabled", False)),
        "base_url": str(getattr(cfg, "base_url", "http://localhost:9621")).rstrip("/"),
        "timeout_seconds": float(getattr(cfg, "timeout_seconds", 12.0)),
        "default_mode": str(getattr(cfg, "default_mode", "hybrid")),
        "max_top_k": int(getattr(cfg, "max_top_k", 20)),
    }


@tool("query_lightrag", parse_docstring=True)
def query_lightrag_tool(
    query: str,
    mode: str | None = None,
    top_k: int = 8,
    filters: dict[str, Any] | None = None,
) -> str:
    """Query LightRAG for graph-oriented evidence and multi-hop relationships.

    Use this tool for objective-driven research when the agent needs relationship
    discovery, cross-entity linkage, and provenance-rich graph context.

    Args:
        query: Natural language graph query.
        mode: Retrieval mode (e.g. local/global/hybrid). Defaults to configured mode.
        top_k: Number of results to return. Capped by config max_top_k.
        filters: Optional provider-specific filter payload.
    """
    cfg = _lightrag_config()
    if not cfg["enabled"]:
        return json.dumps(
            {
                "ok": False,
                "error": "lightrag_disabled",
                "message": "LightRAG integration is disabled. Enable knowledge_vault.lightrag.enabled in config.",
            },
            ensure_ascii=False,
        )

    if not query.strip():
        return json.dumps(
            {"ok": False, "error": "empty_query", "message": "query cannot be empty."},
            ensure_ascii=False,
        )

    capped_top_k = max(1, min(int(top_k), int(cfg["max_top_k"])))
    payload = {
        "query": query,
        "mode": str(mode or cfg["default_mode"]),
        "top_k": capped_top_k,
        "filters": filters or {},
    }

    candidate_paths = ["/query", "/v1/query", "/api/query"]
    headers = {"Content-Type": "application/json"}

    with httpx.Client(timeout=cfg["timeout_seconds"]) as client:
        last_error = None
        for path in candidate_paths:
            url = f"{cfg['base_url']}{path}"
            try:
                response = client.post(url, json=payload, headers=headers)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                body = response.json()
                return json.dumps(
                    {
                        "ok": True,
                        "query": query,
                        "mode": payload["mode"],
                        "top_k": capped_top_k,
                        "endpoint": path,
                        "result": body,
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"

    logger.warning("query_lightrag failed for all candidate endpoints: %s", last_error)
    return json.dumps(
        {
            "ok": False,
            "error": "lightrag_query_failed",
            "message": "Unable to query LightRAG endpoint.",
            "details": last_error,
            "base_url": cfg["base_url"],
        },
        ensure_ascii=False,
    )
```

---

## 2. Tool registry entry

### `backend/src/community/registry.py` (removed entry)

```python
"query_lightrag": {
    "import_path": "src.community.lightrag.tool:query_lightrag_tool",
    "display_name": "LightRAG Query",
    "description": "Graph-oriented evidence retrieval via a local LightRAG server.",
    "source": "builtin",
},
```

---

## 3. Config schema

### `backend/src/config/control_plane_config.py` (removed nested class + field)

Located inside `class KnowledgeVaultConfig(BaseModel):`.

```python
class LightRAGConfig(BaseModel):
    enabled: bool = Field(default=False, description="Whether LightRAG graph query integration is enabled")
    base_url: str = Field(default="http://localhost:9621", description="LightRAG API base URL")
    timeout_seconds: float = Field(default=12.0, ge=1.0, le=120.0, description="HTTP timeout for LightRAG requests")
    default_mode: str = Field(default="hybrid", description="Default query mode for LightRAG")
    max_top_k: int = Field(default=20, ge=1, le=200, description="Maximum top_k per LightRAG query")
    model_config = ConfigDict(extra="allow")
```

Field on `KnowledgeVaultConfig`:

```python
lightrag: LightRAGConfig = Field(default_factory=LightRAGConfig)
```

---

## 4. Control plane service catalog + readiness

### `backend/src/control_plane/service.py` — removed blocks

In `_integration_service_catalog`:

```python
{
    "id": "lightrag",
    "label": "LightRAG",
    "start_command": "start-lightrag",
    "stop_command": "stop-lightrag",
},
```

In `_resolve_integration_services`:

```python
lightrag_cfg = app_config.knowledge_vault.lightrag
lightrag_base_url = lightrag_cfg.base_url or os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621")
services.append(
    {
        "id": "lightrag",
        "label": "LightRAG",
        "base_url": lightrag_base_url,
        "health_path": "/health",
        "headers": {},
        "timeout": max(1.0, float(lightrag_cfg.timeout_seconds)),
        "can_start": True,
    }
)
```

In `_docker_keywords_for_service`:

```python
if service_id == "lightrag":
    return ["lightrag"]
```

---

## 5. Middleware references

### `backend/src/agents/middlewares/phase_tool_filter_middleware.py`

In `_DRAFT_HIDDEN_TOOLS` (line ~45): the string `"query_lightrag"` was a member of the frozenset. Docstring (lines 10-11) listed it among draft-hidden execution tools.

### `backend/src/agents/middlewares/plan_execution_gate_middleware.py`

In `_SCOPE_GATED_TOOLS` (line ~57): the string `"query_lightrag"` was a member.

### `backend/src/agents/middlewares/web_search_circuit_breaker_middleware.py`

In the circuit-open ToolMessage content (line ~107):

```
"...Skip further web_search retries for now. Use successful prior results, "
"query_knowledge_vault/query_lightrag if available, or answer from established knowledge with clear caveats."
```

### `backend/src/agents/middlewares/execution_trace_middleware.py`

```python
_TRACEABLE_TOOL_NAMES = {"web_search", "query_knowledge_vault", "query_lightrag", "task"}
```

### `backend/src/agents/middlewares/planner_middleware.py`

In the planner-output schema docstring (line ~293):

```
- steps[].tools: from {web_search, query_lightrag, query_knowledge_vault,
  read_file, write_file, str_replace, bash, ls, view_image, task,
  present_files}. ...
```

---

## 6. Lead-agent prompt

### `backend/src/agents/lead_agent/prompt.py` — removed `<fetch_policy>` line

In the main system prompt (lines 131-133):

```
3. `query_lightrag` — retrieve graph-oriented, multi-hop relationship evidence when available
```

In `FETCH_POLICY_SECTION` (line 243):

```
- Use `query_knowledge_vault`, `query_lightrag`, and `search_internal_documents` when local indexed context is more relevant than the open web.
```

---

## 7. Knowledge-vault skill

### `skills/knowledge-vault/SKILL.md` — removed section

```markdown
## Graph Evidence Mode

When relational or multi-hop evidence is needed:

1. Call `query_lightrag` with focused graph questions.
2. Merge LightRAG findings with vault context rather than replacing vault notes directly.
3. Use autoresearch pipeline synthesis stages to produce durable updates.

Example:
- "Which entities connect policy A to company B?" → `query_lightrag(query="policy A company B relationship chain", mode="hybrid", top_k=8)`
```

---

## 8. Vault learning — `synthesize_knowledge_graph` accepted `graph_evidence`

### `backend/src/control_plane/vault_learning.py` (line 1966 onward) — `graph_evidence` parameter removed

The method signature included:

```python
def synthesize_knowledge_graph(
    self,
    *,
    objective_id: str,
    topic: str = "",
    graph_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

The body used the payload as:

```python
graph_payload = graph_evidence or {}
...
graph_summary = graph_payload.get("summary")
if isinstance(graph_summary, str) and graph_summary.strip():
    findings.append(graph_summary.strip())
graph_entities = graph_payload.get("entities")
if isinstance(graph_entities, list) and graph_entities:
    findings.append(f"Graph evidence references {len(graph_entities)} entities for this objective.")
...
report = {
    ...
    "graph_evidence": graph_payload,
    ...
}
```

After removal the method no longer accepts `graph_evidence` and the
report omits the `graph_evidence` key.

---

## 9. config.yaml

### `tool_backends.lightrag` (removed block, ~lines 117-120)

```yaml
lightrag:
  enabled: true
  base_url: http://127.0.0.1:9621
  health_path: /health
  timeout_seconds: 30
```

### `knowledge_vault.lightrag` (removed block, ~lines 378-385)

```yaml
lightrag:
  enabled: true
  base_url: http://127.0.0.1:9621
  default_mode: hybrid
  max_top_k: 20
  timeout_seconds: 20
```

---

## 10. Frontend

### `frontend/src/core/control-plane/types.ts` (removed union member)

```ts
export type IntegrationServiceId =
  | "llm"
  | "comfyui"
  | "lightrag"      // <-- removed
  | "websearch";
```

### `frontend/src/app/workspace/integrations/page.tsx` (removed array member)

```ts
const orderedServiceIds: IntegrationServiceId[] = [
  "llm",
  "comfyui",
  "lightrag",       // <-- removed
  "websearch",
];
```

### `frontend/src/app/page.tsx` (removed array member)

```ts
const serviceOrder: Array<IntegrationServiceStatus["id"]> = [
  "llm",
  "comfyui",
  "lightrag",       // <-- removed
  "websearch",
];
```

### `frontend/src/components/workspace/messages/execution-trace-panel.tsx` (removed branch)

```ts
if (toolName === "web_search" || toolName === "query_knowledge_vault" || toolName === "query_lightrag") {
  return "Checking sources.";
}
```

After removal:

```ts
if (toolName === "web_search" || toolName === "query_knowledge_vault") {
  return "Checking sources.";
}
```

---

## 11. Local-stack script

### `scripts/local-stack.sh` (removed sections)

Env vars at the top:

```bash
LIGHTRAG_DIR="${LIGHTRAG_DIR:-$DESKTOP_ROOT/LightRAG}"
LIGHTRAG_PORT="${LOCAL_PORT_LIGHTRAG:-9621}"
LIGHTRAG_BASE_URL="${LIGHTRAG_BASE_URL:-http://localhost:${LIGHTRAG_PORT}}"
INFINITY_RERANK_PORT="${LOCAL_PORT_INFINITY_RERANK:-7997}"
INFINITY_RERANK_BASE_URL="${INFINITY_RERANK_BASE_URL:-http://localhost:${INFINITY_RERANK_PORT}}"
LIGHTRAG_COMPOSE_PROJECT="${LIGHTRAG_COMPOSE_PROJECT:-lightrag}"
LIGHTRAG_COMPOSE_FILE="${LIGHTRAG_COMPOSE_FILE:-$LIGHTRAG_DIR/docker-compose.yml}"
LIGHTRAG_INFINITY_COMPOSE_FILE="${LIGHTRAG_INFINITY_COMPOSE_FILE:-$LIGHTRAG_DIR/docker-compose.infinity-standalone.yaml}"
```

Helper function:

```bash
lightrag_compose() {
    require_file "$LIGHTRAG_COMPOSE_FILE" "LightRAG compose file" || return 1
    require_file "$LIGHTRAG_INFINITY_COMPOSE_FILE" "Infinity compose file" || return 1
    docker compose \
        --project-name "$LIGHTRAG_COMPOSE_PROJECT" \
        --project-directory "$LIGHTRAG_DIR" \
        -f "$LIGHTRAG_COMPOSE_FILE" \
        -f "$LIGHTRAG_INFINITY_COMPOSE_FILE" \
        "$@"
}
```

Compose lifecycle helpers:

```bash
start_lightrag_compose() {
    echo -e "${BLUE}Starting LightRAG compose stack...${NC}"
    lightrag_compose up -d --remove-orphans
}

stop_lightrag_compose() {
    echo -e "${BLUE}Stopping LightRAG compose stack...${NC}"
    lightrag_compose down --remove-orphans
}

start_lightrag_service() {
    print_header
    start_lightrag_compose
    echo -e "${GREEN}LightRAG startup command completed.${NC}"
}

stop_lightrag_service() {
    print_header
    stop_lightrag_compose
    echo -e "${GREEN}LightRAG stop command completed.${NC}"
}
```

`usage()` text:

```
  start-lightrag     Start LightRAG + Infinity compose stack
  stop-lightrag      Stop LightRAG + Infinity compose stack
```

Case arms inside `main()`:

```bash
start-lightrag)
    start_lightrag_service
    ;;
stop-lightrag)
    stop_lightrag_service
    ;;
```

And inside `start_stack` / `stop_stack`:

```bash
start_lightrag_compose
stop_lightrag_compose || true
```

The aggregate banner included:

```bash
echo "LightRAG: ${LIGHTRAG_BASE_URL}"
echo "Infinity Rerank: ${INFINITY_RERANK_BASE_URL}"
```

---

## 12. Tests

### `backend/tests/test_community_tools_api.py`

`query_lightrag` was a member of the expected community-tool registry
set and of the `builtin_expected` set.

### `backend/tests/test_phase_tool_filter_middleware.py`

`query_lightrag` was in the parametrized tool-name tuple asserted to be
inside `_DRAFT_HIDDEN_TOOLS`.

### `backend/tests/test_plan_execution_gate_middleware.py`

`query_lightrag` was in the parametrized tool-name tuple asserted to be
gated when plan status is `"draft"`.

### `backend/tests/test_integration_removal.py`

`_resolve_integration_services` test mocked
`mock_cfg.return_value.knowledge_vault = SimpleNamespace(lightrag=SimpleNamespace(base_url=..., timeout_seconds=...))`.

After removal that mock was replaced with an empty namespace and new
assertions were added that `lightrag` is no longer in the integration
service catalog or in resolved services.

---

## 13. Documentation references

These markdown files still mention LightRAG historically (kept as
historical record; not active code):

- `docs/audit/README.md`
- `docs/prompt-analysis/lead-agent-prompt-analysis-prompt-id-{1,4,6,15,17}.md`
- `backend/docs/deerflow-analysis-and-improvements.md`
- `backend/CLAUDE.md` — line listing community subpackages was edited to drop `lightrag/`.

---

## 14. Default ports the integration assumed

| Port | Service |
|---|---|
| 9621 | LightRAG HTTP API |
| 7997 | Infinity rerank server |
| `$HOME/Desktop/LightRAG/docker-compose.yml` + `docker-compose.infinity-standalone.yaml` | External compose stack expected by `local-stack.sh` |
