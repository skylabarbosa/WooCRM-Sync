"""External data-source connectors used by WooCRM Sync.

Connectors return the application's small normalised record shape.  They do
not know about SQLite or reconciliation state, which keeps live failures
separate from the demo adapter.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class ConnectorError(RuntimeError):
    def __init__(self, source: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.source = source
        self.retryable = retryable


@dataclass(frozen=True)
class NormalizedOrder:
    id: str
    customer_email: str
    customer_name: str
    total: float
    currency: str
    status: str
    created_at: str
    modified_at: str | None = None


@dataclass(frozen=True)
class NormalizedCRMOrder:
    order_id: str
    external_id: str
    email: str
    name: str
    total: float
    currency: str
    order_status: str | None
    crm_id: str
    updated_at: str | None = None


class OrderConnector(Protocol):
    def list_orders(self, *, modified_after: str | None = None) -> list[NormalizedOrder]: ...

    def test_connection(self) -> None: ...


class CRMConnector(Protocol):
    def find_order(self, external_order_id: str) -> NormalizedCRMOrder | None: ...

    def test_connection(self) -> None: ...

    def write_order(self, order: NormalizedOrder, existing: NormalizedCRMOrder | None = None) -> NormalizedCRMOrder: ...


def integration_mode() -> str:
    return os.getenv("INTEGRATION_MODE", "demo").strip().lower()


def crm_provider() -> str:
    return os.getenv("CRM_PROVIDER", "mock").strip().lower()


def writes_enabled() -> bool:
    return os.getenv("CRM_WRITE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def hubspot_field_mapping() -> dict[str, str]:
    return {
        "order_id": os.getenv("HUBSPOT_ORDER_ID_PROPERTY", "woocrm_order_id").strip(),
        "email": os.getenv("HUBSPOT_EMAIL_PROPERTY", "woocrm_email").strip(),
        "total": os.getenv("HUBSPOT_TOTAL_PROPERTY", "amount").strip(),
        "currency": os.getenv("HUBSPOT_CURRENCY_PROPERTY", "deal_currency_code").strip(),
        "order_status": os.getenv("HUBSPOT_STATUS_PROPERTY", "woocrm_order_status").strip(),
    }


def _error(response: httpx.Response, source: str) -> ConnectorError:
    if response.status_code in {401, 403}:
        return ConnectorError(source, f"{source} authentication or permission check failed ({response.status_code})")
    if response.status_code == 429:
        return ConnectorError(source, f"{source} rate limit exceeded", retryable=True)
    if response.status_code >= 500:
        return ConnectorError(source, f"{source} service error ({response.status_code})", retryable=True)
    return ConnectorError(source, f"{source} request failed ({response.status_code})")


class WooCommerceClient:
    source = "WooCommerce"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        store = os.getenv("WOOCOMMERCE_STORE_URL", "").strip().rstrip("/")
        key = os.getenv("WOOCOMMERCE_CONSUMER_KEY", "").strip()
        secret = os.getenv("WOOCOMMERCE_CONSUMER_SECRET", "").strip()
        if not store or not key or not secret:
            raise ConnectorError(self.source, "WooCommerce credentials are not configured")
        self._url = f"{store}/wp-json/wc/v3/orders"
        self._auth = (key, secret)
        self._client = client or httpx.Client(timeout=20.0)

    def _get(self, params: dict[str, Any]) -> httpx.Response:
        try:
            response = self._client.get(self._url, params=params, auth=self._auth)
        except httpx.TimeoutException as exc:
            raise ConnectorError(self.source, "WooCommerce request timed out", retryable=True) from exc
        except httpx.RequestError as exc:
            raise ConnectorError(self.source, "WooCommerce service is unavailable", retryable=True) from exc
        if response.status_code >= 400:
            raise _error(response, self.source)
        return response

    def test_connection(self) -> None:
        self._get({"per_page": 1})

    def list_orders(self, *, modified_after: str | None = None) -> list[NormalizedOrder]:
        records: list[NormalizedOrder] = []
        page = 1
        while True:
            params: dict[str, Any] = {"per_page": 100, "page": page, "orderby": "date", "order": "desc"}
            if modified_after:
                params["modified_after"] = modified_after
            try:
                payload = self._get(params).json()
            except ValueError as exc:
                raise ConnectorError(self.source, "WooCommerce returned malformed JSON") from exc
            if not isinstance(payload, list):
                raise ConnectorError(self.source, "WooCommerce returned an unexpected orders response")
            for item in payload:
                if not isinstance(item, dict) or "id" not in item:
                    raise ConnectorError(self.source, "WooCommerce returned an invalid order record")
                billing = item.get("billing") or {}
                if not isinstance(billing, dict):
                    raise ConnectorError(self.source, "WooCommerce returned an invalid billing record")
                try:
                    total = float(item.get("total"))
                except (TypeError, ValueError) as exc:
                    raise ConnectorError(self.source, "WooCommerce returned an invalid amount") from exc
                if not math.isfinite(total) or len(str(item.get("currency") or "").strip()) != 3:
                    raise ConnectorError(self.source, "WooCommerce returned invalid currency or amount")
                records.append(
                    NormalizedOrder(
                        id=str(item["id"]),
                        customer_email=str(billing.get("email") or "").strip().lower(),
                        customer_name=" ".join(
                            part for part in (billing.get("first_name"), billing.get("last_name")) if part
                        ),
                        total=total,
                        currency=str(item["currency"]).upper(),
                        status=str(item.get("status") or ""),
                        created_at=str(item.get("date_created") or ""),
                        modified_at=str(item.get("date_modified") or "") or None,
                    )
                )
            if len(payload) < 100:
                return records
            page += 1


class HubSpotCRMAdapter:
    source = "HubSpot"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        token = os.getenv("HUBSPOT_ACCESS_TOKEN", "").strip()
        if not token:
            raise ConnectorError(self.source, "HubSpot access token is not configured")
        self._token = token
        self._client = client or httpx.Client(timeout=20.0)
        self._base = "https://api.hubapi.com"

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            headers = dict(kwargs.pop("headers", {}))
            headers["Authorization"] = f"Bearer {self._token}"
            response = self._client.request(method, f"{self._base}{path}", headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise ConnectorError(self.source, "HubSpot request timed out", retryable=True) from exc
        except httpx.RequestError as exc:
            raise ConnectorError(self.source, "HubSpot service is unavailable", retryable=True) from exc
        if response.status_code >= 400:
            raise _error(response, self.source)
        return response

    def test_connection(self) -> None:
        mapping = self._properties()
        self._request(
            "GET",
            "/crm/v3/objects/deals",
            params={"limit": 1, "properties": list(mapping.values())},
        )

    def _properties(self) -> dict[str, str]:
        mapping = hubspot_field_mapping()
        if not all(mapping.values()):
            raise ConnectorError(self.source, "HubSpot field mapping is incomplete")
        return mapping

    def find_contact(self, email: str) -> dict[str, Any] | None:
        response = self._request(
            "POST",
            "/crm/v3/objects/contacts/search",
            json={
                "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email.strip().lower()}]}],
                "properties": ["email", "firstname", "lastname"],
                "limit": 1,
            },
        )
        payload = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return results[0] if results else None

    def find_order(self, external_order_id: str) -> NormalizedCRMOrder | None:
        mapping = self._properties()
        response = self._request(
            "POST",
            "/crm/v3/objects/deals/search",
            json={
                "filterGroups": [{"filters": [{"propertyName": mapping["order_id"], "operator": "EQ", "value": external_order_id}]}],
                "properties": list(mapping.values()),
                "limit": 1,
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorError(self.source, "HubSpot returned malformed JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ConnectorError(self.source, "HubSpot returned an unexpected deal search response")
        results = payload["results"]
        if not results:
            return None
        item = results[0]
        if not isinstance(item, dict) or not isinstance(item.get("properties"), dict):
            raise ConnectorError(self.source, "HubSpot returned an invalid deal record")
        properties = item["properties"]
        try:
            total = float(properties.get(mapping["total"]) or 0)
        except (TypeError, ValueError) as exc:
            raise ConnectorError(self.source, "HubSpot returned an invalid amount") from exc
        crm_id = str(item.get("id") or "")
        if not crm_id or not properties.get(mapping["order_id"]):
            raise ConnectorError(self.source, "HubSpot returned an incomplete deal record")
        return NormalizedCRMOrder(
            order_id=external_order_id,
            external_id=str(properties.get(mapping["order_id"]) or external_order_id),
            email=str(properties.get(mapping["email"]) or ""),
            name="",
            total=total,
            currency=str(properties.get(mapping["currency"]) or "").upper(),
            order_status=properties.get(mapping["order_status"]),
            crm_id=crm_id,
            updated_at=item.get("updatedAt"),
        )

    def write_order(self, order: NormalizedOrder, existing: NormalizedCRMOrder | None = None) -> NormalizedCRMOrder:
        mapping = self._properties()
        properties = {
            mapping["order_id"]: order.id,
            mapping["email"]: order.customer_email,
            mapping["total"]: f"{order.total:g}",
            mapping["currency"]: order.currency,
            mapping["order_status"]: order.status,
        }
        if existing is None:
            self._request("POST", "/crm/v3/objects/deals", json={"properties": properties})
        else:
            if not existing.crm_id:
                raise ConnectorError(self.source, "HubSpot record has no stable CRM ID for update")
            self._request("PATCH", f"/crm/v3/objects/deals/{existing.crm_id}", json={"properties": properties})
        verified = self.find_order(order.id)
        if verified is None:
            raise ConnectorError(self.source, "HubSpot write completed but the record could not be fetched for verification")
        return verified


def connector_status() -> dict[str, Any]:
    mode = integration_mode()
    provider = crm_provider() if mode == "live" else "mock"
    woo_configured = all(
        os.getenv(name, "").strip()
        for name in ("WOOCOMMERCE_STORE_URL", "WOOCOMMERCE_CONSUMER_KEY", "WOOCOMMERCE_CONSUMER_SECRET")
    )
    crm_configured = provider == "hubspot" and bool(os.getenv("HUBSPOT_ACCESS_TOKEN", "").strip())
    return {
        "mode": mode if mode in {"demo", "live"} else "demo",
        "provider": provider,
        "writes_enabled": writes_enabled() if mode == "live" else False,
        "configured": woo_configured and crm_configured if mode == "live" else True,
        "field_mapping_configured": all(hubspot_field_mapping().values()) if mode == "live" and provider == "hubspot" else True,
    }
