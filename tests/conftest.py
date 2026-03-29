"""Shared fixtures for the test suite."""

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthSettings, provide_auth_settings
from app.localdb import LocalDBConfig, LocalQuoteStore
from app.main import Settings, app, get_db_client, get_settings
from app.models import User, UserStatus


@pytest.fixture
def db(tmp_path):
    """Fresh LocalQuoteStore backed by a temporary SQLite file."""
    return LocalQuoteStore(LocalDBConfig(path=str(tmp_path / "test.db")))


@pytest.fixture
async def seeded_db(db):
    """Seeds the DB with admin, regular user, pending user, and 3 quotes."""
    admin = User(
        email="admin@test.com", password="admin-pass",
        admin_name="Admin", status=UserStatus.APPROVED, is_admin=True,
    )
    user = User(
        email="user@test.com", password="user-pass",
        admin_name="User", status=UserStatus.APPROVED, is_admin=False,
    )
    pending = User(
        email="pending@test.com", password="pending-pass",
        admin_name="Pending", status=UserStatus.PENDING, is_admin=False,
    )
    await db.create_user(admin)
    await db.create_user(user)
    await db.create_user(pending)

    pending_quote = await db.create_quote(
        content="Pending quote", content_hash=db.content_hash("Pending quote"),
        source="test", status="PENDING", submitted_by="user@test.com",
    )
    approved_quote = await db.create_quote(
        content="Approved quote", content_hash=db.content_hash("Approved quote"),
        source="test", status="APPROVED", submitted_by="user@test.com",
    )
    rejected_quote = await db.create_quote(
        content="Rejected quote", content_hash=db.content_hash("Rejected quote"),
        source="test", status="REJECTED", submitted_by="user@test.com",
    )

    return {
        "db": db,
        "admin": admin,
        "user": user,
        "pending": pending,
        "pending_quote": pending_quote,
        "approved_quote": approved_quote,
        "rejected_quote": rejected_quote,
    }


@pytest.fixture
def client(seeded_db, monkeypatch, tmp_path):
    """TestClient with dependency overrides for the seeded DB."""
    test_db = seeded_db["db"]

    # Environment variables needed by verify_token and provide_auth_settings
    monkeypatch.setenv("ADMIN_CREDENTIALS", "admin@test.com:admin-pass")
    monkeypatch.setenv("ADMIN_EMAILS", "admin@test.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass")
    monkeypatch.setenv("LOCAL_MODE", "true")
    # Point lifespan's LocalQuoteStore at a temp file so it doesn't touch real local.db
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "lifespan.db"))

    # Clear lru_cache so Settings picks up our env
    get_settings.cache_clear()

    test_settings = Settings(
        LOCAL_MODE=True,
        LOCAL_DB_PATH="unused",
        ADMIN_EMAILS="admin@test.com",
        ADMIN_PASSWORD="admin-pass",
        ADMIN_NAME="Admin",
    )

    test_auth_settings = AuthSettings(
        jwks_url=None,
        admin_emails=["admin@test.com"],
        local_mode=True,
        admin_password="admin-pass",
        admin_name="Admin",
    )

    app.dependency_overrides[get_db_client] = lambda: test_db
    app.dependency_overrides[provide_auth_settings] = lambda: test_auth_settings
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.state.db_client = test_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def admin_cookies():
    return {"admin_token": "admin@test.com:admin-pass:admin"}


@pytest.fixture
def user_cookies():
    return {"admin_token": "user@test.com:user-pass:user"}


@pytest.fixture
def pending_cookies():
    return {"admin_token": "pending@test.com:pending-pass:user"}
