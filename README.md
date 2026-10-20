# WooCRM Sync

Hackathon MVP that reconciles WooCommerce orders with a CRM. Demo mode uses deterministic local records; live mode uses backend-only WooCommerce REST and HubSpot connectors.

## Requirements

- Python 3.12+
- Node.js 20+
- npm

## Production

Startup requires an explicit `APP_ENV` of `demo` or `production`; unknown or
missing values fail closed. Production startup requires `APP_ENV=production`, an `AUTH_TOKEN_SECRET` of at
least 32 bytes, a non-empty `AUTH_USERS_JSON` list, explicit `CORS_ORIGINS`,
and an absolute `DATABASE_PATH` on persistent storage. Each user entry
contains a username, a role (`viewer`, `operator`, or `admin`), and a PBKDF2
`password_hash` using at least 600,000 SHA-256 iterations. Obtain a token from
`POST /api/woocrm/auth/login` with a configured username and password, then
send it in the HTTP header `Authorization: Bearer <access-token>`. GET/HEAD requests require the viewer role, mutating requests
require operator, and the demo reset endpoint requires admin. Health, readiness,
and login remain public. Tokens expire after one hour. In demo mode,
authentication is disabled by default. CORS is controlled by the comma-separated
`CORS_ORIGINS` variable containing HTTPS origins only. HTTP origins are accepted
only for explicitly local development hosts (`localhost`, `127.0.0.1`, or
`::1`) in demo mode. `DEMO_RESET_ENABLED` defaults to true in demo mode and
false in production. The server sets the operator identity from `OPERATOR_NAME`;
client actor headers are ignored.

CRM writes are permanently unavailable in production. `CRM_WRITE_ENABLED`
defaults to `false`, and setting it to `true` never enables production writes.
Non-production live write testing is supported only against dedicated test
accounts and must not use production data or credentials.

SQLite is single-instance storage. Run one backend instance against a persistent
disk, and back up the configured database file before upgrades or operational
changes. The process creates the parent directory only after the configured
path has passed startup validation; it does not support multi-instance
deployment. Use PostgreSQL as a separate future migration if the host requires
multiple application instances.
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
Production CRM writes are permanently disabled. `CRM_WRITE_ENABLED=true` is
recognized only for explicitly configured non-production write testing.

## Importing data

The demo seed remains available through `POST /api/woocrm/reset`, but imported data is stored independently by dataset. The pull-based import endpoints accept a JSON array (or `{ "records": [...] }`) and CSV with these schemas:

- WooCommerce: `id`, `customer_email`, `customer_name`, `total`, `currency`, `status`, `created_at`
- Mock CRM: `order_id`, `email`, `name`, `total`, `currency`, `status` (`SYNCED` or `ERROR`), `order_status`

Use `POST /api/woocrm/import/orders?dataset=my-dataset` and `POST /api/woocrm/import/crm-orders?dataset=my-dataset` with the document as the request body. Reimporting identical records is idempotent; conflicting identifiers are rejected. Reconcile and view data with `POST /api/woocrm/reconcile?dataset=my-dataset` and `GET /api/woocrm/dashboard?dataset=my-dataset`.

## Run the frontend

```powershell
cd frontend
npm ci
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

The default dataset has twelve deterministic fictional orders and a seeded reconciliation run. It includes synced, missing, recoverable error, total mismatch, currency mismatch, newer-CRM, manual-review, blocked, incomplete, previously resolved, and failed-then-verified recovery scenarios, plus a synthetic bulk-change Risk Guard evaluation. A sync includes only `processing` and `completed` orders. Demo replay remains idempotent and isolated from imported datasets; `POST /api/woocrm/reset` clears and recreates only the `default` demo dataset, including its event history and seeded evaluations. For live mode, configure the variables in `backend/.env.example`, set `INTEGRATION_MODE=live` and `CRM_PROVIDER=hubspot`, then use Settings > Test connection. WooCommerce reads are paginated and read-only. The WooCommerce REST API key needs Read access to orders; Write access is not required. HubSpot deal lookup expects the configured deal properties (`HUBSPOT_ORDER_ID_PROPERTY`, `HUBSPOT_STATUS_PROPERTY`, and `HUBSPOT_EMAIL_PROPERTY`; defaults are shown in the example); create these properties on deals. A HubSpot private-app token needs `crm.objects.deals.read` for read-only connection/search checks. No contact scope is required by this adapter. Replay and mismatch correction are permanently blocked from performing live CRM writes in production; any non-production write test must use dedicated test accounts and explicit approval. Both actions remain read-only in production and record a blocked audit event.

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
- `CRM_WRITE_ENABLED=false` (always false in production; true is only for non-production testing)
- `CONNECTOR_MAX_ATTEMPTS` (1-5; defaults to 3)
- `WOOCOMMERCE_STORE_URL`, `WOOCOMMERCE_CONSUMER_KEY`, `WOOCOMMERCE_CONSUMER_SECRET`
- `HUBSPOT_ACCESS_TOKEN`
- `HUBSPOT_ORDER_ID_PROPERTY`, `HUBSPOT_EMAIL_PROPERTY`, `HUBSPOT_TOTAL_PROPERTY`, `HUBSPOT_CURRENCY_PROPERTY`, `HUBSPOT_STATUS_PROPERTY`

The HubSpot adapter supports read-only deal and contact lookup, plus narrowly scoped
non-production write testing. It does not support contact creation, contact updates,
deletion, bulk writes, or arbitrary CRM object types. Production replay and mismatch
correction cannot create or modify CRM records, regardless of `CRM_WRITE_ENABLED`.
Automated tests use mocked HTTP responses only.

## SQLite backup, retention, access control, and restore test

Use an operator account with access to the database volume, but never expose
the database file, backup directory, or credentials through the web service.
Keep the directory owned by the backend service account with mode `0700`, keep
database and backup files at `0600`, and store backups on a separate
encrypted volume or encrypted object-storage bucket.

Before upgrades, configuration changes, or maintenance, make a consistent
backup while the service is running:

```bash
mkdir -p /var/data/backups
chmod 700 /var/data/backups
sqlite3 /var/data/woocrm.db \
  ".backup '/var/data/backups/woocrm-$(date -u +%Y%m%dT%H%M%SZ).db'"
chmod 600 /var/data/backups/woocrm-*.db
sha256sum /var/data/backups/woocrm-*.db > /var/data/backups/SHA256SUMS
```

Retain at least daily backups for 14 days and weekly backups for 12 weeks,
with one recent copy in a separate failure domain. Automate expiration only
after verifying that the retention policy leaves those recovery points, and
monitor backup success, size, and available disk space. Do not commit backups
or checksums containing sensitive metadata to Git.

At least quarterly, perform a restore rehearsal in an isolated staging
directory: stop the staging backend, verify the checksum, restore a selected
backup to a new database path, and run `PRAGMA integrity_check;`. Start one
staging instance against the restored copy, verify `/health` and `/ready`,
sign in, confirm expected order history and audit events, and exercise only
read-only connector checks. Record the backup timestamp, restore duration,
integrity result, and observed recovery point. Never use reset or seed commands
as a restore procedure, and keep `CRM_WRITE_ENABLED=false` during the test.

For an actual restore, stop the backend, preserve the current database for
forensics, copy the verified backup into the configured path, reapply ownership
and permissions, then run the same integrity and read-only smoke checks before
allowing traffic. This procedure does not migrate SQLite or introduce another
database engine.

## Production deployment checklist

### Render backend web service

1. Create a Web Service with root directory `backend`.
2. Use build command `pip install -r requirements.txt` and start command
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Attach a persistent disk mounted at `/var/data`, and set
   `DATABASE_PATH=/var/data/woocrm.db`. This service must remain a single
   backend instance because SQLite is not shared across instances.
4. Set `APP_ENV=production`, `INTEGRATION_MODE=live`, `CRM_PROVIDER=hubspot`,
   and `CORS_ORIGINS` to the exact HTTPS frontend origin,
   `DEMO_RESET_ENABLED=false`, and `CRM_WRITE_ENABLED=false`.
5. Add `AUTH_TOKEN_SECRET` (at least 32 bytes), `AUTH_USERS_JSON`, and any
   connector credentials as Render environment variables or secrets. Use
   placeholders when preparing configuration; never put real values in Git.
6. Set the health check path to `/api/woocrm/health`. Verify
   `/api/woocrm/ready` returns HTTP 200 after startup; it checks database
   availability and returns HTTP 503 without exposing database details when
   the database cannot be opened.

### Render frontend static site

1. Create a Static Site with root directory `frontend`, build command
   `npm ci && npm run build`, and publish directory `dist`.
2. Set the build-time variable `VITE_API_URL` to the deployed backend URL,
   such as `https://your-backend.onrender.com`, without a trailing slash.
   `VITE_API_URL` is the frontend's actual API-client configuration variable.
   It must contain only a URL, never credentials, tokens, or provider keys.
   Local development still defaults to `http://localhost:8000` when this
   variable is absent.
3. Add a Render rewrite rule from `/*` to `/index.html` so refreshing
   `/woocrm/orders`, `/woocrm/settings`, or another client-side route serves
   the SPA entry point.

### Backup, restore, and smoke test

1. Back up `/var/data/woocrm.db` before changes using a SQLite-consistent
   backup, for example `sqlite3 /var/data/woocrm.db ".backup '/var/data/backups/woocrm-YYYYMMDD-HHMMSS.db'"`.
   Keep backups outside Git.
2. To restore, stop the backend, copy a verified backup over
   `/var/data/woocrm.db`, verify ownership and permissions, and start the same
   single instance. Do not use reset or seed commands as a restore procedure.
3. Verify `GET https://your-backend.onrender.com/api/woocrm/health` returns
   `{"status":"ok","service":"woocrm-sync"}`, then verify `/api/woocrm/ready`
   returns HTTP 200. Load the frontend, sign in with a configured user,
   confirm the dashboard loads, and test a read-only connection. Keep
   `CRM_WRITE_ENABLED=false`; do not perform live CRM writes.
4. Against dedicated staging provider accounts, verify timeout/rate-limit
   handling, duplicate recovery, partial failures, audit events, and that
   imported data remains dataset-scoped before any separately authorized
   write test.

## Known Limitations

- Live WooCommerce and HubSpot behavior has not been verified against real accounts.
- There are no database migrations.
- Live search-then-create can race under concurrent requests.
- Production CRM writes are unavailable; use dedicated non-production accounts for any write testing.
