import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .models import QuoteListResponse, QuoteResponse, QuoteStatus


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
                    verified_by TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_status ON quotes(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_content_hash ON quotes(content_hash)")
            conn.commit()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row_to_quote(row: sqlite3.Row) -> QuoteResponse:
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
        )

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
        submitted_by: Optional[str],
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
                    INSERT INTO quotes (id, content, content_hash, status, source, created_at, submitted_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
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
