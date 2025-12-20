"""
Seed MongoDB Atlas (or local SQLite) with the initial quotes from records.txt.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.localdb import LocalDBConfig, LocalDBError, LocalQuoteStore  # noqa: E402
from app.mongostore import MongoConfig, MongoDBError, MongoQuoteStore  # noqa: E402


def parse_quotes(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\d+\.\s*(.*)", line)
        if m:
            content = m.group(1).strip()
            if content:
                items.append(content)
    return items


async def main():
    records_path = ROOT / "records.txt"
    if not records_path.exists():
        print(f"records.txt not found at {records_path}")
        sys.exit(1)

    load_dotenv(dotenv_path=ROOT / ".env", override=False)

    local_raw = (os.getenv("LOCAL_MODE") or "").strip().lower()
    local_mode = local_raw in ("1", "true", "yes", "on")
    local_db_path = os.getenv("LOCAL_DB_PATH", "local.db")
    mongodb_uri = os.getenv("MONGODB_URI")
    mongodb_db = os.getenv("MONGODB_DB", "dans-bullshit")
    mongodb_collection = os.getenv("MONGODB_COLLECTION", "quotes")

    raw_text = records_path.read_text(encoding="utf-8")
    quotes = parse_quotes(raw_text)
    print(f"Parsed {len(quotes)} quotes from {records_path}")

    if local_mode:
        client = LocalQuoteStore(LocalDBConfig(path=local_db_path))
        for content in quotes:
            content_hash = client.content_hash(content)
            try:
                existing = await client.list_quotes(content_hash=content_hash, limit=1)
                if existing.items:
                    print("Skip duplicate by hash")
                    continue
            except LocalDBError as exc:
                print(f"Lookup failed, attempting insert anyway: {exc}")
            try:
                created = await client.create_quote(
                    content=content,
                    content_hash=content_hash,
                    source="records.txt",
                    status="APPROVED",
                    submitted_by=None,
                )
                print(f"Inserted: {created.id}")
            except LocalDBError as exc:
                print(f"Failed to insert quote: {exc}")
        return

    if not mongodb_uri:
        print("Set MONGODB_URI for MongoDB Atlas (or set LOCAL_MODE=1 for local).")
        sys.exit(1)

    mongo_client = AsyncIOMotorClient(mongodb_uri)
    store = MongoQuoteStore(
        MongoConfig(uri=mongodb_uri, db=mongodb_db, collection=mongodb_collection),
        mongo_client,
    )
    await store.ensure_indexes()
    try:
        for content in quotes:
            content_hash = store.content_hash(content)
            # skip duplicates by hash if already present
            try:
                existing = await store.list_quotes(content_hash=content_hash, limit=1)
                if existing.items:
                    print("Skip duplicate by hash")
                    continue
            except MongoDBError as exc:
                print(f"Lookup failed, attempting insert anyway: {exc}")
            try:
                created = await store.create_quote(
                    content=content,
                    content_hash=content_hash,
                    source="records.txt",
                    status="APPROVED",
                    submitted_by=None,
                )
                print(f"Inserted: {created.id}")
            except MongoDBError as exc:
                print(f"Failed to insert quote: {exc}")
                continue
    finally:
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
