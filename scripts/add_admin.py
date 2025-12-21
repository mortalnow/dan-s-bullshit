import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from datetime import datetime

async def add_admin():
    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB", "dans-bullshit")
    
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    admins_col = db["admins"]
    
    email = "admin@example.com"
    password = "password123"
    admin_name = "Admin"
    
    print(f"Adding admin {email} to {db_name}.admins...")
    
    # Check if exists
    existing = await admins_col.find_one({"email": email})
    if existing:
        print("Admin already exists. Updating password and name...")
        await admins_col.update_one(
            {"email": email},
            {"$set": {"password": password, "admin_name": admin_name}}
        )
    else:
        await admins_col.insert_one({
            "email": email,
            "password": password,
            "admin_name": admin_name,
            "created_at": datetime.utcnow()
        })
        print("Admin added successfully!")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(add_admin())

