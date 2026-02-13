"""Unit tests for the auth module."""

import os
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.auth import AdminContext, AuthSettings, build_auth_settings, verify_token
from app.models import User, UserStatus


# ── build_auth_settings ──────────────────────────────────────────────

class TestBuildAuthSettings:
    def test_basic(self):
        env = {
            "ADMIN_EMAILS": "a@b.com,c@d.com",
            "LOCAL_MODE": "true",
            "ADMIN_PASSWORD": "secret",
        }
        s = build_auth_settings(env)
        assert s.local_mode is True
        assert s.admin_emails == ["a@b.com", "c@d.com"]
        assert s.admin_password == "secret"

    def test_local_mode_truthy_variants(self):
        for val in ("1", "true", "yes", "on", "TRUE", "Yes", "ON"):
            s = build_auth_settings({"LOCAL_MODE": val})
            assert s.local_mode is True, f"Failed for {val!r}"

    def test_local_mode_falsy(self):
        for val in ("0", "false", "no", "off", "", "random"):
            s = build_auth_settings({"LOCAL_MODE": val})
            assert s.local_mode is False, f"Failed for {val!r}"

    def test_empty_env(self):
        s = build_auth_settings({})
        assert s.admin_emails == []
        assert s.local_mode is False
        assert s.admin_password is None

    def test_admin_name_default(self):
        s = build_auth_settings({})
        assert s.admin_name == "Qiao"

    def test_admin_name_custom(self):
        s = build_auth_settings({"ADMIN_NAME": "Dan"})
        assert s.admin_name == "Dan"

    def test_email_whitespace_stripping(self):
        s = build_auth_settings({"ADMIN_EMAILS": " a@b.com , c@d.com "})
        assert s.admin_emails == ["a@b.com", "c@d.com"]


# ── AdminContext ─────────────────────────────────────────────────────

class TestAdminContext:
    def test_name_from_email(self):
        ctx = AdminContext(email="dan@example.com", token="t", claims={})
        assert ctx.name == "dan"

    def test_custom_name(self):
        ctx = AdminContext(email="dan@example.com", token="t", claims={}, name="Daniel")
        assert ctx.name == "Daniel"

    def test_defaults(self):
        ctx = AdminContext(email="dan@example.com", token="t", claims={})
        assert ctx.is_admin is False
        assert ctx.status == "APPROVED"


# ── verify_token ─────────────────────────────────────────────────────

class TestVerifyToken:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        """Ensure ADMIN_CREDENTIALS is controlled per test."""
        monkeypatch.delenv("ADMIN_CREDENTIALS", raising=False)

    async def test_admin_role_token_matches_env(self, monkeypatch):
        monkeypatch.setenv("ADMIN_CREDENTIALS", "admin@test.com:admin-pass")
        settings = AuthSettings(
            jwks_url=None, admin_emails=["admin@test.com"],
            local_mode=True, admin_password="admin-pass",
        )
        claims = await verify_token("admin@test.com:admin-pass:admin", settings)
        assert claims["email"] == "admin@test.com"
        assert claims["is_admin"] is True

    async def test_user_role_token_with_db(self, monkeypatch):
        monkeypatch.setenv("ADMIN_CREDENTIALS", "")
        db = AsyncMock()
        db.get_user_by_email = AsyncMock(return_value=User(
            email="user@test.com", password="user-pass",
            admin_name="User", status=UserStatus.APPROVED, is_admin=False,
        ))
        settings = AuthSettings(
            jwks_url=None, admin_emails=[], local_mode=False, admin_password=None,
        )
        claims = await verify_token("user@test.com:user-pass:user", settings, db=db)
        assert claims["email"] == "user@test.com"
        assert claims["is_admin"] is False

    async def test_single_password_local_mode(self, monkeypatch):
        monkeypatch.setenv("ADMIN_CREDENTIALS", "")
        settings = AuthSettings(
            jwks_url=None, admin_emails=["a@b.com"],
            local_mode=True, admin_password="secret",
        )
        claims = await verify_token("secret", settings)
        assert claims["email"] == "a@b.com"
        assert claims["is_admin"] is True

    async def test_invalid_token_raises_401(self, monkeypatch):
        monkeypatch.setenv("ADMIN_CREDENTIALS", "")
        settings = AuthSettings(
            jwks_url=None, admin_emails=[], local_mode=False, admin_password=None,
        )
        with pytest.raises(HTTPException) as exc_info:
            await verify_token("bad-token", settings)
        assert exc_info.value.status_code == 401

    async def test_db_user_found_correct_claims(self, monkeypatch):
        monkeypatch.setenv("ADMIN_CREDENTIALS", "")
        db = AsyncMock()
        db.get_user_by_email = AsyncMock(return_value=User(
            email="u@x.com", password="pw",
            admin_name="U", status=UserStatus.APPROVED, is_admin=False,
        ))
        settings = AuthSettings(
            jwks_url=None, admin_emails=[], local_mode=False, admin_password=None,
        )
        claims = await verify_token("u@x.com:pw:user", settings, db=db)
        assert claims["email"] == "u@x.com"
        assert claims["status"] == "APPROVED"

    async def test_db_user_not_found_raises_401(self, monkeypatch):
        monkeypatch.setenv("ADMIN_CREDENTIALS", "")
        db = AsyncMock()
        db.get_user_by_email = AsyncMock(return_value=None)
        settings = AuthSettings(
            jwks_url=None, admin_emails=[], local_mode=False, admin_password=None,
        )
        with pytest.raises(HTTPException) as exc_info:
            await verify_token("nobody@x.com:pw:user", settings, db=db)
        assert exc_info.value.status_code == 401

    async def test_non_admin_trying_admin_role_raises_403(self, monkeypatch):
        monkeypatch.setenv("ADMIN_CREDENTIALS", "")
        db = AsyncMock()
        db.get_user_by_email = AsyncMock(return_value=User(
            email="u@x.com", password="pw",
            admin_name="U", status=UserStatus.APPROVED, is_admin=False,
        ))
        settings = AuthSettings(
            jwks_url=None, admin_emails=[], local_mode=False, admin_password=None,
        )
        with pytest.raises(HTTPException) as exc_info:
            await verify_token("u@x.com:pw:admin", settings, db=db)
        assert exc_info.value.status_code == 403
