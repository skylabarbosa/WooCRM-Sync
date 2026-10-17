from concurrent.futures import ThreadPoolExecutor
import threading
import time

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


def test_concurrent_live_replays_claim_one_order_before_crm_write(monkeypatch):
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("CRM_PROVIDER", "hubspot")
    monkeypatch.setenv("CRM_WRITE_ENABLED", "true")
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "mock-key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "mock-secret")
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "mock-token")
    records = {}
    write_started = threading.Event()
    release_write = threading.Event()
    writes = []

    class FakeWooCommerce:
        def list_orders(self):
            return [NormalizedOrder("live-race-1", "race@example.test", "Race", 12, "USD", "processing", "2026-10-17T10:00:00Z")]

        def test_connection(self):
            return None

    class SlowCRM:
        def test_connection(self):
            return None

        def find_order(self, order_id):
            return records.get(order_id)

        def write_order(self, order, existing=None):
            writes.append(order.id)
            write_started.set()
            release_write.wait(timeout=3)
            records[order.id] = NormalizedCRMOrder(
                order.id, "crm-race-1", order.customer_email, order.customer_name,
                order.total, order.currency, order.status, "deal-race-1", "2026-10-17T10:01:00Z",
            )
            return records[order.id]

    monkeypatch.setattr(main, "WooCommerceClient", FakeWooCommerce)
    monkeypatch.setattr(main, "HubSpotCRMAdapter", SlowCRM)
    assert client.post("/api/woocrm/reconcile").status_code == 200

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, "/api/woocrm/orders/live-race-1/replay")
        assert write_started.wait(timeout=2)
        second = executor.submit(client.post, "/api/woocrm/orders/live-race-1/replay")
        second_response = second.result(timeout=2)
        release_write.set()
        first_response = first.result(timeout=3)

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert writes == ["live-race-1"]


def test_slow_live_connector_does_not_hold_sqlite_write_transaction(monkeypatch):
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("CRM_PROVIDER", "hubspot")
    monkeypatch.setenv("CRM_WRITE_ENABLED", "true")
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "mock-key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "mock-secret")
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "mock-token")
    write_started = threading.Event()
    release_write = threading.Event()
    records = {}

    class FakeWooCommerce:
        def list_orders(self):
            return [NormalizedOrder("live-slow-1", "slow@example.test", "Slow", 13, "USD", "processing", "2026-10-17T10:00:00Z")]

        def test_connection(self):
            return None

    class SlowCRM:
        def test_connection(self):
            return None

        def find_order(self, order_id):
            return records.get(order_id)

        def write_order(self, order, existing=None):
            write_started.set()
            release_write.wait(timeout=3)
            records[order.id] = NormalizedCRMOrder(
                order.id, "crm-slow-1", order.customer_email, order.customer_name,
                order.total, order.currency, order.status, "deal-slow-1", "2026-10-17T10:01:00Z",
            )
            return records[order.id]

    monkeypatch.setattr(main, "WooCommerceClient", FakeWooCommerce)
    monkeypatch.setattr(main, "HubSpotCRMAdapter", SlowCRM)
    assert client.post("/api/woocrm/reconcile").status_code == 200

    with ThreadPoolExecutor(max_workers=1) as executor:
        replay_future = executor.submit(client.post, "/api/woocrm/orders/live-slow-1/replay")
        assert write_started.wait(timeout=2)
        started = time.monotonic()
        dashboard_response = client.get("/api/woocrm/dashboard")
        elapsed = time.monotonic() - started
        release_write.set()
        replay_response = replay_future.result(timeout=3)

    assert dashboard_response.status_code == 200
    assert elapsed < 1
    assert replay_response.status_code == 200
