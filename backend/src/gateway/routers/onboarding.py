import ipaddress
import json
import logging
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.config.extensions_config import (
    ExtensionsConfig,
    KnowledgeVaultUserConfig,
    UserLlmEndpointConfig,
    get_extensions_config,
    reload_extensions_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _validate_probe_url(url: str) -> str | None:
    """Validate an outbound probe URL.

    Returns an error string if the URL is rejected, else None.
    Rejects non-http(s) schemes and resolves the host to ensure it is not a
    cloud-metadata endpoint. Localhost/loopback is allowed because most user
    LLM/ComfyUI endpoints are bound to 127.0.0.1.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"Unsupported URL scheme '{parsed.scheme}'. Use http:// or https://."
    if not parsed.hostname:
        return "URL is missing a host."

    host = parsed.hostname
    # Block well-known cloud metadata endpoints (AWS/GCP/Azure IMDS).
    if host in {"169.254.169.254", "metadata.google.internal", "metadata"}:
        return "Refusing to probe cloud metadata endpoint."

    try:
        # Resolve once; if any address is the metadata IP, reject.
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Let httpx raise the connection error normally — we just guard against
        # known dangerous targets here.
        return None

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip_str == "169.254.169.254":
            return "Refusing to probe cloud metadata IP."
        if ip.is_link_local and not ip.is_loopback:
            return "Refusing to probe link-local addresses."
    return None


# ─── Request / Response models ───────────────────────────────────────────────

class TestLlmRequest(BaseModel):
    base_url: str = Field(..., description="OpenAI-compatible base URL (e.g. http://localhost:11434/v1)")
    api_key: str = Field(default="", description="Optional API key")


class TestLlmResponse(BaseModel):
    ok: bool
    models: list[str] = Field(default_factory=list, description="Discovered model IDs")
    error: str | None = None


class TestComfyuiRequest(BaseModel):
    base_url: str = Field(..., description="ComfyUI base URL (e.g. http://127.0.0.1:8188)")


class TestComfyuiResponse(BaseModel):
    ok: bool
    error: str | None = None


class TestGenericRequest(BaseModel):
    url: str = Field(..., description="URL to health-check via GET")
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)


class TestGenericResponse(BaseModel):
    ok: bool
    status_code: int | None = None
    error: str | None = None


class LlmEndpointsMap(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    user_models: dict[str, UserLlmEndpointConfig] = Field(
        ...,
        description="Map of endpoint name to configuration",
        alias="userModels",
    )


class LlmEndpointsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    user_models: dict[str, UserLlmEndpointConfig] = Field(
        default_factory=dict,
        alias="userModels",
    )


class EmbeddingEndpointsMap(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    user_embedding_models: dict[str, UserLlmEndpointConfig] = Field(
        ...,
        description="Map of embedding endpoint name to configuration",
        alias="userEmbeddingModels",
    )


class EmbeddingEndpointsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    user_embedding_models: dict[str, UserLlmEndpointConfig] = Field(
        default_factory=dict,
        alias="userEmbeddingModels",
    )


class KnowledgeVaultConfigRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str = Field(default="", description="Absolute folder path for the Obsidian-compatible vault")
    llm_model: str = Field(default="", description="Model used for vault analysis/generation", alias="llmModel")
    embedding_model: str = Field(default="", description="Embedding model used for vault indexing", alias="embeddingModel")


class KnowledgeVaultConfigResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str = Field(default="")
    llm_model: str = Field(default="", alias="llmModel")
    embedding_model: str = Field(default="", alias="embeddingModel")


class CanonicalThresholdsModel(BaseModel):
    """Wire-format thresholds for the canonical alias merge engine."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    auto_lexical_strong: float = Field(default=0.95, ge=0.0, le=1.0, alias="autoLexicalStrong")
    auto_lexical_high: float = Field(default=0.9, ge=0.0, le=1.0, alias="autoLexicalHigh")
    auto_lexical_high_cooc: float = Field(default=0.2, ge=0.0, le=1.0, alias="autoLexicalHighCooc")
    auto_abbreviation_cooc: float = Field(default=0.3, ge=0.0, le=1.0, alias="autoAbbreviationCooc")
    auto_lexical_mid: float = Field(default=0.75, ge=0.0, le=1.0, alias="autoLexicalMid")
    auto_lexical_mid_cooc: float = Field(default=0.5, ge=0.0, le=1.0, alias="autoLexicalMidCooc")
    review_abbreviation_cooc: float = Field(default=0.2, ge=0.0, le=1.0, alias="reviewAbbreviationCooc")
    review_cooc_strong: float = Field(default=0.6, ge=0.0, le=1.0, alias="reviewCoocStrong")
    review_lexical: float = Field(default=0.7, ge=0.0, le=1.0, alias="reviewLexical")
    review_abbreviation_alone: bool = Field(default=True, alias="reviewAbbreviationAlone")


class CanonicalThresholdsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    effective: CanonicalThresholdsModel
    defaults: CanonicalThresholdsModel


class TestEmbeddingRequest(BaseModel):
    base_url: str = Field(..., description="OpenAI-compatible base URL (e.g. http://localhost:11434/v1)")
    api_key: str = Field(default="", description="Optional API key")
    model: str | None = Field(default=None, description="Optional model id to probe with /embeddings; if omitted only /models is hit")


class TestEmbeddingResponse(BaseModel):
    ok: bool
    models: list[str] = Field(default_factory=list, description="Discovered model IDs")
    dimensions: int | None = Field(default=None, description="Embedding vector size if a probe model was provided")
    error: str | None = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_current_config() -> ExtensionsConfig:
    try:
        return get_extensions_config()
    except Exception as exc:
        logger.warning("Failed to load extensions config: %s", exc)
        return ExtensionsConfig(mcp_servers={}, skills={})


def _resolve_save_path() -> Path:
    """Resolve where to persist extensions_config.json.

    Priority: env var hint → existing resolved path → project root next to backend/.
    The env-var hint is honored even if the file does not yet exist, so the very
    first save can create the file at the user-specified location.
    """
    import os as _os

    env_hint = _os.getenv("CAPYBARA_HOME_EXTENSIONS_CONFIG_PATH")
    if env_hint:
        return Path(env_hint)

    try:
        existing = ExtensionsConfig.resolve_config_path()
    except FileNotFoundError:
        existing = None
    if existing is not None:
        return existing

    backend_dir = Path(__file__).resolve().parents[3]
    return backend_dir.parent / "extensions_config.json"


def _load_extensions_knowledge_vault_override() -> KnowledgeVaultUserConfig | None:
    """Read the knowledge-vault override block from extensions_config.json without writing."""
    config_path = _resolve_save_path()
    if not config_path.exists():
        return None
    try:
        with open(config_path, encoding="utf-8") as f:
            raw = json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        return None
    block = raw.get("knowledgeVault") or raw.get("knowledge_vault")
    if not isinstance(block, dict):
        return None
    try:
        return KnowledgeVaultUserConfig.model_validate(block)
    except Exception:
        logger.warning("knowledgeVault override block is malformed; ignoring")
        return None


def _save_extensions_knowledge_vault(kv: KnowledgeVaultUserConfig) -> None:
    config_path = _resolve_save_path()
    if not config_path.exists():
        logger.info("No existing extensions config found; creating at %s", config_path)

    raw: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                raw = json.load(f) or {}
        except json.JSONDecodeError as exc:
            logger.warning("Existing extensions config is not valid JSON (%s); overwriting", exc)
            raw = {}

    raw["knowledgeVault"] = kv.model_dump()

    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    tmp_path.replace(config_path)

    logger.info("Knowledge vault config saved to: %s", config_path)
    reload_extensions_config()

    try:
        from src.config.app_config import reload_app_config

        reload_app_config()
        logger.info("App config reloaded after knowledge vault config update.")
    except Exception as exc:
        logger.warning("Failed to reload app config after saving knowledge vault config: %s", exc)


def _save_extensions_with_user_models(
    user_models: dict[str, UserLlmEndpointConfig] | None = None,
    user_embedding_models: dict[str, UserLlmEndpointConfig] | None = None,
) -> None:
    config_path = _resolve_save_path()
    if not config_path.exists():
        logger.info("No existing extensions config found; creating at %s", config_path)

    # Start from the raw on-disk JSON so any unknown/extra top-level keys survive.
    raw: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                raw = json.load(f) or {}
        except json.JSONDecodeError as exc:
            logger.warning("Existing extensions config is not valid JSON (%s); overwriting", exc)
            raw = {}

    if user_models is not None:
        raw["userModels"] = {name: m.model_dump() for name, m in user_models.items()}
    if user_embedding_models is not None:
        raw["userEmbeddingModels"] = {name: m.model_dump() for name, m in user_embedding_models.items()}

    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    tmp_path.replace(config_path)

    logger.info("User LLM endpoints saved to: %s", config_path)
    reload_extensions_config()
    logger.info("Extensions config reloaded after saving user models.")

    # AppConfig.models is derived from user endpoints; reload so the in-process
    # singleton (used by /api/models, create_chat_model, ModelRouter, etc.)
    # surfaces the new entries without a restart. The LangGraph process sees
    # the change via its own mtime check on extensions_config.json.
    try:
        from src.config.app_config import reload_app_config

        reload_app_config()
        logger.info("App config reloaded so new user models surface in /api/models.")
    except Exception as exc:
        logger.warning("Failed to reload app config after saving user models: %s", exc)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post(
    "/test-llm",
    response_model=TestLlmResponse,
    summary="Test LLM Endpoint",
    description="Send a GET /v1/models request to verify an OpenAI-compatible endpoint and discover available models.",
)
async def test_llm_endpoint(request: TestLlmRequest) -> TestLlmResponse:
    base_url = request.base_url.rstrip("/")
    models_url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"

    headers = {}
    if request.api_key:
        headers["Authorization"] = f"Bearer {request.api_key}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(models_url, headers=headers)
            response.raise_for_status()
            data = response.json()

        model_ids: list[str] = []
        models_data = data.get("data") or data.get("models") or []
        for m in models_data:
            if isinstance(m, dict):
                mid = m.get("id") or m.get("name") or m.get("model")
                if mid:
                    model_ids.append(str(mid))
            elif isinstance(m, str):
                model_ids.append(m)

        return TestLlmResponse(ok=True, models=model_ids)
    except httpx.TimeoutException:
        return TestLlmResponse(ok=False, error="Connection timed out")
    except httpx.ConnectError:
        return TestLlmResponse(ok=False, error="Connection refused — is the server running?")
    except httpx.HTTPStatusError as exc:
        return TestLlmResponse(ok=False, error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}")
    except Exception as exc:
        return TestLlmResponse(ok=False, error=str(exc))


@router.post(
    "/test-comfyui",
    response_model=TestComfyuiResponse,
    summary="Test ComfyUI Endpoint",
    description="Hit the /system_stats endpoint to verify a ComfyUI server is reachable.",
)
async def test_comfyui_endpoint(request: TestComfyuiRequest) -> TestComfyuiResponse:
    base_url = request.base_url.rstrip("/")
    health_url = f"{base_url}/system_stats"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(health_url)
            response.raise_for_status()
        return TestComfyuiResponse(ok=True)
    except httpx.TimeoutException:
        return TestComfyuiResponse(ok=False, error="Connection timed out")
    except httpx.ConnectError:
        return TestComfyuiResponse(ok=False, error="Connection refused — is the ComfyUI server running?")
    except httpx.HTTPStatusError as exc:
        return TestComfyuiResponse(ok=False, error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}")
    except Exception as exc:
        return TestComfyuiResponse(ok=False, error=str(exc))


@router.post(
    "/test-generic",
    response_model=TestGenericResponse,
    summary="Generic Health Check",
    description="Send a GET request to any URL and report reachability and status code.",
)
async def test_generic_endpoint(request: TestGenericRequest) -> TestGenericResponse:
    rejection = _validate_probe_url(request.url)
    if rejection is not None:
        return TestGenericResponse(ok=False, error=rejection)
    try:
        async with httpx.AsyncClient(timeout=request.timeout_seconds, follow_redirects=False) as client:
            response = await client.get(request.url)
            return TestGenericResponse(ok=response.is_success, status_code=response.status_code)
    except httpx.TimeoutException:
        return TestGenericResponse(ok=False, error="Connection timed out")
    except httpx.ConnectError:
        return TestGenericResponse(ok=False, error="Connection refused")
    except Exception as exc:
        return TestGenericResponse(ok=False, error=str(exc))


@router.get(
    "/llm-endpoints",
    response_model=LlmEndpointsResponse,
    summary="List User LLM Endpoints",
    description="Return all user-added LLM endpoints from extensions config.",
)
async def list_llm_endpoints() -> LlmEndpointsResponse:
    config = _load_current_config()
    return LlmEndpointsResponse(user_models=config.user_models)


@router.put(
    "/llm-endpoints",
    response_model=LlmEndpointsResponse,
    summary="Save User LLM Endpoints",
    description="Save user-added LLM endpoints to extensions config, preserving MCP servers and community tools.",
)
async def save_llm_endpoints(request: LlmEndpointsMap) -> LlmEndpointsResponse:
    try:
        _save_extensions_with_user_models(user_models=request.user_models)
        reloaded = get_extensions_config()
        return LlmEndpointsResponse(user_models=reloaded.user_models)
    except Exception as exc:
        logger.error("Failed to save LLM endpoints: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save LLM endpoints: {exc}")


@router.get(
    "/embedding-endpoints",
    response_model=EmbeddingEndpointsResponse,
    summary="List User Embedding Endpoints",
    description="Return all user-added embedding endpoints from extensions config.",
)
async def list_embedding_endpoints() -> EmbeddingEndpointsResponse:
    config = _load_current_config()
    return EmbeddingEndpointsResponse(user_embedding_models=config.user_embedding_models)


@router.put(
    "/embedding-endpoints",
    response_model=EmbeddingEndpointsResponse,
    summary="Save User Embedding Endpoints",
    description="Save user-added embedding endpoints (used by the knowledge graph) to extensions config.",
)
async def save_embedding_endpoints(request: EmbeddingEndpointsMap) -> EmbeddingEndpointsResponse:
    try:
        _save_extensions_with_user_models(user_embedding_models=request.user_embedding_models)
        reloaded = get_extensions_config()
        return EmbeddingEndpointsResponse(user_embedding_models=reloaded.user_embedding_models)
    except Exception as exc:
        logger.error("Failed to save embedding endpoints: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save embedding endpoints: {exc}")


@router.post(
    "/test-embedding",
    response_model=TestEmbeddingResponse,
    summary="Test Embedding Endpoint",
    description="Hit /v1/models on an OpenAI-compatible embedding endpoint, and optionally POST /v1/embeddings with a probe model.",
)
async def test_embedding_endpoint(request: TestEmbeddingRequest) -> TestEmbeddingResponse:
    base_url = request.base_url.rstrip("/")
    base_v1 = base_url if base_url.endswith("/v1") else f"{base_url}/v1"
    models_url = f"{base_v1}/models"
    embeddings_url = f"{base_v1}/embeddings"

    headers = {}
    if request.api_key:
        headers["Authorization"] = f"Bearer {request.api_key}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(models_url, headers=headers)
            response.raise_for_status()
            data = response.json()

        model_ids: list[str] = []
        models_data = data.get("data") or data.get("models") or []
        for m in models_data:
            if isinstance(m, dict):
                mid = m.get("id") or m.get("name") or m.get("model")
                if mid:
                    model_ids.append(str(mid))
            elif isinstance(m, str):
                model_ids.append(m)

        dimensions: int | None = None
        if request.model:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    probe = await client.post(
                        embeddings_url,
                        headers={**headers, "Content-Type": "application/json"},
                        json={"model": request.model, "input": "capyhome embedding healthcheck"},
                    )
                    probe.raise_for_status()
                    payload = probe.json()
                items = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(items, list) and items:
                    vec = items[0].get("embedding") if isinstance(items[0], dict) else None
                    if isinstance(vec, list):
                        dimensions = len(vec)
            except Exception as probe_exc:
                return TestEmbeddingResponse(ok=False, models=model_ids, error=f"Probe failed: {probe_exc}")

        return TestEmbeddingResponse(ok=True, models=model_ids, dimensions=dimensions)
    except httpx.TimeoutException:
        return TestEmbeddingResponse(ok=False, error="Connection timed out")
    except httpx.ConnectError:
        return TestEmbeddingResponse(ok=False, error="Connection refused — is the server running?")
    except httpx.HTTPStatusError as exc:
        return TestEmbeddingResponse(ok=False, error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}")
    except Exception as exc:
        return TestEmbeddingResponse(ok=False, error=str(exc))


def _knowledge_vault_response_from_app() -> KnowledgeVaultConfigResponse:
    """Compose the effective knowledge vault config from app + extensions overrides."""
    from src.config.app_config import get_app_config

    app = get_app_config()
    kv = app.knowledge_vault
    return KnowledgeVaultConfigResponse(
        path=kv.path or "",
        llm_model=kv.cot_model or "",
        embedding_model=kv.vector_embedding_model or "",
    )


@router.get(
    "/knowledge-vault",
    response_model=KnowledgeVaultConfigResponse,
    summary="Get Knowledge Vault Config",
    description="Return the effective knowledge vault folder path, LLM model, and embedding model.",
)
async def get_knowledge_vault_config() -> KnowledgeVaultConfigResponse:
    return _knowledge_vault_response_from_app()


@router.put(
    "/knowledge-vault",
    response_model=KnowledgeVaultConfigResponse,
    summary="Save Knowledge Vault Config",
    description="Persist knowledge vault overrides (folder path, LLM model, embedding model) to extensions_config.json.",
)
async def save_knowledge_vault_config(request: KnowledgeVaultConfigRequest) -> KnowledgeVaultConfigResponse:
    try:
        existing = _load_extensions_knowledge_vault_override()
        kv = KnowledgeVaultUserConfig(
            path=request.path.strip(),
            llm_model=request.llm_model.strip(),
            embedding_model=request.embedding_model.strip(),
            canonical=existing.canonical if existing else None,
        )
        _save_extensions_knowledge_vault(kv)
        return _knowledge_vault_response_from_app()
    except Exception as exc:
        logger.error("Failed to save knowledge vault config: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save knowledge vault config: {exc}")


def _canonical_thresholds_response() -> CanonicalThresholdsResponse:
    from src.config.app_config import get_app_config
    from src.config.control_plane_config import CanonicalThresholdsConfig

    effective = get_app_config().knowledge_vault.canonical
    defaults = CanonicalThresholdsConfig()
    return CanonicalThresholdsResponse(
        effective=CanonicalThresholdsModel.model_validate(effective.model_dump()),
        defaults=CanonicalThresholdsModel.model_validate(defaults.model_dump()),
    )


@router.get(
    "/canonical-thresholds",
    response_model=CanonicalThresholdsResponse,
    summary="Get Canonical Alias Merge Thresholds",
    description="Return the effective canonical merge thresholds and the built-in defaults so the UI can show a reset target.",
)
async def get_canonical_thresholds() -> CanonicalThresholdsResponse:
    return _canonical_thresholds_response()


@router.put(
    "/canonical-thresholds",
    response_model=CanonicalThresholdsResponse,
    summary="Save Canonical Alias Merge Thresholds",
    description="Persist canonical-thresholds overrides to extensions_config.json. Pass null to reset to defaults.",
)
async def save_canonical_thresholds(
    request: CanonicalThresholdsModel | None = None,
) -> CanonicalThresholdsResponse:
    from src.config.extensions_config import CanonicalThresholdsUserConfig

    try:
        existing = _load_extensions_knowledge_vault_override()
        if request is None:
            canonical_override: CanonicalThresholdsUserConfig | None = None
        else:
            canonical_override = CanonicalThresholdsUserConfig.model_validate(request.model_dump())
        kv = KnowledgeVaultUserConfig(
            path=(existing.path if existing else ""),
            llm_model=(existing.llm_model if existing else ""),
            embedding_model=(existing.embedding_model if existing else ""),
            canonical=canonical_override,
        )
        _save_extensions_knowledge_vault(kv)
        return _canonical_thresholds_response()
    except Exception as exc:
        logger.error("Failed to save canonical thresholds: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save canonical thresholds: {exc}")
