#!/usr/bin/env python3
"""Reset all likes counts to 0 in both local and production databases."""

import asyncio
import os
import sqlite3
import sys

from dotenv import load_dotenv

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=dotenv_path, override=False)


def reset_local_likes():
    """Reset likes in local SQLite database."""
    db_path = os.path.join(os.path.dirname(__file__), "..", "local.db")
    if not os.path.exists(db_path):
        print("❌ Local database not found at:", db_path)
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if likes column exists
        cursor.execute("PRAGMA table_info(quotes)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "likes" not in columns:
            print("⚠️  No 'likes' column in local database - nothing to reset")
            conn.close()
            return True
        
        # Reset all likes to 0
        cursor.execute("UPDATE quotes SET likes = 0")
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        print(f"✅ Local: Reset likes to 0 for {affected} quotes")
        return True
    except sqlite3.Error as e:
        print(f"❌ Local database error: {e}")
        return False


async def reset_mongo_likes():
    """Reset likes in MongoDB production database."""
    mongodb_uri = os.environ.get("MONGODB_URI")
    mongodb_db = os.environ.get("MONGODB_DB", "dans-bullshit")
    mongodb_collection = os.environ.get("MONGODB_COLLECTION", "quotes")
    
    if not mongodb_uri:
        print("⚠️  MONGODB_URI not set - skipping production reset")
        return True
    
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        
        client = AsyncIOMotorClient(mongodb_uri)
        collection = client[mongodb_db][mongodb_collection]
        
        # Reset all likes to 0
        result = await collection.update_many({}, {"$set": {"likes": 0}})
        
        client.close()
        
        print(f"✅ Production: Reset likes to 0 for {result.modified_count} quotes")
        return True
    except Exception as e:
        print(f"❌ MongoDB error: {e}")
        return False


async def main():
    print("🔄 Resetting all likes counts to 0...\n")
    
    # Reset local
    local_success = reset_local_likes()
    
    # Reset production
    mongo_success = await reset_mongo_likes()
    
    print()
    if local_success and mongo_success:
        print("✅ All likes reset successfully!")
    else:
        print("⚠️  Some resets failed - check errors above")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

