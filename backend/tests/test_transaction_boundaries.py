from concurrent.futures import ThreadPoolExecutor

import pytest
from app import main
from app.connectors import ConnectorError, NormalizedCRMOrder, NormalizedOrder
from app.main import app
from fastapi.testclient import TestClient


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "transaction-test.db")
    monkeypatch.setenv("INTEGRATION_MODE", "demo")
    main.init_db()
    assert client.post("/api/woocrm/reset").status_code == 200


def test_read_dashboard_can_run_while_a_writer_transaction_is_open():
    with main.db(write=True) as connection:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(client.get, "/api/woocrm/dashboard")
            response = future.result(timeout=2)
    assert response.status_code == 200


def test_live_reconciliation_persists_connector_failure_after_fetch(monkeypatch):
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("CRM_PROVIDER", "hubspot")

    class FakeWooCommerce:
        def list_orders(self):
            return [NormalizedOrder(
                id="live-failure-1",
                customer_email="failure@example.test",
                customer_name="Failure Case",
                total=12,
                currency="USD",
                status="processing",
                created_at="2026-10-17T10:00:00Z",
            )]

    class FailingHubSpot:
        def find_order(self, order_id):
            raise ConnectorError("HubSpot", "mock connector failure")

    monkeypatch.setattr(main, "WooCommerceClient", FakeWooCommerce)
    monkeypatch.setattr(main, "HubSpotCRMAdapter", FailingHubSpot)

    response = client.post("/api/woocrm/reconcile")

    assert response.status_code == 200
    with main.db() as connection:
        crm = connection.execute(
            "SELECT status,error_message FROM crm_orders WHERE dataset=? AND order_id=?",
            ("default", "live-failure-1"),
        ).fetchone()
        event = connection.execute(
            "SELECT outcome FROM order_events WHERE dataset=? AND order_id=?",
            ("default", "live-failure-1"),
        ).fetchone()
        run = connection.execute(
            "SELECT status,processed FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert crm["status"] == "ERROR"
    assert crm["error_message"] == "HubSpot: mock connector failure"
    assert event["outcome"] == "failed"
    assert dict(run) == {"status": "completed", "processed": 1}


def test_live_reconciliation_persists_successful_external_values(monkeypatch):
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("CRM_PROVIDER", "hubspot")

    class FakeWooCommerce:
        def list_orders(self):
            return [NormalizedOrder(
                id="live-success-1",
                customer_email="success@example.test",
                customer_name="Success Case",
                total=24,
                currency="USD",
                status="completed",
                created_at="2026-10-17T10:00:00Z",
            )]

    class FakeHubSpot:
        def find_order(self, order_id):
            return NormalizedCRMOrder(
                order_id=order_id,
                external_id="crm-success-1",
                email="success@example.test",
                name="Success Case",
                total=24,
                currency="USD",
                order_status="completed",
                crm_id="crm-success-1",
                updated_at="2026-10-17T10:01:00Z",
            )

    monkeypatch.setattr(main, "WooCommerceClient", FakeWooCommerce)
    monkeypatch.setattr(main, "HubSpotCRMAdapter", FakeHubSpot)

    response = client.post("/api/woocrm/reconcile")

    assert response.status_code == 200
    with main.db() as connection:
        order = connection.execute(
            "SELECT source,environment FROM orders WHERE dataset=? AND id=?",
            ("default", "live-success-1"),
        ).fetchone()
        crm = connection.execute(
            "SELECT status,total,source,environment FROM crm_orders WHERE dataset=? AND order_id=?",
            ("default", "live-success-1"),
        ).fetchone()
        event = connection.execute(
            "SELECT outcome FROM order_events WHERE dataset=? AND order_id=?",
            ("default", "live-success-1"),
        ).fetchone()
    assert dict(order) == {"source": "woocommerce", "environment": "live"}
    assert crm["status"] == "SYNCED"
    assert crm["total"] == 24
    assert crm["source"] == "hubspot"
    assert crm["environment"] == "live"
    assert event["outcome"] == "completed"
