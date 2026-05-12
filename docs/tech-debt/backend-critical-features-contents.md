# Backend Critical Features — Contents

Date: 2026-05-12  
Scope: `backend/src` (feature-level review)

## 1) Runtime & Orchestration Core
- Lead agent construction and execution flow (`agents/lead_agent/agent.py`)
- Thread state model and persistence boundaries (`agents/thread_state.py`)
- Middleware chain ordering and policy enforcement (`agents/middlewares/*`)
- Embedded client runtime (`client.py`)

## 2) Sandbox & File Operations
- Sandbox abstraction/provider lifecycle (`sandbox/sandbox.py`, `sandbox/sandbox_provider.py`)
- Local sandbox command/file execution (`sandbox/local/local_sandbox.py`)
- Virtual path translation and thread path mapping (`sandbox/path_mapping.py`, `sandbox/tools.py`)
- Built-in filesystem/editing tools exposed to agent (`sandbox/tools.py`)

## 3) Gateway API Surface
- FastAPI app lifecycle and component startup (`gateway/app.py`)
- Artifacts serving and mounted path resolution (`gateway/routers/artifacts.py`)
- Upload lifecycle and conversion pipeline (`gateway/routers/uploads.py`)
- Skill management/install/update (`gateway/routers/skills.py`)
- Run controls/resume (`gateway/routers/runs.py`)

## 4) Dreamy Workflow & Mounted Folder Path
- Workflow storage and editing (`gateway/routers/dreamy.py`)
- Mounted folder selection/listing and persistence (`gateway/routers/dreamy.py`)
- Artifact integration for mounted files (`gateway/routers/artifacts.py`)

## 5) Subagent Delegation System
- Subagent executor lifecycle and threading model (`subagents/executor.py`)
- Task state/result tracking and cleanup (`subagents/executor.py`)
- Timeout behavior and cancellation semantics (`subagents/executor.py`)

## 6) MCP/Extensions/Tool Loading
- Extensions configuration load and env resolution (`config/extensions_config.py`)
- MCP tool caching and refresh behavior (`mcp/cache.py`)
- Unified tool assembly with built-ins/community/MCP (`tools/tools.py`)

## 7) Memory Pipeline
- Debounced memory queue and immediate update path (`agents/memory/queue.py`)
- Async memory updater integration and failure handling (`agents/memory/updater.py`)
- Memory middleware coupling (`agents/middlewares/memory_middleware.py`)

## 8) Integrations & Channels
- Channel manager/service lifecycle (`channels/manager.py`, `channels/service.py`)
- Trigger/pipeline/control-plane touchpoints (`control_plane/*`, `gateway/routers/pipelines.py`)

## 9) Cross-Cutting Security & Reliability Controls
- Permission policy middleware (`agents/middlewares/permission_middleware.py`)
- Search privacy guards (`agents/middlewares/search_privacy_middleware.py`, `security/*`)
- Observability patterns and error handling consistency (logging/exception pathways across modules)
