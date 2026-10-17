# WooCRM Sync

Hackathon MVP that reconciles WooCommerce orders with a CRM. Demo mode uses deterministic local records; live mode uses backend-only WooCommerce REST and HubSpot connectors.

## Requirements

- Python 3.12+
- Node.js 20+
- npm

## Production

Production startup requires `APP_ENV=production`, a non-empty
`AUTH_TOKEN_SECRET`, and a non-empty `AUTH_USERS_JSON` list. Each user entry
contains a username, a role (`viewer`, `operator`, or `admin`), and a PBKDF2
`password_hash`. Obtain a token from `POST /api/woocrm/auth/login` with a
configured username and password, then send it as `Authorization: Bearer
<access-token>`. GET/HEAD requests require the viewer role, mutating requests
require operator, and the demo reset endpoint requires admin. Health, readiness,
and login remain public. Tokens expire after one hour. In demo mode,
authentication is disabled by default. CORS is controlled by the comma-separated
`CORS_ORIGINS` variable. `DEMO_RESET_ENABLED` defaults to true in demo mode and
false in production. The server sets the operator identity from `OPERATOR_NAME`;
client actor headers are ignored.

Keep `CRM_WRITE_ENABLED=false` unless live writes have been independently
verified; enabling it can create or update CRM records.

SQLite is single-instance storage. Run one backend instance against a persistent
disk, and back up `backend/woocrm.db` before upgrades or operational changes.
The import limits are 10 MB per document and 5,000 records by default; set
`MAX_IMPORT_BYTES` and `MAX_IMPORT_RECORDS` explicitly when a different limit
is required. Place frontend variables in `frontend/.env.local`, copied from
`frontend/.env.example`; never put backend credentials or bearer tokens in a
`VITE_*` variable.

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

Order investigation actions are available from `/woocrm/orders/{order_id}`. The backend stores
dataset-scoped action and reconciliation events in `order_events`; inspect them with
`GET /api/woocrm/orders/{order_id}/history?dataset=...`. Replay and mismatch correction are
followed by a fresh comparison before the API reports verification. The Settings page reports the active mode and provider and can test verified connectivity.

Risk Guard evaluates every proposed CRM write immediately before it is applied. It flags
large total changes, currency changes, unusually large requested batches, and stale or
untrustworthy timestamp comparisons without labeling any signal as fraud. Review records
are available from `GET /api/woocrm/risk-guard/evaluations`; approval is recorded with
the server-set operator and is tied to the exact evaluated record fingerprint. A changed CRM record invalidates that
approval. `POST /api/woocrm/risk-guard/batch` evaluates the actual affected order IDs,
and `GET/PUT /api/woocrm/risk-guard/settings` reads or changes validated thresholds
Live CRM writes remain disabled unless
`CRM_WRITE_ENABLED=true` is explicitly configured.

## Importing data

The demo seed remains available through `POST /api/woocrm/reset`, but imported data is stored independently by dataset. The pull-based import endpoints accept a JSON array (or `{ "records": [...] }`) and CSV with these schemas:

- WooCommerce: `id`, `customer_email`, `customer_name`, `total`, `currency`, `status`, `created_at`
- Mock CRM: `order_id`, `email`, `name`, `total`, `currency`, `status` (`SYNCED` or `ERROR`), `order_status`

Use `POST /api/woocrm/import/orders?dataset=my-dataset` and `POST /api/woocrm/import/crm-orders?dataset=my-dataset` with the document as the request body. Reimporting identical records is idempotent; conflicting identifiers are rejected. Reconcile and view data with `POST /api/woocrm/reconcile?dataset=my-dataset` and `GET /api/woocrm/dashboard?dataset=my-dataset`.

## Run the frontend

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173/woocrm/ (Vite's fallback serves the dashboard at this path too).
For a non-default API URL, copy `frontend/.env.example` to `frontend/.env.local` and set
`VITE_API_URL` there; do not put API keys in `VITE_*` variables.

## Test

```powershell
cd backend
$env:PYTHONPATH = "."
pytest
```

The default dataset has twelve deterministic fictional orders and a seeded reconciliation run. It includes synced, missing, recoverable error, total mismatch, currency mismatch, newer-CRM, manual-review, blocked, incomplete, previously resolved, and failed-then-verified recovery scenarios, plus a synthetic bulk-change Risk Guard evaluation. A sync includes only `processing` and `completed` orders. Demo replay remains idempotent and isolated from imported datasets; `POST /api/woocrm/reset` clears and recreates only the `default` demo dataset, including its event history and seeded evaluations. For live mode, configure the variables in `backend/.env.example`, set `INTEGRATION_MODE=live` and `CRM_PROVIDER=hubspot`, then use Settings > Test connection. WooCommerce reads are paginated and read-only. The WooCommerce REST API key needs Read access to orders; Write access is not required. HubSpot deal lookup expects the configured deal properties (`HUBSPOT_ORDER_ID_PROPERTY`, `HUBSPOT_STATUS_PROPERTY`, and `HUBSPOT_EMAIL_PROPERTY`; defaults are shown in the example); create these properties on deals. A HubSpot private-app token needs `crm.objects.deals.read` for read-only connection/search checks and `crm.objects.deals.write` only for replay or mismatch correction. No contact scope is required by this adapter. Live replay creates a deal only after searching by the stable WooCommerce order ID, and mismatch correction updates an existing deal only after explicit confirmation. Both actions fetch the CRM record again and reconcile it before reporting success. Live writes remain disabled by default and are not implemented by the demo reset path.

Live environment variables:

- `APP_ENV=demo|production`
- `DATABASE_PATH` (optional; defaults to `backend/woocrm.db`)
- `AUTH_TOKEN_SECRET` (required in production)
- `AUTH_USERS_JSON` (required in production; JSON users with PBKDF2 password hashes and `viewer`, `operator`, or `admin` roles)
- `OPERATOR_NAME` (optional server-side audit identity)
- `CORS_ORIGINS` (comma-separated allowed frontend origins)
- `DEMO_RESET_ENABLED` (defaults to true in demo and false in production)
- `MAX_IMPORT_BYTES` and `MAX_IMPORT_RECORDS` (optional import limits)
- `INTEGRATION_MODE=demo|live`
- `CRM_PROVIDER=mock|hubspot`
- `CRM_WRITE_ENABLED=false` (keep disabled until explicitly configured)
- `CONNECTOR_MAX_ATTEMPTS` (1-5; defaults to 3)
- `WOOCOMMERCE_STORE_URL`, `WOOCOMMERCE_CONSUMER_KEY`, `WOOCOMMERCE_CONSUMER_SECRET`
- `HUBSPOT_ACCESS_TOKEN`
- `HUBSPOT_ORDER_ID_PROPERTY`, `HUBSPOT_EMAIL_PROPERTY`, `HUBSPOT_TOTAL_PROPERTY`, `HUBSPOT_CURRENCY_PROPERTY`, `HUBSPOT_STATUS_PROPERTY`

The HubSpot adapter currently supports deal search, deal creation, and deal property updates. It does not support contact creation, contact updates, deletion, bulk writes, or arbitrary CRM object types. Automated tests use mocked HTTP responses only; a real account test is still required before enabling live writes.

## Known Limitations

- Live WooCommerce and HubSpot behavior has not been verified against real accounts.
- There are no database migrations.
- Live search-then-create can race under concurrent requests.
- A real account test is still required before enabling live CRM writes.
