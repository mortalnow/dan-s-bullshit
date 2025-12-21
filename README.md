# Dan Quotes Service

A FastAPI-based quote submission and moderation system with a modern, minimal web UI. Users can register and submit quotes, which are held as **PENDING** until an admin approves them. Approved quotes are then served via web interface and JSON API.

## Features

- **User Registration**: New users can register and wait for admin approval.
- **Admin Moderation**:
  - **Quote Review**: Approve, reject, or edit quotes before they go live.
  - **User Management**: Approve new registrations or delete accounts.
  - **Full Archive**: View the complete history of approved and rejected quotes (Admins only).
- **Interactive UI**:
  - **Quote Dispenser**: Shuffle through approved wisdom on the home page.
  - **Donate Button**: Support the service via a QR code popup.
  - **Easter Egg**: Click the character's head for a surprise.
  - **Mobile Responsive**: Fully optimized for phones and tablets with adaptive layouts.
- **Robust Authentication**:
  - Unified login for both administrators and regular users.
  - Role-based access control (Admins vs. Users).
  - Secure session management using HTTP-only cookies.
- **Dual Database Support**: 
  - **MongoDB Atlas**: Manages `quotes`, `users`, and `admins` collections for production.
  - **SQLite**: Local development mode with full feature parity.

## Project Structure

```
.
├── app/
│   ├── main.py              # FastAPI application and routes
│   ├── models.py            # Pydantic models for quotes and users
│   ├── auth.py              # Authentication and role management
│   ├── mongostore.py        # MongoDB (Motor) client implementation
│   ├── localdb.py           # SQLite database implementation
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS and images
├── scripts/
│   ├── import_records.py    # Seed quotes from records.txt
│   └── add_admin.py         # Utility to add admin accounts
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Setup & Configuration

### Prerequisites

- Python 3.9+
- `uv` package manager (recommended) or `pip`

### Installation

1. Install `uv` (if needed):
```bash
brew install uv
```

2. Create virtual environment and install dependencies:
```bash
uv sync
```

### Configuration

Create a `.env` file in the project root:

```env
LOCAL_MODE=0/1
ADMIN_EMAILS=admin@example.com
ADMIN_PASSWORD=your_secure_password
ADMIN_NAME=AdminName
MONGODB_URI=your_mongodb_connection_string
```

## Running the Application

### Local Mode (SQLite)

1. Set `LOCAL_MODE=1` in `.env`.
2. Start the server:
```bash
uv run uvicorn app.main:app --reload
```

### Production Mode (MongoDB)

1. Set `LOCAL_MODE=0` and provide `MONGODB_URI` in `.env`.
2. Start the server:
```bash
uv run uvicorn app.main:app --reload
```

## API Endpoints

### Public Endpoints
- `GET /api/quotes` - List approved quotes
- `GET /api/quotes/random` - Get a random approved quote
- `POST /api/quotes` - Submit a new quote (requires approved user account)

### Admin Endpoints
- `GET /api/admin/quotes` - List all quotes for moderation
- `POST /api/admin/quotes/{id}/approve` - Approve a submission

## License

[Add your license here]
