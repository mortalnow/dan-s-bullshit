"""Unit tests for Pydantic models — no DB or HTTP needed."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import (
    QuoteAdminUpdate,
    QuoteCreate,
    QuoteListResponse,
    QuoteResponse,
    SubmitResult,
    User,
    UserLogin,
    UserStatus,
)


# ── QuoteCreate ──────────────────────────────────────────────────────

class TestQuoteCreate:
    def test_valid(self):
        q = QuoteCreate(content="hello", submitted_by="dan")
        assert q.content == "hello"
        assert q.submitted_by == "dan"
        assert q.source is None

    def test_with_source(self):
        q = QuoteCreate(content="hello", submitted_by="dan", source="slack")
        assert q.source == "slack"

    def test_content_min_length(self):
        with pytest.raises(ValidationError):
            QuoteCreate(content="", submitted_by="dan")

    def test_content_max_length(self):
        with pytest.raises(ValidationError):
            QuoteCreate(content="x" * 2001, submitted_by="dan")

    def test_content_at_boundary(self):
        q = QuoteCreate(content="x" * 2000, submitted_by="dan")
        assert len(q.content) == 2000

    def test_content_single_char(self):
        q = QuoteCreate(content="a", submitted_by="dan")
        assert q.content == "a"

    def test_submitted_by_min_length(self):
        with pytest.raises(ValidationError):
            QuoteCreate(content="hello", submitted_by="")

    def test_submitted_by_max_length(self):
        with pytest.raises(ValidationError):
            QuoteCreate(content="hello", submitted_by="x" * 101)

    def test_submitted_by_at_boundary(self):
        q = QuoteCreate(content="hello", submitted_by="x" * 100)
        assert len(q.submitted_by) == 100

    def test_missing_content(self):
        with pytest.raises(ValidationError):
            QuoteCreate(submitted_by="dan")

    def test_missing_submitted_by(self):
        with pytest.raises(ValidationError):
            QuoteCreate(content="hello")


# ── QuoteResponse ────────────────────────────────────────────────────

class TestQuoteResponse:
    def test_full_fields(self):
        now = datetime.utcnow()
        r = QuoteResponse(
            id="abc",
            content="hi",
            content_hash="hash123",
            status="APPROVED",
            source="web",
            created_at=now,
            submitted_by="dan",
            verified_at=now,
            verified_by="admin@test.com",
            likes=5,
        )
        assert r.id == "abc"
        assert r.likes == 5
        assert r.verified_by == "admin@test.com"

    def test_defaults(self):
        r = QuoteResponse(id="x", content="hi", status="PENDING")
        assert r.likes == 0
        assert r.source is None
        assert r.content_hash is None
        assert r.created_at is None
        assert r.submitted_by is None
        assert r.verified_at is None
        assert r.verified_by is None


# ── QuoteListResponse ────────────────────────────────────────────────

class TestQuoteListResponse:
    def test_with_items(self):
        item = QuoteResponse(id="1", content="hi", status="APPROVED")
        resp = QuoteListResponse(items=[item], next_cursor="2")
        assert len(resp.items) == 1
        assert resp.next_cursor == "2"

    def test_empty_list(self):
        resp = QuoteListResponse(items=[])
        assert resp.items == []
        assert resp.next_cursor is None

    def test_null_cursor(self):
        resp = QuoteListResponse(items=[], next_cursor=None)
        assert resp.next_cursor is None


# ── QuoteAdminUpdate ─────────────────────────────────────────────────

class TestQuoteAdminUpdate:
    def test_valid_pending(self):
        u = QuoteAdminUpdate(status="PENDING")
        assert u.status == "PENDING"

    def test_valid_approved(self):
        u = QuoteAdminUpdate(status="APPROVED")
        assert u.status == "APPROVED"

    def test_valid_rejected(self):
        u = QuoteAdminUpdate(status="REJECTED", verified_by="admin@x.com")
        assert u.status == "REJECTED"
        assert u.verified_by == "admin@x.com"

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            QuoteAdminUpdate(status="INVALID")


# ── User ─────────────────────────────────────────────────────────────

class TestUser:
    def test_defaults(self):
        u = User(email="a@b.com", password="pw", admin_name="A")
        assert u.status == UserStatus.PENDING
        assert u.is_admin is False
        assert isinstance(u.created_at, datetime)

    def test_user_status_enum(self):
        assert UserStatus.PENDING.value == "PENDING"
        assert UserStatus.APPROVED.value == "APPROVED"

    def test_explicit_fields(self):
        u = User(
            email="x@y.com",
            password="p",
            admin_name="X",
            status=UserStatus.APPROVED,
            is_admin=True,
        )
        assert u.is_admin is True
        assert u.status == UserStatus.APPROVED


# ── UserLogin ────────────────────────────────────────────────────────

class TestUserLogin:
    def test_valid(self):
        ul = UserLogin(email="a@b.com", password="pw")
        assert ul.email == "a@b.com"
        assert ul.password == "pw"


# ── SubmitResult ─────────────────────────────────────────────────────

class TestSubmitResult:
    def test_fields(self):
        sr = SubmitResult(id="abc", status="PENDING")
        assert sr.id == "abc"
        assert sr.status == "PENDING"
