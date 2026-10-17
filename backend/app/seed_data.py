from __future__ import annotations

from typing import Any


def seed_orders() -> list[dict[str, Any]]:
    people = [
        ("maya.chen@example.test", "Maya Chen"),
        ("liam.carter@example.test", "Liam Carter"),
        ("sofia.rossi@example.test", "Sofia Rossi"),
        ("noah.williams@example.test", "Noah Williams"),
        ("ava.patel@example.test", "Ava Patel"),
        ("ethan.brown@example.test", "Ethan Brown"),
        ("olivia.martin@example.test", "Olivia Martin"),
        ("harper.lee@example.test", "Harper Lee"),
        ("jackson.reed@example.test", "Jackson Reed"),
        ("isla.morgan@example.test", "Isla Morgan"),
        ("lucas.silva@example.test", "Lucas Silva"),
        ("riley.nguyen@example.test", "Riley Nguyen"),
        ("chloe.adams@example.test", "Chloe Adams"),
        ("benjamin.kim@example.test", "Benjamin Kim"),
        ("elena.garcia@example.test", "Elena Garcia"),
        ("mason.wright@example.test", "Mason Wright"),
        ("nora.johnson@example.test", "Nora Johnson"),
        ("owen.thompson@example.test", "Owen Thompson"),
        ("piper.evans@example.test", "Piper Evans"),
        ("samuel.hall@example.test", "Samuel Hall"),
    ]
    totals = [129, 82.5, 45, 210, 67, 315, 99, 156, 74, 188, 42, 236, 55, 148, 92, 275, 64, 119, 81, 173]
    statuses = (["processing"] * 18) + ["cancelled", "failed"]
    return [
        {
            "id": str(index + 1001),
            "customer_email": email,
            "customer_name": name,
            "total": float(totals[index]),
            "currency": "USD" if index not in (4, 8, 14, 18) else "EUR",
            "status": statuses[index],
            "created_at": f"2026-10-{index + 1:02d}T10:00:00Z",
            "modified_at": f"2026-10-{index + 1:02d}T12:00:00Z",
        }
        for index, (email, name) in enumerate(people)
    ]


def seed_crm_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for order in orders[:8]:
        records.append({
            "order_id": order["id"], "email": order["customer_email"], "name": order["customer_name"],
            "total": order["total"], "currency": order["currency"], "status": "SYNCED",
            "order_status": order["status"],
            "updated_at": f"2026-10-{int(order['id']) - 1000:02d}T11:00:00Z",
        })
    for order, total in zip(orders[12:15], (180.0, 300.0, 200.0)):
        records.append({
            "order_id": order["id"], "email": order["customer_email"], "name": order["customer_name"],
            "total": total, "currency": order["currency"], "status": "SYNCED",
            "order_status": order["status"],
            "updated_at": f"2026-10-{int(order['id']) - 1000:02d}T11:00:00Z",
        })
    for order in orders[15:18]:
        records.append({
            "order_id": order["id"], "email": order["customer_email"], "name": order["customer_name"],
            "total": order["total"], "currency": order["currency"], "status": "ERROR",
            "order_status": order["status"], "error_message": "Demo connector timeout",
            "updated_at": f"2026-10-{int(order['id']) - 1000:02d}T11:05:00Z",
        })
    return records


def seed_crm_contacts(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Contacts are independent CRM people records, not CRM order/deal records."""
    return [
        {
            "email": orders[index]["customer_email"],
            "status": "FOUND",
            "contact_id": f"demo-contact-{orders[index]['id']}",
            "verified_at": f"2026-10-{index + 1:02d}T14:00:00Z",
            "source": "demo",
        }
        for index in (8, 9, 10, 11)
    ]
