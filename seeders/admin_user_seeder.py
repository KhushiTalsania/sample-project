"""
Admin User Seeder
Creates 4 admin users for testing purposes
"""

import asyncio
import sys
import os
from datetime import datetime
from bson import ObjectId

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from core.auth.password_utils import get_password_utils


class AdminUserSeeder:
    def __init__(self):
        load_dotenv()
        self.mongo_url = os.getenv('MONGO_URL', 'mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main')
        self.client = None
        self.db = None
        self.password_utils = get_password_utils()
        
    async def connect(self):
        """Connect to MongoDB"""
        self.client = AsyncIOMotorClient(self.mongo_url)
        self.db = self.client['betting_main']
        print("✅ Connected to MongoDB")
        
    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            print("✅ Disconnected from MongoDB")
    
    async def seed_admin_users(self):
        """Seed admin users"""
        print("🌱 Seeding admin users...")
        print("="*50)
        
        # Admin users data
        admin_users = [
            {
                "email": "tj@mailinator.com",
                "password": "Admin@1234",
                "name": "TJ Admin",
                "role": "admin",
                "avatar_url": "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=150&h=150&fit=crop&crop=face"
            },
            {
                "email": "qa@mailinator.com", 
                "password": "Admin@1234",
                "name": "QA Admin",
                "role": "admin",
                "avatar_url": "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=150&h=150&fit=crop&crop=face"
            },
            {
                "email": "dev@mailinator.com",
                "password": "Admin@1234", 
                "name": "Dev Admin",
                "role": "admin",
                "avatar_url": "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=150&h=150&fit=crop&crop=face"
            },
            {
                "email": "uat@mailinator.com",
                "password": "Admin@1234",
                "name": "UAT Admin", 
                "role": "admin",
                "avatar_url": "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=150&h=150&fit=crop&crop=face"
            }
        ]
        
        # Get admins collection
        admins_collection = self.db['admins']
        
        # Clear existing admin users first
        await admins_collection.delete_many({})
        print("🗑️ Cleared existing admin users")
        
        # Create admin users
        created_users = []
        for user_data in admin_users:
            try:
                # Hash the password
                hashed_password = self.password_utils.hash_password(user_data['password'])
                
                # Create admin document
                admin_doc = {
                    "_id": ObjectId(),
                    "email": user_data['email'],
                    "password_hash": hashed_password,
                    "name": user_data['name'],
                    "role": user_data['role'],
                    "avatar_url": user_data['avatar_url'],
                    "is_active": True,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
                
                # Insert into database
                result = await admins_collection.insert_one(admin_doc)
                
                created_users.append({
                    "id": str(result.inserted_id),
                    "email": user_data['email'],
                    "name": user_data['name'],
                    "role": user_data['role'],
                    "avatar_url": user_data['avatar_url']
                })
                
                print(f"✅ Created admin: {user_data['email']} ({user_data['name']})")
                
            except Exception as e:
                print(f"❌ Error creating admin {user_data['email']}: {e}")
        
        print(f"\n📊 Summary:")
        print(f"✅ Total admin users created: {len(created_users)}")
        print(f"✅ Collection: admins")
        
        return created_users
    
    async def verify_seeded_users(self):
        """Verify that the seeded users exist and can be retrieved"""
        print("\n🔍 Verifying seeded admin users...")
        print("="*50)
        
        admins_collection = self.db['admins']
        
        # Count total admins
        total_count = await admins_collection.count_documents({})
        print(f"📊 Total admins in database: {total_count}")
        
        # Get all admins
        admins = []
        async for admin in admins_collection.find({}):
            admins.append({
                "id": str(admin['_id']),
                "email": admin['email'],
                "name": admin['name'],
                "role": admin['role'],
                "avatar_url": admin.get('avatar_url', ''),
                "is_active": admin.get('is_active', False)
            })
        
        print(f"\n👥 Admin users:")
        for admin in admins:
            print(f"  📧 {admin['email']} - {admin['name']} ({admin['role']}) - Active: {admin['is_active']}")
        
        return admins


async def main():
    """Main function to run the seeder"""
    seeder = AdminUserSeeder()
    
    try:
        await seeder.connect()
        await seeder.seed_admin_users()
        await seeder.verify_seeded_users()
        print("\n🎉 Admin user seeding completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during seeding: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await seeder.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
