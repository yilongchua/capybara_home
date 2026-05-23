"""Tests for the community tools Gateway API and get_available_tools integration."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.community.registry import COMMUNITY_TOOL_REGISTRY

# ─── Registry sanity checks ───────────────────────────────────────────────────


def test_registry_has_expected_tools():
    expected = {
        "web_search",
        "query_knowledge_vault",
        "save_to_knowledge_vault",
        "comfyui_generate",
        "image_search",
    }
    assert set(COMMUNITY_TOOL_REGISTRY.keys()) == expected


def test_registry_entries_have_required_fields():
    for name, entry in COMMUNITY_TOOL_REGISTRY.items():
        assert "import_path" in entry, f"{name} missing import_path"
        assert "display_name" in entry, f"{name} missing display_name"
        assert "description" in entry, f"{name} missing description"
        assert entry["source"] in ("builtin", "config"), f"{name} has invalid source"


def test_builtin_tools_are_marked_correctly():
    builtin_expected = {"web_search", "query_knowledge_vault", "save_to_knowledge_vault"}
    for name in builtin_expected:
        assert COMMUNITY_TOOL_REGISTRY[name]["source"] == "builtin", f"{name} should be 'builtin'"


def test_config_tools_are_marked_correctly():
    config_expected = {"comfyui_generate", "image_search"}
    for name in config_expected:
        assert COMMUNITY_TOOL_REGISTRY[name]["source"] == "config", f"{name} should be 'config'"


# ─── Gateway API ──────────────────────────────────────────────────────────────


@pytest.fixture
def temp_extensions_config():
    """Create a temporary extensions_config.json and yield its path."""
    data = {"mcpServers": {}, "skills": {}, "communityTools": {}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        return Path(f.name)


@pytest.fixture
def gateway_client(temp_extensions_config):
    with (
        patch("src.config.extensions_config.ExtensionsConfig.resolve_config_path", return_value=temp_extensions_config),
        patch("src.gateway.app.get_app_config", return_value=MagicMock(models=[])),
    ):
        from src.config.extensions_config import reset_extensions_config
        from src.gateway.app import create_app

        reset_extensions_config()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, temp_extensions_config
        reset_extensions_config()


def test_list_community_tools_returns_all_registry_tools(gateway_client):
    client, _ = gateway_client
    resp = client.get("/api/tools/community")
    assert resp.status_code == 200
    data = resp.json()
    names = {t["name"] for t in data["tools"]}
    assert names == set(COMMUNITY_TOOL_REGISTRY.keys())


def test_list_community_tools_defaults_all_enabled(gateway_client):
    client, _ = gateway_client
    resp = client.get("/api/tools/community")
    data = resp.json()
    for tool in data["tools"]:
        assert tool["enabled"] is True, f"{tool['name']} should default to enabled"


def test_update_community_tool_disables_and_persists(gateway_client):
    client, config_path = gateway_client
    resp = client.put("/api/tools/community/web_search", json={"enabled": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False

    # Verify persisted to file
    saved = json.loads(config_path.read_text())
    assert saved["communityTools"]["web_search"]["enabled"] is False


def test_update_community_tool_re_enables(gateway_client):
    client, _ = gateway_client
    client.put("/api/tools/community/web_search", json={"enabled": False})
    resp = client.put("/api/tools/community/web_search", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


def test_update_unknown_tool_returns_404(gateway_client):
    client, _ = gateway_client
    resp = client.put("/api/tools/community/nonexistent_tool", json={"enabled": False})
    assert resp.status_code == 404


def test_list_reflects_saved_override(gateway_client):
    client, _ = gateway_client
    client.put("/api/tools/community/comfyui_generate", json={"enabled": False})
    resp = client.get("/api/tools/community")
    data = resp.json()
    tool = next(t for t in data["tools"] if t["name"] == "comfyui_generate")
    assert tool["enabled"] is False


# ─── get_available_tools integration ─────────────────────────────────────────


def test_get_available_tools_respects_community_override(tmp_path):
    """Disabling web_search via communityTools should exclude it from the tool list."""
    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {}, "skills": {}, "communityTools": {"web_search": {"enabled": False}}})
    )

    mock_tool = MagicMock()
    mock_tool.name = "web_search"

    mock_app_config = MagicMock()
    mock_app_config.tools = []
    mock_app_config.models = []
    mock_app_config.get_model_config.return_value = None

    with (
        patch("src.tools.tools.get_app_config", return_value=mock_app_config),
        patch("src.config.extensions_config.ExtensionsConfig.resolve_config_path", return_value=config_file),
        patch("src.community.web_search.web_search_tool", mock_tool),
        patch("src.tools.tools.web_search_tool", mock_tool),
    ):
        from src.tools.tools import get_available_tools

        tools = get_available_tools(include_mcp=False)

    tool_names = [t.name for t in tools]
    assert "web_search" not in tool_names


def test_get_available_tools_builtin_enabled_by_default(tmp_path):
    """With no overrides all builtin tools should appear."""
    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(json.dumps({"mcpServers": {}, "skills": {}, "communityTools": {}}))

    mock_app_config = MagicMock()
    mock_app_config.tools = []
    mock_app_config.models = []
    mock_app_config.get_model_config.return_value = None

    with (
        patch("src.tools.tools.get_app_config", return_value=mock_app_config),
        patch("src.config.extensions_config.ExtensionsConfig.resolve_config_path", return_value=config_file),
    ):
        from importlib import reload

        import src.tools.tools as tools_module

        reload(tools_module)
        tools = tools_module.get_available_tools(include_mcp=False)

    tool_names = [t.name for t in tools]
    # All builtin tools should be present when not overridden
    for name in ("web_search", "query_knowledge_vault", "save_to_knowledge_vault"):
        assert name in tool_names, f"Expected {name} in default tool list"
