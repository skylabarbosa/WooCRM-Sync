import json
import importlib
import os
import subprocess
import sys
import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from app import main
from app.connectors import ConnectorError


def production_auth(monkeypatch):
    def password_hash(password):
        salt = b"test-auth-salt"
        derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 1000)
        return "pbkdf2_sha256$1000$%s$%s" % (
            base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(derived).decode(),
        )
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-signing-secret")
    monkeypatch.setenv("AUTH_USERS_JSON", json.dumps([
        {"username": "viewer", "role": "viewer", "password_hash": password_hash("viewer-password")},
        {"username": "operator", "role": "operator", "password_hash": password_hash("operator-password")},
        {"username": "admin", "role": "admin", "password_hash": password_hash("admin-password")},
    ]))


def bearer(client, username, password):
    response = client.post("/api/woocrm/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def isolated_app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "hardening.db")
    monkeypatch.setenv("APP_ENV", "demo")
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    monkeypatch.delenv("DEMO_RESET_ENABLED", raising=False)
    main.init_db()
    return TestClient(main.app)


def test_production_requires_user_authentication_and_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "production.db")
    monkeypatch.setenv("APP_ENV", "production")
    production_auth(monkeypatch)
    main.init_db()
    client = TestClient(main.app)

    assert client.get("/api/woocrm/dashboard").status_code == 401
    assert client.post("/api/woocrm/reset").status_code == 401
    assert client.get("/api/woocrm/dashboard", headers=bearer(client, "viewer", "viewer-password")).status_code == 200
    assert client.post("/api/woocrm/reconcile", headers=bearer(client, "viewer", "viewer-password")).status_code == 403
    assert client.post("/api/woocrm/reconcile", headers=bearer(client, "operator", "operator-password")).status_code == 200
    assert client.post("/api/woocrm/reset", headers=bearer(client, "operator", "operator-password")).status_code == 403
    assert client.post("/api/woocrm/reset", headers=bearer(client, "admin", "admin-password")).status_code == 403
    assert client.get("/api/woocrm/health").status_code == 200
    assert client.get("/api/woocrm/ready").status_code == 200


def test_invalid_credentials_are_rejected_before_work(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "production.db")
    monkeypatch.setenv("APP_ENV", "production")
    production_auth(monkeypatch)
    client = TestClient(main.app)

    response = client.post("/api/woocrm/auth/login", json={"username": "operator", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_missing_production_auth_configuration_refuses_startup(tmp_path):
    main.DATABASE_PATH = tmp_path / "startup-guard.db"
    environment = os.environ.copy()
    environment.update({"APP_ENV": "production", "DATABASE_PATH": str(tmp_path / "startup.db")})
    environment.pop("AUTH_TOKEN_SECRET", None)
    environment.pop("AUTH_USERS_JSON", None)
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=main.BASE_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "AUTH_TOKEN_SECRET is required" in result.stderr


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
    production_auth(monkeypatch)
    headers = bearer(isolated_app, "admin", "admin-password")
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


def test_hubspot_token_never_appears_in_captured_logs_or_api_responses(isolated_app, monkeypatch, caplog):
    token = "hubspot-production-token-that-must-not-leak"
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("CRM_PROVIDER", "hubspot")
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", token)

    class FailingHubSpot:
        def test_connection(self):
            raise ConnectorError("HubSpot", f"upstream echoed {token}")

    class WorkingWoo:
        def test_connection(self):
            return None

    monkeypatch.setattr(main, "WooCommerceClient", WorkingWoo)
    monkeypatch.setattr(main, "HubSpotCRMAdapter", FailingHubSpot)
    with caplog.at_level("ERROR", logger="app.main"):
        response = isolated_app.post("/api/woocrm/test-connection")

    assert response.status_code == 502
    assert token not in response.text
    assert token not in caplog.text
    assert "[REDACTED]" in caplog.text
