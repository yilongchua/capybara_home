import importlib

from fastapi.testclient import TestClient

from src.gateway.config import GatewayConfig


def test_api_key_middleware_blocks_requests_without_key(monkeypatch):
    gateway_app_module = importlib.import_module("src.gateway.app")

    monkeypatch.setattr(
        gateway_app_module,
        "get_gateway_config",
        lambda: GatewayConfig(
            host="0.0.0.0",
            port=8001,
            cors_origins=["http://localhost:3000"],
            api_key="secret",
            api_key_header="x-api-key",
        ),
    )

    client = TestClient(gateway_app_module.create_app())
    response = client.get("/api/nonexistent")
    assert response.status_code == 401
    assert "Unauthorized" in response.json()["detail"]


def test_api_key_middleware_accepts_x_api_key(monkeypatch):
    gateway_app_module = importlib.import_module("src.gateway.app")

    monkeypatch.setattr(
        gateway_app_module,
        "get_gateway_config",
        lambda: GatewayConfig(
            host="0.0.0.0",
            port=8001,
            cors_origins=["http://localhost:3000"],
            api_key="secret",
            api_key_header="x-api-key",
        ),
    )

    client = TestClient(gateway_app_module.create_app())
    response = client.get("/api/nonexistent", headers={"x-api-key": "secret"})
    assert response.status_code == 404


def test_api_key_middleware_accepts_bearer_token(monkeypatch):
    gateway_app_module = importlib.import_module("src.gateway.app")

    monkeypatch.setattr(
        gateway_app_module,
        "get_gateway_config",
        lambda: GatewayConfig(
            host="0.0.0.0",
            port=8001,
            cors_origins=["http://localhost:3000"],
            api_key="secret",
            api_key_header="x-api-key",
        ),
    )

    client = TestClient(gateway_app_module.create_app())
    response = client.get("/api/nonexistent", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 404


def test_health_endpoint_reports_degraded_components(monkeypatch):
    gateway_app_module = importlib.import_module("src.gateway.app")

    monkeypatch.setattr(
        gateway_app_module,
        "get_gateway_config",
        lambda: GatewayConfig(
            host="0.0.0.0",
            port=8001,
            cors_origins=["http://localhost:3000"],
            api_key="",
            api_key_header="x-api-key",
        ),
    )

    app = gateway_app_module.create_app()
    app.state.component_status = {
        "channels": {"status": "failed", "error": "example"},
        "generation_poller": {"status": "running", "error": None},
    }

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["service"] == "capybara-home-gateway"
    assert payload["components"]["channels"]["status"] == "failed"
