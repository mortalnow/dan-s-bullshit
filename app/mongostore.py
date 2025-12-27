import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from .models import QuoteListResponse, QuoteResponse, QuoteStatus, User, UserStatus


@dataclass(frozen=True)
class MongoConfig:
    uri: str
    db: str
    collection: str = "quotes"
    admin_collection: str = "admins"
    user_collection: str = "users"


class MongoDBError(Exception):
    """Raised when MongoDB operations fail."""


class MongoQuoteStore:
    def __init__(self, config: MongoConfig, client: AsyncIOMotorClient):
        self.config = config
        self.client = client
        self._collection: AsyncIOMotorCollection = client[config.db][config.collection]
        self._admin_collection: AsyncIOMotorCollection = client[config.db][config.admin_collection]
        self._user_collection: AsyncIOMotorCollection = client[config.db][config.user_collection]

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
            likes=doc.get("likes", 0),
        )

    # Initialization ------------------------------------------------
    async def ensure_indexes(self) -> None:
        try:
            await self._collection.create_index("content_hash", unique=True, sparse=True)
            await self._collection.create_index("status")
            await self._collection.create_index([("created_at", -1), ("id", -1)])
            await self._admin_collection.create_index("email", unique=True)
            await self._user_collection.create_index("email", unique=True)
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    # Admin / Users -------------------------------------------------
    async def get_user_by_email(self, email: str, is_admin: bool = False) -> Optional[User]:
        try:
            coll = self._admin_collection if is_admin else self._user_collection
            doc = await coll.find_one({"email": email.lower()})
            if not doc:
                return None
            return User(
                email=doc["email"],
                password=doc["password"],
                admin_name=doc.get("admin_name") or doc.get("name") or doc["email"].split("@")[0],
                status=doc.get("status", UserStatus.APPROVED if is_admin else UserStatus.PENDING),
                is_admin=is_admin or doc.get("is_admin", False),
                created_at=doc.get("created_at", datetime.utcnow()),
            )
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def create_user(self, user: User) -> User:
        try:
            coll = self._admin_collection if user.is_admin else self._user_collection
            doc = {
                "email": user.email.lower(),
                "password": user.password,
                "admin_name": user.admin_name,
                "status": user.status,
                "is_admin": user.is_admin,
                "created_at": user.created_at,
            }
            await coll.insert_one(doc)
            return user
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def list_users(self, status: Optional[UserStatus] = None) -> list[User]:
        query = {}
        if status:
            query["status"] = status
        try:
            # We list only from the users collection for moderation
            cursor = self._user_collection.find(query).sort("created_at", -1)
            users = []
            async for doc in cursor:
                users.append(User(
                    email=doc["email"],
                    password=doc["password"],
                    admin_name=doc.get("admin_name") or doc.get("name") or doc["email"].split("@")[0],
                    status=doc.get("status", UserStatus.PENDING),
                    is_admin=doc.get("is_admin", False),
                    created_at=doc.get("created_at", datetime.utcnow()),
                ))
            return users
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def update_user_status(self, email: str, status: UserStatus) -> bool:
        try:
            # Status updates only happen for the users collection
            result = await self._user_collection.update_one(
                {"email": email.lower()},
                {"$set": {"status": status}}
            )
            return result.modified_count > 0
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def delete_user(self, email: str) -> bool:
        try:
            # Deletion only happens for the users collection (rejecting a registration)
            result = await self._user_collection.delete_one({"email": email.lower()})
            return result.deleted_count > 0
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def get_admin_by_email(self, email: str) -> Optional[User]:
        return await self.get_user_by_email(email, is_admin=True)

    # CRUD ----------------------------------------------------------
    async def create_quote(
        self,
        content: str,
        content_hash: str,
        source: Optional[str],
        status: QuoteStatus,
        submitted_by: str,
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
                "likes": 0,
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

    async def update_quote(
        self,
        quote_id: str,
        content: Optional[str] = None,
        status: Optional[QuoteStatus] = None,
        submitted_by: Optional[str] = None,
        verified_by: Optional[str] = None,
    ) -> QuoteResponse:
        update_data = {}
        if content is not None:
            update_data["content"] = content
            update_data["content_hash"] = self.content_hash(content)
        if status is not None:
            update_data["status"] = status
            update_data["verified_at"] = self._now_iso() if status in ("APPROVED", "REJECTED") else None
        if submitted_by is not None:
            update_data["submitted_by"] = submitted_by
        if verified_by is not None:
            update_data["verified_by"] = verified_by

        try:
            updated = await self._collection.find_one_and_update(
                {"_id": quote_id},
                {"$set": update_data},
                return_document=ReturnDocument.AFTER,
            )
            if not updated:
                raise MongoDBError("Quote not found")
            return self._doc_to_quote(updated)
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

    async def latest_quote(self, status: Optional[QuoteStatus] = None) -> Optional[QuoteResponse]:
        query: dict = {}
        if status:
            query["status"] = status
        try:
            doc = (
                await self._collection.find(query)
                .sort([("created_at", -1), ("id", -1)])
                .limit(1)
                .to_list(length=1)
            )
            if not doc:
                return None
            return self._doc_to_quote(doc[0])
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

    async def increment_likes(self, quote_id: str) -> QuoteResponse:
        """Increment the likes count for a quote."""
        try:
            updated = await self._collection.find_one_and_update(
                {"_id": quote_id},
                {"$inc": {"likes": 1}, "$setOnInsert": {"likes": 1}},
                return_document=ReturnDocument.AFTER,
                upsert=False,
            )
            if not updated:
                raise MongoDBError("Quote not found")
            return self._doc_to_quote(updated)
        except PyMongoError as exc:
            raise MongoDBError(str(exc)) from exc

