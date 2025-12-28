import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from .models import QuoteListResponse, QuoteResponse, QuoteStatus


class InstantDBError(Exception):
    """Raised when InstantDB operations fail."""


@dataclass
class InstantDBConfig:
    app_id: str
    api_key: str
    base_url: str = "https://api.instantdb.com"
    quotes_path: str = "/v1/apps/{app_id}/collections/quotes"

    def formatted_quotes_path(self) -> str:
        return self.quotes_path.format(app_id=self.app_id)

    def quote_detail_path(self, quote_id: str) -> str:
        path = self.formatted_quotes_path()
        if not path.endswith("/"):
            path = f"{path}/"
        return f"{path}{quote_id}"


class InstantDBClient:
    """
    Thin HTTP client for InstantDB.
    The exact REST shape may vary; paths/base URL are env-configurable.
    """

    def __init__(self, config: InstantDBConfig, http: httpx.AsyncClient):
        self.config = config
        self.http = http

    # Utility -----------------------------------------------------
    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"

    # CRUD --------------------------------------------------------
    async def create_quote(
        self,
        content: str,
        content_hash: str,
        source: Optional[str],
        status: QuoteStatus,
        submitted_by: str,
    ) -> QuoteResponse:
        payload: Dict[str, Any] = {
            "content": content,
            "content_hash": content_hash,
            "source": source,
            "status": status,
            "submitted_by": submitted_by,
        }
        url = self._url(self.config.formatted_quotes_path())
        resp = await self.http.post(url, json=payload, headers=self._headers(), timeout=10)
        if resp.status_code >= 300:
            raise InstantDBError(f"InstantDB create failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return QuoteResponse(**data)

    async def get_quote(self, quote_id: str) -> Optional[QuoteResponse]:
        url = self._url(self.config.quote_detail_path(quote_id))
        resp = await self.http.get(url, headers=self._headers(), timeout=10)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 300:
            raise InstantDBError(f"InstantDB get failed: {resp.status_code} {resp.text}")
        return QuoteResponse(**resp.json())

    async def list_quotes(
        self,
        status: Optional[QuoteStatus] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
        content_hash: Optional[str] = None,
        submitted_by: Optional[str] = None,
    ) -> QuoteListResponse:
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        if content_hash:
            params["content_hash"] = content_hash
        if submitted_by:
            params["submitted_by"] = submitted_by
        url = self._url(self.config.formatted_quotes_path())
        resp = await self.http.get(url, headers=self._headers(), params=params, timeout=10)
        if resp.status_code >= 300:
            raise InstantDBError(f"InstantDB list failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return QuoteListResponse(**data)

    async def update_status(
        self,
        quote_id: str,
        status: QuoteStatus,
        verified_by: Optional[str] = None,
    ) -> QuoteResponse:
        payload: Dict[str, Any] = {"status": status, "verified_by": verified_by}
        url = self._url(self.config.quote_detail_path(quote_id))
        resp = await self.http.patch(url, json=payload, headers=self._headers(), timeout=10)
        if resp.status_code >= 300:
            raise InstantDBError(f"InstantDB update failed: {resp.status_code} {resp.text}")
        return QuoteResponse(**resp.json())

    async def random_approved(self) -> Optional[QuoteResponse]:
        # Fetch a small batch and pick randomly client-side.
        quotes = await self.list_quotes(status="APPROVED", limit=50)
        if not quotes.items:
            return None
        import random

        return random.choice(quotes.items)

