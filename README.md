# Dan Quotes Service

A FastAPI-based quote submission and moderation system with a minimal web UI. Users can submit quotes, which are held as **PENDING** until an admin approves them. Approved quotes are then served via web interface and JSON API.

## Features

- **Quote Submission**: Web form and API endpoint for submitting new quotes
- **Moderation Queue**: Admin panel to review, approve, or reject pending quotes
- **Random Quote Display**: Web interface showing random approved quotes
- **REST API**: JSON API endpoints for programmatic access
- **Dual Database Support**: 
  - **InstantDB** (cloud) - Production mode
  - **SQLite** (local) - Development/demo mode
- **Authentication**: JWT-based admin authentication (InstantDB) or password-based (local mode)
- **Duplicate Detection**: Content hashing prevents duplicate quote submissions

## Tech Stack

- **Framework**: FastAPI
- **Templates**: Jinja2
- **Database**: InstantDB (cloud) or SQLite (local)
- **Authentication**: PyJWT with JWKS verification
- **HTTP Client**: httpx

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application and routes
│   ├── models.py            # Pydantic models for quotes
│   ├── auth.py              # Authentication and admin context
│   ├── instantdb.py         # InstantDB client implementation
│   ├── localdb.py            # SQLite database implementation
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS and images
├── scripts/
│   └── import_records.py    # Script to seed database from records.txt
├── records.txt              # Initial quotes data
├── requirements.txt         # Python dependencies
├── pyproject.toml          # Project configuration
└── README.md               # This file
```

## Setup

### Prerequisites

- Python 3.9+
- `uv` package manager (recommended) or `pip`

### Installation

#### Using `uv` (Recommended)

1. Install `uv` (if needed):
```bash
brew install uv
```

2. Create virtual environment and install dependencies:
```bash
uv venv
uv sync
```

#### Using `pip`

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

### Environment Variables

Create a `.env` file in the project root:

#### InstantDB Mode (Production)

```env
INSTANTDB_APP_ID=your_app_id
INSTANTDB_API_KEY=your_server_key
INSTANTDB_BASE_URL=https://api.instantdb.com
INSTANTDB_QUOTES_PATH=/v1/apps/{app_id}/collections/quotes
INSTANTDB_JWKS_URL=https://your-jwks-url
ADMIN_EMAILS=you@example.com,other@example.com
```

#### Local Mode (Development/Demo)

```env
LOCAL_MODE=1
LOCAL_DB_PATH=local.db
ADMIN_PASSWORD=dev-password
```


## Running the Application

### Local Mode (SQLite)

1. Set environment variables in `.env`:
```bash
export LOCAL_MODE=1
export LOCAL_DB_PATH=local.db
export ADMIN_PASSWORD=dev-password
```

2. (Optional) Seed the database with initial quotes:
```bash
uv run python scripts/import_records.py
```

3. Start the server:
```bash
uv run uvicorn app.main:app --reload
```

4. Access the application:
   - **Home**: `http://localhost:8000/`
   - **Submit Form**: `http://localhost:8000/submit`
   - **Admin Panel**: `http://localhost:8000/admin/login` (use `ADMIN_PASSWORD`)

### InstantDB Mode (Production)

1. Configure environment variables (see above)

2. (Optional) Import initial quotes:
```bash
uv run python scripts/import_records.py
```

3. Start the server:
```bash
uv run uvicorn app.main:app --reload
```

4. Access the application:
   - **Web**: `http://localhost:8000/` (browse), `/submit`, `/random`
   - **Admin**: `/admin` (requires JWT bearer token with admin email)
   - **API**: See API endpoints below

## Authentication

### Local Mode

- Admin authentication uses a simple password (`ADMIN_PASSWORD`)
- Login via `/admin/login` form
- Token stored in HTTP-only cookie

### InstantDB Mode

- Admin authentication uses JWT tokens from InstantDB
- JWT is verified against `INSTANTDB_JWKS_URL` (or `INSTANTDB_TOKEN_VERIFY_URL`)
- Admin allowlist comes from `ADMIN_EMAILS` (comma-separated)
- JWT must contain an `email` claim matching an admin email
- Send `Authorization: Bearer <instantdb_jwt>` header on admin routes
- Or use cookie-based auth via `/admin/login` endpoint

## API Endpoints

### Public Endpoints

- `GET /api/quotes` - List quotes (default: APPROVED status)
  - Query params: `status`, `limit`, `cursor`
- `GET /api/quotes/random` - Get a random approved quote
- `GET /api/quotes/{quote_id}` - Get a specific approved quote
- `POST /api/quotes` - Submit a new quote (creates as PENDING)
  - Body: `{"content": "...", "source": "...", "submitted_by": "..."}`

### Admin Endpoints (Requires Authentication)

- `GET /api/admin/quotes` - List quotes (default: PENDING status)
  - Query params: `status`, `limit`, `cursor`
- `POST /api/admin/quotes/{quote_id}/approve` - Approve a quote
- `POST /api/admin/quotes/{quote_id}/reject` - Reject a quote

### Web Routes

- `GET /` - Home page (displays random quote)
- `GET /random` - Redirects to home
- `GET /submit` - Quote submission form
- `POST /submit` - Submit quote via form
- `GET /admin` - Admin moderation queue (requires auth)
- `GET /admin/login` - Admin login page
- `POST /admin/login` - Admin login endpoint

## Data Import

Import quotes from `records.txt`:

```bash
uv run python scripts/import_records.py
```

This script:
- Parses numbered quotes from `records.txt`
- Computes content hashes to prevent duplicates
- Inserts quotes as `APPROVED` with `source=records.txt`
- Works in both local and InstantDB modes

## Quote Status Flow

1. **PENDING**: Newly submitted quotes awaiting moderation
2. **APPROVED**: Quotes approved by admin, visible to public
3. **REJECTED**: Quotes rejected by admin, not visible to public

## Database Abstraction

The application uses a database abstraction layer that supports both InstantDB and SQLite:

- **InstantDBClient** (`app/instantdb.py`): HTTP client for InstantDB API
- **LocalQuoteStore** (`app/localdb.py`): SQLite implementation

Both implement the same interface:
- `create_quote()` - Create a new quote
- `get_quote()` - Get quote by ID
- `list_quotes()` - List quotes with filtering
- `update_status()` - Update quote status (approve/reject)
- `random_approved()` - Get random approved quote
- `content_hash()` - Compute content hash for deduplication

## Development

### Project Configuration

The project uses `pyproject.toml` for configuration. Dependencies are managed via `uv` or `pip`.

### Code Structure

- **Models** (`app/models.py`): Pydantic models for request/response validation
- **Main** (`app/main.py`): FastAPI app, routes, and request handling
- **Auth** (`app/auth.py`): JWT verification and admin context management
- **Database Clients**: Separate implementations for InstantDB and SQLite

### Customizing InstantDB API Paths

The InstantDB client is path-configurable via environment variables:
- `INSTANTDB_BASE_URL`: Base URL for InstantDB API
- `INSTANTDB_QUOTES_PATH`: Path template for quotes collection

If your InstantDB API paths differ, adjust these environment values accordingly.

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]
