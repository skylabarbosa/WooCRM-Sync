from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.risk_guard import RiskSettings, evaluate_batch, evaluate_change

from app.connectors import (
    ConnectorError,
    HubSpotCRMAdapter,
    NormalizedOrder,
    WooCommerceClient,
    connector_status,
    crm_provider,
    integration_mode,
    writes_enabled,
)
from app.seed_data import seed_crm_contacts, seed_crm_orders, seed_orders

BASE_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "woocrm.db"))
ELIGIBLE_STATUSES = {"processing", "completed"}
ORDER_STATUSES = {"pending", "processing", "on-hold", "completed", "cancelled", "failed", "refunded", "checkout-draft"}
CRM_STATUSES = {"SYNCED", "ERROR"}
STATES = {"SYNCED", "MISSING", "MISMATCH", "ERROR", "NOT_ELIGIBLE"}
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}

app = FastAPI(title="WooCRM Sync", version="0.3.0")
logger = logging.getLogger(__name__)
DATASET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_IMPORT_BYTES_DEFAULT = 10 * 1024 * 1024
MAX_IMPORT_RECORDS_DEFAULT = 5000
FIELD_MAX_LENGTHS = {
    "id": 100, "order_id": 100, "customer_email": 320, "email": 320,
    "customer_name": 200, "name": 200, "currency": 3, "status": 32,
    "order_status": 32, "created_at": 64, "modified_at": 64, "updated_at": 64,
}


def _is_true(value: str | None, *, default: bool = False) -> bool:
    return (value or ("true" if default else "false")).strip().lower() in {"1", "true", "yes", "on"}


def app_env() -> str:
    return os.getenv("APP_ENV", "demo").strip().lower()


def operator_name() -> str:
    return os.getenv("OPERATOR_NAME", "operator").strip() or "operator"


def auth_token_secret() -> str:
    return os.getenv("AUTH_TOKEN_SECRET", "").strip()


def configured_users() -> dict[str, dict[str, str]]:
    raw = os.getenv("AUTH_USERS_JSON", "").strip()
    try:
        users = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AUTH_USERS_JSON must be valid JSON") from exc
    if not isinstance(users, list) or not users:
        raise RuntimeError("AUTH_USERS_JSON must contain at least one user")
    configured: dict[str, dict[str, str]] = {}
    for user in users:
        if not isinstance(user, dict):
            raise RuntimeError("AUTH_USERS_JSON entries must be objects")
        username = str(user.get("username", "")).strip()
        role = str(user.get("role", "")).strip().lower()
        password_hash = str(user.get("password_hash", "")).strip()
        if not username or role not in ROLE_RANK or not password_hash.startswith("pbkdf2_sha256$"):
            raise RuntimeError("AUTH_USERS_JSON entries require username, valid role, and PBKDF2 password_hash")
        configured[username] = {"role": role, "password_hash": password_hash}
    return configured


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt.encode()), int(iterations))
        return secrets.compare_digest(derived, base64.urlsafe_b64decode(expected.encode()))
    except (ValueError, TypeError):
        return False


def _token_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode_token_part(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_access_token(username: str, role: str) -> str:
    payload = json.dumps({"sub": username, "role": role, "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())}, separators=(",", ":")).encode()
    encoded = _token_part(payload)
    signature = _token_part(hmac.new(auth_token_secret().encode(), encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def token_identity(value: str) -> tuple[str, str] | None:
    try:
        encoded, signature = value.split(".", 1)
        expected = _token_part(hmac.new(auth_token_secret().encode(), encoded.encode(), hashlib.sha256).digest())
        if not secrets.compare_digest(signature, expected):
            return None
        payload = json.loads(_decode_token_part(encoded))
        username, role, expires = payload["sub"], payload["role"], payload["exp"]
        if not isinstance(username, str) or role not in ROLE_RANK or not isinstance(expires, int) or expires < int(datetime.now(timezone.utc).timestamp()):
            return None
        user = configured_users().get(username)
        return (username, role) if user and user["role"] == role else None
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def import_limit(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        limit = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if limit < 1:
        raise RuntimeError(f"{name} must be positive")
    return limit


def validate_dataset_name(dataset: str) -> str:
    if not DATASET_PATTERN.fullmatch(dataset):
        raise HTTPException(422, "Dataset name must match ^[a-z0-9][a-z0-9_-]{0,39}$")
    return dataset


def _redact_secrets(message: str) -> str:
    redacted = message
    for secret in (auth_token_secret(), os.getenv("HUBSPOT_ACCESS_TOKEN", "").strip(),
                   os.getenv("WOOCOMMERCE_CONSUMER_KEY", "").strip(),
                   os.getenv("WOOCOMMERCE_CONSUMER_SECRET", "").strip()):
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def connector_failure(exc: ConnectorError, operation: str) -> HTTPException:
    correlation_id = uuid.uuid4().hex[:12]
    detail = _redact_secrets(str(exc))
    logger.error("Connector failure operation=%s source=%s correlation_id=%s detail=%s",
                 operation, exc.source, correlation_id, detail)
    return HTTPException(502, f"{exc.source} request failed; reference {correlation_id}")


def validate_startup_config() -> None:
    if app_env() == "production":
        if not auth_token_secret():
            raise RuntimeError("AUTH_TOKEN_SECRET is required when APP_ENV=production")
        configured_users()


validate_startup_config()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_access_control(request: Request, call_next: Any) -> Any:
    public_paths = {"/api/woocrm/health", "/api/woocrm/ready", "/api/woocrm/auth/login"}
    if app_env() == "production" and request.url.path not in public_paths and request.method != "OPTIONS":
        required_role = "viewer" if request.method in {"GET", "HEAD"} else "operator"
        if request.url.path == "/api/woocrm/reset":
            required_role = "admin"
        scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
        identity = token_identity(supplied) if scheme.lower() == "bearer" else None
        if identity is None or ROLE_RANK[identity[1]] < ROLE_RANK[required_role]:
            return JSONResponse(status_code=401 if identity is None else 403, content={"detail": "Authentication required" if identity is None else "Insufficient role"})
    return await call_next(request)


@contextmanager
def db(*, write: bool = False) -> Any:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def eligible(order: sqlite3.Row) -> bool:
    return order["status"] in ELIGIBLE_STATUSES


def order_state(order: sqlite3.Row, crm: sqlite3.Row | None) -> str:
    if not eligible(order):
        return "NOT_ELIGIBLE"
    if crm is None:
        return "MISSING"
    if crm["status"] == "ERROR":
        return "ERROR"
    values = (
        abs(float(crm["total"]) - float(order["total"])) < 0.001,
        crm["currency"] == order["currency"],
        crm["order_status"] == order["status"],
        normalize_email(crm["email"]) == normalize_email(order["customer_email"]),
    )
    return "SYNCED" if all(values) else "MISMATCH"


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
          id TEXT NOT NULL,
          dataset TEXT NOT NULL DEFAULT 'default',
          customer_email TEXT NOT NULL, customer_name TEXT NOT NULL,
          total REAL NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, modified_at TEXT, source TEXT NOT NULL DEFAULT 'demo',
          environment TEXT NOT NULL DEFAULT 'demo', last_checked_at TEXT,
          PRIMARY KEY (dataset, id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS orders_dataset_id_unique ON orders(dataset, id);
        CREATE TABLE IF NOT EXISTS customers (
          dataset TEXT NOT NULL DEFAULT 'default', email TEXT NOT NULL, name TEXT NOT NULL,
          order_count INTEGER NOT NULL DEFAULT 0, lifetime_value REAL NOT NULL DEFAULT 0,
          crm_id TEXT, last_synced_at TEXT, PRIMARY KEY (dataset, email)
        );
        CREATE TABLE IF NOT EXISTS crm_orders (
          dataset TEXT NOT NULL DEFAULT 'default', order_id TEXT NOT NULL,
          email TEXT NOT NULL, name TEXT NOT NULL, total REAL NOT NULL,
          currency TEXT NOT NULL, status TEXT NOT NULL, order_status TEXT,
          error_message TEXT, updated_at TEXT, source TEXT NOT NULL DEFAULT 'demo',
          environment TEXT NOT NULL DEFAULT 'demo', last_checked_at TEXT,
          PRIMARY KEY (dataset, order_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS crm_orders_dataset_order_id_unique ON crm_orders(dataset, order_id);
        CREATE TABLE IF NOT EXISTS crm_contacts (
          dataset TEXT NOT NULL DEFAULT 'default', email TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('FOUND', 'NOT_FOUND', 'NOT_CHECKED', 'LOOKUP_ERROR')),
          contact_id TEXT, verified_at TEXT NOT NULL, source TEXT NOT NULL,
          PRIMARY KEY (dataset, email)
        );
        CREATE TABLE IF NOT EXISTS sync_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, dataset TEXT NOT NULL DEFAULT 'default',
          started_at TEXT NOT NULL, completed_at TEXT, processed INTEGER NOT NULL DEFAULT 0,
          created INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0,
          skipped INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS order_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          dataset TEXT NOT NULL DEFAULT 'default',
          order_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          outcome TEXT NOT NULL,
          message TEXT NOT NULL,
          error_message TEXT,
          before_values TEXT,
          after_values TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS risk_settings (
          key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS risk_evaluations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, dataset TEXT NOT NULL, order_id TEXT NOT NULL,
          field TEXT NOT NULL, risk_status TEXT NOT NULL, rule_ids TEXT NOT NULL,
          explanation TEXT NOT NULL, existing_value TEXT, proposed_value TEXT,
          evidence TEXT NOT NULL, required_action TEXT NOT NULL, evaluated_at TEXT NOT NULL,
          fingerprint TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
          approval_actor TEXT, approval_at TEXT, outcome TEXT NOT NULL DEFAULT 'flagged'
        );
        CREATE TABLE IF NOT EXISTS live_write_claims (
          dataset TEXT NOT NULL,
          order_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('in_progress', 'completed', 'failed', 'uncertain')),
          message TEXT,
          external_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (dataset, order_id)
        );
        """
    )
    for table in ("orders", "crm_orders"):
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for column, definition in (
            ("modified_at", "TEXT"),
            ("source", "TEXT NOT NULL DEFAULT 'demo'"),
            ("environment", "TEXT NOT NULL DEFAULT 'demo'"),
            ("last_checked_at", "TEXT"),
        ):
            if column not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with db(write=True) as connection:
        contact_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='crm_contacts'"
        ).fetchone()
        if contact_schema and "LOOKUP_ERROR" not in (contact_schema["sql"] or ""):
            connection.execute("ALTER TABLE crm_contacts RENAME TO legacy_crm_contacts")
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        migrated_tables: set[str] = set()
        for table in ("orders", "crm_orders", "customers", "sync_runs"):
            if table in tables:
                columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                if "dataset" not in columns:
                    connection.execute(f"ALTER TABLE {table} RENAME TO legacy_{table}")
                    migrated_tables.add(table)
        _create_schema(connection)
        if "legacy_crm_contacts" in tables:
            connection.execute(
                """INSERT OR IGNORE INTO crm_contacts(dataset,email,status,contact_id,verified_at,source)
                   SELECT dataset,email,status,contact_id,verified_at,source FROM legacy_crm_contacts"""
            )
            connection.execute("DROP TABLE legacy_crm_contacts")
        connection.executemany(
            "INSERT OR IGNORE INTO risk_settings(key,value) VALUES (?,?)",
            [
                ("absolute_total_change", "100"),
                ("percentage_total_change", "50"),
                ("batch_change_limit", "25"),
                ("newer_crm_policy", "review"),
                ("missing_timestamp_policy", "review"),
            ],
        )
        if "orders" in migrated_tables:
            connection.execute(
                """INSERT OR IGNORE INTO orders(id,customer_email,customer_name,total,currency,status,created_at)
                   SELECT CAST(id AS TEXT),customer_email,customer_name,total,currency,status,created_at FROM legacy_orders"""
            )
            connection.execute(
                """INSERT OR IGNORE INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,error_message,updated_at)
                   SELECT 'default',CAST(order_id AS TEXT),email,name,total,currency,status,order_status,error_message,updated_at
                   FROM legacy_crm_orders"""
            )
        if "customers" in migrated_tables:
            connection.execute(
                """INSERT OR IGNORE INTO customers(dataset,email,name,order_count,lifetime_value,crm_id,last_synced_at)
                   SELECT 'default',email,name,order_count,lifetime_value,crm_id,last_synced_at FROM legacy_customers"""
            )
        if "sync_runs" in migrated_tables:
            connection.execute(
                """INSERT OR IGNORE INTO sync_runs(id,dataset,started_at,completed_at,processed,created,updated,skipped,status)
                   SELECT id,'default',started_at,completed_at,processed,created,updated,skipped,status FROM legacy_sync_runs"""
            )
        for table in migrated_tables:
            connection.execute(f"DROP TABLE legacy_{table}")
        if connection.execute("SELECT COUNT(*) FROM orders WHERE dataset='default'").fetchone()[0] == 0:
            reset_data(connection)
        elif integration_mode() == "demo":
            ensure_demo_contact_outcomes(connection)


def reset_data(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM orders WHERE dataset='default'")
    connection.execute("DELETE FROM customers WHERE dataset='default'")
    connection.execute("DELETE FROM crm_orders WHERE dataset='default'")
    connection.execute("DELETE FROM crm_contacts WHERE dataset='default'")
    connection.execute("DELETE FROM sync_runs WHERE dataset='default'")
    connection.execute("DELETE FROM order_events WHERE dataset='default'")
    connection.execute("DELETE FROM risk_evaluations WHERE dataset='default'")
    connection.execute("DELETE FROM live_write_claims WHERE dataset='default'")
    connection.execute("DELETE FROM risk_settings WHERE key LIKE 'demo_%'")
    orders = seed_orders()
    connection.executemany(
        """INSERT INTO orders(id,dataset,customer_email,customer_name,total,currency,status,created_at,modified_at)
           VALUES (:id,'default',:customer_email,:customer_name,:total,:currency,:status,:created_at,:modified_at)""",
        orders,
    )
    connection.executemany(
        "INSERT INTO customers(dataset,email,name) VALUES (?,?,?)",
        [("default", order["customer_email"], order["customer_name"]) for order in orders],
    )
    connection.executemany(
        """INSERT INTO crm_contacts(dataset,email,status,contact_id,verified_at,source)
           VALUES ('default',:email,:status,:contact_id,:verified_at,:source)""",
        [{**record, "email": normalize_email(record["email"])} for record in seed_crm_contacts(orders)],
    )
    connection.executemany(
        """INSERT INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,error_message,updated_at)
           VALUES ('default',:order_id,:email,:name,:total,:currency,:status,:order_status,:error_message,:updated_at)""",
        [{**record, "error_message": record.get("error_message"), "updated_at": record.get("updated_at", now())} for record in seed_crm_orders(orders)],
    )
    connection.execute(
        "INSERT INTO sync_runs(dataset,started_at,completed_at,processed,created,updated,skipped,status) VALUES ('default','2026-10-14T16:00:00Z','2026-10-14T16:00:08Z',20,0,0,2,'completed')"
    )
    events = [
        ("1001", "reconciliation", "verified", "Demo order matched WooCommerce and CRM values.", None),
        ("1016", "replay", "failed", "Recovery attempt timed out at the CRM connector.", "Demo connector timeout"),
        ("1016", "reconciliation", "verified", "Later verification confirmed the connector recovered.", None),
        ("1013", "mismatch_correction", "completed", "A previously reviewed CRM mismatch was resolved.", None),
        ("1018", "replay", "failed", "First recovery attempt returned a transient timeout.", "Transient demo timeout"),
        ("1018", "reconciliation", "verified", "Later verification confirmed the order is synchronized.", None),
    ]
    connection.executemany(
        """INSERT INTO order_events(dataset,order_id,event_type,outcome,message,error_message,created_at)
           VALUES ('default',?,?,?,?,?,?)""",
        [(order_id, event_type, outcome, message, error, f"2026-10-14T16:{index + 10:02d}:00Z")
         for index, (order_id, event_type, outcome, message, error) in enumerate(events)],
    )
    demo_evaluations = [
        ("1013", "REVIEW_REQUIRED", ["LARGE_TOTAL_CHANGE"], "Total differs from CRM by more than the configured threshold."),
        ("1014", "REVIEW_REQUIRED", ["LARGE_TOTAL_CHANGE"], "CRM contains a reviewed total difference."),
        ("1015", "REVIEW_REQUIRED", ["LARGE_TOTAL_CHANGE"], "Large order change requires manual review."),
        ("__BATCH__", "REVIEW_REQUIRED", ["BULK_CHANGE_ANOMALY"], "Demo batch exceeds the configured change threshold."),
    ]
    for order_id, status, rule_ids, explanation in demo_evaluations:
        connection.execute(
            """INSERT INTO risk_evaluations(dataset,order_id,field,risk_status,rule_ids,explanation,
               existing_value,proposed_value,evidence,required_action,evaluated_at,fingerprint,outcome)
               VALUES ('default',?,'order',?,?,?,?,?,?,?,?,?,'flagged')""",
            (order_id, status, json.dumps(rule_ids), json.dumps([explanation]), json.dumps(None),
             json.dumps(None), json.dumps({"demo": True}), "block" if status == "BLOCKED" else "request_confirmation",
             "2026-10-14T16:00:00Z", f"demo-{order_id}"),
        )


def refresh_customer(connection: sqlite3.Connection, dataset: str, email: str, timestamp: str) -> None:
    normalized = normalize_email(email)
    rows = connection.execute(
        "SELECT * FROM orders WHERE dataset=? AND lower(trim(customer_email))=? AND status IN ('processing','completed')",
        (dataset, normalized),
    ).fetchall()
    if len(rows) < 14:
        return
    connection.execute(
        """INSERT INTO customers(dataset,email,name,order_count,lifetime_value,crm_id,last_synced_at)
           VALUES (?,?,?,?,?,?,?) ON CONFLICT(dataset,email) DO UPDATE SET name=excluded.name,
           order_count=excluded.order_count,lifetime_value=excluded.lifetime_value,
           last_synced_at=excluded.last_synced_at""",
        (dataset, normalized, rows[0]["customer_name"], len(rows), sum(row["total"] for row in rows),
         None, timestamp),
    )


def sync_order(connection: sqlite3.Connection, order: sqlite3.Row, approval_id: int | None = None) -> str:
    if not eligible(order):
        return "NOT_ELIGIBLE"
    crm = connection.execute(
        "SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (order["dataset"], order["id"])
    ).fetchone()
    enforce_risk_guard(connection, order, crm, approval_id)
    timestamp = now()
    connection.execute(
        """INSERT INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,updated_at)
           VALUES (?,?,?,?,?,?, 'SYNCED',?,?) ON CONFLICT(dataset,order_id) DO UPDATE SET
           email=excluded.email,name=excluded.name,total=excluded.total,currency=excluded.currency,
           status='SYNCED',order_status=excluded.order_status,error_message=NULL,updated_at=excluded.updated_at""",
        (order["dataset"], order["id"], normalize_email(order["customer_email"]), order["customer_name"],
         order["total"], order["currency"], order["status"], timestamp),
    )
    refresh_customer(connection, order["dataset"], order["customer_email"], timestamp)
    return "SYNCED"


def compared_values(order: sqlite3.Row, crm: sqlite3.Row | None) -> dict[str, Any]:
    return {
        "billing_email": order["customer_email"],
        "total": order["total"],
        "currency": order["currency"],
        "order_status": order["status"],
    } if crm is None else {
        "billing_email": crm["email"],
        "total": crm["total"],
        "currency": crm["currency"],
        "order_status": crm["order_status"],
    }


def record_event(
    connection: sqlite3.Connection,
    dataset: str,
    order_id: str,
    event_type: str,
    outcome: str,
    message: str,
    *,
    error_message: str | None = None,
    before_values: dict[str, Any] | None = None,
    after_values: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """INSERT INTO order_events(dataset,order_id,event_type,outcome,message,error_message,
           before_values,after_values,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (dataset, str(order_id), event_type, outcome, message, error_message,
         json.dumps(before_values) if before_values is not None else None,
         json.dumps(after_values) if after_values is not None else None, now()),
    )


class RiskBlocked(RuntimeError):
    def __init__(self, evaluation_id: int, evaluation: dict[str, Any]) -> None:
        super().__init__(f"Risk guard requires review ({evaluation_id})")
        self.evaluation_id = evaluation_id
        self.evaluation = evaluation


def risk_settings(connection: sqlite3.Connection) -> RiskSettings:
    values = {row["key"]: row["value"] for row in connection.execute("SELECT key,value FROM risk_settings")}
    try:
        return RiskSettings(
            absolute_total_change=float(values.get("absolute_total_change", 100)),
            percentage_total_change=float(values.get("percentage_total_change", 50)),
            batch_change_limit=int(values.get("batch_change_limit", 25)),
            newer_crm_policy=values.get("newer_crm_policy", "review"),
            missing_timestamp_policy=values.get("missing_timestamp_policy", "review"),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(500, "Risk guard settings are invalid") from exc


def persist_evaluation(connection: sqlite3.Connection, dataset: str, evaluation: dict[str, Any]) -> int:
    cursor = connection.execute(
        """INSERT INTO risk_evaluations(dataset,order_id,field,risk_status,rule_ids,explanation,
           existing_value,proposed_value,evidence,required_action,evaluated_at,fingerprint)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            dataset, evaluation["order_id"], evaluation["field"], evaluation["risk_status"],
            json.dumps(evaluation["rule_ids"]), json.dumps([r["explanation"] for r in evaluation["rules"]]),
            json.dumps(evaluation["existing_value"]), json.dumps(evaluation["proposed_value"]),
            json.dumps(evaluation.get("evidence", evaluation["rules"])), evaluation["required_action"], now(),
            evaluation["fingerprint"],
        ),
    )
    return int(cursor.lastrowid)


def evaluation_payload(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("rule_ids", "explanation", "existing_value", "proposed_value", "evidence"):
        result[key] = json.loads(result[key])
    result["approved"] = bool(result["approved"])
    return result


def enforce_risk_guard(
    connection: sqlite3.Connection, order: sqlite3.Row, crm: sqlite3.Row | None, approval_id: int | None = None,
) -> dict[str, Any]:
    evaluation = evaluate_change(order, crm, risk_settings(connection))
    evaluation_id = persist_evaluation(connection, order["dataset"], evaluation)
    if evaluation["risk_status"] == "CLEAR":
        return evaluation
    if evaluation["risk_status"] == "BLOCKED":
        connection.commit()
        raise RiskBlocked(evaluation_id, evaluation)
    if approval_id is not None:
        approved = connection.execute(
            "SELECT * FROM risk_evaluations WHERE id=? AND dataset=? AND order_id=? AND approved=1",
            (approval_id, order["dataset"], str(order["id"])),
        ).fetchone()
        if approved and approved["fingerprint"] == evaluation["fingerprint"]:
            return evaluation
    connection.commit()
    raise RiskBlocked(evaluation_id, evaluation)


class SyncResult(BaseModel):
    run_id: int
    processed: int
    created: int
    updated: int
    skipped: int
    message: str


class RiskSettingsPayload(BaseModel):
    absolute_total_change: float
    percentage_total_change: float
    batch_change_limit: int
    newer_crm_policy: str = "review"
    missing_timestamp_policy: str = "review"


class RiskApproval(BaseModel):
    actor: str = "operator"


class RiskBatchPayload(BaseModel):
    order_ids: list[str]


class LoginPayload(BaseModel):
    username: str
    password: str


def ensure_demo_contact_outcomes(connection: sqlite3.Connection) -> None:
    """Insert missing simulated contact outcomes without changing existing rows."""
    rows = connection.execute(
        "SELECT id,customer_email,customer_name FROM orders WHERE dataset='default' ORDER BY id"
    ).fetchall()
    if not rows:
        return
    records = seed_crm_contacts([dict(row) for row in rows])
    connection.executemany(
        """INSERT OR IGNORE INTO crm_contacts(dataset,email,status,contact_id,verified_at,source)
           VALUES ('default',:email,:status,:contact_id,:verified_at,:source)""",
        [{**record, "email": normalize_email(record["email"])} for record in records],
    )


def reconcile_demo_contacts(connection: sqlite3.Connection, orders: list[sqlite3.Row]) -> None:
    """Resolve every eligible demo customer against the seeded CRM contact set."""
    demo_contacts = {
        normalize_email(record["email"]): record
        for record in seed_crm_contacts([dict(order) for order in orders])
    }
    checked_at = now()
    checked_emails = {
        normalize_email(order["customer_email"])
        for order in orders
        if eligible(order)
    }
    for email in checked_emails:
        contact = demo_contacts.get(email)
        connection.execute(
            """INSERT INTO crm_contacts(dataset,email,status,contact_id,verified_at,source)
               VALUES ('default',?,?,?,?, 'demo')
               ON CONFLICT(dataset,email) DO UPDATE SET status=excluded.status,
               contact_id=excluded.contact_id,verified_at=excluded.verified_at,source=excluded.source""",
            (email, "FOUND" if contact and contact["status"] == "FOUND" else "NOT_FOUND",
             contact.get("contact_id") if contact else None, checked_at),
        )


def run_sync(dataset: str = "default") -> SyncResult:
    if integration_mode() == "live":
        return run_live_sync(dataset)
    with db(write=True) as connection:
        if dataset == "default":
            ensure_demo_contact_outcomes(connection)
        run_id = connection.execute("INSERT INTO sync_runs(dataset,started_at,status) VALUES (?,?,'running')", (dataset, now())).lastrowid
        orders = connection.execute("SELECT * FROM orders WHERE dataset=? ORDER BY id", (dataset,)).fetchall()
        if dataset == "default":
            reconcile_demo_contacts(connection, orders)
        touched: set[str] = set()
        skipped = 0
        for order in orders:
            if eligible(order):
                touched.add(order["customer_email"])
            else:
                skipped += 1
            if eligible(order):
                refresh_customer(connection, dataset, order["customer_email"], now())
            crm = connection.execute(
                "SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order["id"])
            ).fetchone()
            record_event(
                connection, dataset, order["id"], "reconciliation", "completed",
                f"Compared WooCommerce and CRM values; result: {order_state(order, crm)}",
                before_values=compared_values(order, crm),
            )
        processed = len(orders)
        connection.execute(
            "UPDATE sync_runs SET completed_at=?,processed=?,created=0,updated=0,skipped=?,status='completed' WHERE id=?",
            (now(), processed, skipped, run_id),
        )
    return SyncResult(run_id=run_id, processed=processed, created=0, updated=0, skipped=skipped,
                      message="Reconciliation completed; mismatches require explicit update")


def run_live_sync(dataset: str) -> SyncResult:
    """Fetch both external systems and reconcile only the selected dataset."""
    started = now()
    try:
        woo = WooCommerceClient()
        orders = woo.list_orders()
        if crm_provider() != "hubspot":
            raise ConnectorError("CRM", f"Unsupported live CRM provider: {crm_provider()}")
        crm = HubSpotCRMAdapter()
    except ConnectorError as exc:
        with db(write=True) as connection:
            run_id = connection.execute(
                "INSERT INTO sync_runs(dataset,started_at,completed_at,status) VALUES (?,?,?,'error')",
                (dataset, started, now()),
            ).lastrowid
            record_event(connection, dataset, "*", "reconciliation", "failed", "Live reconciliation could not start.", error_message=f"{exc.source}: {exc}")
        raise connector_failure(exc, "live reconciliation startup") from exc

    processed = skipped = 0
    find_contact = getattr(crm, "find_contact", None)
    verified_contacts: dict[str, dict[str, Any]] = {}
    fetched: list[dict[str, Any]] = []
    for order in orders:
        checked = now()
        normalized_email = normalize_email(order.customer_email)
        if callable(find_contact) and normalized_email not in verified_contacts:
            try:
                contact = find_contact(normalized_email)
            except ConnectorError as exc:
                verified_contacts[normalized_email] = {"status": "LOOKUP_ERROR", "error": exc}
                logger.warning("CRM contact lookup failed source=%s email=%s detail=%s",
                               exc.source, normalized_email, _redact_secrets(str(exc)))
            else:
                verified_contacts[normalized_email] = {
                    "status": "FOUND" if contact else "NOT_FOUND",
                    "contact_id": str(contact.get("id")) if isinstance(contact, dict) and contact.get("id") else None,
                }
        try:
            fetched.append({"order": order, "checked": checked, "crm": crm.find_order(order.id)})
        except (ConnectorError, ValueError) as exc:
            fetched.append({"order": order, "checked": checked, "error": exc})

    with db(write=True) as connection:
        run_id = connection.execute("INSERT INTO sync_runs(dataset,started_at,status) VALUES (?,?,'running')", (dataset, started)).lastrowid
        for result in fetched:
            order = result["order"]
            checked = result["checked"]
            connection.execute(
                """INSERT INTO orders(id,dataset,customer_email,customer_name,total,currency,status,created_at,source,environment,last_checked_at)
                   VALUES (?,?,?,?,?,?,?,?, 'woocommerce','live',?)
                   ON CONFLICT(dataset,id) DO UPDATE SET customer_email=excluded.customer_email,
                   customer_name=excluded.customer_name,total=excluded.total,currency=excluded.currency,
                   status=excluded.status,created_at=excluded.created_at,source='woocommerce',
                   environment='live',last_checked_at=excluded.last_checked_at""",
                (order.id, dataset, order.customer_email, order.customer_name, order.total, order.currency,
                 order.status, order.created_at, checked),
            )
            processed += 1
            if not eligible(connection.execute("SELECT * FROM orders WHERE dataset=? AND id=?", (dataset, order.id)).fetchone()):
                skipped += 1
                continue
            normalized_email = normalize_email(order.customer_email)
            contact = verified_contacts.get(normalized_email)
            if contact:
                error = contact.get("error")
                connection.execute(
                    """INSERT INTO crm_contacts(dataset,email,status,contact_id,verified_at,source)
                       VALUES (?,?,?,?,?,'hubspot')
                       ON CONFLICT(dataset,email) DO UPDATE SET status=excluded.status,
                       contact_id=excluded.contact_id,verified_at=excluded.verified_at,source=excluded.source""",
                    (dataset, normalized_email, contact["status"], contact.get("contact_id"), checked),
                )
            error = result.get("error")
            if error is None:
                found = result["crm"]
                if found is None:
                    connection.execute("DELETE FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order.id))
                else:
                    connection.execute(
                        """INSERT INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,
                           error_message,updated_at,source,environment,last_checked_at)
                           VALUES (?,?,?,?,?,?, 'SYNCED',?,NULL,?,'hubspot','live',?)
                           ON CONFLICT(dataset,order_id) DO UPDATE SET email=excluded.email,name=excluded.name,
                           total=excluded.total,currency=excluded.currency,order_status=excluded.order_status,
                           status='SYNCED',error_message=NULL,updated_at=excluded.updated_at,source='hubspot',
                           environment='live',last_checked_at=excluded.last_checked_at""",
                        (dataset, order.id, found.email, found.name, found.total, found.currency,
                         found.order_status, found.updated_at or checked, checked),
                    )
                current = connection.execute("SELECT * FROM orders WHERE dataset=? AND id=?", (dataset, order.id)).fetchone()
                current_crm = connection.execute("SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order.id)).fetchone()
                record_event(connection, dataset, order.id, "reconciliation", "completed",
                             f"Compared live WooCommerce and HubSpot values; result: {order_state(current, current_crm)}",
                             before_values=compared_values(current, current_crm))
            else:
                message = _redact_secrets(
                    f"{error.source}: {error}" if isinstance(error, ConnectorError) else f"HubSpot: {error}"
                )
                connection.execute(
                    """INSERT INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,
                       error_message,updated_at,source,environment,last_checked_at)
                       VALUES (?,?,?,?,?,?, 'ERROR',NULL,?,?, 'hubspot','live',?)
                       ON CONFLICT(dataset,order_id) DO UPDATE SET status='ERROR',error_message=excluded.error_message,
                       source='hubspot',environment='live',last_checked_at=excluded.last_checked_at""",
                    (dataset, order.id, order.customer_email, order.customer_name, order.total, order.currency,
                     message, checked, checked),
                )
                record_event(connection, dataset, order.id, "reconciliation", "failed",
                             "Live CRM lookup failed.", error_message=message)
        connection.execute(
            "UPDATE sync_runs SET completed_at=?,processed=?,skipped=?,status='completed' WHERE id=?",
            (now(), processed, skipped, run_id),
        )
    return SyncResult(run_id=run_id, processed=processed, created=0, updated=0, skipped=skipped,
                      message="Live reconciliation completed; values were retrieved from WooCommerce and HubSpot")


def snapshot(dataset: str = "default") -> dict[str, Any]:
    with db() as connection:
        orders = []
        for row in connection.execute("SELECT * FROM orders WHERE dataset=? ORDER BY id", (dataset,)).fetchall():
            item = dict(row)
            crm = connection.execute(
                "SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, row["id"])
            ).fetchone()
            item["state"] = order_state(row, crm)
            item["crm"] = dict(crm) if crm else None
            item["id"] = int(item["id"]) if item["id"].isdigit() else item["id"]
            orders.append(item)
        customers = [dict(row) for row in connection.execute("SELECT * FROM customers WHERE dataset=? ORDER BY name", (dataset,))]
        contacts = {
            normalize_email(row["email"]): dict(row)
            for row in connection.execute("SELECT * FROM crm_contacts WHERE dataset=?", (dataset,)).fetchall()
        }
        activities = {
            row["email"]: row["last_activity"]
            for row in connection.execute(
                """SELECT lower(trim(o.customer_email)) AS email,
                          MAX(COALESCE(e.created_at, c.updated_at, o.modified_at, o.created_at)) AS last_activity
                   FROM orders o
                   LEFT JOIN crm_orders c ON c.dataset=o.dataset AND c.order_id=o.id
                   LEFT JOIN order_events e ON e.dataset=o.dataset AND e.order_id=o.id
                   WHERE o.dataset=? AND o.status IN ('processing','completed')
                   GROUP BY lower(trim(o.customer_email))""",
                (dataset,),
            ).fetchall()
        }
        last = connection.execute("SELECT * FROM sync_runs WHERE dataset=? ORDER BY id DESC LIMIT 1", (dataset,)).fetchone()
    groups: dict[str, dict[str, Any]] = {}
    for order in (o for o in orders if o["state"] != "NOT_ELIGIBLE"):
        key = normalize_email(order["customer_email"])
        group = groups.setdefault(key, {
            "email": key, "name": order["customer_name"], "order_count": 0, "lifetime_value": 0,
            "synced_count": 0, "attention_count": 0, "attention_details": [],
        })
        group["order_count"] += 1
        group["lifetime_value"] += order["total"]
        if order["state"] == "SYNCED":
            group["synced_count"] += 1
        else:
            group["attention_count"] += 1
            group["attention_details"].append(f"Order #{order['id']}: {order['state']}")
    for key, group in groups.items():
        contact = contacts.get(key)
        group["crm_contact_status"] = contact["status"] if contact else "NOT_CHECKED"
        group["crm_contact_id"] = contact["contact_id"] if contact else None
        group["crm_contact_verified_at"] = contact["verified_at"] if contact else None
        group["last_activity"] = activities.get(key)
        group["sync_state"] = "NEEDS_ATTENTION" if group["attention_count"] else "SYNCED"
    contact_counts = {
        "FOUND": sum(group["crm_contact_status"] == "FOUND" for group in groups.values()),
        "NOT_FOUND": sum(group["crm_contact_status"] == "NOT_FOUND" for group in groups.values()),
        "NOT_CHECKED": sum(group["crm_contact_status"] == "NOT_CHECKED" for group in groups.values()),
        "LOOKUP_ERROR": sum(group["crm_contact_status"] == "LOOKUP_ERROR" for group in groups.values()),
    }
    counts = {state: sum(o["state"] == state for o in orders) for state in STATES}
    return {"orders": orders, "customers": customers, "eligible_order_count": sum(o["state"] != "NOT_ELIGIBLE" for o in orders),
            "eligible_customer_count": len(groups), "groups": list(groups.values()), "contact_counts": contact_counts,
            "customer_attention_count": sum(group["attention_count"] > 0 for group in groups.values()),
            "counts": counts,
            "last_run": dict(last) if last else None}


def parse_import(body: bytes, content_type: str, format_name: str | None) -> list[dict[str, Any]]:
    try:
        if (format_name or "").lower() == "csv" or "text/csv" in content_type:
            reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""), strict=True)
            if reader.fieldnames is None:
                raise ValueError("CSV must include a header row")
            if None in reader.fieldnames:
                raise ValueError("CSV contains an empty header")
            records = list(reader)
            if any(None in record for record in records):
                raise ValueError("CSV contains a row with more fields than its header")
            return records
        payload = json.loads(body)
        records = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise ValueError("JSON must be an array of records or an object with a records array")
        return records
    except (UnicodeDecodeError, csv.Error, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"Invalid import document: {exc}") from exc


def validate_records(records: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    required = {"id", "customer_email", "customer_name", "total", "currency", "status", "created_at"} if source == "woo" else {
        "order_id", "email", "name", "total", "currency", "status", "order_status"
    }
    validated = []
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise HTTPException(422, f"Record {index} must be an object")
        missing = sorted(required - record.keys())
        if missing:
            raise HTTPException(422, f"Record {index} is missing required fields: {', '.join(missing)}")
        for field, value in record.items():
            maximum = FIELD_MAX_LENGTHS.get(field)
            if maximum is not None and (not isinstance(value, str) or len(value) > maximum):
                raise HTTPException(422, f"Record {index} field '{field}' exceeds the maximum length of {maximum}")
        identifier = record["id"] if source == "woo" else record["order_id"]
        if not isinstance(identifier, (str, int)) or not str(identifier).strip():
            raise HTTPException(422, f"Record {index} has an invalid identifier")
        email_field = "customer_email" if source == "woo" else "email"
        if not isinstance(record[email_field], str) or not EMAIL_PATTERN.fullmatch(record[email_field].strip()):
            raise HTTPException(422, f"Record {index} field '{email_field}' is not a valid email address")
        try:
            total = float(record["total"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"Record {index} total must be numeric") from exc
        if not math.isfinite(total) or total < 0 or len(str(record["currency"]).strip()) != 3:
            raise HTTPException(422, f"Record {index} has invalid currency or amount")
        status = str(record["status"]).strip()
        if status not in (ORDER_STATUSES if source == "woo" else CRM_STATUSES):
            raise HTTPException(422, f"Record {index} has unsupported {source} status: {status}")
        timestamp_fields = ("created_at", "modified_at") if source == "woo" else ("updated_at",)
        for field in timestamp_fields:
            value = record.get(field)
            if value is not None:
                if not isinstance(value, str):
                    raise HTTPException(422, f"Record {index} field '{field}' must be an ISO timestamp")
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise HTTPException(422, f"Record {index} field '{field}' must be an ISO timestamp") from exc
        if source == "woo":
            validated.append({**record, "id": str(identifier).strip(), "total": total, "currency": str(record["currency"]).upper(), "status": status})
        else:
            order_status = str(record["order_status"]).strip()
            if order_status not in ORDER_STATUSES:
                raise HTTPException(422, f"Record {index} has unsupported CRM order status: {order_status}")
            validated.append({**record, "order_id": str(identifier).strip(), "total": total, "currency": str(record["currency"]).upper(), "status": status})
    return validated


def import_records(records: list[dict[str, Any]], source: str, dataset: str) -> dict[str, Any]:
    table = "orders" if source == "woo" else "crm_orders"
    identifier_column = "id" if source == "woo" else "order_id"
    inserted = 0
    skipped = 0
    with db(write=True) as connection:
        accepted: dict[str, dict[str, Any]] = {}
        for record in records:
            identifier = str(record["id"] if source == "woo" else record["order_id"])
            normalized = (
                {"id": identifier, "customer_email": record["customer_email"], "customer_name": record["customer_name"],
                 "total": record["total"], "currency": record["currency"], "status": record["status"], "created_at": record["created_at"]}
                if source == "woo" else
                {"order_id": identifier, "email": normalize_email(record["email"]), "name": record["name"],
                 "total": record["total"], "currency": record["currency"], "status": record["status"],
                 "order_status": record["order_status"]}
            )
            prior = accepted.get(identifier)
            if prior is not None:
                if prior != normalized:
                    raise HTTPException(409, f"Conflicting {source} records for identifier {identifier}")
                skipped += 1
                continue
            accepted[identifier] = normalized
            existing = connection.execute(
                f"SELECT * FROM {table} WHERE dataset=? AND {identifier_column}=?",
                (dataset, identifier),
            ).fetchone()
            if existing:
                if any(existing[key] != value for key, value in normalized.items()):
                    raise HTTPException(409, f"Conflicting {source} record for identifier {identifier}")
                skipped += 1
                continue
            if source == "woo":
                connection.execute(
                    """INSERT INTO orders(id,dataset,customer_email,customer_name,total,currency,status,created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (record["id"], dataset, record["customer_email"], record["customer_name"], record["total"],
                     record["currency"], record["status"], record["created_at"]),
                )
            else:
                connection.execute(
                    """INSERT INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,error_message,updated_at)
                       VALUES (?,?,?,?,?,?,?,? ,NULL,?)""",
                    (dataset, record["order_id"], normalize_email(record["email"]), record["name"], record["total"],
                     record["currency"], record["status"], record["order_status"], now()),
                )
            inserted += 1
    return {
        "imported": inserted,
        "inserted": inserted,
        "skipped": skipped,
        "rejected": 0,
        "source": source,
        "dataset": dataset,
        "message": f"Imported {inserted} {source} record(s); skipped {skipped} existing record(s)",
    }


init_db()


@app.get("/api/woocrm/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "woocrm-sync"}


@app.post("/api/woocrm/auth/login")
def login(payload: LoginPayload) -> dict[str, str]:
    if app_env() != "production":
        raise HTTPException(404, "Authentication is only enabled in production")
    user = configured_users().get(payload.username.strip())
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": issue_access_token(payload.username.strip(), user["role"]), "token_type": "bearer", "role": user["role"]}


@app.get("/api/woocrm/ready")
def ready() -> JSONResponse:
    try:
        with db(write=True) as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/api/woocrm/config")
def config() -> dict[str, Any]:
    return connector_status()


@app.get("/api/woocrm/datasets")
def datasets() -> dict[str, Any]:
    with db() as connection:
        names = {
            row["dataset"]
            for table in ("orders", "crm_orders", "customers", "sync_runs")
            for row in connection.execute(f"SELECT DISTINCT dataset FROM {table}")
        }
        result = []
        for dataset in sorted(names):
            order_count = connection.execute("SELECT COUNT(*) FROM orders WHERE dataset=?", (dataset,)).fetchone()[0]
            crm_count = connection.execute("SELECT COUNT(*) FROM crm_orders WHERE dataset=?", (dataset,)).fetchone()[0]
            customer_count = connection.execute("SELECT COUNT(*) FROM customers WHERE dataset=?", (dataset,)).fetchone()[0]
            last_run = connection.execute(
                "SELECT completed_at, status FROM sync_runs WHERE dataset=? ORDER BY id DESC LIMIT 1", (dataset,)
            ).fetchone()
            source = connection.execute(
                "SELECT source, environment FROM orders WHERE dataset=? GROUP BY source, environment ORDER BY COUNT(*) DESC LIMIT 1",
                (dataset,),
            ).fetchone()
            result.append({
                "name": dataset,
                "order_count": order_count,
                "crm_record_count": crm_count,
                "customer_count": customer_count,
                "source": source["source"] if source else "unknown",
                "environment": source["environment"] if source else "unknown",
                "last_run": dict(last_run) if last_run else None,
                "resettable": dataset == "default",
            })
    return {"datasets": result}


@app.get("/api/woocrm/risk-guard")
@app.get("/api/woocrm/risk-guard/evaluations")
def risk_guard(dataset: str = Query("default"), status: str | None = Query(None), rule: str | None = Query(None)) -> dict[str, Any]:
    with db() as connection:
        query = "SELECT * FROM risk_evaluations WHERE dataset=?"
        parameters: list[Any] = [dataset]
        if status:
            query += " AND risk_status=?"
            parameters.append(status)
        query += " ORDER BY id DESC"
        rows = [evaluation_payload(row) for row in connection.execute(query, parameters).fetchall()]
        settings = risk_settings(connection).__dict__
    if rule:
        rows = [row for row in rows if rule in row["rule_ids"]]
    return {"evaluations": rows, "count": len(rows), "settings": settings}


@app.get("/api/woocrm/risk-guard/settings")
def get_risk_settings() -> dict[str, Any]:
    with db() as connection:
        return risk_settings(connection).__dict__


@app.post("/api/woocrm/risk-guard/batch")
def evaluate_risk_batch(payload: RiskBatchPayload, dataset: str = Query("default")) -> dict[str, Any]:
    requested = list(dict.fromkeys(str(order_id) for order_id in payload.order_ids))
    with db() as connection:
        affected = []
        for order_id in requested:
            order = find_order(connection, dataset, order_id)
            if not order or not eligible(order):
                continue
            crm = connection.execute("SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order_id)).fetchone()
            if order_state(order, crm) != "SYNCED":
                affected.append(order_id)
        result = evaluate_batch(len(affected), risk_settings(connection))
        if result["risk_status"] != "CLEAR":
            result["order_ids"] = affected
            result["evaluated_at"] = now()
    return result


@app.put("/api/woocrm/risk-guard/settings")
def update_risk_settings(payload: RiskSettingsPayload) -> dict[str, Any]:
    if not math.isfinite(payload.absolute_total_change) or payload.absolute_total_change < 0:
        raise HTTPException(422, "absolute_total_change must be finite and non-negative")
    if not math.isfinite(payload.percentage_total_change) or payload.percentage_total_change < 0:
        raise HTTPException(422, "percentage_total_change must be finite and non-negative")
    if payload.batch_change_limit < 1 or payload.newer_crm_policy not in {"review", "block"} or payload.missing_timestamp_policy not in {"review", "allow"}:
        raise HTTPException(422, "Risk settings contain unsupported values")
    with db(write=True) as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO risk_settings(key,value) VALUES (?,?)",
            [(key, str(value)) for key, value in payload.model_dump().items()],
        )
    return {**payload.model_dump(), "actor": operator_name()}


@app.post("/api/woocrm/risk-guard/evaluations/{evaluation_id}/approve")
def approve_risk_evaluation(evaluation_id: int, payload: RiskApproval) -> dict[str, Any]:
    actor = operator_name()
    with db(write=True) as connection:
        row = connection.execute("SELECT * FROM risk_evaluations WHERE id=?", (evaluation_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Risk evaluation not found")
        if row["risk_status"] == "BLOCKED":
            raise HTTPException(409, "Blocked evaluations cannot be approved")
        connection.execute(
            "UPDATE risk_evaluations SET approved=1,approval_actor=?,approval_at=?,outcome='approved' WHERE id=?",
            (actor, now(), evaluation_id),
        )
        return evaluation_payload(connection.execute("SELECT * FROM risk_evaluations WHERE id=?", (evaluation_id,)).fetchone())


@app.post("/api/woocrm/risk-guard/evaluations/{evaluation_id}/reject")
def reject_risk_evaluation(evaluation_id: int, payload: RiskApproval) -> dict[str, Any]:
    actor = operator_name()
    with db(write=True) as connection:
        if not connection.execute("SELECT 1 FROM risk_evaluations WHERE id=?", (evaluation_id,)).fetchone():
            raise HTTPException(404, "Risk evaluation not found")
        connection.execute("UPDATE risk_evaluations SET outcome='rejected',approval_actor=?,approval_at=? WHERE id=?", (actor, now(), evaluation_id))
    return {"evaluation_id": evaluation_id, "outcome": "rejected", "actor": actor}


@app.post("/api/woocrm/test-connection")
def test_connection() -> dict[str, Any]:
    status = connector_status()
    if status["mode"] == "demo":
        return {**status, "connection": "verified", "message": "Demo connectors are available locally"}
    try:
        WooCommerceClient().test_connection()
        if crm_provider() != "hubspot":
            raise ConnectorError("CRM", f"Unsupported live CRM provider: {crm_provider()}")
        HubSpotCRMAdapter().test_connection()
    except ConnectorError as exc:
        raise connector_failure(exc, "connection test") from exc
    return {**status, "configured": True, "connection": "verified", "message": "WooCommerce and HubSpot connections verified"}


@app.get("/api/woocrm/dashboard")
def dashboard(dataset: str = Query("default")) -> dict[str, Any]:
    return {**snapshot(dataset), "integration": connector_status()}


@app.get("/api/woocrm/orders/{order_id}/history")
def order_history(order_id: str, dataset: str = Query("default")) -> dict[str, Any]:
    with db() as connection:
        if not find_order(connection, dataset, order_id):
            raise HTTPException(404, "Order not found")
        events = []
        for row in connection.execute(
            "SELECT * FROM order_events WHERE dataset=? AND order_id=? ORDER BY id DESC",
            (dataset, str(order_id)),
        ).fetchall():
            event = dict(row)
            event["before_values"] = json.loads(event["before_values"]) if event["before_values"] else None
            event["after_values"] = json.loads(event["after_values"]) if event["after_values"] else None
            events.append(event)
    return {"order_id": order_id, "dataset": dataset, "events": events}


@app.post("/api/woocrm/sync", response_model=SyncResult)
def sync(dataset: str = Query("default")) -> SyncResult:
    return run_sync(dataset)


@app.post("/api/woocrm/reconcile", response_model=SyncResult)
def reconcile(dataset: str = Query("default")) -> SyncResult:
    return run_sync(dataset)


@app.post("/api/woocrm/reset")
def reset() -> dict[str, str]:
    if not _is_true(os.getenv("DEMO_RESET_ENABLED"), default=app_env() == "demo"):
        raise HTTPException(403, "Demo reset is disabled")
    with db(write=True) as connection:
        reset_data(connection)
    return {"message": "Demo data reset"}


@app.post("/api/woocrm/failure")
def failure() -> dict[str, str]:
    with db(write=True) as connection:
        row = connection.execute("SELECT * FROM crm_orders WHERE dataset='default' ORDER BY order_id DESC LIMIT 1").fetchone()
        if not row:
            raise HTTPException(409, "No CRM records available")
        connection.execute("UPDATE crm_orders SET status='ERROR',error_message='Mock CRM failure' WHERE dataset=? AND order_id=?", (row["dataset"], row["order_id"]))
    return {"message": "Mock CRM failure enabled"}


@app.post("/api/woocrm/import/{source}")
async def import_source(source: str, request: Request, dataset: str = Query("default"), format_name: str | None = Query(None, alias="format")) -> dict[str, Any]:
    if source not in {"orders", "crm-orders"}:
        raise HTTPException(404, "Import source must be orders or crm-orders")
    dataset = validate_dataset_name(dataset)
    max_bytes = import_limit("MAX_IMPORT_BYTES", MAX_IMPORT_BYTES_DEFAULT)
    max_records = import_limit("MAX_IMPORT_RECORDS", MAX_IMPORT_RECORDS_DEFAULT)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(413, f"Import exceeds the {max_bytes}-byte limit")
        except ValueError as exc:
            raise HTTPException(422, "Content-Length must be a valid integer") from exc
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_bytes:
            raise HTTPException(413, f"Import exceeds the {max_bytes}-byte limit")
        chunks.append(chunk)
    records = parse_import(b"".join(chunks), request.headers.get("content-type", ""), format_name)
    if len(records) > max_records:
        raise HTTPException(413, f"Import contains more than the {max_records}-record limit")
    records = validate_records(records, "woo" if source == "orders" else "crm")
    return import_records(records, "woo" if source == "orders" else "crm", dataset)


def find_order(connection: sqlite3.Connection, dataset: str, order_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM orders WHERE dataset=? AND id=?", (dataset, str(order_id))).fetchone()


def live_write_action(order_id: str, dataset: str, event_type: str, approval_id: int | None = None) -> dict[str, Any]:
    action_label = "Replay" if event_type == "replay" else "Mismatch correction"
    with db() as connection:
        order = find_order(connection, dataset, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        crm = connection.execute(
            "SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order["id"])
        ).fetchone()
        state = order_state(order, crm)
        allowed = {"MISSING", "ERROR"} if event_type == "replay" else {"MISMATCH"}
        if state not in allowed:
            reason = f"{action_label} is only allowed for {', '.join(sorted(allowed))}; current state is {state}"
            record_event(connection, dataset, order_id, event_type, "blocked", f"{action_label} was not run.", error_message=reason)
            connection.commit()
            raise HTTPException(409, reason)
        if order["environment"] != "live" or order["source"] != "woocommerce":
            reason = "Live CRM writes are restricted to orders fetched from WooCommerce in live mode"
            record_event(connection, dataset, order_id, event_type, "blocked", f"{action_label} was not run.", error_message=reason)
            connection.commit()
            raise HTTPException(409, reason)

        status = connector_status()
        if not status["configured"] or not status.get("field_mapping_configured", False):
            reason = "Live CRM writes are blocked until connector configuration and field mapping are verified"
            blocked_reason = reason
            before = compared_values(order, crm)
            current_order = dict(order)
            current_crm = dict(crm) if crm else None
            # The audit event is written below, after this read transaction closes.
            pass
        elif not writes_enabled():
            reason = "Live CRM writes are disabled; set CRM_WRITE_ENABLED=true only after verification"
            blocked_reason = reason
            before = compared_values(order, crm)
            current_order = dict(order)
            current_crm = dict(crm) if crm else None
            pass
        else:
            blocked_reason = None
            before = compared_values(order, crm)
            current_order = dict(order)
            current_crm = dict(crm) if crm else None
    if blocked_reason is not None:
        with db(write=True) as connection:
            record_event(connection, dataset, order_id, event_type, "blocked", f"{action_label} was not run.", error_message=blocked_reason)
        raise HTTPException(409, blocked_reason)

    try:
        woo = WooCommerceClient()
        crm_adapter = HubSpotCRMAdapter()
        woo.test_connection()
        crm_adapter.test_connection()
        external = crm_adapter.find_order(str(order_id))
        if event_type == "mismatch_correction" and external is None:
            raise ConnectorError("HubSpot", "Mismatch correction requires the existing CRM record to be found")
        normalized = NormalizedOrder(
            id=str(current_order["id"]),
            customer_email=normalize_email(current_order["customer_email"]),
            customer_name=current_order["customer_name"],
            total=float(current_order["total"]),
            currency=current_order["currency"],
            status=current_order["status"],
            created_at=current_order["created_at"],
        )
    except (ConnectorError, ValueError) as exc:
        message = _redact_secrets(f"{exc.source}: {exc}" if isinstance(exc, ConnectorError) else str(exc))
        with db(write=True) as connection:
            checked = now()
            connection.execute(
                """INSERT INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,
                   error_message,updated_at,source,environment,last_checked_at)
                   VALUES (?,?,?,?,?,?, 'ERROR',NULL,?,?, 'hubspot','live',?)
                   ON CONFLICT(dataset,order_id) DO UPDATE SET status='ERROR',error_message=excluded.error_message,
                   source='hubspot',environment='live',last_checked_at=excluded.last_checked_at""",
                (dataset, order_id, normalize_email(current_order["customer_email"]), current_order["customer_name"],
                 current_order["total"], current_order["currency"], message, checked, checked),
            )
            connection.execute(
                """INSERT INTO live_write_claims(dataset,order_id,event_type,status,message,created_at,updated_at)
                   VALUES (?,?,?,'failed',?,?,?) ON CONFLICT(dataset,order_id) DO UPDATE SET
                   event_type=excluded.event_type,status='failed',message=excluded.message,updated_at=excluded.updated_at""",
                (dataset, order_id, event_type, message, checked, checked),
            )
            record_event(connection, dataset, order_id, event_type, "failed", f"{action_label} was not verified.", error_message=message)
        if isinstance(exc, ConnectorError):
            raise connector_failure(exc, f"live {event_type}") from exc
        raise HTTPException(502, f"{action_label} failed: {message}") from exc

    try:
        with db(write=True) as connection:
            current = find_order(connection, dataset, order_id)
            current_crm_row = connection.execute(
                "SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order_id)
            ).fetchone()
            if not current or order_state(current, current_crm_row) not in (
                {"MISSING", "ERROR"} if event_type == "replay" else {"MISMATCH"}
            ):
                raise HTTPException(409, f"{action_label} is no longer allowed because the order state changed")
            enforce_risk_guard(connection, current, external, approval_id)
            claim = connection.execute(
                "SELECT * FROM live_write_claims WHERE dataset=? AND order_id=?", (dataset, order_id)
            ).fetchone()
            if claim and claim["status"] in {"in_progress", "uncertain"}:
                raise HTTPException(409, "A live CRM write for this order is already in progress or requires reconciliation")
            if claim and claim["status"] == "completed":
                return {"state": "SYNCED", "message": f"{action_label} was already completed for order {order_id}"}
            timestamp = now()
            connection.execute(
                """INSERT INTO live_write_claims(dataset,order_id,event_type,status,created_at,updated_at)
                   VALUES (?,?,?,'in_progress',?,?) ON CONFLICT(dataset,order_id) DO UPDATE SET
                   event_type=excluded.event_type,status='in_progress',message=NULL,updated_at=excluded.updated_at""",
                (dataset, order_id, event_type, timestamp, timestamp),
            )
            current_order = dict(current)
            normalized = NormalizedOrder(
                id=str(current["id"]),
                customer_email=normalize_email(current["customer_email"]),
                customer_name=current["customer_name"],
                total=float(current["total"]),
                currency=current["currency"],
                status=current["status"],
                created_at=current["created_at"],
            )
            before = compared_values(current, current_crm_row)
    except RiskBlocked as exc:
        with db(write=True) as connection:
            record_event(connection, dataset, order_id, event_type, "blocked",
                         f"{action_label} was not run because the risk guard blocked it.", error_message=str(exc))
        raise HTTPException(409, {"message": str(exc), "evaluation_id": exc.evaluation_id, "evaluation": exc.evaluation})

    write_started = False
    try:
        write_started = True
        verified = crm_adapter.write_order(normalized, external)
        checked_external = crm_adapter.find_order(str(order_id))
        if checked_external is None:
            raise ConnectorError("HubSpot", f"{action_label} completed but fresh verification found no CRM record")
        if checked_external.external_id != verified.external_id:
            raise ConnectorError("HubSpot", f"{action_label} verification returned a different CRM record")
        with db(write=True) as connection:
            current = find_order(connection, dataset, order_id)
            if not current:
                raise ConnectorError("SQLite", "WooCommerce order disappeared before live write persistence")
            connection.execute(
                """INSERT INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,
                   error_message,updated_at,source,environment,last_checked_at)
                   VALUES (?,?,?,?,?,?, 'SYNCED',?,NULL,?,'hubspot','live',?)
                   ON CONFLICT(dataset,order_id) DO UPDATE SET email=excluded.email,name=excluded.name,
                   total=excluded.total,currency=excluded.currency,status='SYNCED',order_status=excluded.order_status,
                   error_message=NULL,updated_at=excluded.updated_at,source='hubspot',environment='live',
                   last_checked_at=excluded.last_checked_at""",
                (dataset, order_id, checked_external.email, checked_external.name, checked_external.total,
                 checked_external.currency, checked_external.order_status, checked_external.updated_at or now(), now()),
            )
            after = connection.execute("SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order_id)).fetchone()
            if order_state(current, after) != "SYNCED":
                raise ConnectorError("SQLite", f"{action_label} completed but persisted verification returned {order_state(current, after)}")
            timestamp = now()
            connection.execute(
                "UPDATE live_write_claims SET status='completed',message=?,external_id=?,updated_at=? WHERE dataset=? AND order_id=?",
                (f"{action_label} completed and verified", checked_external.external_id, timestamp, dataset, order_id),
            )
            record_event(connection, dataset, order_id, event_type, "verified",
                         f"{action_label} completed and a fresh CRM lookup verified consistency.",
                         before_values=before, after_values=compared_values(current, after))
        return {"state": "SYNCED", "message": f"{action_label} completed for order {order_id} and verified"}
    except (ConnectorError, ValueError) as exc:
        message = _redact_secrets(f"{exc.source}: {exc}" if isinstance(exc, ConnectorError) else str(exc))
        with db(write=True) as connection:
            status = "uncertain" if write_started else "failed"
            connection.execute(
                "UPDATE live_write_claims SET status=?,message=?,updated_at=? WHERE dataset=? AND order_id=?",
                (status, message, now(), dataset, order_id),
            )
            connection.execute(
                """INSERT INTO crm_orders(dataset,order_id,email,name,total,currency,status,order_status,
                   error_message,updated_at,source,environment,last_checked_at)
                   VALUES (?,?,?,?,?,?, 'ERROR',NULL,?,?, 'hubspot','live',?)
                   ON CONFLICT(dataset,order_id) DO UPDATE SET status='ERROR',error_message=excluded.error_message,
                   source='hubspot',environment='live',last_checked_at=excluded.last_checked_at""",
                (dataset, order_id, normalize_email(current_order["customer_email"]), current_order["customer_name"],
                 current_order["total"], current_order["currency"], message, now(), now()),
            )
            record_event(connection, dataset, order_id, event_type, "failed", f"{action_label} was not verified.", error_message=message)
        if isinstance(exc, ConnectorError):
            raise connector_failure(exc, f"live {event_type}") from exc
        raise HTTPException(502, f"{action_label} failed: {message}") from exc


@app.post("/api/woocrm/orders/{order_id}/replay")
def replay(order_id: str, dataset: str = Query("default"), approval_id: int | None = Query(None)) -> dict[str, Any]:
    if integration_mode() == "live":
        return live_write_action(order_id, dataset, "replay", approval_id)
    blocked_reason: str | None = None
    failure: HTTPException | None = None
    with db(write=True) as connection:
        order = find_order(connection, dataset, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        crm = connection.execute("SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order["id"])).fetchone()
        state = order_state(order, crm)
        if state not in {"MISSING", "ERROR"}:
            blocked_reason = f"Replay is only allowed for MISSING or recoverable ERROR; current state is {state}"
            record_event(connection, dataset, order_id, "replay", "blocked", "Replay was not run.", error_message=blocked_reason)
        else:
            try:
                result = sync_order(connection, order) if approval_id is None else sync_order(connection, order, approval_id)
                after = connection.execute("SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order["id"])).fetchone()
                verified_state = order_state(order, after)
                if verified_state != "SYNCED":
                    raise HTTPException(502, f"Replay write completed but fresh verification returned {verified_state}")
                record_event(
                    connection, dataset, order_id, "replay", "verified",
                    "Replay completed and a fresh comparison verified consistency.",
                    before_values=compared_values(order, crm),
                    after_values=compared_values(order, after),
                )
                return {"state": result, "message": f"Order {order_id} replayed and verified"}
            except HTTPException as exc:
                record_event(connection, dataset, order_id, "replay", "failed", "Replay was not applied.", error_message=str(exc.detail))
                failure = exc
            except RiskBlocked as exc:
                record_event(connection, dataset, order_id, "replay", "blocked", "Replay was held by the risk guard.", error_message=str(exc))
                failure = HTTPException(409, {"message": str(exc), "evaluation_id": exc.evaluation_id, "evaluation": exc.evaluation})
            except Exception as exc:
                record_event(connection, dataset, order_id, "replay", "failed", "Replay was not applied.", error_message=str(exc))
                failure = HTTPException(502, "Replay failed while communicating with the simulated CRM")
    if failure is not None:
        raise failure
    if blocked_reason is not None:
        raise HTTPException(409, blocked_reason)
    raise HTTPException(500, "Replay did not produce a result")


@app.post("/api/woocrm/orders/{order_id}/update")
def update_mismatch(order_id: str, dataset: str = Query("default"), approval_id: int | None = Query(None)) -> dict[str, Any]:
    if integration_mode() == "live":
        return live_write_action(order_id, dataset, "mismatch_correction", approval_id)
    try:
        with db(write=True) as connection:
            order = find_order(connection, dataset, order_id)
            if not order:
                raise HTTPException(404, "Order not found")
            crm = connection.execute("SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order["id"])).fetchone()
            if order_state(order, crm) != "MISMATCH":
                raise HTTPException(409, "Order is not mismatched")
            before = compared_values(order, crm)
            sync_order(connection, order, approval_id)
            after = connection.execute("SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order["id"])).fetchone()
            verified_state = order_state(order, after)
            if verified_state != "SYNCED":
                raise HTTPException(502, f"CRM update completed but fresh verification returned {verified_state}")
            record_event(
                connection, dataset, order_id, "mismatch_correction", "verified",
                "CRM values were updated from WooCommerce and a fresh comparison verified consistency.",
                before_values=before, after_values=compared_values(order, after),
            )
        return {"state": "SYNCED", "message": f"CRM updated from WooCommerce for order {order_id} and verified"}
    except HTTPException as exc:
        with db(write=True) as connection:
            if find_order(connection, dataset, order_id):
                record_event(connection, dataset, order_id, "mismatch_correction", "failed", "Mismatch correction was not applied.", error_message=str(exc.detail))
        raise
    except RiskBlocked as exc:
        with db(write=True) as connection:
            record_event(connection, dataset, order_id, "mismatch_correction", "blocked", "Mismatch correction was held by the risk guard.", error_message=str(exc))
        raise HTTPException(409, {"message": str(exc), "evaluation_id": exc.evaluation_id, "evaluation": exc.evaluation})


@app.post("/api/woocrm/orders/{order_id}/mismatch")
def create_mismatch(order_id: str, dataset: str = Query("default")) -> dict[str, str]:
    if integration_mode() == "live":
        raise HTTPException(409, "Demo mismatch injection is unavailable in live mode")
    with db(write=True) as connection:
        order = find_order(connection, dataset, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        crm = connection.execute("SELECT * FROM crm_orders WHERE dataset=? AND order_id=?", (dataset, order["id"])).fetchone()
        if not crm:
            sync_order(connection, order)
        connection.execute("UPDATE crm_orders SET total=total+1 WHERE dataset=? AND order_id=?", (dataset, order["id"]))
    return {"message": "A demo CRM mismatch was introduced"}
