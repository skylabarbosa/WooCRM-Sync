from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "woocrm.db"))

app = FastAPI(title="WooCRM Sync", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def db() -> Any:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_orders() -> list[dict[str, Any]]:
    customers = [
        ("maya@example.com", "Maya Chen", "maya@example.com"),
        ("liam@example.com", "Liam Carter", "liam@example.com"),
        ("sofia@example.com", "Sofia Rossi", "sofia@example.com"),
        ("noah@example.com", "Noah Williams", "noah@example.com"),
        ("maya@example.com", "Maya Chen", "maya@example.com"),
        ("ava@example.com", "Ava Patel", "ava@example.com"),
        ("liam@example.com", "Liam Carter", "liam@example.com"),
        ("ethan@example.com", "Ethan Brown", "ethan@example.com"),
        ("sofia@example.com", "Sofia Rossi", "sofia@example.com"),
        ("olivia@example.com", "Olivia Martin", "olivia@example.com"),
    ]
    statuses = ["processing", "completed", "pending", "processing", "completed", "completed", "cancelled", "processing", "completed", "on-hold"]
    return [
        {
            "id": index + 1001,
            "customer_email": email,
            "customer_name": name,
            "total": float([129, 82.5, 45, 210, 67, 315, 99, 156, 74, 188][index]),
            "currency": "USD",
            "status": statuses[index],
            "created_at": f"2026-10-{index + 1:02d}T10:00:00Z",
        }
        for index, (email, name, _) in enumerate(customers)
    ]


def init_db() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY, customer_email TEXT NOT NULL, customer_name TEXT NOT NULL,
                total REAL NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS customers (
                email TEXT PRIMARY KEY, name TEXT NOT NULL, order_count INTEGER NOT NULL DEFAULT 0,
                lifetime_value REAL NOT NULL DEFAULT 0, crm_id TEXT, last_synced_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, completed_at TEXT,
                processed INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'running'
            );
            """
        )
        if connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO orders VALUES (:id,:customer_email,:customer_name,:total,:currency,:status,:created_at)",
                seed_orders(),
            )
        if connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO customers(email,name,order_count,lifetime_value) VALUES (?,?,?,?)",
                [
                    ("maya@example.com", "Maya Chen", 2, 196),
                    ("liam@example.com", "Liam Carter", 1, 82.5),
                    ("legacy@example.com", "Legacy Contact", 0, 0),
                ],
            )


def eligible(order: sqlite3.Row) -> bool:
    return order["status"] in {"processing", "completed"} and order["total"] > 0


def snapshot() -> dict[str, Any]:
    with db() as connection:
        orders = [dict(row) for row in connection.execute("SELECT * FROM orders ORDER BY id")]
        customers = [dict(row) for row in connection.execute("SELECT * FROM customers ORDER BY name")]
        last_run = connection.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    eligible_orders = [order for order in orders if order["status"] in {"processing", "completed"} and order["total"] > 0]
    groups: dict[str, dict[str, Any]] = {}
    for order in eligible_orders:
        group = groups.setdefault(order["customer_email"], {"email": order["customer_email"], "name": order["customer_name"], "order_count": 0, "lifetime_value": 0})
        group["order_count"] += 1
        group["lifetime_value"] += order["total"]
    return {
        "orders": orders,
        "customers": customers,
        "eligible_order_count": len(eligible_orders),
        "eligible_customer_count": len(groups),
        "last_run": dict(last_run) if last_run else None,
    }


class SyncResult(BaseModel):
    run_id: int
    processed: int
    created: int
    updated: int
    skipped: int
    message: str


def run_sync() -> SyncResult:
    started = now()
    with db() as connection:
        cursor = connection.execute("INSERT INTO sync_runs(started_at) VALUES (?)", (started,))
        run_id = cursor.lastrowid
        orders = connection.execute("SELECT * FROM orders ORDER BY id").fetchall()
        groups: dict[str, dict[str, Any]] = {}
        skipped = 0
        for order in orders:
            if not eligible(order):
                skipped += 1
                continue
            group = groups.setdefault(order["customer_email"], {"name": order["customer_name"], "order_count": 0, "lifetime_value": 0})
            group["order_count"] += 1
            group["lifetime_value"] += order["total"]
        created = updated = 0
        for email, group in groups.items():
            existing = connection.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
            if existing:
                changed = existing["order_count"] != group["order_count"] or abs(existing["lifetime_value"] - group["lifetime_value"]) > 0.001 or existing["name"] != group["name"]
                connection.execute(
                    "UPDATE customers SET name=?,order_count=?,lifetime_value=?,crm_id=COALESCE(crm_id,?),last_synced_at=? WHERE email=?",
                    (group["name"], group["order_count"], group["lifetime_value"], f"crm_{email.split('@')[0]}", started, email),
                )
                updated += int(changed)
            else:
                connection.execute(
                    "INSERT INTO customers(email,name,order_count,lifetime_value,crm_id,last_synced_at) VALUES (?,?,?,?,?,?)",
                    (email, group["name"], group["order_count"], group["lifetime_value"], f"crm_{email.split('@')[0]}", started),
                )
                created += 1
        processed = len(orders)
        connection.execute(
            "UPDATE sync_runs SET completed_at=?,processed=?,created=?,updated=?,skipped=?,status='completed' WHERE id=?",
            (now(), processed, created, updated, skipped, run_id),
        )
    return SyncResult(run_id=run_id, processed=processed, created=created, updated=updated, skipped=skipped, message="Sync completed idempotently")


init_db()


@app.get("/api/woocrm/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "woocrm-sync"}


@app.get("/api/woocrm/dashboard")
def dashboard() -> dict[str, Any]:
    return snapshot()


@app.post("/api/woocrm/sync", response_model=SyncResult)
def sync() -> SyncResult:
    return run_sync()


@app.post("/api/woocrm/reconcile", response_model=SyncResult)
def reconcile() -> SyncResult:
    return run_sync()


@app.post("/api/woocrm/reset")
def reset() -> dict[str, str]:
    with db() as connection:
        connection.execute("DELETE FROM orders")
        connection.execute("DELETE FROM customers")
        connection.execute("DELETE FROM sync_runs")
        connection.executemany(
            "INSERT INTO orders VALUES (:id,:customer_email,:customer_name,:total,:currency,:status,:created_at)",
            seed_orders(),
        )
        connection.executemany(
            "INSERT INTO customers(email,name,order_count,lifetime_value) VALUES (?,?,?,?)",
            [("maya@example.com", "Maya Chen", 2, 196), ("liam@example.com", "Liam Carter", 1, 82.5), ("legacy@example.com", "Legacy Contact", 0, 0)],
        )
    return {"message": "Demo data reset"}


@app.post("/api/woocrm/orders/{order_id}/mismatch")
def create_mismatch(order_id: int) -> dict[str, str]:
    with db() as connection:
        order = connection.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        connection.execute("UPDATE customers SET lifetime_value=lifetime_value+1 WHERE email=?", (order["customer_email"],))
    return {"message": "A demo CRM mismatch was introduced"}
