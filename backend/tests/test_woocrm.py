from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dashboard_has_ten_deterministic_orders():
    response = client.get("/api/woocrm/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["orders"]) == 10
    assert payload["eligible_order_count"] == 7


def test_sync_is_idempotent():
    first = client.post("/api/woocrm/reset")
    assert first.status_code == 200
    first = client.post("/api/woocrm/sync").json()
    second = client.post("/api/woocrm/sync").json()
    assert first["created"] == 4
    assert second["created"] == 0
    assert second["updated"] == 0


def test_reconcile_corrects_mismatch():
    client.post("/api/woocrm/reset")
    client.post("/api/woocrm/sync")
    client.post("/api/woocrm/orders/1001/mismatch")
    result = client.post("/api/woocrm/reconcile").json()
    assert result["updated"] >= 1
