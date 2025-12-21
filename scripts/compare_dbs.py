import asyncio
import os
import sqlite3
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

async def compare_dbs():
    load_dotenv()
    
    # Remote MongoDB info
    mongo_uri = os.getenv("MONGODB_URI")
    mongo_db_name = os.getenv("MONGODB_DB", "dans-bullshit")
    
    if not mongo_uri:
        print("Error: MONGODB_URI not found in .env")
        return

    # Local SQLite info
    sqlite_path = "local.db"
    
    print("--- Database Comparison ---")
    
    # 1. Connect to MongoDB
    print(f"Connecting to MongoDB Atlas...")
    mongo_client = AsyncIOMotorClient(mongo_uri)
    mongo_db = mongo_client[mongo_db_name]
    
    # 2. Connect to SQLite
    print(f"Connecting to Local SQLite ({sqlite_path})...")
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    
    try:
        # Compare Quotes
        m_quotes_count = await mongo_db["quotes"].count_documents({})
        s_quotes_count = sqlite_conn.execute("SELECT count(*) FROM quotes").fetchone()[0]
        
        print(f"\n[Quotes]")
        print(f"  Remote (Mongo): {m_quotes_count}")
        print(f"  Local (SQLite): {s_quotes_count}")
        print(f"  Difference:     {m_quotes_count - s_quotes_count}")
        
        # Compare Users
        m_users_count = await mongo_db["users"].count_documents({})
        s_users_count = sqlite_conn.execute("SELECT count(*) FROM users").fetchone()[0]
        
        print(f"\n[Users]")
        print(f"  Remote (Mongo): {m_users_count}")
        print(f"  Local (SQLite): {s_users_count}")
        print(f"  Difference:     {m_users_count - s_users_count}")
        
        # Compare Admins (if separate collection or filtered)
        m_admins_count = await mongo_db["admins"].count_documents({})
        s_admins_count = sqlite_conn.execute("SELECT count(*) FROM users WHERE is_admin = 1").fetchone()[0]
        
        print(f"\n[Admins]")
        print(f"  Remote (Mongo): {m_admins_count}")
        print(f"  Local (SQLite): {s_admins_count}")
        print(f"  Difference:     {m_admins_count - s_admins_count}")
        
        # Let's see some specific diffs for quotes (e.g., content hashes)
        print("\nChecking for missing quotes...")
        # Get all local hashes
        s_hashes = set(row['content_hash'] for row in sqlite_conn.execute("SELECT content_hash FROM quotes").fetchall())
        
        # Get remote hashes
        m_hashes = set()
        async for q in mongo_db["quotes"].find({}, {"content_hash": 1}):
            m_hashes.add(q.get("content_hash"))
            
        missing_locally = m_hashes - s_hashes
        missing_remotely = s_hashes - m_hashes
        
        if missing_locally:
            print(f"  - {len(missing_locally)} quotes on remote but NOT local.")
            print("    Examples:")
            async for q in mongo_db["quotes"].find({"content_hash": {"$in": list(missing_locally)}}).limit(3):
                content = q.get('content', '')[:50] + "..." if len(q.get('content', '')) > 50 else q.get('content')
                print(f"      * {content}")
        else:
            print("  - All remote quotes exist locally.")
            
        if missing_remotely:
            print(f"  - {len(missing_remotely)} quotes on local but NOT remote.")
            print("    Examples:")
            placeholders = ','.join('?' for _ in missing_remotely)
            rows = sqlite_conn.execute(f"SELECT content FROM quotes WHERE content_hash IN ({placeholders}) LIMIT 3", list(missing_remotely)).fetchall()
            for r in rows:
                content = r['content'][:50] + "..." if len(r['content']) > 50 else r['content']
                print(f"      * {content}")
        else:
            print("  - All local quotes exist on remote.")

    except Exception as e:
        print(f"Error during comparison: {e}")
    finally:
        mongo_client.close()
        sqlite_conn.close()

if __name__ == "__main__":
    asyncio.run(compare_dbs())
