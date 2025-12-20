---
name: Dan quotes service
overview: FastAPI backend + server-rendered UI. Accepts quotes, queues as PENDING, allows admin approval, serves APPROVED quotes via web and JSON API. Production DB is MongoDB Atlas; local mode uses SQLite. Seed data comes from records.txt via importer.
todos:
  - id: mongo-schema
    content: Define/confirm Mongo schema/indexes for `quotes` (status, content_hash unique).
    status: completed
  - id: backend-fastapi
    content: Implement FastAPI app with public + admin endpoints, Mongo/SQLite clients, and Pydantic models.
    status: completed
  - id: web-ui
    content: Add Jinja2 templates for browse/submit/admin queue pages and minimal styling.
    status: completed
  - id: auth-admin
    content: Integrate JWT auth (JWKS) and admin allowlist check for protected routes/pages; password auth in local mode.
    status: completed
  - id: import-seed
    content: Create `scripts/import_records.py` to parse `records.txt`, dedupe, and seed Mongo/SQLite as APPROVED.
    status: completed
  - id: docs-runbook
    content: Write README with env vars, local run, and import instructions.
    status: completed
---

# Dan Quotes Service (FastAPI + MongoDB/SQLite)

## Architecture

- **Backend**: FastAPI (Python) with server-rendered pages (Jinja2) + JSON API.
- **Database**: MongoDB Atlas (prod) or SQLite (local).
- **Auth**: JWT (JWKS) for admin-only actions; password in local mode.
```mermaid
sequenceDiagram
participant User
participant Web as FastAPI_Web
participant API as FastAPI_API
participant DB as MongoDB/SQLite
participant Admin

User->>Web: Submit_quote(form)
Web->>API: POST_/api/quotes
API->>DB: Insert_quote(status=PENDING)
DB-->>API: quoteId
API-->>Web: Confirmation

Admin->>Web: Open_admin_queue
Web->>API: GET_/api/admin/quotes?status=PENDING
API->>DB: Query_pending
DB-->>API: pendingQuotes
API-->>Web: Render_queue

Admin->>Web: Approve_quote
Web->>API: POST_/api/admin/quotes/{id}/approve
API->>API: Verify_JWT_isAdmin_or_Password_Local
API->>DB: Update_quote(status=APPROVED, verifiedAt, verifiedBy)
DB-->>API: ok
API-->>Web: Updated_queue

User->>API: GET_/api/quotes(random/list/latest)
API->>DB: Query_approved_latest
DB-->>API: approvedQuotes
API-->>User: JSON
```

## Data model (Mongo/SQLite)

- **Collection/Table**: `quotes`
  - `id` (string/uuid)
  - `content` (string)
  - `content_hash` (string; dedupe, unique index)
  - `status` (enum: `PENDING` | `APPROVED` | `REJECTED`)
  - `source` (string; e.g. `records.txt` or `web_submit`)
  - `created_at` (timestamp)
  - `submitted_by` (string; optional)
  - `verified_at` (timestamp, nullable)
  - `verified_by` (string, nullable)

## Backend features

- **Public web pages**
  - `/` list approved quotes (pagination)
  - `/random` show one random approved quote
  - `/submit` form to submit a new quote
- **Admin web pages (JWT-authenticated or password in local)**
  - `/admin` pending queue (approve/reject)

## API surface

- **Public**
  - `GET /api/quotes` (list approved; `limit`, `cursor`)
  - `GET /api/quotes/random`
  - `GET /api/quotes/latest` (most recent, optional `status`)
  - `GET /api/quotes/{id}` (approved only)
  - `POST /api/quotes` (create pending)
- **Admin (requires JWT + isAdmin; password in local)**
  - `GET /api/admin/quotes?status=PENDING`
  - `POST /api/admin/quotes/{id}/approve`
  - `POST /api/admin/quotes/{id}/reject`

## Auth + admin check

- Accept `Authorization: Bearer <jwt>` on admin routes.
- Verify token using JWKS URL (`INSTANTDB_JWKS_URL` / `INSTANTDB_TOKEN_VERIFY_URL`).
- Determine admin via allowlist `ADMIN_EMAILS`.
- Local mode: password-only using `ADMIN_PASSWORD`.

## Initial import (seed from records.txt)

- Script [`scripts/import_records.py`](scripts/import_records.py):
  - Parses numbered bullet lines in [`records.txt`](records.txt).
  - Normalizes whitespace, computes `content_hash`.
  - Inserts into Mongo/SQLite as `APPROVED` with `source=records.txt`.
  - Skips duplicates by `content_hash`.

## Project structure

- [`app/main.py`](app/main.py) FastAPI app, routers, template wiring.
- [`app/mongostore.py`](app/mongostore.py) Mongo client wrapper (CRUD + query helpers).
- [`app/auth.py`](app/auth.py) JWT verification + `is_admin()`.
- [`app/models.py`](app/models.py) Pydantic request/response models.
- [`app/templates/`](app/templates/) Jinja2 templates for pages.
- [`app/static/`](app/static/) CSS and assets.
- [`scripts/import_records.py`](scripts/import_records.py) seed importer.
- [`requirements.txt`](requirements.txt) pinned deps (fastapi, uvicorn, jinja2, motor, httpx, python-dotenv).
- [`README.md`](README.md) setup, env vars, run + import steps.

## Configuration (env vars)

- `MONGODB_URI`, `MONGODB_DB`, `MONGODB_COLLECTION`
- `LOCAL_MODE`, `LOCAL_DB_PATH`, `ADMIN_PASSWORD` (local)
- `INSTANTDB_JWKS_URL` or `INSTANTDB_TOKEN_VERIFY_URL` (JWKS for JWT verify)
- `ADMIN_EMAILS`

## Acceptance criteria

- Can submit a quote → lands as **PENDING**.
- Admin can view queue and **APPROVE/REJECT**.
- Only **APPROVED** quotes appear on `/`, `/random`, `/api/quotes`, and `/api/quotes/{id}`.
- `/api/quotes/latest` returns the most recently inserted quote (optional status filter).
- One command/script imports the existing `records.txt` quotes into Mongo/SQLite as **APPROVED**.