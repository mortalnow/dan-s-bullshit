import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

async def check_mongo():
    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB", "dans-bullshit")
    
    print(f"Connecting to: {uri[:20]}...")
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    
    # Check admins
    admins_col = db["admins"]
    print(f"Checking collection: {admins_col.name}")
    
    count = await admins_col.count_documents({})
    print(f"Total admins found: {count}")
    
    async for admin in admins_col.find():
        print(f"Admin: {admin.get('email')} | Name: {admin.get('admin_name')}")

    # Check quotes
    quotes_col = db["quotes"]
    q_count = await quotes_col.count_documents({})
    print(f"Total quotes found: {q_count}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check_mongo())

