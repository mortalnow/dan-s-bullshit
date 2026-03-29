"""Tests for JSON API endpoints (/api/*)."""

import pytest


class TestApiListQuotes:
    def test_default_returns_approved(self, client, seeded_db):
        r = client.get("/api/quotes")
        assert r.status_code == 200
        data = r.json()
        assert all(q["status"] == "APPROVED" for q in data["items"])

    def test_status_filter(self, client, seeded_db):
        r = client.get("/api/quotes?status=PENDING")
        assert r.status_code == 200
        data = r.json()
        assert all(q["status"] == "PENDING" for q in data["items"])

    def test_pagination(self, client, seeded_db):
        r = client.get("/api/quotes?status=PENDING&limit=1")
        data = r.json()
        assert len(data["items"]) <= 1


class TestApiRandomQuote:
    def test_returns_quote_or_null(self, client, seeded_db):
        r = client.get("/api/quotes/random")
        assert r.status_code == 200


class TestApiGetQuote:
    def test_approved_returns_200(self, client, seeded_db):
        qid = seeded_db["approved_quote"].id
        r = client.get(f"/api/quotes/{qid}")
        assert r.status_code == 200
        assert r.json()["id"] == qid

    def test_pending_returns_404(self, client, seeded_db):
        qid = seeded_db["pending_quote"].id
        r = client.get(f"/api/quotes/{qid}", follow_redirects=False)
        # Global 404 handler redirects to /error
        assert r.status_code == 303

    def test_nonexistent_returns_404(self, client):
        r = client.get("/api/quotes/does-not-exist", follow_redirects=False)
        assert r.status_code == 303


class TestApiLatestQuote:
    def test_default_returns_approved_only(self, client, seeded_db):
        r = client.get("/api/quotes/latest")
        assert r.status_code == 200
        data = r.json()
        if data:
            assert data["status"] == "APPROVED"

    def test_status_filter_approved(self, client, seeded_db):
        r = client.get("/api/quotes/latest?status=APPROVED")
        assert r.status_code == 200
        data = r.json()
        if data:
            assert data["status"] == "APPROVED"

    def test_explicit_pending_filter(self, client, seeded_db):
        r = client.get("/api/quotes/latest?status=PENDING")
        assert r.status_code == 200
        data = r.json()
        if data:
            assert data["status"] == "PENDING"


class TestApiCreateQuote:
    def test_creates_with_201(self, client):
        r = client.post("/api/quotes", json={
            "content": "New quote", "submitted_by": "tester",
        })
        assert r.status_code == 201
        assert r.json()["content"] == "New quote"
        assert r.json()["status"] == "PENDING"

    def test_missing_content_422(self, client):
        r = client.post("/api/quotes", json={"submitted_by": "tester"})
        assert r.status_code == 422

    def test_deduplication(self, client):
        payload = {"content": "dupe test", "submitted_by": "tester"}
        r1 = client.post("/api/quotes", json=payload)
        r2 = client.post("/api/quotes", json=payload)
        assert r1.json()["id"] == r2.json()["id"]


class TestApiLikeQuote:
    def test_increments_likes(self, client, seeded_db):
        qid = seeded_db["approved_quote"].id
        r = client.post(f"/api/quotes/{qid}/like")
        assert r.status_code == 200
        assert r.json()["likes"] == 1


class TestApiAdminQuotes:
    def test_admin_can_list(self, client, admin_cookies):
        r = client.get("/api/admin/quotes", cookies=admin_cookies)
        assert r.status_code == 200

    def test_no_cookies_401(self, client):
        r = client.get("/api/admin/quotes")
        assert r.status_code == 401

    def test_user_cookies_403(self, client, user_cookies):
        r = client.get("/api/admin/quotes", cookies=user_cookies)
        assert r.status_code == 403


class TestApiAdminApprove:
    def test_approve(self, client, seeded_db, admin_cookies):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/api/admin/quotes/{qid}/approve", cookies=admin_cookies)
        assert r.status_code == 200
        assert r.json()["status"] == "APPROVED"

    def test_no_cookies_401(self, client, seeded_db):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/api/admin/quotes/{qid}/approve")
        assert r.status_code == 401


class TestApiAdminReject:
    def test_reject(self, client, seeded_db, admin_cookies):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/api/admin/quotes/{qid}/reject", cookies=admin_cookies)
        assert r.status_code == 200
        assert r.json()["status"] == "REJECTED"
