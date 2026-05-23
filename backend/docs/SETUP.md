# Setup Guide

Quick setup instructions for CapyHome.

## Configuration Setup

CapyHome uses a YAML configuration file that should be placed in the **project root directory**.

### Steps

1. **Navigate to project root**:
   ```bash
   cd /path/to/CapyHome
   ```

2. **Copy example configuration**:
   ```bash
   cp config.example.yaml config.yaml
   ```

3. **Edit configuration**:
   ```bash
   # Option A: Set environment variables (recommended)
   export OPENAI_API_KEY="your-key-here"

   # Option B: Edit config.yaml directly
   vim config.yaml  # or your preferred editor
   ```

4. **Verify configuration**:
   ```bash
   cd backend
   python -c "from src.config import get_app_config; print('✓ Config loaded:', get_app_config().models[0].name)"
   ```

## Important Notes

- **Location**: `config.yaml` should be in `CapyHome/` (project root), not `CapyHome/backend/`
- **Git**: `config.yaml` is automatically ignored by git (contains secrets)
- **Priority**: If both `backend/config.yaml` and `../config.yaml` exist, backend version takes precedence

## Configuration File Locations

The backend searches for `config.yaml` in this order:

1. `CAPYBARA_HOME_CONFIG_PATH` environment variable (if set)
2. `backend/config.yaml` (current directory when running from backend/)
3. `CapyHome/config.yaml` (parent directory - **recommended location**)

**Recommended**: Place `config.yaml` in project root (`CapyHome/config.yaml`).

## Sandbox Setup (Optional but Recommended)

If you plan to use Docker/Container-based sandbox (configured in `config.yaml` under `sandbox.use: src.community.aio_sandbox:AioSandboxProvider`), it's highly recommended to pre-pull the container image:

```bash
# From project root
make setup-sandbox
```

**Why pre-pull?**
- The sandbox image (~500MB+) is pulled on first use, causing a long wait
- Pre-pulling provides clear progress indication
- Avoids confusion when first using the agent

If you skip this step, the image will be automatically pulled on first agent execution, which may take several minutes depending on your network speed.

## Troubleshooting

### Config file not found

```bash
# Check where the backend is looking
cd CapyHome/backend
python -c "from src.config.app_config import AppConfig; print(AppConfig.resolve_config_path())"
```

If it can't find the config:
1. Ensure you've copied `config.example.yaml` to `config.yaml`
2. Verify you're in the correct directory
3. Check the file exists: `ls -la ../config.yaml`

### Permission denied

```bash
chmod 600 ../config.yaml  # Protect sensitive configuration
```

## Knowledge Vault Query Tool

The knowledge vault can be queried directly from chat as a tool (`query_knowledge_vault`). This enables the agent to search compiled research notes, entities, concepts, and syntheses stored in `knowledge_vault/02_compiled/` using BM25 keyword ranking — without hitting the web.

### How it works

The tool is registered under the `vault` tool group and is always available to the lead agent when that group is included. It reads markdown pages from disk on every call, so results always reflect the latest vault state.

**Tool name**: `query_knowledge_vault`

**Parameters**:
| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Natural-language search query |
| `categories` | list\[string\] | all | Vault sections to search: `sources`, `entities`, `concepts`, `syntheses`, `queries` |
| `limit` | integer | 5 | Max results to return (1–20) |

**Example agent invocations**:
```
query_knowledge_vault(query="LangGraph agent memory")
query_knowledge_vault(query="climate policy", categories=["syntheses", "concepts"])
query_knowledge_vault(query="OpenAI GPT-4", limit=10)
```

### Setup

The tool is registered in `config.yaml` under the `vault` group and requires no external services:

```yaml
tool_groups:
  - name: vault

tools:
  - name: query_knowledge_vault
    group: vault
    use: src.community.knowledge_vault_search.tool:query_knowledge_vault_tool
```

Both `config.yaml` and `config.example.yaml` include this entry by default. No additional configuration is needed.

### Vault directory layout searched

```
knowledge_vault/
└── 02_compiled/
    ├── sources/      # Ingested articles
    ├── entities/     # Named entity pages
    ├── concepts/     # Concept pages
    ├── syntheses/    # Multi-source summaries
    └── queries/      # Query result pages
```

Pages must be markdown files with optional YAML frontmatter (`title`, `tags`, `source_url`). The tool parses frontmatter automatically — no special setup required for existing vault pages.

### When the agent uses it

When the `knowledge-vault` skill is enabled, the agent can call `query_knowledge_vault` to check whether the vault has relevant material on a topic. The skill's Query Mode section describes this behaviour in detail.

### Implementation

| File | Purpose |
|---|---|
| `backend/src/community/knowledge_vault_search/search.py` | `VaultSearcher` class — BM25 scoring, frontmatter parsing, excerpt extraction |
| `backend/src/community/knowledge_vault_search/tool.py` | `@tool("query_knowledge_vault")` LangChain wrapper |
| `backend/src/community/knowledge_vault_search/__init__.py` | Package export |
| `backend/tests/test_vault_search.py` | Unit tests (30 tests) |

## See Also

- [Configuration Guide](docs/CONFIGURATION.md) - Detailed configuration options
- [Architecture Overview](CLAUDE.md) - System architecture
