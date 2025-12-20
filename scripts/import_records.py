"""
Seed InstantDB with the initial quotes from records.txt.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.instantdb import InstantDBClient, InstantDBConfig, InstantDBError  # noqa: E402
from app.localdb import LocalDBConfig, LocalDBError, LocalQuoteStore  # noqa: E402


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

    app_id = os.getenv("INSTANTDB_APP_ID")
    api_key = os.getenv("INSTANTDB_API_KEY")
    base_url = os.getenv("INSTANTDB_BASE_URL", "https://api.instantdb.com")
    quotes_path = os.getenv("INSTANTDB_QUOTES_PATH", "/v1/apps/{app_id}/collections/quotes")

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

    if not app_id or not api_key:
        print("Set INSTANTDB_APP_ID and INSTANTDB_API_KEY, or set LOCAL_MODE=1 for a fully-local demo.")
        sys.exit(1)

    cfg = InstantDBConfig(app_id=app_id, api_key=api_key, base_url=base_url, quotes_path=quotes_path)
    async with httpx.AsyncClient() as http:
        client = InstantDBClient(cfg, http)
        for content in quotes:
            content_hash = client.content_hash(content)
            # skip duplicates by hash if already present
            try:
                existing = await client.list_quotes(content_hash=content_hash, limit=1)
                if existing.items:
                    print("Skip duplicate by hash")
                    continue
            except InstantDBError as exc:
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
            except InstantDBError as exc:
                print(f"Failed to insert quote: {exc}")
                continue


if __name__ == "__main__":
    asyncio.run(main())
