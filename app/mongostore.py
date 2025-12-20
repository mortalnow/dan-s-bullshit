import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from .models import QuoteListResponse, QuoteResponse, QuoteStatus


@dataclass(frozen=True)
class MongoConfig:
    uri: str
    db: str
    collection: str = "quotes"


class MongoDBError(Exception):
    """Raised when MongoDB operations fail."""


class MongoQuoteStore:
    def __init__(self, config: MongoConfig, client: AsyncIOMotorClient):
        self.config = config
        self.client = client
        self._collection: AsyncIOMotorCollection = client[config.db][config.collection]

    # Utilities -----------------------------------------------------
    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _doc_to_quote(doc: dict) -> QuoteResponse:
        quote_id = doc.get("id") or str(doc.get("_id"))
        return QuoteResponse(
            id=quote_id,
            content=doc["content"],
            content_hash=doc.get("content_hash"),
            status=doc["status"],
            source=doc.get("source"),
            created_at=doc.get("created_at"),
            submitted_by=doc.get("submitted_by"),
            verified_at=doc.get("verified_at"),
            verified_by=doc.get("verified_by"),
        )

    # Initialization ------------------------------------------------
    async def ensure_indexes(self) -> None:
        try:
            await self._collection.create_index("content_hash", unique=True, sparse=True)
            await self._collection.create_index("status")
            await self._collection.create_index([("created_at", -1), ("id", -1)])
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    # CRUD ----------------------------------------------------------
    async def create_quote(
        self,
        content: str,
        content_hash: str,
        source: Optional[str],
        status: QuoteStatus,
        submitted_by: Optional[str],
    ) -> QuoteResponse:
        quote_id = uuid.uuid4().hex
        created_at = self._now_iso()
        try:
            existing = await self._collection.find_one({"content_hash": content_hash})
            if existing:
                return self._doc_to_quote(existing)

            doc = {
                "_id": quote_id,
                "id": quote_id,
                "content": content,
                "content_hash": content_hash,
                "status": status,
                "source": source,
                "created_at": created_at,
                "submitted_by": submitted_by,
                "verified_at": None,
                "verified_by": None,
            }
            await self._collection.insert_one(doc)
            return self._doc_to_quote(doc)
        except DuplicateKeyError:
            existing = await self._collection.find_one({"content_hash": content_hash})
            if existing:
                return self._doc_to_quote(existing)
            raise MongoDBError("Duplicate content hash")  # pragma: no cover
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def get_quote(self, quote_id: str) -> Optional[QuoteResponse]:
        try:
            doc = await self._collection.find_one({"_id": quote_id})
            if not doc:
                return None
            return self._doc_to_quote(doc)
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

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

        query: dict = {}
        if status:
            query["status"] = status
        if content_hash:
            query["content_hash"] = content_hash

        try:
            cursor_obj = (
                self._collection.find(query)
                .sort([("created_at", -1), ("id", -1)])
                .skip(offset)
                .limit(limit)
            )
            items = [self._doc_to_quote(doc) async for doc in cursor_obj]
            next_cursor = str(offset + len(items)) if len(items) == limit else None
            return QuoteListResponse(items=items, next_cursor=next_cursor)
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def update_status(
        self,
        quote_id: str,
        status: QuoteStatus,
        verified_by: Optional[str] = None,
    ) -> QuoteResponse:
        verified_at = self._now_iso() if status in ("APPROVED", "REJECTED") else None
        try:
            updated = await self._collection.find_one_and_update(
                {"_id": quote_id},
                {"$set": {"status": status, "verified_by": verified_by, "verified_at": verified_at}},
                return_document=ReturnDocument.AFTER,
            )
            if not updated:
                raise MongoDBError("Quote not found")
            return self._doc_to_quote(updated)
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def random_approved(self) -> Optional[QuoteResponse]:
        try:
            docs = await self._collection.aggregate(
                [{"$match": {"status": "APPROVED"}}, {"$sample": {"size": 1}}]
            ).to_list(length=1)
            if not docs:
                return None
            return self._doc_to_quote(docs[0])
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

