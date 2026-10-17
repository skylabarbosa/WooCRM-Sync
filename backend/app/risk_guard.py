"""Deterministic, connector-independent risk evaluation for CRM changes."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RiskSettings:
    absolute_total_change: float = 100.0
    percentage_total_change: float = 50.0
    batch_change_limit: int = 25
    newer_crm_policy: str = "review"
    missing_timestamp_policy: str = "review"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _get(value: Any, key: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(key, default)
    try:
        return value[key]
    except (KeyError, IndexError, TypeError):
        return getattr(value, key, default)


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def fingerprint(order: Any, crm: Any | None) -> str:
    payload = {
        "order_id": str(_get(order, "id")),
        "order_total": _get(order, "total"),
        "order_currency": _get(order, "currency"),
        "order_status": _get(order, "status"),
        "order_modified_at": _get(order, "modified_at"),
        "crm_total": _get(crm, "total"),
        "crm_currency": _get(crm, "currency"),
        "crm_updated_at": _get(crm, "updated_at"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def evaluate_change(order: Any, crm: Any | None, settings: RiskSettings) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    proposed_total = _number(_get(order, "total"))
    existing_total = _number(_get(crm, "total")) if crm else None
    if proposed_total is None or proposed_total < 0 or (existing_total is not None and existing_total < 0):
        rules.append({
            "id": "INVALID_TOTAL",
            "explanation": "Order totals must be finite, numeric, and non-negative.",
            "evidence": {"existing_total": existing_total, "proposed_total": proposed_total},
            "status": "BLOCKED",
        })
    currency = str(_get(order, "currency") or "").strip().upper()
    existing_currency = str(_get(crm, "currency") or "").strip().upper() if crm else None
    if len(currency) != 3 or (existing_currency is not None and len(existing_currency) != 3):
        rules.append({
            "id": "INVALID_CURRENCY",
            "explanation": "A valid three-letter currency code is required.",
            "evidence": {"existing_currency": existing_currency, "proposed_currency": currency},
            "status": "BLOCKED",
        })
    elif crm and currency != existing_currency:
        rules.append({
            "id": "CURRENCY_CHANGED",
            "explanation": "The proposed currency differs from the CRM currency; amounts were not compared across currencies.",
            "evidence": {
                "existing_currency": existing_currency, "proposed_currency": currency,
                "existing_amount": existing_total, "proposed_amount": proposed_total,
            },
            "status": "REVIEW_REQUIRED",
        })
    absolute_difference = None
    percentage_difference = None
    if crm and proposed_total is not None and existing_total is not None and currency == existing_currency:
        absolute_difference = abs(proposed_total - existing_total)
        if existing_total != 0:
            percentage_difference = absolute_difference / abs(existing_total) * 100
        if absolute_difference >= settings.absolute_total_change or (
            percentage_difference is not None and percentage_difference >= settings.percentage_total_change
        ):
            rules.append({
                "id": "LARGE_TOTAL_CHANGE",
                "explanation": "The order total exceeds a configured absolute or percentage change threshold.",
                "evidence": {
                    "existing_total": existing_total, "proposed_total": proposed_total,
                    "absolute_difference": absolute_difference, "percentage_difference": percentage_difference,
                    "absolute_threshold": settings.absolute_total_change,
                    "percentage_threshold": settings.percentage_total_change,
                },
                "status": "REVIEW_REQUIRED",
            })
    if crm:
        source_timestamp_available = isinstance(order, dict) or (
            hasattr(order, "keys") and "modified_at" in order.keys()
        )
        source_timestamp = _timestamp(_get(order, "modified_at")) if source_timestamp_available else None
        crm_timestamp = _timestamp(_get(crm, "updated_at"))
        if source_timestamp_available and crm_timestamp and source_timestamp and crm_timestamp > source_timestamp:
            rules.append({
                "id": "NEWER_CRM_VALUE",
                "explanation": "The CRM record is newer than the incoming source record.",
                "evidence": {
                    "field": "order",
                    "crm_updated_at": _get(crm, "updated_at"),
                    "source_modified_at": _get(order, "modified_at"),
                },
                "status": "BLOCKED" if settings.newer_crm_policy == "block" else "REVIEW_REQUIRED",
            })
        elif source_timestamp_available and settings.missing_timestamp_policy == "review" and (
            not crm_timestamp or not source_timestamp
        ):
            rules.append({
                "id": "UNTRUSTWORTHY_TIMESTAMPS",
                "explanation": "Comparable source and CRM timestamps are unavailable for a potentially destructive update.",
                "evidence": {"crm_updated_at": _get(crm, "updated_at"), "source_modified_at": source_timestamp},
                "status": "REVIEW_REQUIRED",
            })
    highest = "CLEAR"
    if any(rule["status"] == "BLOCKED" for rule in rules):
        highest = "BLOCKED"
    elif rules:
        highest = "REVIEW_REQUIRED"
    return {
        "risk_status": highest,
        "rule_ids": [rule["id"] for rule in rules],
        "rules": rules,
        "order_id": str(_get(order, "id")),
        "field": "order",
        "existing_value": {"total": existing_total, "currency": existing_currency} if crm else None,
        "proposed_value": {"total": proposed_total, "currency": currency},
        "absolute_difference": absolute_difference,
        "percentage_difference": percentage_difference,
        "required_action": "proceed" if highest == "CLEAR" else ("block" if highest == "BLOCKED" else "request_confirmation"),
        "fingerprint": fingerprint(order, crm),
    }


def evaluate_batch(change_count: int, settings: RiskSettings, *, baseline: int | None = None) -> dict[str, Any]:
    evidence: dict[str, Any] = {"proposed_change_count": change_count, "configured_limit": settings.batch_change_limit}
    if baseline is not None:
        evidence["historical_baseline"] = baseline
    else:
        evidence["historical_baseline"] = None
    flagged = change_count > settings.batch_change_limit or (baseline is not None and change_count > baseline * 2)
    return {
        "risk_status": "REVIEW_REQUIRED" if flagged else "CLEAR",
        "rule_ids": ["BULK_CHANGE_ANOMALY"] if flagged else [],
        "rules": [{
            "id": "BULK_CHANGE_ANOMALY",
            "explanation": "The proposed batch exceeds the configured change limit." if baseline is None else "The proposed batch is unusually large compared with the historical baseline.",
            "evidence": evidence,
            "status": "REVIEW_REQUIRED",
        }] if flagged else [],
        "required_action": "request_confirmation" if flagged else "proceed",
        "evidence": evidence,
    }
