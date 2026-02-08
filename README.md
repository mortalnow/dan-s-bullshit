# 但言弹语 Dan's Bullshit

A quote submission and moderation platform built with FastAPI. Users register, submit memorable quotes, and admins curate them through a moderation queue. Approved quotes are served on a public homepage via an AJAX-powered "quote dispenser."

*Approved wisdom, unapproved chaos.*

## Features

- **Quote Dispenser** -- Shuffle through approved quotes on the homepage with instant AJAX updates (no page refresh). Dynamic font sizing keeps long quotes readable.
- **User Registration & Approval** -- Self-service registration with an admin approval gate. Pending users cannot submit quotes.
- **Admin Moderation** -- Approve, reject, or edit quotes before they go live. Bulk approve/reject all pending quotes at once.
- **User Dashboard** -- Regular users see their own submission history and can edit and resubmit rejected quotes.
- **Like System** -- "Oh, Shit!" button lets anyone (including unregistered visitors) like quotes with a live counter.
- **Content Deduplication** -- SHA-256 hashing prevents the same quote from being submitted twice.
- **Dual Database Support** -- `LOCAL_MODE=1` uses SQLite (zero-config development); `LOCAL_MODE=0` uses MongoDB Atlas (production).
- **Role-Based Access** -- Unified login for admins and users. Cookie-based sessions with HTTP-only cookies.
- **Mobile-First UI** -- Brutalist/neo-magazine design with iPhone safe area support (notch, Dynamic Island), 44px touch targets, and iOS zoom prevention.
- **Donate Modal** -- QR code popup for supporting the project.

## Project Structure

```
.
├── app/
│   ├── main.py              # FastAPI app, routes, settings, lifespan
│   ├── models.py            # Pydantic models (Quote, User, enums)
│   ├── auth.py              # Authentication, JWT verification, role checks
│   ├── mongostore.py        # MongoDB (Motor) data access layer
│   ├── localdb.py           # SQLite data access layer
│   ├── templates/           # Jinja2 HTML templates (9 files)
│   └── static/              # CSS, favicon, images
├── scripts/
│   ├── test_user_flow.py    # E2E test: register → approve → submit → approve → verify
│   ├── check_prod_users.py  # List users from MongoDB production
│   ├── compare_dbs.py       # Diff quotes/users between MongoDB and SQLite
│   └── reset_likes.py       # Zero out all like counters
├── dansbullshit_docs/       # Comprehensive project documentation
├── pyproject.toml           # Project metadata & dependencies
├── requirements.txt         # Pinned dependencies
└── .env                     # Environment config (git-ignored)
```

## Setup & Configuration

### Prerequisites

- Python 3.9+
- `uv` package manager (recommended) or `pip`

### Installation

```bash
brew install uv   # if needed
uv sync
```

### Configuration

Create a `.env` file in the project root:

```env
LOCAL_MODE=1                              # 1 = SQLite, 0 = MongoDB
ADMIN_EMAILS=admin@example.com            # Comma-separated for multiple admins
ADMIN_PASSWORD=your_password              # Comma-separated to match multiple admins
ADMIN_NAME=YourName
MONGODB_URI=your_mongodb_connection_string  # Required when LOCAL_MODE=0
```

For multiple admins with individual passwords, use either:

```env
# Option A: Matching comma-separated lists
ADMIN_EMAILS=alice@example.com,bob@example.com
ADMIN_PASSWORD=alice_pass,bob_pass

# Option B: Explicit credential pairs
ADMIN_CREDENTIALS=alice@example.com:alice_pass,bob@example.com:bob_pass
```

## Running the Application

```bash
uv run uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000`. In local mode, the admin account defined in `.env` is auto-created on first startup.

## API Endpoints

### Public

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/quotes` | List approved quotes (paginated) |
| `GET` | `/api/quotes/random` | Get a random approved quote |
| `GET` | `/api/quotes/latest` | Get the most recent quote (optional `?status=` filter) |
| `GET` | `/api/quotes/{id}` | Get a specific approved quote |
| `POST` | `/api/quotes` | Submit a new quote (JSON body) |
| `POST` | `/api/quotes/{id}/like` | Increment like count (no auth required) |

### Admin (requires admin cookie)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/admin/quotes` | List quotes for moderation (default: pending) |
| `POST` | `/api/admin/quotes/{id}/approve` | Approve a quote |
| `POST` | `/api/admin/quotes/{id}/reject` | Reject a quote |

### Web Pages

| Route | Description |
|---|---|
| `/` | Homepage with quote dispenser |
| `/register` | User registration form |
| `/admin/login` | Login (admins and users) |
| `/admin` | Dashboard (moderation, archive, users, or user history) |
| `/submit` | Quote submission form (requires approved account) |

## Scripts

```bash
# Run the full E2E test (requires running server)
uv run python scripts/test_user_flow.py --cleanup

# List production users
uv run python scripts/check_prod_users.py

# Compare MongoDB and SQLite data
uv run python scripts/compare_dbs.py

# Reset all like counters
uv run python scripts/reset_likes.py
```

## Documentation

Detailed architecture documentation is available in [`dansbullshit_docs/`](./dansbullshit_docs/):

- **[1. Project Overview](./dansbullshit_docs/1.%20Project%20Overview.md)** -- Tech stack, features, getting started
- **[2. Architecture Overview](./dansbullshit_docs/2.%20Architecture%20Overview.md)** -- C4 diagrams, data model, design decisions
- **[3. Workflow Overview](./dansbullshit_docs/3.%20Workflow%20Overview.md)** -- Sequence diagrams for all core flows
- **Deep Dives:**
  - [Database Layer](./dansbullshit_docs/deep_dive/Database%20Layer.md) -- MongoDB vs SQLite implementations
  - [Authentication](./dansbullshit_docs/deep_dive/Authentication.md) -- Cookie auth, role system, security notes
  - [Frontend & UI](./dansbullshit_docs/deep_dive/Frontend%20%26%20UI.md) -- Design system, mobile optimizations
  - [Scripts & Testing](./dansbullshit_docs/deep_dive/Scripts%20%26%20Testing.md) -- E2E test flow, utility scripts

## Tech Stack

| Component | Technology |
|---|---|
| Framework | FastAPI 0.115 |
| Templating | Jinja2 |
| Database (prod) | MongoDB Atlas via Motor |
| Database (dev) | SQLite |
| Auth | PyJWT + cookie sessions |
| Validation | Pydantic 2.10 |
| Package Manager | uv |
| Server | Uvicorn |
