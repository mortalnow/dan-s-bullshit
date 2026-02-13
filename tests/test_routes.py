"""Tests for HTML/form web routes."""

import pytest


# ── Registration ─────────────────────────────────────────────────────

class TestRegister:
    def test_get_form(self, client):
        r = client.get("/register")
        assert r.status_code == 200

    def test_post_success(self, client):
        r = client.post("/register", data={
            "email": "new@test.com", "password": "pw", "name": "New",
        })
        assert r.status_code == 200

    def test_post_duplicate_email(self, client, seeded_db):
        r = client.post("/register", data={
            "email": "user@test.com", "password": "pw", "name": "Dup",
        })
        assert r.status_code == 400


# ── Login ────────────────────────────────────────────────────────────

class TestLogin:
    def test_get_admin_login_form(self, client):
        r = client.get("/admin/login")
        assert r.status_code == 200

    def test_get_login_redirects(self, client):
        r = client.get("/login", follow_redirects=False)
        assert r.status_code in (301, 302, 303, 307)
        assert "/admin/login" in r.headers.get("location", "")

    def test_post_admin_success(self, client, seeded_db):
        r = client.post("/admin/login", data={
            "email": "admin@test.com", "token": "admin-pass",
        }, follow_redirects=False)
        assert r.status_code == 302
        assert "admin_token" in r.cookies

    def test_post_user_success(self, client, seeded_db):
        r = client.post("/admin/login", data={
            "email": "user@test.com", "token": "user-pass",
        }, follow_redirects=False)
        assert r.status_code == 302
        cookie = r.cookies.get("admin_token", "")
        assert ":user" in cookie

    def test_post_wrong_password(self, client, seeded_db):
        r = client.post("/admin/login", data={
            "email": "user@test.com", "token": "wrong",
        }, follow_redirects=False)
        assert r.status_code == 302
        assert "error" in r.headers.get("location", "").lower()

    def test_post_empty_email(self, client):
        r = client.post("/admin/login", data={
            "email": "", "token": "x",
        }, follow_redirects=False)
        assert r.status_code == 302
        assert "error" in r.headers.get("location", "").lower()


# ── Logout ───────────────────────────────────────────────────────────

class TestLogout:
    def test_post_logout(self, client, admin_cookies):
        r = client.post("/admin/logout", cookies=admin_cookies, follow_redirects=False)
        assert r.status_code == 302
        assert "/admin/login" in r.headers.get("location", "")


# ── Homepage ─────────────────────────────────────────────────────────

class TestHomepage:
    def test_get_home(self, client, seeded_db):
        r = client.get("/")
        assert r.status_code == 200

    def test_get_random_redirects(self, client):
        r = client.get("/random", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers.get("location") == "/"


# ── Submit ───────────────────────────────────────────────────────────

class TestSubmit:
    def test_get_authenticated(self, client, user_cookies):
        r = client.get("/submit", cookies=user_cookies)
        assert r.status_code == 200

    def test_get_unauthenticated(self, client):
        r = client.get("/submit", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers.get("location", "").lower()

    def test_post_authenticated(self, client, user_cookies):
        r = client.post("/submit", data={
            "content": "Test quote", "submitted_by": "tester",
        }, cookies=user_cookies)
        assert r.status_code == 201

    def test_post_empty_content(self, client, user_cookies):
        r = client.post("/submit", data={
            "content": "   ", "submitted_by": "tester",
        }, cookies=user_cookies)
        assert r.status_code == 400


# ── Admin Dashboard ──────────────────────────────────────────────────

class TestAdminDashboard:
    def test_moderation_as_admin(self, client, admin_cookies):
        r = client.get("/admin?mode=moderation", cookies=admin_cookies)
        assert r.status_code == 200

    def test_archive_as_admin(self, client, admin_cookies):
        r = client.get("/admin?mode=archive", cookies=admin_cookies)
        assert r.status_code == 200

    def test_users_as_admin(self, client, admin_cookies):
        r = client.get("/admin?mode=users", cookies=admin_cookies)
        assert r.status_code == 200

    def test_user_forced_to_archive(self, client, user_cookies):
        r = client.get("/admin?mode=moderation", cookies=user_cookies)
        assert r.status_code == 200

    def test_unauthenticated_redirects(self, client):
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code == 302
        assert "/admin/login" in r.headers.get("location", "")


# ── Admin Actions ────────────────────────────────────────────────────

class TestAdminActions:
    def test_approve_quote(self, client, seeded_db, admin_cookies):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/admin/approve/{qid}", data={
            "content": "Pending quote",
        }, cookies=admin_cookies, follow_redirects=False)
        assert r.status_code == 303

    def test_reject_quote(self, client, seeded_db, admin_cookies):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/admin/reject/{qid}", cookies=admin_cookies, follow_redirects=False)
        assert r.status_code == 303

    def test_update_quote(self, client, seeded_db, admin_cookies):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/admin/update/{qid}", data={
            "content": "Updated", "submitted_by": "user@test.com", "action": "approve",
        }, cookies=admin_cookies, follow_redirects=False)
        assert r.status_code == 303

    def test_unauthenticated_401(self, client, seeded_db):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/admin/approve/{qid}", data={"content": "x"})
        assert r.status_code == 401

    def test_non_admin_403(self, client, seeded_db, user_cookies):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/admin/approve/{qid}", data={
            "content": "x",
        }, cookies=user_cookies)
        assert r.status_code == 403


# ── Resubmit ─────────────────────────────────────────────────────────

class TestResubmit:
    def test_own_rejected_quote(self, client, seeded_db, user_cookies):
        qid = seeded_db["rejected_quote"].id
        r = client.post(f"/admin/resubmit/{qid}", data={
            "content": "Revised content",
        }, cookies=user_cookies, follow_redirects=False)
        assert r.status_code == 303

    def test_not_own_quote(self, client, seeded_db, admin_cookies):
        # admin trying to resubmit user's quote
        qid = seeded_db["rejected_quote"].id
        r = client.post(f"/admin/resubmit/{qid}", data={
            "content": "Revised",
        }, cookies=admin_cookies)
        assert r.status_code == 403

    def test_non_rejected_quote(self, client, seeded_db, user_cookies):
        qid = seeded_db["pending_quote"].id
        r = client.post(f"/admin/resubmit/{qid}", data={
            "content": "Revised",
        }, cookies=user_cookies)
        assert r.status_code == 400

    def test_nonexistent_quote(self, client, user_cookies):
        r = client.post("/admin/resubmit/does-not-exist", data={
            "content": "Revised",
        }, cookies=user_cookies, follow_redirects=False)
        # Global 404 handler redirects to /error
        assert r.status_code == 303


# ── Bulk Update ──────────────────────────────────────────────────────

class TestBulkUpdate:
    def test_approve_all(self, client, admin_cookies):
        r = client.post("/admin/bulk-update", data={
            "action": "approve_all",
        }, cookies=admin_cookies, follow_redirects=False)
        assert r.status_code == 303

    def test_reject_all(self, client, admin_cookies):
        r = client.post("/admin/bulk-update", data={
            "action": "reject_all",
        }, cookies=admin_cookies, follow_redirects=False)
        assert r.status_code == 303

    def test_unauthenticated_401(self, client):
        r = client.post("/admin/bulk-update", data={"action": "approve_all"})
        assert r.status_code == 401


# ── User Management ──────────────────────────────────────────────────

class TestUserManagement:
    def test_approve_user(self, client, seeded_db, admin_cookies):
        r = client.post("/admin/users/pending@test.com/approve",
                        cookies=admin_cookies, follow_redirects=False)
        assert r.status_code == 303

    def test_reject_user(self, client, seeded_db, admin_cookies):
        r = client.post("/admin/users/pending@test.com/reject",
                        cookies=admin_cookies, follow_redirects=False)
        assert r.status_code == 303

    def test_unauthenticated_401(self, client):
        r = client.post("/admin/users/pending@test.com/approve")
        assert r.status_code == 401
