#!/usr/bin/env python3
"""
Migration script to merge admins collection into users collection.
This is a one-time migration for the unified user system.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=dotenv_path, override=False)


async def migrate_mongo_admins():
    """Migrate admins from 'admins' collection to 'users' collection in MongoDB."""
    mongodb_uri = os.environ.get("MONGODB_URI")
    mongodb_db = os.environ.get("MONGODB_DB", "dans-bullshit")
    
    if not mongodb_uri:
        print("⚠️  MONGODB_URI not set - skipping MongoDB migration")
        return True
    
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        
        client = AsyncIOMotorClient(mongodb_uri)
        db = client[mongodb_db]
        admins_collection = db["admins"]
        users_collection = db["users"]
        
        # Get all admins
        admins_cursor = admins_collection.find({})
        admins = await admins_cursor.to_list(length=1000)
        
        if not admins:
            print("ℹ️  No admins found in 'admins' collection to migrate")
            client.close()
            return True
        
        migrated = 0
        skipped = 0
        
        for admin in admins:
            email = admin.get("email", "").lower()
            if not email:
                continue
            
            # Check if already exists in users collection
            existing = await users_collection.find_one({"email": email})
            
            if existing:
                # Update existing user to be admin
                if not existing.get("is_admin"):
                    await users_collection.update_one(
                        {"email": email},
                        {"$set": {"is_admin": True, "status": "APPROVED"}}
                    )
                    print(f"  ✅ Upgraded existing user to admin: {email}")
                    migrated += 1
                else:
                    print(f"  ⏭️  Already admin in users: {email}")
                    skipped += 1
            else:
                # Create new user with admin privileges
                user_doc = {
                    "email": email,
                    "password": admin.get("password", ""),
                    "admin_name": admin.get("admin_name") or admin.get("name") or email.split("@")[0],
                    "status": "APPROVED",
                    "is_admin": True,
                    "created_at": admin.get("created_at"),
                }
                await users_collection.insert_one(user_doc)
                print(f"  ✅ Migrated admin to users: {email}")
                migrated += 1
        
        client.close()
        print(f"\n✅ MongoDB migration complete: {migrated} migrated, {skipped} skipped")
        return True
        
    except Exception as e:
        print(f"❌ MongoDB migration error: {e}")
        return False


async def main():
    print("🔄 Migrating admins to unified users collection...\n")
    
    success = await migrate_mongo_admins()
    
    print()
    if success:
        print("✅ Migration complete!")
        print("\nNote: You can now safely remove the 'admins' collection from MongoDB")
        print("      after verifying the migration was successful.")
    else:
        print("❌ Migration failed - check errors above")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

