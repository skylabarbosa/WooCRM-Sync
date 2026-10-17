import json
import importlib
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import main
from app.connectors import ConnectorError


@pytest.fixture
def isolated_app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "hardening.db")
    monkeypatch.setenv("APP_ENV", "demo")
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    monkeypatch.delenv("DEMO_RESET_ENABLED", raising=False)
    main.init_db()
    return TestClient(main.app)


def test_production_requires_key_for_reads_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "production.db")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_ACCESS_KEY", "correct-key")
    client = TestClient(main.app)

    assert client.get("/api/woocrm/dashboard").status_code == 401
    assert client.post("/api/woocrm/reset").status_code == 401
    assert client.get("/api/woocrm/health").status_code == 200
    assert client.get("/api/woocrm/ready").status_code == 200


def test_invalid_key_is_rejected_before_work(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "production.db")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_ACCESS_KEY", "correct-key")
    client = TestClient(main.app)

    response = client.get("/api/woocrm/dashboard", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_missing_production_key_refuses_startup(tmp_path):
    main.DATABASE_PATH = tmp_path / "startup-guard.db"
    environment = os.environ.copy()
    environment.update({"APP_ENV": "production", "DATABASE_PATH": str(tmp_path / "startup.db")})
    environment.pop("API_ACCESS_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=main.BASE_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "API_ACCESS_KEY is required" in result.stderr


def test_server_owned_actor_ignores_client_actor(isolated_app, monkeypatch):
    monkeypatch.setenv("OPERATOR_NAME", "server-operator")
    response = isolated_app.put(
        "/api/woocrm/risk-guard/settings",
        headers={"X-Actor": "client-actor"},
        json={
            "absolute_total_change": 100,
            "percentage_total_change": 50,
            "batch_change_limit": 25,
        },
    )
    assert response.status_code == 200
    assert response.json()["actor"] == "server-operator"


def test_reset_is_blocked_by_environment_and_flag(isolated_app, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_ACCESS_KEY", "correct-key")
    headers = {"X-API-Key": "correct-key"}
    assert isolated_app.post("/api/woocrm/reset", headers=headers).status_code == 403
    monkeypatch.setenv("APP_ENV", "demo")
    monkeypatch.setenv("DEMO_RESET_ENABLED", "false")
    assert isolated_app.post("/api/woocrm/reset", headers=headers).status_code == 403


def test_ready_does_not_leak_database_details(isolated_app, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "not-a-database")
    (tmp_path / "not-a-database").mkdir()
    response = isolated_app.get("/api/woocrm/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_cors_env_and_preflight_include_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("CORS_ORIGINS", "https://console.example")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "cors.db"))
    importlib.reload(main)
    main.init_db()
    client = TestClient(main.app)
    response = client.options(
        "/api/woocrm/dashboard",
        headers={
            "Origin": "https://console.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://console.example"
    assert "X-API-Key" in response.headers["access-control-allow-headers"]


@pytest.mark.parametrize("dataset", ["BadName", "too-long-" + "a" * 40, "-invalid"])
def test_dataset_name_validation(isolated_app, dataset):
    response = isolated_app.post(
        f"/api/woocrm/import/orders?dataset={dataset}",
        json=[],
    )
    assert response.status_code == 422
    assert "Dataset name must match" in response.json()["detail"]


def test_import_size_and_record_limits(isolated_app, monkeypatch):
    monkeypatch.setenv("MAX_IMPORT_BYTES", "10")
    too_large = isolated_app.post(
        "/api/woocrm/import/orders",
        data=b'{"records":[]}',
        headers={"content-type": "application/json"},
    )
    assert too_large.status_code == 413

    monkeypatch.setenv("MAX_IMPORT_BYTES", "100000")
    monkeypatch.setenv("MAX_IMPORT_RECORDS", "1")
    too_many = isolated_app.post(
        "/api/woocrm/import/orders",
        json=[{}, {}],
    )
    assert too_many.status_code == 413


def test_connector_errors_are_sanitized(isolated_app, monkeypatch):
    secret = "connector-secret"
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", secret)

    class FailingWoo:
        def test_connection(self):
            raise ConnectorError("WooCommerce", secret)

    monkeypatch.setattr(main, "WooCommerceClient", FailingWoo)
    response = isolated_app.post("/api/woocrm/test-connection")
    assert response.status_code == 502
    assert secret not in response.text
    assert "reference" in response.json()["detail"]
