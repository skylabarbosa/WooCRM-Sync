import math

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app, db
from app.risk_guard import RiskSettings, evaluate_batch, evaluate_change

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "risk-test.db")
    main.init_db()
    assert client.post("/api/woocrm/reset").status_code == 200


def order(**changes):
    return {
        "id": "1", "total": 100, "currency": "USD", "status": "processing",
        "modified_at": "2026-10-14T10:00:00+00:00", **changes,
    }


def crm(**changes):
    return {
        "total": 100, "currency": "USD", "updated_at": "2026-10-14T09:00:00+00:00", **changes,
    }


def test_normal_change_is_clear():
    assert evaluate_change(order(total=101), crm(), RiskSettings()).get("risk_status") == "CLEAR"


def test_large_total_and_zero_value_are_safe():
    result = evaluate_change(order(total=125), crm(total=0), RiskSettings(absolute_total_change=20))
    assert result["risk_status"] == "REVIEW_REQUIRED"
    assert result["percentage_difference"] is None
    assert "LARGE_TOTAL_CHANGE" in result["rule_ids"]


def test_invalid_and_nonfinite_totals_are_blocked():
    for value in (-1, "nope", math.inf, math.nan):
        result = evaluate_change(order(total=value), crm(), RiskSettings())
        assert result["risk_status"] == "BLOCKED"
        assert "INVALID_TOTAL" in result["rule_ids"]


def test_currency_change_never_compares_amounts():
    result = evaluate_change(order(total=999, currency="EUR"), crm(total=10), RiskSettings())
    assert result["risk_status"] == "REVIEW_REQUIRED"
    assert "CURRENCY_CHANGED" in result["rule_ids"]
    assert result["absolute_difference"] is None


def test_newer_crm_and_missing_timestamps_are_conservative():
    newer = evaluate_change(order(), crm(updated_at="2026-10-14T11:00:00+00:00"), RiskSettings())
    assert "NEWER_CRM_VALUE" in newer["rule_ids"]
    missing = evaluate_change({key: value for key, value in order().items() if key != "modified_at"}, crm(), RiskSettings())
    assert "UNTRUSTWORTHY_TIMESTAMPS" in missing["rule_ids"]


def test_bulk_rule_reports_no_baseline_when_unavailable():
    result = evaluate_batch(4, RiskSettings(batch_change_limit=3))
    assert result["risk_status"] == "REVIEW_REQUIRED"
    assert result["evidence"]["historical_baseline"] is None


def test_approval_is_specific_and_stale_records_are_rejected():
    with db() as connection:
        connection.execute("UPDATE risk_settings SET value='0' WHERE key='absolute_total_change'")
        connection.execute("UPDATE crm_orders SET total=total+1 WHERE order_id='1001'")
    response = client.post("/api/woocrm/orders/1001/update")
    assert response.status_code == 409
    evaluation_id = response.json()["detail"]["evaluation_id"]
    assert client.post(f"/api/woocrm/risk-guard/evaluations/{evaluation_id}/approve", headers={"x-actor": "tester"}, json={"actor": "tester"}).status_code == 200
    with db() as connection:
        connection.execute("UPDATE crm_orders SET total=total+2 WHERE order_id='1001'")
    stale = client.post(f"/api/woocrm/orders/1001/update?approval_id={evaluation_id}")
    assert stale.status_code == 409


def test_batch_endpoint_counts_actual_affected_orders():
    result = client.post("/api/woocrm/risk-guard/batch", json={"order_ids": ["1001", "1002", "missing"]})
    assert result.status_code == 200
    assert result.json()["evidence"]["proposed_change_count"] == 0
