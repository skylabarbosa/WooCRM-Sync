# WooCRM Sync

Hackathon MVP that synchronizes deterministic WooCommerce order data into a mock CRM. It demonstrates eligibility filtering, customer grouping, idempotent replay, reconciliation, mismatch correction, and demo reset without requiring external credentials.

## Requirements

- Python 3.12+
- Node.js 20+
- npm

## Run the backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "."
uvicorn app.main:app --reload --port 8000
```

The API is namespaced under `/api/woocrm/`. It creates `backend/woocrm.db` automatically.

## Run the frontend

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173/woocrm/ (Vite's fallback serves the dashboard at this path too).

## Test

```powershell
cd backend
$env:PYTHONPATH = "."
pytest
```

The default dataset has ten deterministic orders. A sync includes only `processing` and `completed` orders, groups them by email, and upserts mock CRM contacts. Replaying is idempotent. The API also exposes `POST /api/woocrm/orders/{order_id}/mismatch` to demonstrate reconciliation.
