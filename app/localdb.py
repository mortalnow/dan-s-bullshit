import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .models import QuoteListResponse, QuoteResponse, QuoteStatus, User, UserStatus


@dataclass(frozen=True)
class LocalDBConfig:
    path: str = "local.db"


class LocalDBError(Exception):
    """Raised when local DB operations fail."""


class LocalQuoteStore:
    def __init__(self, config: LocalDBConfig):
        self.config = config
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.config.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            # Check if likes column exists, if not add it
            cursor = conn.execute("PRAGMA table_info(quotes)")
            columns = [row[1] for row in cursor.fetchall()]
            if "likes" not in columns:
                conn.execute("ALTER TABLE quotes ADD COLUMN likes INTEGER DEFAULT 0")
            
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quotes (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    content_hash TEXT,
                    status TEXT NOT NULL,
                    source TEXT,
                    created_at TEXT,
                    submitted_by TEXT,
                    verified_at TEXT,
                    verified_by TEXT,
                    likes INTEGER DEFAULT 0
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_status ON quotes(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_content_hash ON quotes(content_hash)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    password TEXT NOT NULL,
                    admin_name TEXT,
                    status TEXT NOT NULL,
                    is_admin INTEGER DEFAULT 0,
                    created_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
            conn.commit()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row_to_quote(row: sqlite3.Row) -> QuoteResponse:
        # Handle likes field - it might not exist in older database schemas
        likes = 0
        try:
            if "likes" in row.keys():
                likes = row["likes"] or 0
        except (KeyError, IndexError):
            likes = 0
        
        return QuoteResponse(
            id=row["id"],
            content=row["content"],
            content_hash=row["content_hash"],
            status=row["status"],
            source=row["source"],
            created_at=row["created_at"],
            submitted_by=row["submitted_by"],
            verified_at=row["verified_at"],
            verified_by=row["verified_by"],
            likes=likes,
        )

    # User methods ------------------------------------------------
    async def get_user_by_email(self, email: str, is_admin: bool = False) -> Optional[User]:
        """Get user by email. If is_admin=True, only return if user is an admin."""
        try:
            with self._connect() as conn:
                if is_admin:
                    row = conn.execute(
                        "SELECT * FROM users WHERE email = ? AND is_admin = 1 LIMIT 1", 
                        (email.lower(),)
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM users WHERE email = ? LIMIT 1", 
                        (email.lower(),)
                    ).fetchone()
                if not row:
                    return None
                return User(
                    email=row["email"],
                    password=row["password"],
                    admin_name=row["admin_name"],
                    status=row["status"],
                    is_admin=bool(row["is_admin"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
        except (sqlite3.Error, ValueError) as exc:
            raise LocalDBError(str(exc)) from exc

    async def create_user(self, user: User) -> User:
        """Create a new user in the unified users table."""
        try:
            status_value = user.status.value if hasattr(user.status, 'value') else user.status
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users (email, password, admin_name, status, is_admin, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user.email.lower(), user.password, user.admin_name, status_value, 1 if user.is_admin else 0, user.created_at.isoformat()),
                )
                conn.commit()
                return user
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def list_users(self, status: Optional[UserStatus] = None, include_admins: bool = False) -> list[User]:
        """List users. By default excludes admins (for user moderation)."""
        conditions = []
        params = []
        if status:
            status_value = status.value if hasattr(status, 'value') else status
            conditions.append("status = ?")
            params.append(status_value)
        if not include_admins:
            conditions.append("is_admin = 0")
        
        query = "SELECT * FROM users"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        
        try:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
                return [User(
                    email=r["email"],
                    password=r["password"],
                    admin_name=r["admin_name"],
                    status=r["status"],
                    is_admin=bool(r["is_admin"]),
                    created_at=datetime.fromisoformat(r["created_at"]),
                ) for r in rows]
        except (sqlite3.Error, ValueError) as exc:
            raise LocalDBError(str(exc)) from exc

    async def update_user_status(self, email: str, status: UserStatus) -> bool:
        """Update user status (for approval/rejection)."""
        try:
            status_value = status.value if hasattr(status, 'value') else status
            with self._connect() as conn:
                updated = conn.execute(
                    "UPDATE users SET status = ? WHERE email = ?",
                    (status_value, email.lower()),
                ).rowcount
                conn.commit()
                return updated > 0
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def set_user_admin(self, email: str, is_admin: bool) -> bool:
        """Set or remove admin privileges for a user."""
        try:
            with self._connect() as conn:
                if is_admin:
                    # Also set status to APPROVED when making admin
                    updated = conn.execute(
                        "UPDATE users SET is_admin = ?, status = ? WHERE email = ?",
                        (1, UserStatus.APPROVED.value, email.lower()),
                    ).rowcount
                else:
                    updated = conn.execute(
                        "UPDATE users SET is_admin = ? WHERE email = ?",
                        (0, email.lower()),
                    ).rowcount
                conn.commit()
                return updated > 0
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def delete_user(self, email: str) -> bool:
        try:
            with self._connect() as conn:
                deleted = conn.execute("DELETE FROM users WHERE email = ?", (email.lower(),)).rowcount
                conn.commit()
                return deleted > 0
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def get_admin_by_email(self, email: str) -> Optional[User]:
        user = await self.get_user_by_email(email)
        if user and user.is_admin:
            return user
        return None

    # API-compatible methods --------------------------------------
    @staticmethod
    def content_hash(content: str) -> str:
        from .instantdb import InstantDBClient

        return InstantDBClient.content_hash(content)

    async def create_quote(
        self,
        content: str,
        content_hash: str,
        source: Optional[str],
        status: QuoteStatus,
        submitted_by: str,
    ) -> QuoteResponse:
        try:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT * FROM quotes WHERE content_hash = ? LIMIT 1",
                    (content_hash,),
                ).fetchone()
                if existing:
                    return self._row_to_quote(existing)

                quote_id = uuid.uuid4().hex
                created_at = self._now_iso()
                conn.execute(
                    """
                    INSERT INTO quotes (id, content, content_hash, status, source, created_at, submitted_by, likes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (quote_id, content, content_hash, status, source, created_at, submitted_by),
                )
                row = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
                conn.commit()
                if not row:
                    raise LocalDBError("Insert failed")
                return self._row_to_quote(row)
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def get_quote(self, quote_id: str) -> Optional[QuoteResponse]:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM quotes WHERE id = ? LIMIT 1", (quote_id,)).fetchone()
                if not row:
                    return None
                return self._row_to_quote(row)
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def list_quotes(
        self,
        status: Optional[QuoteStatus] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> QuoteListResponse:
        try:
            offset = int(cursor) if cursor else 0
        except ValueError:
            offset = 0

        where = []
        params: list[object] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if content_hash:
            where.append("content_hash = ?")
            params.append(content_hash)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([limit, offset])

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT * FROM quotes
                    {where_sql}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    params,
                ).fetchall()
                items = [self._row_to_quote(r) for r in rows]
                next_cursor = str(offset + len(items)) if len(items) == limit else None
                return QuoteListResponse(items=items, next_cursor=next_cursor)
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def update_quote(
        self,
        quote_id: str,
        content: Optional[str] = None,
        status: Optional[QuoteStatus] = None,
        submitted_by: Optional[str] = None,
        verified_by: Optional[str] = None,
    ) -> QuoteResponse:
        verified_at = self._now_iso() if status in ("APPROVED", "REJECTED") else None
        
        update_fields = []
        params = []
        if content is not None:
            update_fields.append("content = ?")
            params.append(content)
            update_fields.append("content_hash = ?")
            params.append(self.content_hash(content))
        if status is not None:
            update_fields.append("status = ?")
            params.append(status)
            update_fields.append("verified_at = ?")
            params.append(verified_at)
        if submitted_by is not None:
            update_fields.append("submitted_by = ?")
            params.append(submitted_by)
        if verified_by is not None:
            update_fields.append("verified_by = ?")
            params.append(verified_by)
            
        if not update_fields:
            # Nothing to update
            return await self.get_quote(quote_id)

        params.append(quote_id)
        sql = f"UPDATE quotes SET {', '.join(update_fields)} WHERE id = ?"
        
        try:
            with self._connect() as conn:
                updated = conn.execute(sql, tuple(params)).rowcount
                if not updated:
                    raise LocalDBError("Quote not found")
                row = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
                conn.commit()
                if not row:
                    raise LocalDBError("Quote not found")
                return self._row_to_quote(row)
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def update_status(
        self,
        quote_id: str,
        status: QuoteStatus,
        verified_by: Optional[str] = None,
    ) -> QuoteResponse:
        verified_at = self._now_iso() if status in ("APPROVED", "REJECTED") else None
        try:
            with self._connect() as conn:
                updated = conn.execute(
                    """
                    UPDATE quotes
                    SET status = ?, verified_by = ?, verified_at = ?
                    WHERE id = ?
                    """,
                    (status, verified_by, verified_at, quote_id),
                ).rowcount
                if not updated:
                    raise LocalDBError("Quote not found")
                row = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
                conn.commit()
                if not row:
                    raise LocalDBError("Quote not found")
                return self._row_to_quote(row)
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def random_approved(self) -> Optional[QuoteResponse]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM quotes
                    WHERE status = 'APPROVED'
                    ORDER BY RANDOM()
                    LIMIT 1
                    """
                ).fetchone()
                if not row:
                    return None
                return self._row_to_quote(row)
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def latest_quote(self, status: Optional[QuoteStatus] = None) -> Optional[QuoteResponse]:
        try:
            with self._connect() as conn:
                if status:
                    row = conn.execute(
                        """
                        SELECT * FROM quotes
                        WHERE status = ?
                        ORDER BY created_at DESC, id DESC
                        LIMIT 1
                        """,
                        (status,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """
                        SELECT * FROM quotes
                        ORDER BY created_at DESC, id DESC
                        LIMIT 1
                        """
                    ).fetchone()
                if not row:
                    return None
                return self._row_to_quote(row)
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc

    async def increment_likes(self, quote_id: str) -> QuoteResponse:
        """Increment the likes count for a quote."""
        try:
            with self._connect() as conn:
                # First ensure the likes column exists
                cursor = conn.execute("PRAGMA table_info(quotes)")
                columns = [row[1] for row in cursor.fetchall()]
                if "likes" not in columns:
                    conn.execute("ALTER TABLE quotes ADD COLUMN likes INTEGER DEFAULT 0")
                
                # Update the likes count
                conn.execute(
                    "UPDATE quotes SET likes = COALESCE(likes, 0) + 1 WHERE id = ?",
                    (quote_id,),
                )
                row = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
                conn.commit()
                if not row:
                    raise LocalDBError("Quote not found")
                return self._row_to_quote(row)
        except sqlite3.Error as exc:
            raise LocalDBError(str(exc)) from exc
