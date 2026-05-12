"""Regression tests verifying searxng, crawl4ai, and Onyx MCP integrations are removed.

These tests ensure:
- The removed community modules no longer exist in importable form
- VaultLearningManager works without searxng_base_url and has no _discover_with_searxng
- FolderSyncTarget has no upload_to_onyx / connector_prefix fields
- KnowledgeVaultConfig has no searxng_base_url field
- PipelinesConfig has no onyx_ingestion_enabled / onyx_ingestion_base_url fields
- _build_folder_sync_manifest output has no onyx-related keys
- Service catalog excludes onyx_mcp, searxng, crawl4ai entries
- _core_services_readiness returns an empty list
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.config.control_plane_config import ToolBackendEndpointConfig, ToolBackendsConfig

# ---------------------------------------------------------------------------
# 1. Removed modules are gone
# ---------------------------------------------------------------------------


def test_searxng_module_not_importable() -> None:
    """src.community.searxng must not exist after removal."""
    for key in list(sys.modules.keys()):
        if "community.searxng" in key:
            del sys.modules[key]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.community.searxng.tools")


def test_crawl4ai_module_not_importable() -> None:
    """src.community.crawl4ai must not exist after removal."""
    for key in list(sys.modules.keys()):
        if "community.crawl4ai" in key:
            del sys.modules[key]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.community.crawl4ai.tools")


def test_onyx_bridge_module_not_importable() -> None:
    """src.community.onyx_bridge must not exist after removal."""
    for key in list(sys.modules.keys()):
        if "community.onyx_bridge" in key:
            del sys.modules[key]
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.community.onyx_bridge.tools")


def test_mcp_internal_search_available() -> None:
    """src.mcp.internal_search should be importable and expose helper APIs."""
    for key in list(sys.modules.keys()):
        if "mcp.internal_search" in key:
            del sys.modules[key]
    module = importlib.import_module("src.mcp.internal_search")
    assert hasattr(module, "register_internal_search_target")
    assert hasattr(module, "search_internal_documents_tool")


# ---------------------------------------------------------------------------
# 2. VaultLearningManager: no searxng_base_url, no _discover_with_searxng
# ---------------------------------------------------------------------------


def test_vault_learning_manager_no_searxng_base_url_param(tmp_path: Path) -> None:
    """VaultLearningManager.__init__ must not accept searxng_base_url."""
    from src.control_plane.vault_learning import VaultLearningManager

    with pytest.raises(TypeError, match="searxng_base_url"):
        VaultLearningManager(vault_root=tmp_path, searxng_base_url="http://localhost:8080")


def test_vault_learning_manager_no_discover_with_searxng(tmp_path: Path) -> None:
    """VaultLearningManager must not have _discover_with_searxng method."""
    from src.control_plane.vault_learning import VaultLearningManager

    mgr = VaultLearningManager(vault_root=tmp_path)
    assert not hasattr(mgr, "_discover_with_searxng"), (
        "_discover_with_searxng should have been removed along with the SearXNG integration"
    )


def test_vault_learning_manager_no_searxng_base_url_attr(tmp_path: Path) -> None:
    """Instantiated VaultLearningManager must not expose a searxng_base_url attribute."""
    from src.control_plane.vault_learning import VaultLearningManager

    mgr = VaultLearningManager(vault_root=tmp_path)
    assert not hasattr(mgr, "searxng_base_url"), (
        "searxng_base_url attribute should not exist on VaultLearningManager"
    )


def test_vault_discovery_without_topic_still_works(tmp_path: Path) -> None:
    """Discover with explicit URLs works without SearXNG autoresearch."""
    from src.control_plane.vault_learning import VaultLearningManager

    mgr = VaultLearningManager(vault_root=tmp_path, allowed_domains=["example.com"])
    report = mgr.discover(urls=["https://example.com/page"], source="test", topic="anything")
    assert report["candidate_count"] == 1


# ---------------------------------------------------------------------------
# 3. Config models: removed fields
# ---------------------------------------------------------------------------


def test_folder_sync_target_no_upload_to_onyx() -> None:
    """FolderSyncTarget must not have upload_to_onyx or connector_prefix fields."""
    from src.control_plane.models import FolderSyncTarget

    target = FolderSyncTarget(id="t1", path="/tmp")
    assert not hasattr(target, "upload_to_onyx"), "upload_to_onyx should have been removed"
    assert not hasattr(target, "connector_prefix"), "connector_prefix should have been removed"


def test_knowledge_vault_config_no_searxng_base_url() -> None:
    """KnowledgeVaultConfig must not have searxng_base_url field."""
    from src.config.control_plane_config import KnowledgeVaultConfig

    cfg = KnowledgeVaultConfig()
    assert not hasattr(cfg, "searxng_base_url"), "searxng_base_url should have been removed from KnowledgeVaultConfig"


def test_pipelines_config_no_onyx_ingestion_fields() -> None:
    """PipelinesConfig must not have onyx_ingestion_enabled or onyx_ingestion_base_url."""
    from src.config.control_plane_config import PipelinesConfig

    cfg = PipelinesConfig()
    assert not hasattr(cfg, "onyx_ingestion_enabled"), (
        "onyx_ingestion_enabled should have been removed from PipelinesConfig"
    )
    assert not hasattr(cfg, "onyx_ingestion_base_url"), (
        "onyx_ingestion_base_url should have been removed from PipelinesConfig"
    )


# ---------------------------------------------------------------------------
# 4. _build_folder_sync_manifest: no onyx keys in output
# ---------------------------------------------------------------------------


def test_folder_sync_manifest_no_onyx_keys(tmp_path: Path) -> None:
    """_build_folder_sync_manifest must not include prepared_for_onyx or onyx_ingestion keys."""
    from src.control_plane.service import ControlPlaneService
    from src.control_plane.store import ControlPlaneStore

    # Create a simple test file in tmp_path for the scan
    (tmp_path / "note.txt").write_text("hello")

    store = ControlPlaneStore(path=tmp_path / "state.json")
    svc = ControlPlaneService(store=store)

    with patch("src.control_plane.service.get_app_config") as mock_cfg:
        from src.config.control_plane_config import PipelinesConfig

        mock_cfg.return_value.pipelines = PipelinesConfig(
            folder_sync_max_files=10,
            folder_sync_max_bytes=10 * 1024 * 1024,
        )
        manifest = svc._build_folder_sync_manifest(target_id=None, override_path=str(tmp_path))

    assert "prepared_for_onyx" not in manifest, "prepared_for_onyx key must not appear in manifest"
    assert "onyx_ingestion" not in manifest, "onyx_ingestion key must not appear in manifest"
    for item in manifest.get("files", []):
        assert "upload_to_onyx" not in item, "upload_to_onyx must not appear in file entries"
        assert "connector_prefix" not in item, "connector_prefix must not appear in file entries"


# ---------------------------------------------------------------------------
# 5. Service catalog: no onyx_mcp / searxng / crawl4ai entries
# ---------------------------------------------------------------------------


def test_integration_service_catalog_excludes_removed_services(tmp_path: Path) -> None:
    """_integration_service_catalog must not list onyx_mcp, searxng, or crawl4ai."""
    from src.control_plane.service import ControlPlaneService
    from src.control_plane.store import ControlPlaneStore

    store = ControlPlaneStore(path=tmp_path / "state.json")
    svc = ControlPlaneService(store=store)
    catalog = svc._integration_service_catalog()
    ids = {item["id"] for item in catalog}

    assert "onyx_mcp" not in ids, "onyx_mcp must not appear in service catalog"
    assert "searxng" not in ids, "searxng must not appear in service catalog"
    assert "crawl4ai" not in ids, "crawl4ai must not appear in service catalog"


def test_integration_service_catalog_contains_expected_services(tmp_path: Path) -> None:
    """Service catalog must still contain comfyui."""
    from src.control_plane.service import ControlPlaneService
    from src.control_plane.store import ControlPlaneStore

    store = ControlPlaneStore(path=tmp_path / "state.json")
    svc = ControlPlaneService(store=store)
    catalog = svc._integration_service_catalog()
    ids = {item["id"] for item in catalog}

    assert "comfyui" in ids, "comfyui must remain in service catalog"
    assert "marinetime_mcp" not in ids, "marinetime_mcp must be removed from service catalog"


def test_core_services_readiness_returns_empty(tmp_path: Path) -> None:
    """_core_services_readiness must return an empty list (no onyx/searxng/crawl4ai checks)."""
    from src.control_plane.service import ControlPlaneService
    from src.control_plane.store import ControlPlaneStore

    store = ControlPlaneStore(path=tmp_path / "state.json")
    svc = ControlPlaneService(store=store)
    result = svc._core_services_readiness()

    assert result == [], f"Expected empty readiness list, got: {result}"


def test_resolve_integration_services_excludes_removed(tmp_path: Path) -> None:
    """_resolve_integration_services must not include onyx_mcp, searxng, or crawl4ai."""
    from src.control_plane.service import ControlPlaneService
    from src.control_plane.store import ControlPlaneStore

    store = ControlPlaneStore(path=tmp_path / "state.json")
    svc = ControlPlaneService(store=store)

    with patch("src.control_plane.service.get_app_config") as mock_cfg:
        mock_cfg.return_value.tool_backends = ToolBackendsConfig(
            comfyui=ToolBackendEndpointConfig(enabled=True, base_url="http://localhost:8188"),
        )
        mock_cfg.return_value.knowledge_vault = SimpleNamespace(
            lightrag=SimpleNamespace(
                base_url="http://localhost:9621",
                timeout_seconds=12.0,
            )
        )
        mock_cfg.return_value.model_extra = {}

        services = svc._resolve_integration_services()

    ids = {s["id"] for s in services}
    assert "onyx_mcp" not in ids, "onyx_mcp must not appear in resolved services"
    assert "searxng" not in ids, "searxng must not appear in resolved services"
    assert "crawl4ai" not in ids, "crawl4ai must not appear in resolved services"
