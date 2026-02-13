"""Integration tests for LocalQuoteStore (fresh SQLite per test)."""

import pytest

from app.localdb import LocalDBConfig, LocalDBError, LocalQuoteStore
from app.models import User, UserStatus


@pytest.fixture
def db(tmp_path):
    return LocalQuoteStore(LocalDBConfig(path=str(tmp_path / "test.db")))


# ═══════════════════════════════════════════════════════════════════════
# Quote tests
# ═══════════════════════════════════════════════════════════════════════

class TestCreateQuote:
    async def test_returns_quote_response(self, db):
        q = await db.create_quote(
            content="Hello world",
            content_hash=db.content_hash("Hello world"),
            source="test",
            status="PENDING",
            submitted_by="dan",
        )
        assert q.id
        assert q.content == "Hello world"
        assert q.status == "PENDING"
        assert q.submitted_by == "dan"

    async def test_sets_content_hash(self, db):
        h = db.content_hash("Hello world")
        q = await db.create_quote(
            content="Hello world", content_hash=h,
            source=None, status="PENDING", submitted_by="dan",
        )
        assert q.content_hash == h

    async def test_deduplication(self, db):
        h = db.content_hash("dup")
        q1 = await db.create_quote(content="dup", content_hash=h, source=None, status="PENDING", submitted_by="dan")
        q2 = await db.create_quote(content="dup", content_hash=h, source=None, status="PENDING", submitted_by="dan")
        assert q1.id == q2.id


class TestGetQuote:
    async def test_found(self, db):
        q = await db.create_quote(content="hi", content_hash=db.content_hash("hi"), source=None, status="PENDING", submitted_by="d")
        found = await db.get_quote(q.id)
        assert found is not None
        assert found.id == q.id

    async def test_not_found(self, db):
        assert await db.get_quote("nonexistent") is None


class TestListQuotes:
    async def _seed(self, db):
        for i, s in enumerate(["PENDING", "APPROVED", "REJECTED"]):
            await db.create_quote(content=f"q{i}", content_hash=db.content_hash(f"q{i}"), source=None, status=s, submitted_by="dan")

    async def test_all(self, db):
        await self._seed(db)
        result = await db.list_quotes()
        assert len(result.items) == 3

    async def test_filter_by_status(self, db):
        await self._seed(db)
        result = await db.list_quotes(status="APPROVED")
        assert all(q.status == "APPROVED" for q in result.items)
        assert len(result.items) == 1

    async def test_filter_by_submitted_by(self, db):
        await self._seed(db)
        await db.create_quote(content="other", content_hash=db.content_hash("other"), source=None, status="PENDING", submitted_by="alice")
        result = await db.list_quotes(submitted_by="alice")
        assert len(result.items) == 1

    async def test_filter_by_content_hash(self, db):
        h = db.content_hash("findme")
        await db.create_quote(content="findme", content_hash=h, source=None, status="PENDING", submitted_by="d")
        result = await db.list_quotes(content_hash=h)
        assert len(result.items) == 1

    async def test_pagination_limit(self, db):
        for i in range(5):
            await db.create_quote(content=f"p{i}", content_hash=db.content_hash(f"p{i}"), source=None, status="PENDING", submitted_by="d")
        result = await db.list_quotes(limit=2)
        assert len(result.items) == 2
        assert result.next_cursor == "2"

    async def test_pagination_cursor_navigation(self, db):
        for i in range(5):
            await db.create_quote(content=f"p{i}", content_hash=db.content_hash(f"p{i}"), source=None, status="PENDING", submitted_by="d")
        page1 = await db.list_quotes(limit=2)
        page2 = await db.list_quotes(limit=2, cursor=page1.next_cursor)
        assert len(page2.items) == 2
        # Pages should have different items
        ids1 = {q.id for q in page1.items}
        ids2 = {q.id for q in page2.items}
        assert ids1.isdisjoint(ids2)

    async def test_pagination_last_page(self, db):
        for i in range(3):
            await db.create_quote(content=f"p{i}", content_hash=db.content_hash(f"p{i}"), source=None, status="PENDING", submitted_by="d")
        result = await db.list_quotes(limit=5)
        assert result.next_cursor is None

    async def test_ordering_newest_first(self, db):
        await db.create_quote(content="old", content_hash=db.content_hash("old"), source=None, status="PENDING", submitted_by="d")
        await db.create_quote(content="new", content_hash=db.content_hash("new"), source=None, status="PENDING", submitted_by="d")
        result = await db.list_quotes()
        assert result.items[0].content == "new"


class TestUpdateQuote:
    async def test_content_change(self, db):
        q = await db.create_quote(content="old", content_hash=db.content_hash("old"), source=None, status="PENDING", submitted_by="d")
        updated = await db.update_quote(q.id, content="new")
        assert updated.content == "new"
        assert updated.content_hash == db.content_hash("new")

    async def test_status_change_sets_verified_at(self, db):
        q = await db.create_quote(content="c", content_hash=db.content_hash("c"), source=None, status="PENDING", submitted_by="d")
        updated = await db.update_quote(q.id, status="APPROVED", verified_by="admin@test.com")
        assert updated.status == "APPROVED"
        assert updated.verified_at is not None
        assert updated.verified_by == "admin@test.com"

    async def test_not_found_raises(self, db):
        with pytest.raises(LocalDBError):
            await db.update_quote("nonexistent", content="x")


class TestUpdateStatus:
    async def test_sets_status_and_verified(self, db):
        q = await db.create_quote(content="c", content_hash=db.content_hash("c"), source=None, status="PENDING", submitted_by="d")
        updated = await db.update_status(q.id, "APPROVED", verified_by="a@b.com")
        assert updated.status == "APPROVED"
        assert updated.verified_by == "a@b.com"
        assert updated.verified_at is not None

    async def test_not_found_raises(self, db):
        with pytest.raises(LocalDBError):
            await db.update_status("nonexistent", "APPROVED")


class TestRandomApproved:
    async def test_returns_approved(self, db):
        await db.create_quote(content="yes", content_hash=db.content_hash("yes"), source=None, status="APPROVED", submitted_by="d")
        q = await db.random_approved()
        assert q is not None
        assert q.status == "APPROVED"

    async def test_none_when_no_approved(self, db):
        await db.create_quote(content="no", content_hash=db.content_hash("no"), source=None, status="PENDING", submitted_by="d")
        assert await db.random_approved() is None


class TestBulkUpdateStatus:
    async def test_updates_all_pending(self, db):
        for i in range(3):
            await db.create_quote(content=f"b{i}", content_hash=db.content_hash(f"b{i}"), source=None, status="PENDING", submitted_by="d")
        count = await db.bulk_update_status("APPROVED", verified_by="admin")
        assert count == 3
        result = await db.list_quotes(status="APPROVED")
        assert len(result.items) == 3

    async def test_custom_target_status(self, db):
        await db.create_quote(content="a", content_hash=db.content_hash("a"), source=None, status="APPROVED", submitted_by="d")
        await db.create_quote(content="p", content_hash=db.content_hash("p"), source=None, status="PENDING", submitted_by="d")
        count = await db.bulk_update_status("REJECTED", target_status="APPROVED")
        assert count == 1


class TestLatestQuote:
    async def test_newest_overall(self, db):
        await db.create_quote(content="old", content_hash=db.content_hash("old"), source=None, status="PENDING", submitted_by="d")
        await db.create_quote(content="new", content_hash=db.content_hash("new"), source=None, status="APPROVED", submitted_by="d")
        q = await db.latest_quote()
        assert q.content == "new"

    async def test_with_status_filter(self, db):
        await db.create_quote(content="pending", content_hash=db.content_hash("pending"), source=None, status="PENDING", submitted_by="d")
        await db.create_quote(content="approved", content_hash=db.content_hash("approved"), source=None, status="APPROVED", submitted_by="d")
        q = await db.latest_quote(status="PENDING")
        assert q.content == "pending"

    async def test_empty_returns_none(self, db):
        assert await db.latest_quote() is None


class TestIncrementLikes:
    async def test_increments(self, db):
        q = await db.create_quote(content="l", content_hash=db.content_hash("l"), source=None, status="APPROVED", submitted_by="d")
        assert q.likes == 0
        q = await db.increment_likes(q.id)
        assert q.likes == 1
        q = await db.increment_likes(q.id)
        assert q.likes == 2

    async def test_not_found_raises(self, db):
        with pytest.raises(LocalDBError):
            await db.increment_likes("nonexistent")


class TestContentHash:
    def test_deterministic(self):
        assert LocalQuoteStore.content_hash("hello") == LocalQuoteStore.content_hash("hello")

    def test_strips_whitespace(self):
        assert LocalQuoteStore.content_hash("  hello  ") == LocalQuoteStore.content_hash("hello")

    def test_different_content_differs(self):
        assert LocalQuoteStore.content_hash("a") != LocalQuoteStore.content_hash("b")


# ═══════════════════════════════════════════════════════════════════════
# User tests
# ═══════════════════════════════════════════════════════════════════════

class TestCreateUser:
    async def test_create(self, db):
        u = User(email="a@b.com", password="pw", admin_name="A")
        created = await db.create_user(u)
        assert created.email == "a@b.com"

    async def test_duplicate_raises(self, db):
        u = User(email="a@b.com", password="pw", admin_name="A")
        await db.create_user(u)
        with pytest.raises(LocalDBError):
            await db.create_user(u)


class TestGetUserByEmail:
    async def test_found(self, db):
        await db.create_user(User(email="a@b.com", password="pw", admin_name="A"))
        u = await db.get_user_by_email("a@b.com")
        assert u is not None
        assert u.email == "a@b.com"

    async def test_not_found(self, db):
        assert await db.get_user_by_email("missing@b.com") is None

    async def test_is_admin_filter(self, db):
        await db.create_user(User(email="a@b.com", password="pw", admin_name="A", is_admin=False))
        assert await db.get_user_by_email("a@b.com", is_admin=True) is None


class TestListUsers:
    async def _seed(self, db):
        await db.create_user(User(email="admin@b.com", password="pw", admin_name="Admin", is_admin=True, status=UserStatus.APPROVED))
        await db.create_user(User(email="user@b.com", password="pw", admin_name="User", is_admin=False, status=UserStatus.PENDING))

    async def test_excludes_admins_by_default(self, db):
        await self._seed(db)
        users = await db.list_users()
        assert all(not u.is_admin for u in users)
        assert len(users) == 1

    async def test_include_admins(self, db):
        await self._seed(db)
        users = await db.list_users(include_admins=True)
        assert len(users) == 2

    async def test_filter_by_status(self, db):
        await self._seed(db)
        users = await db.list_users(status=UserStatus.PENDING)
        assert all(u.status == UserStatus.PENDING for u in users)


class TestUpdateUserStatus:
    async def test_success(self, db):
        await db.create_user(User(email="a@b.com", password="pw", admin_name="A", status=UserStatus.PENDING))
        result = await db.update_user_status("a@b.com", UserStatus.APPROVED)
        assert result is True
        u = await db.get_user_by_email("a@b.com")
        assert u.status == UserStatus.APPROVED

    async def test_nonexistent(self, db):
        result = await db.update_user_status("nobody@b.com", UserStatus.APPROVED)
        assert result is False


class TestSetUserAdmin:
    async def test_set_admin_approves(self, db):
        await db.create_user(User(email="a@b.com", password="pw", admin_name="A", status=UserStatus.PENDING))
        result = await db.set_user_admin("a@b.com", True)
        assert result is True
        u = await db.get_user_by_email("a@b.com")
        assert u.is_admin is True
        assert u.status == UserStatus.APPROVED

    async def test_remove_admin(self, db):
        await db.create_user(User(email="a@b.com", password="pw", admin_name="A", is_admin=True, status=UserStatus.APPROVED))
        await db.set_user_admin("a@b.com", False)
        u = await db.get_user_by_email("a@b.com")
        assert u.is_admin is False


class TestDeleteUser:
    async def test_success(self, db):
        await db.create_user(User(email="a@b.com", password="pw", admin_name="A"))
        assert await db.delete_user("a@b.com") is True
        assert await db.get_user_by_email("a@b.com") is None

    async def test_nonexistent(self, db):
        assert await db.delete_user("nobody@b.com") is False


class TestGetAdminByEmail:
    async def test_admin_found(self, db):
        await db.create_user(User(email="a@b.com", password="pw", admin_name="A", is_admin=True, status=UserStatus.APPROVED))
        u = await db.get_admin_by_email("a@b.com")
        assert u is not None
        assert u.is_admin is True

    async def test_non_admin_returns_none(self, db):
        await db.create_user(User(email="a@b.com", password="pw", admin_name="A", is_admin=False))
        assert await db.get_admin_by_email("a@b.com") is None
