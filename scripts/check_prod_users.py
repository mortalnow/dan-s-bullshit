import asyncio
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

async def list_users():
    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB", "dans-bullshit")
    
    if not uri:
        print("Error: MONGODB_URI not set")
        return

    print(f"Connecting to MongoDB...")
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    users_col = db["users"]
    
    count = await users_col.count_documents({})
    print(f"Total users found: {count}")
    
    async for user in users_col.find():
        print(f"User: {user.get('email')} | Admin: {user.get('is_admin')} | Status: {user.get('status')} | Name: {user.get('admin_name')}")
    
    # Also check the old admins collection just in case migration wasn't run
    admins_col = db["admins"]
    admin_count = await admins_col.count_documents({})
    if admin_count > 0:
        print(f"\nFound {admin_count} users in OLD 'admins' collection (migration might be needed):")
        async for admin in admins_col.find():
            print(f"Admin (OLD): {admin.get('email')}")

    client.close()

if __name__ == "__main__":
    asyncio.run(list_users())

