# Dan Quotes Service

FastAPI backend with a minimal web UI that lets people submit quotes, holds them as **PENDING** until an admin approves, then serves approved quotes via web and JSON API. InstantDB is the primary store.

## Setup

### Using `uv` (recommended)

1) Install `uv` (if needed)
```bash
brew install uv
```

2) Create the environment + install deps (choose one)

Option A: `pyproject.toml` (recommended)
```bash
uv venv
uv sync
```

Option B: `requirements.txt`
```bash
uv venv
uv pip install -r requirements.txt
```

3) Env vars (create `.env` if you like)
```
INSTANTDB_APP_ID=your_app_id
INSTANTDB_API_KEY=your_server_key
INSTANTDB_BASE_URL=https://api.instantdb.com          # or your custom base
INSTANTDB_QUOTES_PATH=/v1/apps/{app_id}/collections/quotes
INSTANTDB_JWKS_URL=...                                # JWKS/verify URL from InstantDB
ADMIN_EMAILS=you@example.com,other@example.com
```

## Local demo (no InstantDB)

Set:
```
LOCAL_MODE=1
LOCAL_DB_PATH=local.db
ADMIN_PASSWORD=dev-password
```
You can also just copy `.env.demo` to `.env` (or keep both; `.env.demo` is loaded after `.env` and overrides it).

Seed from `records.txt`:
```bash
uv run python scripts/import_records.py
```

Run:
```bash
uv run uvicorn app.main:app --reload
```

- Browse: `http://localhost:8000/` and `/random`
- Admin: go to `/admin/login` and use `ADMIN_PASSWORD`

## Run (InstantDB mode)
```bash
uv run uvicorn app.main:app --reload
```
- Web: `http://localhost:8000/` (browse), `/submit`, `/random`
- Admin: `/admin` (needs bearer token with admin email in JWT)
- API: `/api/quotes`, `/api/quotes/random`, `/api/quotes/{id}`, admin routes under `/api/admin/...`

## Admin auth
- Send `Authorization: Bearer <instantdb_jwt>` on admin routes.
- JWT is verified against `INSTANTDB_JWKS_URL` (or `INSTANTDB_TOKEN_VERIFY_URL` if you map that).
- Admin allowlist comes from `ADMIN_EMAILS` (comma separated). The JWT must contain an `email` claim.

## Initial import
```bash
uv run python scripts/import_records.py
```
Reads `records.txt`, computes hashes, inserts as `APPROVED` with `source=records.txt`. Requires InstantDB env vars above.

## Notes on InstantDB API shape
The InstantDB client is path-configurable (`INSTANTDB_BASE_URL`, `INSTANTDB_QUOTES_PATH`). If your API paths differ, adjust the env values; the client posts to the quotes collection path and PATCHes a quote detail path inferred from it.
