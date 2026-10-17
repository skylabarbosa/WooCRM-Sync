import json
import pytest
import httpx
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main
from app.connectors import ConnectorError, HubSpotCRMAdapter, NormalizedCRMOrder, NormalizedOrder, WooCommerceClient
from app.main import app, db

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "woocrm-test.db")
    main.init_db()
    reset()


def dashboard():
    response = client.get("/api/woocrm/dashboard")
    assert response.status_code == 200
    return response.json()


def reset():
    response = client.post("/api/woocrm/reset")
    assert response.status_code == 200


def test_health_endpoint():
    response = client.get("/api/woocrm/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_has_twenty_deterministic_orders_with_expected_scenarios():
    reset()
    payload = dashboard()
    assert len(payload["orders"]) == 20
    assert payload["eligible_order_count"] == 18
    assert payload["counts"] == {"SYNCED": 8, "MISSING": 4, "ERROR": 3, "MISMATCH": 3, "NOT_ELIGIBLE": 2}
    assert len([order for order in payload["orders"] if order["crm"]]) == 14


def test_reconcile_identifies_missing_without_overwriting():
    reset()
    result = client.post("/api/woocrm/reconcile")
    assert result.status_code == 200
    payload = dashboard()
    assert next(order["state"] for order in payload["orders"] if order["id"] == 1009) == "MISSING"
    assert payload["counts"]["MISSING"] == 4


def test_replay_missing_order_is_idempotently_restricted():
    reset()
    assert client.post("/api/woocrm/orders/1009/replay").status_code == 200
    assert next(order["state"] for order in dashboard()["orders"] if order["id"] == 1009) == "SYNCED"
    assert client.post("/api/woocrm/orders/1009/replay").status_code == 409
    events = client.get("/api/woocrm/orders/1009/history").json()["events"]
    assert events[0]["outcome"] == "blocked"
    assert events[0]["error_message"].endswith("current state is SYNCED")
    assert not any(event["outcome"] == "failed" for event in events)


def test_replay_rejects_mismatch_and_explicit_update_corrects_it():
    reset()
    assert client.post("/api/woocrm/orders/1001/mismatch").status_code == 200
    assert client.post("/api/woocrm/orders/1001/replay").status_code == 409
    assert next(order["state"] for order in dashboard()["orders"] if order["id"] == 1001) == "MISMATCH"
    assert client.post("/api/woocrm/orders/1001/update").status_code == 200
    assert next(order["state"] for order in dashboard()["orders"] if order["id"] == 1001) == "SYNCED"
    events = client.get("/api/woocrm/orders/1001/history").json()["events"]
    assert any(event["outcome"] == "blocked" and event["event_type"] == "replay" for event in events)
    assert any(event["outcome"] == "verified" and event["event_type"] == "mismatch_correction" for event in events)


def test_reconcile_detects_order_status_mismatch():
    reset()
    with db() as connection:
        connection.execute("UPDATE crm_orders SET order_status='completed' WHERE order_id=1001")
    assert next(order["state"] for order in dashboard()["orders"] if order["id"] == 1001) == "MISMATCH"
    client.post("/api/woocrm/reconcile")
    assert next(order["state"] for order in dashboard()["orders"] if order["id"] == 1001) == "MISMATCH"


def test_error_replay_recovers_and_updates_metrics():
    reset()
    assert client.post("/api/woocrm/orders/1016/replay").status_code == 200
    assert dashboard()["counts"] == {"SYNCED": 9, "MISSING": 4, "ERROR": 2, "MISMATCH": 3, "NOT_ELIGIBLE": 2}


def test_error_replay_records_real_failure_then_safe_retry(monkeypatch):
    reset()
    original_sync_order = main.sync_order

    def failing_sync_order(connection, order):
        raise RuntimeError("temporary simulated CRM outage")

    monkeypatch.setattr(main, "sync_order", failing_sync_order)
    failed = client.post("/api/woocrm/orders/1016/replay")
    assert failed.status_code == 502
    failed_events = client.get("/api/woocrm/orders/1016/history").json()["events"]
    assert failed_events[0]["outcome"] == "failed"
    assert "temporary simulated CRM outage" in failed_events[0]["error_message"]

    monkeypatch.setattr(main, "sync_order", original_sync_order)
    assert client.post("/api/woocrm/orders/1016/replay").status_code == 200
    assert dashboard()["counts"]["ERROR"] == 2
    refreshed_events = client.get("/api/woocrm/orders/1016/history").json()["events"]
    assert refreshed_events[0]["outcome"] == "verified"
    assert any(event["outcome"] == "failed" for event in refreshed_events)


def test_ineligible_orders_cannot_be_replayed():
    reset()
    with db() as connection:
        connection.execute(
            "INSERT INTO orders(id,dataset,customer_email,customer_name,total,currency,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("2001", "default", "ineligible@example.com", "Ineligible", 12, "USD", "cancelled", "2026-10-20T10:00:00Z"),
        )
    payload = dashboard()
    assert next(order["state"] for order in payload["orders"] if order["id"] == 2001) == "NOT_ELIGIBLE"
    assert client.post("/api/woocrm/orders/2001/replay").status_code == 409
    events = client.get("/api/woocrm/orders/2001/history").json()["events"]
    assert events[0]["outcome"] == "blocked"
    assert "NOT_ELIGIBLE" in events[0]["error_message"]


def test_customer_grouping_normalizes_billing_email():
    reset()
    with db() as connection:
        connection.execute("UPDATE orders SET customer_email=' MAYA@EXAMPLE.COM ' WHERE id=1001")
    groups = {group["email"]: group for group in dashboard()["groups"]}
    assert groups["maya@example.com"]["order_count"] == 1


def test_customer_snapshot_exposes_authoritative_group_metrics_and_unknown_contacts():
    reset()
    payload = dashboard()
    assert payload["eligible_customer_count"] == len(payload["groups"])
    assert payload["customer_attention_count"] == sum(group["attention_count"] > 0 for group in payload["groups"])
    assert all(group["synced_count"] <= group["order_count"] for group in payload["groups"])
    assert payload["contact_counts"]["NOT_FOUND"] == 2
    assert sum(group["crm_contact_status"] == "FOUND" for group in payload["groups"]) == 4
    assert sum(group["crm_contact_status"] == "NOT_CHECKED" for group in payload["groups"]) == 12

    with db() as connection:
        connection.execute(
            "INSERT INTO orders(id,dataset,customer_email,customer_name,total,currency,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("customer-metrics-1", "default", "new-group@example.test", "New Group", 12, "USD", "processing", "2026-10-20T10:00:00Z"),
        )
    changed = dashboard()
    assert changed["eligible_customer_count"] == payload["eligible_customer_count"] + 1
    assert next(group for group in changed["groups"] if group["email"] == "new-group@example.test")["order_count"] == 1


def test_customer_contact_counts_only_use_persisted_verification():
    reset()
    with db() as connection:
        connection.executemany(
            """INSERT INTO crm_contacts(dataset,email,status,contact_id,verified_at,source)
               VALUES ('default',?,?,?,?,?)""",
            [
                ("maya.chen@example.test", "FOUND", "contact-1", "2026-10-20T10:00:00Z", "hubspot"),
                ("liam.carter@example.test", "NOT_FOUND", None, "2026-10-20T10:00:00Z", "hubspot"),
            ],
        )
    payload = dashboard()
    assert payload["contact_counts"]["FOUND"] == 5
    assert payload["contact_counts"]["NOT_FOUND"] == 3
    assert next(group for group in payload["groups"] if group["email"] == "maya.chen@example.test")["crm_contact_status"] == "FOUND"
    assert next(group for group in payload["groups"] if group["email"] == "liam.carter@example.test")["crm_contact_status"] == "NOT_FOUND"


def test_reset_restores_initial_state_and_metrics_follow_actions():
    reset()
    client.post("/api/woocrm/orders/1009/replay")
    assert dashboard()["counts"]["SYNCED"] == 9
    reset()
    payload = dashboard()
    assert payload["counts"] == {"SYNCED": 8, "MISSING": 4, "ERROR": 3, "MISMATCH": 3, "NOT_ELIGIBLE": 2}


def test_missing_orders_can_have_contacts_without_crm_order_records():
    reset()
    payload = dashboard()
    missing = {str(order["id"]) for order in payload["orders"] if order["state"] == "MISSING"}
    assert missing == {"1009", "1010", "1011", "1012"}
    assert payload["contact_counts"]["FOUND"] == 4
    for order_id in missing:
        order = next(order for order in payload["orders"] if str(order["id"]) == order_id)
        group = next(group for group in payload["groups"] if group["email"] == order["customer_email"])
        assert group["crm_contact_status"] == "FOUND"
        assert order["crm"] is None


def test_demo_reset_is_idempotent_without_duplicate_default_records():
    reset()
    reset()
    with db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders WHERE dataset='default'").fetchone()[0] == 20
        assert connection.execute("SELECT COUNT(*) FROM crm_orders WHERE dataset='default'").fetchone()[0] == 14
        assert connection.execute("SELECT COUNT(*) FROM crm_contacts WHERE dataset='default'").fetchone()[0] == 6
        assert connection.execute(
            "SELECT COUNT(*) FROM orders WHERE dataset='default' GROUP BY id HAVING COUNT(*) > 1"
        ).fetchall() == []


def test_arbitrary_order_import_reconcile_replay_and_idempotency():
    reset()
    dataset = f"imp-{uuid4().hex}"
    order = {
        "id": "new-order-9001", "customer_email": "new@example.com", "customer_name": "New Customer",
        "total": 25.5, "currency": "EUR", "status": "processing", "created_at": "2026-10-30T10:00:00Z",
    }
    response = client.post(f"/api/woocrm/import/orders?dataset={dataset}", json=[order])
    assert response.status_code == 200
    assert client.post(f"/api/woocrm/reconcile?dataset={dataset}").status_code == 200
    imported = client.get(f"/api/woocrm/dashboard?dataset={dataset}").json()
    assert imported["counts"] == {"SYNCED": 0, "MISSING": 1, "ERROR": 0, "MISMATCH": 0, "NOT_ELIGIBLE": 0}
    repeated = client.post(f"/api/woocrm/import/orders?dataset={dataset}", json=[order]).json()
    assert repeated["imported"] == 0
    assert repeated["inserted"] == 0
    assert repeated["skipped"] == 1
    assert client.post(f"/api/woocrm/orders/new-order-9001/replay?dataset={dataset}").status_code == 200
    assert client.post(f"/api/woocrm/orders/new-order-9001/replay?dataset={dataset}").status_code == 409
    assert client.get(f"/api/woocrm/dashboard?dataset={dataset}").json()["counts"]["SYNCED"] == 1


def test_crm_import_mismatch_and_invalid_import():
    reset()
    dataset = f"ctl-{uuid4().hex}"
    order = {
        "id": "new-order-9002", "customer_email": "new@example.com", "customer_name": "New Customer",
        "total": 40, "currency": "USD", "status": "processing", "created_at": "2026-10-30T10:00:00Z",
    }
    assert client.post(f"/api/woocrm/import/orders?dataset={dataset}", json=[order]).status_code == 200
    crm = {
        "order_id": "new-order-9002", "email": "new@example.com", "name": "New Customer",
        "total": 41, "currency": "USD", "status": "SYNCED", "order_status": "processing",
    }
    assert client.post(f"/api/woocrm/import/crm-orders?dataset={dataset}", json=[crm]).status_code == 200
    client.post(f"/api/woocrm/reconcile?dataset={dataset}")
    assert client.get(f"/api/woocrm/dashboard?dataset={dataset}").json()["counts"]["MISMATCH"] == 1
    assert client.post(f"/api/woocrm/orders/new-order-9002/replay?dataset={dataset}").status_code == 409
    update = client.post(f"/api/woocrm/orders/new-order-9002/update?dataset={dataset}")
    assert update.status_code == 409
    evaluation_id = update.json()["detail"]["evaluation_id"]
    assert client.post(
        f"/api/woocrm/risk-guard/evaluations/{evaluation_id}/approve",
        headers={"x-actor": "tester"},
        json={"actor": "tester"},
    ).status_code == 200
    assert client.post(
        f"/api/woocrm/orders/new-order-9002/update?dataset={dataset}&approval_id={evaluation_id}"
    ).status_code == 200
    invalid = client.post("/api/woocrm/import/orders", json=[{"id": "bad"}])
    assert invalid.status_code == 422


def test_reset_preserves_imported_datasets():
    reset()
    dataset = f"iso-{uuid4().hex}"
    order = {
        "id": "isolated-order", "customer_email": "isolated@example.com", "customer_name": "Isolated Customer",
        "total": 12, "currency": "USD", "status": "processing", "created_at": "2026-10-30T10:00:00Z",
    }
    assert client.post(f"/api/woocrm/import/orders?dataset={dataset}", json=[order]).status_code == 200
    assert client.post("/api/woocrm/reset").status_code == 200
    assert client.get(f"/api/woocrm/dashboard?dataset={dataset}").json()["orders"][0]["id"] == "isolated-order"


def test_csv_import_reports_inserted_and_skipped_records():
    dataset = f"csv-{uuid4().hex}"
    csv_body = (
        "id,customer_email,customer_name,total,currency,status,created_at\n"
        "csv-1,csv@example.com,CSV Customer,12.50,usd,processing,2026-10-30T10:00:00Z\n"
    )
    response = client.post(
        f"/api/woocrm/import/orders?dataset={dataset}&format=csv",
        content=csv_body,
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    repeated = client.post(
        f"/api/woocrm/import/orders?dataset={dataset}&format=csv",
        content=csv_body,
        headers={"content-type": "text/csv"},
    )
    assert repeated.json()["skipped"] == 1
    assert client.get(f"/api/woocrm/dashboard?dataset={dataset}").json()["orders"][0]["currency"] == "USD"


def test_duplicate_rows_in_one_import_are_counted_once_and_conflicts_are_rejected():
    dataset = f"dup-{uuid4().hex}"
    order = {
        "id": "duplicate-1", "customer_email": "duplicate@example.com", "customer_name": "Duplicate",
        "total": 5, "currency": "USD", "status": "processing", "created_at": "2026-10-30T10:00:00Z",
    }
    result = client.post(f"/api/woocrm/import/orders?dataset={dataset}", json=[order, order])
    assert result.status_code == 200
    assert result.json()["inserted"] == 1
    assert result.json()["skipped"] == 1
    conflict = {**order, "total": 6}
    response = client.post(f"/api/woocrm/import/orders?dataset={dataset}", json=[order, conflict])
    assert response.status_code == 409
    assert "Conflicting" in response.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ([{"id": "bad"}], "missing required fields"),
        ([{"id": "bad", "customer_email": "a@example.com", "customer_name": "A", "total": "nan",
           "currency": "USD", "status": "processing", "created_at": "2026-10-30T10:00:00Z"}], "invalid currency or amount"),
        ([{"id": "bad", "customer_email": "a@example.com", "customer_name": "A", "total": 1,
           "currency": "USD", "status": "unknown", "created_at": "2026-10-30T10:00:00Z"}], "unsupported woo status"),
    ],
)
def test_invalid_import_records_are_rejected(payload, detail):
    response = client.post("/api/woocrm/import/orders", json=payload)
    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_malformed_csv_and_json_are_rejected():
    assert client.post(
        "/api/woocrm/import/orders?format=csv",
        content="id,customer_email\n\"unterminated",
        headers={"content-type": "text/csv"},
    ).status_code == 422


def test_woocommerce_connector_normalizes_live_order_response(monkeypatch):
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "secret")

    def handler(request):
        assert request.url.path.endswith("/orders")
        return httpx.Response(
            200,
            json=[{
                "id": 42,
                "billing": {"email": " Buyer@Example.COM ", "first_name": "Ada", "last_name": "Lovelace"},
                "total": "19.95",
                "currency": "usd",
                "status": "processing",
                "date_created": "2026-10-14T10:00:00Z",
                "date_modified": "2026-10-14T10:05:00Z",
            }],
        )

    order = WooCommerceClient(client=httpx.Client(transport=httpx.MockTransport(handler))).list_orders()[0]
    assert order.id == "42"
    assert order.customer_email == "buyer@example.com"
    assert order.customer_name == "Ada Lovelace"
    assert order.total == 19.95
    assert order.currency == "USD"


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ([{"id": 42, "billing": {}, "total": "not-a-number", "currency": "USD"}], "invalid amount"),
        ({"results": []}, "unexpected orders response"),
    ],
)
def test_woocommerce_malformed_order_response_is_an_error(monkeypatch, payload, error):
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "secret")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ConnectorError, match=error):
        WooCommerceClient(client=httpx.Client(transport=transport)).list_orders()


@pytest.mark.parametrize(
    ("response", "error", "retryable"),
    [
        (httpx.Response(401), "authentication or permission check failed", False),
        (httpx.Response(429), "rate limit exceeded", True),
    ],
)
def test_woocommerce_http_failures_are_explicit_connector_errors(monkeypatch, response, error, retryable):
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "secret")
    transport = httpx.MockTransport(lambda request: response)
    with pytest.raises(ConnectorError, match=error) as raised:
        WooCommerceClient(client=httpx.Client(transport=transport)).list_orders()
    assert raised.value.retryable is retryable


def test_woocommerce_timeout_is_an_explicit_connector_error(monkeypatch):
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "secret")

    def timeout(request):
        raise httpx.ReadTimeout("simulated timeout", request=request)

    with pytest.raises(ConnectorError, match="request timed out") as raised:
        WooCommerceClient(client=httpx.Client(transport=httpx.MockTransport(timeout))).list_orders()
    assert raised.value.retryable is True


def test_woocommerce_retries_mocked_timeout_then_succeeds(monkeypatch):
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "secret")
    monkeypatch.setenv("CONNECTOR_MAX_ATTEMPTS", "2")
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("simulated timeout", request=request)
        return httpx.Response(200, json=[])

    assert WooCommerceClient(client=httpx.Client(transport=httpx.MockTransport(handler))).list_orders() == []
    assert calls == 2


def test_hubspot_connector_searches_by_stable_id_and_verifies_write(monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "token")
    calls = []
    responses = [
        httpx.Response(200, json={"results": []}),
        httpx.Response(201, json={"id": "deal-7"}),
        httpx.Response(200, json={"results": [{
            "id": "deal-7",
            "updatedAt": "2026-10-14T10:10:00Z",
            "properties": {
                "woocrm_order_id": "42", "woocrm_email": "buyer@example.com",
                "amount": "19.95", "deal_currency_code": "USD", "woocrm_order_status": "processing",
            },
        }]}),
    ]

    def handler(request):
        calls.append((request.method, request.url.path, request.content))
        return responses.pop(0)

    adapter = HubSpotCRMAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    order = NormalizedOrder("42", "buyer@example.com", "Ada Lovelace", 19.95, "USD", "processing", "2026-10-14T10:00:00Z")
    assert adapter.find_order("42") is None
    verified = adapter.write_order(order)
    assert verified.crm_id == "deal-7"
    assert [call[0:2] for call in calls] == [
        ("POST", "/crm/v3/objects/deals/search"),
        ("POST", "/crm/v3/objects/deals"),
        ("POST", "/crm/v3/objects/deals/search"),
    ]
    assert b'"woocrm_order_id":"42"' in calls[1][2]


def test_hubspot_connector_sends_bearer_token_without_exposing_it(monkeypatch):
    token = "hubspot-secret-token"
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", token)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={"message": f"do not echo {token}"})

    adapter = HubSpotCRMAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ConnectorError) as raised:
        adapter.test_connection()

    assert requests[0].headers["Authorization"] == f"Bearer {token}"
    assert token not in str(raised.value)


def test_hubspot_mocked_authentication_failure_is_not_retried(monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "token")
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"message": "unauthorized"})

    with pytest.raises(ConnectorError, match="authentication or permission") as raised:
        HubSpotCRMAdapter(client=httpx.Client(transport=httpx.MockTransport(handler))).test_connection()
    assert raised.value.retryable is False
    assert calls == 1


def test_hubspot_retries_mocked_service_failure_then_succeeds(monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "token")
    monkeypatch.setenv("CONNECTOR_MAX_ATTEMPTS", "2")
    responses = [httpx.Response(503), httpx.Response(200, json={"results": []})]

    def handler(request):
        return responses.pop(0)

    HubSpotCRMAdapter(client=httpx.Client(transport=httpx.MockTransport(handler))).test_connection()
    assert responses == []


def test_hubspot_search_rejects_malformed_results_instead_of_missing(monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "token")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"unexpected": []}))
    adapter = HubSpotCRMAdapter(client=httpx.Client(transport=transport))
    with pytest.raises(ConnectorError, match="unexpected deal search response"):
        adapter.find_order("42")


def test_hubspot_connection_checks_deals_without_writing(monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "token")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    HubSpotCRMAdapter(client=httpx.Client(transport=httpx.MockTransport(handler))).test_connection()
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/crm/v3/objects/deals"


def test_hubspot_contact_lookup_normalizes_email(monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "token")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"results": [{"id": "contact-1"}]})

    adapter = HubSpotCRMAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert adapter.find_contact("  Buyer@Example.com ")["id"] == "contact-1"
    payload = json.loads(requests[0].content)
    assert payload["filterGroups"][0]["filters"][0]["value"] == "buyer@example.com"


def test_live_lookup_failure_is_error_not_missing(monkeypatch):
    reset()
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("CRM_PROVIDER", "hubspot")
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "secret")
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "token")

    class FakeWoo:
        def list_orders(self):
            from app.connectors import NormalizedOrder
            return [NormalizedOrder("live-1", "live@example.com", "Live Buyer", 12, "USD", "processing", "2026-10-14T10:00:00Z")]

    class FailingCRM:
        def __init__(self):
            pass

        def find_order(self, external_order_id):
            raise ConnectorError("HubSpot", "simulated lookup failure")

    monkeypatch.setattr(main, "WooCommerceClient", FakeWoo)
    monkeypatch.setattr(main, "HubSpotCRMAdapter", FailingCRM)
    assert client.post("/api/woocrm/reconcile").status_code == 200
    snapshot = client.get("/api/woocrm/dashboard").json()
    live_order = next(order for order in snapshot["orders"] if order["id"] == "live-1")
    assert live_order["state"] == "ERROR"
    assert live_order["state"] != "MISSING"
    assert client.get("/api/woocrm/orders/live-1/history").json()["events"][0]["outcome"] == "failed"


def test_live_contact_reconciliation_persists_found_not_found_and_lookup_error(monkeypatch):
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("CRM_PROVIDER", "hubspot")

    class FakeWoo:
        def list_orders(self):
            return [
                NormalizedOrder("live-contact-1", " Found@Example.com ", "Found", 12, "USD", "processing", "2026-10-14T10:00:00Z"),
                NormalizedOrder("live-contact-2", "missing@example.com", "Missing", 13, "USD", "processing", "2026-10-14T10:00:00Z"),
                NormalizedOrder("live-contact-3", "error@example.com", "Error", 14, "USD", "processing", "2026-10-14T10:00:00Z"),
            ]

    class FakeCRM:
        def __init__(self):
            pass

        def find_contact(self, email):
            if email == "found@example.com":
                return {"id": "contact-1"}
            if email == "error@example.com":
                raise ConnectorError("HubSpot", "simulated contact lookup failure")
            return None

        def find_order(self, external_order_id):
            return None

    monkeypatch.setattr(main, "WooCommerceClient", FakeWoo)
    monkeypatch.setattr(main, "HubSpotCRMAdapter", FakeCRM)
    assert client.post("/api/woocrm/reconcile").status_code == 200
    groups = {group["email"]: group for group in client.get("/api/woocrm/dashboard").json()["groups"]}
    assert groups["found@example.com"]["crm_contact_status"] == "FOUND"
    assert groups["missing@example.com"]["crm_contact_status"] == "NOT_FOUND"
    assert groups["error@example.com"]["crm_contact_status"] == "LOOKUP_ERROR"


def test_live_replay_writes_then_reconciles_with_mocked_connectors(monkeypatch):
    reset()
    monkeypatch.setenv("INTEGRATION_MODE", "live")
    monkeypatch.setenv("CRM_PROVIDER", "hubspot")
    monkeypatch.setenv("CRM_WRITE_ENABLED", "true")
    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "key")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "secret")
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "token")
    records = {}

    class FakeWoo:
        def list_orders(self):
            return [NormalizedOrder("live-2", "live@example.com", "Live Buyer", 12, "USD", "processing", "2026-10-14T10:00:00Z")]

        def test_connection(self):
            return None

    class FakeCRM:
        def test_connection(self):
            return None

        def find_order(self, external_order_id):
            return records.get(external_order_id)

        def write_order(self, order, existing=None):
            assert existing is None
            records[order.id] = NormalizedCRMOrder(
                order.id, order.id, order.customer_email, order.customer_name, order.total,
                order.currency, order.status, "deal-live-2", "2026-10-14T10:15:00Z",
            )
            return records[order.id]

    monkeypatch.setattr(main, "WooCommerceClient", FakeWoo)
    monkeypatch.setattr(main, "HubSpotCRMAdapter", FakeCRM)
    assert client.post("/api/woocrm/reconcile").status_code == 200
    response = client.post("/api/woocrm/orders/live-2/replay")
    assert response.status_code == 200
    assert client.get("/api/woocrm/dashboard").json()["orders"][0]["state"] == "SYNCED"
    event = client.get("/api/woocrm/orders/live-2/history").json()["events"][0]
    assert event["outcome"] == "verified"
    assert event["event_type"] == "replay"
    assert client.post(
        "/api/woocrm/import/orders",
        content="{not-json",
        headers={"content-type": "application/json"},
    ).status_code == 422


def test_reconciliation_does_not_repair_missing_records():
    dataset = f"rec-{uuid4().hex}"
    order = {
        "id": "missing-1", "customer_email": "missing@example.com", "customer_name": "Missing",
        "total": 10, "currency": "USD", "status": "processing", "created_at": "2026-10-30T10:00:00Z",
    }
    client.post(f"/api/woocrm/import/orders?dataset={dataset}", json=[order])
    client.post(f"/api/woocrm/reconcile?dataset={dataset}")
    snapshot = client.get(f"/api/woocrm/dashboard?dataset={dataset}").json()
    assert snapshot["counts"]["MISSING"] == 1
    assert snapshot["orders"][0]["crm"] is None


def test_simultaneous_import_retries_create_one_order():
    """The transaction and composite key make a duplicate retry harmless."""
    dataset = f"race-{uuid4().hex}"
    order = {
        "id": "once", "customer_email": "once@example.com", "customer_name": "Once",
        "total": 10, "currency": "USD", "status": "processing", "created_at": "2026-10-30T10:00:00Z",
    }

    def submit():
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(f"/api/woocrm/import/orders?dataset={dataset}", json=[order]).json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))

    assert sorted(result["inserted"] for result in results) == [0, 1]
    with db() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders WHERE dataset=? AND id='once'", (dataset,)
        ).fetchone()[0] == 1
