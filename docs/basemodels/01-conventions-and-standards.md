# 01 — Conventions & Standards for CapyHome BaseModels

Every existing and proposed `BaseModel` in this catalogue MUST follow the conventions below. Reviewers should reject PRs that introduce a `BaseModel` violating these rules without explicit justification.

---

## 1. `model_config` — the only knob that varies by purpose

Pick one of four canonical configs depending on the model's role:

| Purpose | `ConfigDict` | Rationale |
|---------|-------------|-----------|
| **Persisted snapshot** (disk JSON, sqlite blob, control-plane snapshot) | `extra="allow", frozen=False, populate_by_name=True` | Forward-compatible: a newer process writing unknown fields must not break older readers. |
| **Wire-format event** (SSE payload, channel inbound/outbound, subagent task envelope) | `extra="forbid", frozen=True` | Hash-stable, replay-safe, prevents accidental enlargement of the SSE schema. |
| **FastAPI request body** | `extra="forbid", populate_by_name=True, str_strip_whitespace=True` | Reject typos from clients; trim whitespace defensively. |
| **FastAPI response body** | `extra="forbid", populate_by_name=True` | Drift detection (the `TestGatewayConformance` test relies on this). |
| **Config tree node** (`src/config/`) | `extra="allow"` (current default) | YAML may carry experimental keys before a code change lands. |

```python
# Canonical example for a wire-format event
class ActivityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ...
```

---

## 2. Field declarations

| Rule | Example |
|------|---------|
| Always use `Field(..., description="…")` for **public API** models. The description renders in `/openapi.json`. | `id: str = Field(..., description="UUIDv4")` |
| Use `default_factory` for mutable defaults — **never** bare `[]` or `{}`. | `tags: list[str] = Field(default_factory=list)` |
| Use `datetime` (timezone-aware UTC) for all timestamps; never `str` and never `float` (except where SSE wire format already commits to epoch float — flag those in tables). | `created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))` |
| Use `Literal["a", "b"]` for closed sets; promote to `enum.StrEnum` if the set is shared across ≥ 3 files. | `status: Literal["pending", "running", "completed"]` |
| Use union-with-`None` (`str | None`) not `Optional[str]` (PEP 604 only). | `error: str | None = None` |
| Numeric bounds via `Field(..., ge=0, le=1)` for confidences/probabilities. | `confidence: float = Field(..., ge=0.0, le=1.0)` |

---

## 3. Base class hierarchy (proposed)

To remove repetition of `model_config` and timestamping, introduce three shared base classes under `src/models/base.py` (NEW FILE — see §4 below):

```text
CapyBaseModel                           (root — sets extra="forbid", frozen=False, populate_by_name=True)
 ├── CapyEvent                          (extra="forbid", frozen=True; for SSE/channel events)
 ├── CapyEntity                         (adds id: str, created_at, updated_at; for persisted records)
 │    ├── PipelineRun, ApprovalRequest, GenerationJob, AutoresearchObjective, …
 ├── CapyRequest                        (str_strip_whitespace=True; FastAPI inbound)
 ├── CapyResponse                       (forbid extra, populate_by_name; FastAPI outbound)
 └── CapyConfigNode                     (extra="allow"; for src/config/ tree)
```

This is **proposed**, not required — the migration can preserve `BaseModel` directly inheritance if the team prefers minimal diff.

---

## 4. Proposed shared module — `src/models/base.py`

| Class | Purpose | model_config |
|-------|---------|--------------|
| `CapyBaseModel` | Project-wide root, sets sane defaults. | `extra="forbid", populate_by_name=True` |
| `CapyEvent` | SSE / wire-format events; **immutable**. | `extra="forbid", frozen=True` |
| `CapyEntity` | Adds `id: str`, `created_at: datetime`, `updated_at: datetime`. | inherits |
| `CapyRequest` | Inbound FastAPI body; strips whitespace. | `extra="forbid", str_strip_whitespace=True` |
| `CapyResponse` | Outbound FastAPI body. | `extra="forbid", populate_by_name=True` |
| `CapyConfigNode` | YAML config nodes; lenient. | `extra="allow"` |
| `TimestampMixin` | `created_at`, `updated_at` only. | n/a |
| `IdentifiedMixin` | `id: str = Field(default_factory=...)` | n/a |

---

## 5. Naming conventions

| Pattern | Use for |
|---------|---------|
| `XxxConfig` | Anything under `src/config/` or shaped like config. |
| `XxxRequest` / `XxxResponse` | FastAPI bodies. |
| `XxxEvent` | SSE / channel / runtime events. |
| `XxxState` | Persisted thread-state shapes (LangGraph `ThreadState` field types). |
| `XxxRecord` | Internal store rows (channel `MessageRecord`, queue `MemoryQueueRecord`, …). |
| `XxxInput` / `XxxOutput` | Tool argument / return shapes. |
| `XxxSpec` | Static declarative descriptors (`MiddlewareSpec`, `SubagentSpec`). |
| `XxxReport` | Outcome envelopes from internal sub-systems (`AgentExecutionReport`, `QualityCheckReport`). |

> ❗ Avoid generic names like `Data`, `Info`, `Item` without a prefix. They collide across modules. The current `ViewedImageData`, `BackgroundFollowupJob`, `TodoNodeInput` and `ResolvedAttachment` all already follow this rule — keep it.

---

## 6. Validation discipline

| Rule | Rationale |
|------|-----------|
| Every wire-format model MUST `extra="forbid"`. | Catches frontend/backend schema drift in CI via `TestGatewayConformance`. |
| Every event with `seq` MUST validate `seq >= 1` via `Field(..., ge=1)`. | Sequence-0 is a sentinel in `runtime_events.append_runtime_event`. |
| Every `path` field MUST validate non-empty and **not contain** `..` (path traversal). Use a shared `validator` in `src/models/base.py`. | Sandbox virtual paths flow into shell commands. |
| Every model that round-trips through `json.dumps` MUST set `model_config["ser_json_timedelta"]` if it carries `timedelta`, else avoid the type. | Default Pydantic JSON output for `timedelta` is ISO 8601 duration — frontend doesn't parse it. |

---

## 7. Deprecations to avoid in new code

| Legacy pattern | Replace with |
|---------------|--------------|
| `datetime.utcnow()` (already used in [agents/memory/queue.py:21](../../backend/src/agents/memory/queue.py#L21)) | `datetime.now(UTC)` (used in `control_plane/models.py:11`) |
| Raw `dict[str, Any]` payloads on the wire | Concrete `BaseModel` (see §6, item 3 of README) |
| `frozen` `@dataclass` for hashable values | `BaseModel` with `model_config = ConfigDict(frozen=True)` — same hashability via `model_dump()` tuple key, but with JSON ser/de |
| `total=False` `TypedDict` for persisted snapshots | `BaseModel` with explicit `default=None` or `default_factory` |
| Class attributes for "fake defaults" (`status: str = "pending"`) without a `Literal` constraint | `Literal["pending", …]` + `Field(default="pending")` |

---

## 8. Reference: existing exemplars

When in doubt about style, copy the patterns from these well-shaped files (all currently in the repo):

| File | Why it's exemplary |
|------|-------------------|
| [src/control_plane/models.py](../../backend/src/control_plane/models.py) | Consistent `extra="allow"`, `default_factory` for timestamps, `Literal[...]` for status enums, `new_id(prefix)` helper. |
| [src/generation/models.py](../../backend/src/generation/models.py) | Minimal, focused, uses `Literal` type aliases (`GenerationJobKind`, `GenerationJobStatus`). |
| [src/config/extensions_config.py](../../backend/src/config/extensions_config.py) | Nested config with both inbound parsing and outbound persistence. |
| [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | Largest router cluster — illustrates request/response naming, field grouping by feature. |
