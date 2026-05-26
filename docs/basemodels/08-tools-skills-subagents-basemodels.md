# 08 — Tools, Skills, Subagents, MCP, Sandbox & Memory BaseModels

Scope: the long tail of subsystems that today rely on `@dataclass`, `TypedDict`, or untyped `dict` payloads but should be promoted to `BaseModel` because their values cross a process / disk / wire boundary.

* `src/tools/builtins/` — tool input/output envelopes.
* `src/skills/` — skill metadata.
* `src/subagents/` — subagent configuration + executor records.
* `src/mcp/` — MCP token cache + preview results.
* `src/sandbox/` — sandbox metadata.
* `src/agents/memory/` — memory store + facts.
* `src/community/` — community tool registry.

---

## 8.1 Tools — built-in tool I/O

### 8.1.1 PROPOSED migrations

| Target `BaseModel` | Replaces (TypedDict) | File | Line | Fields |
|--------------------|----------------------|------|-----:|--------|
| `ClarificationOption` | TypedDict `ClarificationOption` | [src/tools/builtins/clarification_tool.py](../../backend/src/tools/builtins/clarification_tool.py) | 6 | `label: str`, `recommended: bool = False`, `description: str \| None = None`. **Collapse with the planner copy in §07.** |
| `TodoNodeInput` | TypedDict `TodoNodeInput` | [src/tools/builtins/write_todos_tool.py](../../backend/src/tools/builtins/write_todos_tool.py) | 18 | See §06.4 — collapse to single source. |
| `_TodoToolState` | TypedDict `_TodoToolState` | [src/tools/builtins/write_todos_tool.py](../../backend/src/tools/builtins/write_todos_tool.py) | 29 | Use the actual `ThreadState` slice types (`PlanState`, `TodoGraphState`) directly — eliminate this duplicate definition. |

### 8.1.2 PROPOSED — NEW tool I/O models

| New `BaseModel` | Target file | Tool | Fields |
|-----------------|-------------|------|--------|
| `ClarificationToolInput` | [src/tools/builtins/clarification_tool.py](../../backend/src/tools/builtins/clarification_tool.py) | `ask_clarification` | `question: str` (min_length=1), `options: list[ClarificationOption] = []` |
| `PresentFilesToolInput` | [src/tools/builtins/present_file_tool.py](../../backend/src/tools/builtins/present_file_tool.py) | `present_files` | `paths: list[str]` (min_items=1), `note: str = ""` — paths validated to be under `/mnt/user-data/workspace`. |
| `PresentFilesToolOutput` | same | same | `accepted: list[str]`, `rejected: list[PresentFileRejection]` |
| `PresentFileRejection` | same | — | `path: str`, `reason: Literal["outside_workspace","not_found","not_file"]` |
| `ViewImageToolInput` | [src/tools/builtins/view_image_tool.py](../../backend/src/tools/builtins/view_image_tool.py) | `view_image` | `path: str` — must end with image MIME suffix. |
| `ViewImageToolOutput` | same | same | `base64: str`, `mime_type: Literal["image/png","image/jpeg","image/gif","image/webp"]`, `width: int (ge=1) \| None`, `height: int (ge=1) \| None` |
| `RecallToolInput` | [src/tools/builtins/recall_tool.py](../../backend/src/tools/builtins/recall_tool.py) | `recall` | `query: str` (min_length=1), `top_k: int (ge=1, le=20) = 5` |
| `RecallToolOutput` | same | same | `facts: list[MemoryFact]`, `behavior_rules: list[BehaviorRule]` |
| `SetupAgentToolInput` | [src/tools/builtins/setup_agent_tool.py](../../backend/src/tools/builtins/setup_agent_tool.py) | `setup_agent` | `tools: list[str] = []`, `skills: list[str] = []`, `mcp_servers: list[str] = []` |
| `TaskToolInput` | [src/tools/builtins/task_tool.py](../../backend/src/tools/builtins/task_tool.py) | `task` | `description: str` (min_length=1), `prompt: str` (min_length=1), `subagent_type: str`, `max_turns: int (ge=1, le=200) = 25`, `target_endpoint: Literal["primary","helper"] = "primary"`, `tool_budget: int \| None = None` |
| `TaskToolOutput` | same | same | `task_id: str`, `status: Literal["dispatched","deferred"]`, `reason: str \| None = None` |
| `WriteTodosToolInput` | [src/tools/builtins/write_todos_tool.py](../../backend/src/tools/builtins/write_todos_tool.py) | `write_todos` | `todos: list[TodoNodeInput]` (min_items=1) |
| `WriteTodosToolOutput` | same | same | `accepted: bool`, `reason: Literal["draft_completion_blocked","completed_plan_frozen","validation_failed","ok"]`, `errors: list[str] = []` |

### 8.1.3 Sandbox tool I/O (`src/sandbox/tools.py`)

| New `BaseModel` | Tool | Fields |
|-----------------|------|--------|
| `BashToolInput` | `bash` | `command: str` (min_length=1), `description: str \| None = None`, `run_in_background: bool = False`, `timeout: int (ge=1, le=600000) \| None = None` |
| `BashToolOutput` | `bash` | `exit_code: int`, `stdout: str`, `stderr: str`, `duration_ms: int (ge=0)`, `truncated: bool = False` |
| `LsToolInput` | `ls` | `path: str` (default=`/mnt/user-data/workspace`), `max_depth: int (ge=1, le=4) = 2` |
| `LsToolOutput` | `ls` | `entries: list[LsEntry]`, `truncated: bool = False` |
| `LsEntry` | `ls` | `name: str`, `kind: Literal["file","dir","symlink"]`, `size: int (ge=0) \| None`, `modified_at: datetime \| None` |
| `ReadFileToolInput` | `read_file` | `path: str`, `offset: int (ge=0) \| None`, `limit: int (ge=1) \| None`, `pages: str \| None = None` |
| `ReadFileToolOutput` | `read_file` | `content: str`, `truncated: bool`, `total_lines: int (ge=0)` |
| `WriteFileToolInput` | `write_file` | `path: str`, `content: str`, `mode: Literal["overwrite","append"] = "overwrite"` |
| `WriteFileToolOutput` | `write_file` | `bytes_written: int (ge=0)`, `created: bool` |
| `StrReplaceToolInput` | `str_replace` | `path: str`, `old_string: str` (min_length=1), `new_string: str`, `replace_all: bool = False` |
| `StrReplaceToolOutput` | `str_replace` | `replacements: int (ge=0)`, `success: bool` |

---

## 8.2 Skills — `src/skills/`

### 8.2.1 PROPOSED migrations

| Target `BaseModel` | Replaces (`@dataclass`) | File | Line | Fields |
|--------------------|-------------------------|------|-----:|--------|
| `Skill` | `Skill` | [src/skills/types.py](../../backend/src/skills/types.py) | 5 | `name: str`, `description: str`, `license: str \| None`, `skill_dir: Path` (`arbitrary_types_allowed=True`), `skill_file: Path`, `relative_path: Path`, `category: Literal["public","custom"]`, `enabled: bool = False`, `paths: list[str] \| None = None`, `workflow: bool = False` |
| | | | | `model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)` — preserves the helper methods (`skill_path`, `get_container_path`, `get_container_file_path`). |

### 8.2.2 PROPOSED — NEW skill metadata model

The SKILL.md frontmatter is currently parsed by [src/skills/parser.py](../../backend/src/skills/parser.py) into a raw dict before being passed to `Skill(...)`. Add an intermediate validation layer:

| New `BaseModel` | Target file | Fields |
|-----------------|-------------|--------|
| `SkillFrontmatter` | `src/skills/types.py` | `name: str` (regex `^[a-z0-9-]+$`), `description: str` (min_length=1, max_length=1000), `license: str \| None = None`, `allowed_tools: list[str] = []`, `paths: list[str] = []`, `workflow: bool = False`, `version: str \| None = None` |

`parser.py:load_skills()` then does `SkillFrontmatter.model_validate(yaml.safe_load(...))` and rejects malformed frontmatter at load time instead of crashing on access.

---

## 8.3 Subagents — `src/subagents/`

### 8.3.1 PROPOSED migrations

| Target `BaseModel` | Replaces (`@dataclass`) | File | Line | Fields |
|--------------------|-------------------------|------|-----:|--------|
| `SubagentConfig` | `SubagentConfig` | [src/subagents/config.py](../../backend/src/subagents/config.py) | 6 | `name: str` (regex `^[a-z0-9-]+$`), `description: str` (min_length=1), `system_prompt: str` (min_length=1), `tools: list[str] \| None = None`, `disallowed_tools: list[str] = ["task"]`, `model: str = "inherit"`, `max_turns: int (ge=1, le=200) = 50`, `timeout_seconds: int (ge=10, le=7200) = 3600` |
| `SubagentExecutorRecord` | unnamed `@dataclass` | [src/subagents/executor.py](../../backend/src/subagents/executor.py) | 39 | `task_id: str`, `subagent_type: str`, `description: str`, `prompt: str`, `status: Literal["queued","running","completed","failed","timed_out","cancelled"]`, `started_at: datetime`, `completed_at: datetime \| None`, `result: str \| None`, `error: str \| None`, `tool_budget: int \| None`, `target_endpoint: Literal["primary","helper"]`, `parent_thread_id: str`, `parent_assistant_message_id: str \| None`, `group_id: str \| None`, `group_title: str \| None` |

### 8.3.2 PROPOSED — NEW subagent envelopes

| New `BaseModel` | Target file | Fields |
|-----------------|-------------|--------|
| `SubagentTaskEnvelope` | [src/subagents/executor.py](../../backend/src/subagents/executor.py) | `task_id: str`, `subagent: SubagentConfig`, `prompt: str`, `parent_thread_id: str`, `parent_state_snapshot: dict[str, Any] = {}` (or typed sub-snapshot), `max_turns: int (ge=1)`, `dispatched_at: datetime` |
| `SubagentTaskResult` | [src/subagents/executor.py](../../backend/src/subagents/executor.py) | `task_id: str`, `status: Literal["completed","failed","timed_out","cancelled"]`, `result: str = ""`, `error: str \| None = None`, `turns_used: int (ge=0)`, `tools_called: list[str] = []`, `duration_ms: int (ge=0)`, `completed_at: datetime` |
| `SubagentRegistration` | [src/subagents/registry.py](../../backend/src/subagents/registry.py) | `name: str`, `source: Literal["builtin","config","user_custom"]`, `config: SubagentConfig` |

---

## 8.4 MCP — `src/mcp/`

### 8.4.1 PROPOSED migrations

| Target `BaseModel` | Replaces (`@dataclass`) | File | Line | Fields |
|--------------------|-------------------------|------|-----:|--------|
| `OAuthTokenRecord` | `_OAuthToken` | [src/mcp/oauth.py](../../backend/src/mcp/oauth.py) | 16 | `server_name: str`, `access_token: str` (`SecretStr`), `token_type: str = "Bearer"`, `expires_at: datetime` |

### 8.4.2 PROPOSED — NEW MCP models

| New `BaseModel` | Target file | Fields |
|-----------------|-------------|--------|
| `McpToolDescriptor` | [src/mcp/cache.py](../../backend/src/mcp/cache.py) | `server_name: str`, `tool_name: str`, `display_name: str`, `description: str`, `input_schema: dict[str, Any]`, `loaded_at: datetime`, `transport: Literal["stdio","sse","http"]` |
| `McpServerHealth` | [src/mcp/client.py](../../backend/src/mcp/client.py) | `server_name: str`, `status: Literal["healthy","degraded","unreachable","auth_required"]`, `last_checked_at: datetime`, `error: str \| None = None`, `tools_available: int (ge=0)` |
| `McpInternalSearchResult` | [src/mcp/internal_search.py](../../backend/src/mcp/internal_search.py) | `server_name: str`, `tool_name: str`, `score: float (ge=0, le=1)`, `excerpt: str` — currently a raw dict. |

---

## 8.5 Sandbox — `src/sandbox/`

### 8.5.1 PROPOSED migrations

| Target `BaseModel` | Replaces (`@dataclass`) | File | Line | Fields |
|--------------------|-------------------------|------|-----:|--------|
| `SandboxInfo` | `SandboxInfo` | [src/community/aio_sandbox/sandbox_info.py](../../backend/src/community/aio_sandbox/sandbox_info.py) | 9 | `sandbox_id: str`, `sandbox_url: str` (URL validator), `container_name: str \| None = None`, `container_id: str \| None = None`, `created_at: datetime` — drop the `to_dict` / `from_dict` helpers (replaced by `model_dump` / `model_validate`). |

### 8.5.2 PROPOSED — NEW sandbox models

| New `BaseModel` | Target file | Fields |
|-----------------|-------------|--------|
| `VirtualPathMapping` | [src/sandbox/path_mapping.py](../../backend/src/sandbox/path_mapping.py) | `virtual: str` (must start with `/mnt/`), `physical: str` (absolute path), `kind: Literal["workspace","uploads","outputs","skills","mounted"]`, `read_only: bool = False` |
| `SandboxProvisionRequest` | [src/sandbox/sandbox_provider.py](../../backend/src/sandbox/sandbox_provider.py) | `thread_id: str`, `volume_mounts: list[VirtualPathMapping] = []`, `env: dict[str, str] = {}`, `kind: Literal["local","aio","provisioner"]` |
| `SandboxProvisionResponse` | same | `sandbox_id: str`, `sandbox_url: str \| None`, `mode: Literal["local","aio","provisioner"]`, `created_at: datetime` |
| `LocalSandboxStatus` | [src/sandbox/local/local_sandbox.py](../../backend/src/sandbox/local/local_sandbox.py) | `sandbox_id: Literal["local"] = "local"`, `workspace_path: str`, `pid: int \| None`, `active: bool` |

---

## 8.6 Memory — `src/agents/memory/`

The memory store (`backend/.capyhome/memory.json`) is currently a free-form dict. Promote the schema to `BaseModel` (in addition to the gateway response models which already exist):

| New `BaseModel` | Target file | Fields |
|-----------------|-------------|--------|
| `MemoryStore` | [src/agents/memory/store.py](../../backend/src/agents/memory/store.py) | `userContext: UserContext`, `historyContext: HistoryContext`, `facts: list[MemoryFact]`, `behaviorRules: list[BehaviorRule]`, `compactionArchive: list[CompactionArchiveEntry] = []`, `version: int = 1` |
| `MemoryFact` | same | (mirror gateway `Fact` — single source) `id: str`, `content: str`, `category: Literal["preference","knowledge","context","behavior","goal"]`, `confidence: float (ge=0, le=1)`, `createdAt: datetime`, `source: str` |
| `BehaviorRule` | same | (mirror gateway model) `id: str`, `name: str`, `body: str`, `enabled: bool`, `createdAt: datetime`, `updatedAt: datetime` |
| `CompactionArchiveEntry` | [src/agents/memory/compaction_archive.py](../../backend/src/agents/memory/compaction_archive.py) | `thread_id: str`, `summary: str`, `messages_compressed: int`, `messages_kept: int`, `compacted_at: datetime`, `pre_token_count: int (ge=0)`, `post_token_count: int (ge=0)` |
| `MemoryVectorEntry` | [src/agents/memory/vector_store.py](../../backend/src/agents/memory/vector_store.py) | `fact_id: str`, `vector: list[float]`, `model: str`, `dimension: int (ge=1)`, `created_at: datetime` |
| `MemoryUpdaterResult` | [src/agents/memory/updater.py](../../backend/src/agents/memory/updater.py) | `added: list[MemoryFact] = []`, `removed: list[str] = []`, `replaced: list[tuple[str, MemoryFact]] = []`, `context_diff: dict[str, str] = {}`, `latency_ms: int (ge=0)`, `model: str` |
| `MemoryVersion` | [src/agents/memory/store.py](../../backend/src/agents/memory/store.py) | `version_id: str`, `sha: str` (regex sha256), `previous_version_id: str \| None`, `created_at: datetime`, `actor: Literal["user","system","memory_updater","redaction"]`, `change_summary: str`, `storage_path: str` |

> **Single source of truth rule**: the gateway memory router (§04.4) currently re-declares `Fact`, `BehaviorRule`, `UserContext`, `HistoryContext`. Once these are promoted to `src/agents/memory/store.py`, the gateway must import them — duplicate definitions are flagged as audit finding GW-1 / MEM-1.

---

## 8.7 Community tools — `src/community/registry.py`

| Target `BaseModel` | Replaces (TypedDict) | File | Line | Fields |
|--------------------|----------------------|------|-----:|--------|
| `CommunityToolEntry` | TypedDict `CommunityToolEntry` | [src/community/registry.py](../../backend/src/community/registry.py) | 15 | `import_path: str` (regex `^src\.[a-z_.]+:[a-z_]+$`), `display_name: str`, `description: str` (min_length=1), `source: Literal["builtin","config"]` |

The registry itself stays `dict[str, CommunityToolEntry]`; only the value type changes.

---

## 8.8 Knowledge Vault search internals

| New `BaseModel` | Target file | Fields |
|-----------------|-------------|--------|
| `VaultSearchHit` | [src/community/knowledge_vault_search/search.py](../../backend/src/community/knowledge_vault_search/search.py) | `path: str`, `title: str`, `score: float (ge=0)`, `excerpt: str`, `bm25_terms: list[str] = []` |
| `VaultSaveRequest` (internal) | [src/community/knowledge_vault_search/save_tool.py](../../backend/src/community/knowledge_vault_search/save_tool.py) | (mirror gateway model — share single definition) |
| `VaultVectorIndexEntry` | [src/community/knowledge_vault_search/vector_index.py](../../backend/src/community/knowledge_vault_search/vector_index.py) | `path: str`, `vector: list[float]`, `model: str`, `dimension: int (ge=1)`, `updated_at: datetime` |

---

## 8.9 Audit findings — actionable

| # | Finding | Suggested fix |
|---|---------|---------------|
| TL-1 | `present_files` tool has no schema for path rejection reasons. | Add `PresentFileRejection` model (above). |
| TL-2 | `task_tool` accepts a free-form `prompt` of any length; can overflow LLM context. | `prompt: str = Field(..., min_length=1, max_length=200_000)`. |
| SK-1 | `Skill` is `@dataclass`, hash/equality come for free, but the `Path` fields prevent JSON round-trip. | Migrate with `model_config = ConfigDict(arbitrary_types_allowed=True)` and add `field_serializer` that emits `str(path)`. |
| SK-2 | Skill discovery silently ignores malformed YAML frontmatter. | `SkillFrontmatter` validation + log warning. |
| SA-1 | `SubagentConfig.disallowed_tools` default `["task"]` is shared mutable. | Use `default_factory=lambda: ["task"]`. (Already correct in dataclass — confirm in BaseModel.) |
| SA-2 | `SubagentExecutorRecord` (unnamed `@dataclass`) lacks `target_endpoint` validation. | `Literal["primary","helper"]`. |
| MCP-1 | `_OAuthToken.access_token` stored in plain memory — should be `SecretStr` to avoid accidental logging via `repr`. | Use `pydantic.SecretStr`. |
| SB-1 | `SandboxInfo.from_dict` accepts legacy `base_url` alias. | Use Pydantic `validation_alias=AliasChoices("sandbox_url","base_url")` to preserve the alias. |
| MEM-1 | `Fact`, `BehaviorRule` exist both in `src/gateway/routers/memory.py` (gateway response models) and would be re-declared in `src/agents/memory/store.py`. | Define **once** in `src/agents/memory/store.py`; gateway imports them. |
| MEM-2 | `ConversationContext` (queue.py) uses deprecated `datetime.utcnow()`. | Switch to `datetime.now(UTC)`. |
| CM-1 | `CommunityToolEntry.import_path` is a free-form `str` — typos surface as `ImportError` at first tool call. | Regex-validate at registry definition time. |
| VAULT-1 | `VaultSearchHit.score` (BM25) has no upper bound; not always in [0,1]. | Constraint `ge=0` only — drop upper. |
