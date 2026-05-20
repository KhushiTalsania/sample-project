from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
import os
from dotenv import load_dotenv
import asyncio
from pymongo import ASCENDING, DESCENDING, TEXT
import logging
from datetime import datetime, timezone
from bson import ObjectId
from typing import Optional, Tuple, List

# Setup logging
logger = logging.getLogger(__name__)

load_dotenv()

# Database configuration
MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DATABASE_NAME", "betting_main")
AUTO_SEED_ENABLED = os.getenv("AUTO_SEED_ENABLED", "true").lower() == "true"

# MongoDB client
client = AsyncIOMotorClient(
    MONGO_URL,
    tls=True,
    tlsAllowInvalidCertificates=True,  # Use only if you're in dev or staging
    serverSelectionTimeoutMS=5000,  # Reduced from 20000
    connectTimeoutMS=5000,  # Reduced from 20000
    socketTimeoutMS=10000,  # Reduced from 20000
    maxPoolSize=50,  # Connection pool size
    minPoolSize=10,  # Minimum connections in pool
    maxIdleTimeMS=30000,  # Close idle connections after 30 seconds
    waitQueueTimeoutMS=2500,  # Wait queue timeout
    retryWrites=True,
    retryReads=True
)

db = client[DB_NAME]

async def get_database():
    """Get the main database instance"""
    return db

def get_club_collection() -> AsyncIOMotorCollection:
    """Get the clubs collection"""
    return db["clubs"]

def get_user_collection() -> AsyncIOMotorCollection:
    """Get the users collection from auth service database"""
    return db["users"]

def get_membership_collection():
    """Get the club memberships collection"""
    return db["club_memberships"]

def get_trial_membership_collection():
    """Get trial membership tracking collection"""
    return db["trial_memberships"]

def get_trial_club_access_collection():
    """Get trial club access tracking collection"""
    return db["trial_club_access"]

def get_group_access_collection():
    """Get group access tracking collection"""
    return db["group_access"]

def get_refund_requests_collection():
    """Get refund requests collection"""
    return db["refund_requests"]

def get_club_payments_collection():
    """Get club payments collection for tracking Stripe transactions"""
    return db["club_payments"]

def get_webhook_events_collection():
    """Get webhook events collection for tracking Stripe webhooks"""
    return db["webhook_events"]

async def update_captain_club_count(captain_id: str, increment: bool = True) -> bool:
    """Update the club count for a captain in the auth database. Club count can only be 0 or 1."""
    try:
        logger.info(f"🔄 Starting club count update for captain {captain_id}, increment: {increment}")
        
        # Connect to auth database
        auth_db_name = os.getenv("AUTH_DATABASE_NAME", "betting_main")
        logger.info(f"🔍 Connecting to auth database: {auth_db_name}")
        auth_db = client[auth_db_name]
        users_collection = auth_db["users"]
        
        # Get current club count
        logger.info(f"🔍 Looking up user with ID: {captain_id}")
        user = await users_collection.find_one({"_id": ObjectId(captain_id)})
        if not user:
            logger.error(f"❌ Captain {captain_id} not found in auth database")
            return False
        
        current_count = user.get("club_count", 0)
        logger.info(f"🔍 Current club count for captain {captain_id}: {current_count}")
        
        # Update count - club_count can only be 0 or 1
        if increment:
            new_count = 1  # Always set to 1 when incrementing
            logger.info(f"📈 Setting club count to 1 for captain {captain_id} (was {current_count})")
        else:
            new_count = 0  # Always set to 0 when decrementing
            logger.info(f"📉 Setting club count to 0 for captain {captain_id} (was {current_count})")
        
        # Update the user's club count
        logger.info(f"🔄 Updating club count in database for captain {captain_id}")
        result = await users_collection.update_one(
            {"_id": ObjectId(captain_id)},
            {"$set": {"club_count": new_count, "updated_at": datetime.now(timezone.utc)}}
        )
        
        logger.info(f"🔍 Update result: modified_count={result.modified_count}, matched_count={result.matched_count}")
        
        if result.modified_count > 0:
            logger.info(f"✅ Successfully updated club count to {new_count} for captain {captain_id}")
            return True
        else:
            logger.warning(f"⚠️ No changes made to club count for captain {captain_id} (count may already be {new_count})")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error updating club count for captain {captain_id}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return False

async def recalculate_captain_club_count(captain_id: str) -> bool:
    """
    Recalculate and update the club count for a captain based on actual completed clubs.
    This ensures the count reflects only clubs that have completed ALL 5 steps.
    IMPORTANT: Once club_count = 1, it should never go back to 0.
    """
    try:
        # Get current club count from auth database first
        auth_db_name = os.getenv("AUTH_DATABASE_NAME", "betting_main")
        auth_db = client[auth_db_name]
        users_collection = auth_db["users"]
        
        user = await users_collection.find_one({"_id": ObjectId(captain_id)})
        if not user:
            logger.warning(f"Captain {captain_id} not found in auth database")
            return False
        
        current_club_count = user.get("club_count", 0)
        
        # Count clubs where the user is the captain and has completed ALL 5 steps
        clubs_collection = get_club_collection()
        completed_clubs_count = await clubs_collection.count_documents({
            "captain_id": captain_id,
            "is_active": True,  # Only count active clubs
            "club_complete_step": 5  # Only count clubs that have completed ALL 5 steps
        })
        
        logger.info(f"🔍 Recalculated club count for captain {captain_id}: {completed_clubs_count} completed clubs (current: {current_club_count})")
        
        # IMPORTANT: Once club_count = 1, it should never go back to 0
        # Only update if the new count is higher than current, or if current is 0 and new is 0
        if completed_clubs_count > current_club_count or (current_club_count == 0 and completed_clubs_count == 0):
            new_count = completed_clubs_count
            logger.info(f"📊 Updating club count from {current_club_count} to {new_count}")
        else:
            # Preserve the current count (don't decrease from 1 to 0)
            new_count = current_club_count
            logger.info(f"🔒 Preserving club count at {new_count} (preventing decrease from {current_club_count} to {completed_clubs_count})")
        
        result = await users_collection.update_one(
            {"_id": ObjectId(captain_id)},
            {"$set": {"club_count": new_count, "updated_at": datetime.now(timezone.utc)}}
        )
        
        if result.modified_count > 0:
            logger.info(f"✅ Updated club count to {new_count} for captain {captain_id}")
            return True
        else:
            logger.info(f"ℹ️ Club count already correct for captain {captain_id}: {new_count}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error recalculating club count for captain {captain_id}: {e}")
        return False

async def update_club_count_on_step_change(captain_id: str, club_id: str, new_step: int) -> bool:
    """
    Update club count when a club's completion step changes.
    IMPORTANT: Only recalculate for step 5 (completion), not for intermediate steps.
    """
    try:
        logger.info(f"🔄 Club step change for captain {captain_id}, club {club_id} to step {new_step}")
        
        # Only recalculate club count when reaching step 5 (completion)
        # For steps 2, 3, 4, we don't need to recalculate as club_count should remain unchanged
        if new_step == 5:
            logger.info(f"🎯 Club reached step 5, recalculating club count for captain {captain_id}")
            success = await recalculate_captain_club_count(captain_id)
            
            if success:
                logger.info(f"✅ Club count updated successfully for captain {captain_id} after step 5 completion")
            else:
                logger.warning(f"⚠️ Failed to update club count for captain {captain_id} after step 5 completion")
            
            return success
        else:
            logger.info(f"ℹ️ Skipping club count recalculation for step {new_step} (only recalculate on step 5)")
            return True
        
    except Exception as e:
        logger.error(f"❌ Error updating club count on step change for captain {captain_id}: {e}")
        return False

async def handle_club_deletion_or_deactivation(captain_id: str, club_id: str, action: str = "deletion") -> bool:
    """
    Handle club count updates when a club is deleted or deactivated.
    This ensures the count reflects only active, completed clubs.
    
    Args:
        captain_id: ID of the captain
        club_id: ID of the club being deleted/deactivated
        action: Either "deletion" or "deactivation"
    """
    try:
        logger.info(f"🗑️ Handling club {action} for captain {captain_id}, club {club_id}")
        
        # Recalculate the total club count for this captain
        success = await recalculate_captain_club_count(captain_id)
        
        if success:
            logger.info(f"✅ Club count updated successfully for captain {captain_id} after {action}")
        else:
            logger.warning(f"⚠️ Failed to update club count for captain {captain_id} after {action}")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Error handling club {action} for captain {captain_id}: {e}")
        return False

def get_admin_db():
    """Get admin database connection for inclusions and sports data"""
    admin_db_name = os.getenv("ADMIN_DATABASE_NAME", "betting_main")
    logger.info(f"Connecting to admin database: {admin_db_name}")
    admin_db = client[admin_db_name]
    return admin_db

def get_inclusions_collection():
    """Get inclusions collection from admin database"""
    try:
        admin_db = get_admin_db()
        collection = admin_db["inclusions"]
        print("collectioncollectioncollectioncollection",collection)
        logger.info(f"Successfully connected to inclusions collection in database: {admin_db.name}")
        return collection
    except Exception as e:
        logger.error(f"Error connecting to inclusions collection: {e}")
        raise

def get_sports_collection():
    """Get sports collection from admin database"""
    try:
        admin_db = get_admin_db()
        collection = admin_db["sports"]
        logger.info(f"Successfully connected to sports collection in database: {admin_db.name}")
        return collection
    except Exception as e:
        logger.error(f"Error connecting to sports collection: {e}")
        raise

async def check_database_health():
    """Check database connection health and log details"""
    try:
        logger.info("Checking database connection health...")
        logger.info(f"MongoDB URL: {MONGO_URL}")
        logger.info(f"Main database: {DB_NAME}")
        logger.info(f"Admin database: {os.getenv('ADMIN_DATABASE_NAME', 'betting_main')}")
        
        # Test main database connection
        await client.admin.command('ping')
        logger.info("✅ Main database connection successful")
        
        # Test admin database connection
        admin_db = get_admin_db()
        await admin_db.command('ping')
        logger.info("✅ Admin database connection successful")
        
        # Test inclusions collection
        inclusions_collection = get_inclusions_collection()
        count = await inclusions_collection.count_documents({})
        logger.info(f"✅ Inclusions collection accessible, document count: {count}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Database health check failed: {e}")
        return False

async def create_club_indexes():
    """Create necessary indexes for club collection"""
    club_collection = get_club_collection()
    
    try:
        # Create indexes for efficient querying
        indexes = [
            # Text index for search functionality
            [("name", TEXT), ("description", TEXT)],
            
            # Unique index for club name to prevent duplicates
            [("name", ASCENDING)],
            
            # Individual field indexes for filtering and sorting
            [("category", ASCENDING)],
            [("win_pct", DESCENDING)],
            [("member_count", DESCENDING)],
            [("created_at", DESCENDING)],
            [("captain_id", ASCENDING)],
            [("is_active", ASCENDING)],
            [("status", ASCENDING)],
            [("captain_details.full_name", ASCENDING)],
            
            # Compound indexes for common query patterns
            [("is_active", ASCENDING), ("win_pct", DESCENDING)],
            [("is_active", ASCENDING), ("created_at", DESCENDING)],
            [("is_active", ASCENDING), ("member_count", DESCENDING)],
            [("category", ASCENDING), ("is_active", ASCENDING)],
            [("captain_id", ASCENDING), ("is_active", ASCENDING)],
            [("captain_id", ASCENDING), ("status", ASCENDING)],
            [("captain_id", ASCENDING), ("created_at", DESCENDING)],
            
            # Pricing field indexes (for embedded pricing_plans array)
            [("pricing_plans.price", ASCENDING)],
            [("pricing_plans.plan", ASCENDING)],
            [("pricing_plans.stripe_product_id", ASCENDING)],
            [("pricing_plans.stripe_price_id", ASCENDING)],
        ]
        
        for index in indexes:
            try:
                # Handle unique index for club name
                if index == [("name", ASCENDING)]:
                    # Check if there are any duplicate names before creating unique index
                    duplicate_names = await club_collection.aggregate([
                        {"$group": {"_id": "$name", "count": {"$sum": 1}}},
                        {"$match": {"count": {"$gt": 1}}}
                    ]).to_list(None)
                    
                    if duplicate_names:
                        print(f"⚠️ Found duplicate club names: {[d['_id'] for d in duplicate_names]}")
                        print("⚠️ Cannot create unique index on name field due to existing duplicates")
                        print("⚠️ Please resolve duplicates before creating unique index")
                    else:
                        await club_collection.create_index(index, unique=True)
                        print(f"✅ Created unique index: {index}")
                else:
                    await club_collection.create_index(index)
                    print(f"✅ Created index: {index}")
            except Exception as e:
                print(f"⚠️ Index creation warning for {index}: {e}")
        
        print("✅ Club collection indexes created successfully")
        
    except Exception as e:
        print(f"❌ Error creating club indexes: {e}")

async def create_membership_indexes():
    """Create necessary indexes for membership collection"""
    membership_collection = get_membership_collection()
    
    try:
        # Create indexes for membership queries
        indexes = [
            # Compound indexes for common membership queries
            [("user_id", ASCENDING), ("club_id", ASCENDING)],
            [("club_id", ASCENDING), ("subscription_status", ASCENDING)],
            [("user_id", ASCENDING), ("subscription_status", ASCENDING)],
            
            # Individual field indexes
            [("user_id", ASCENDING)],
            [("club_id", ASCENDING)],
            [("subscription_status", ASCENDING)],
            [("expires_date", ASCENDING)],
            [("created_at", DESCENDING)],
            [("payment_id", ASCENDING)],
        ]
        
        for index in indexes:
            try:
                await membership_collection.create_index(index)
                print(f"✅ Created membership index: {index}")
            except Exception as e:
                print(f"⚠️ Membership index creation warning for {index}: {e}")
        
        print("✅ Membership collection indexes created successfully")
        
    except Exception as e:
        print(f"❌ Error creating membership indexes: {e}")

async def create_trial_indexes():
    """Create necessary indexes for trial-related collections"""
    
    # Trial membership indexes
    trial_collection = get_trial_membership_collection()
    trial_indexes = [
        [("user_id", ASCENDING)],
        [("trial_start_date", ASCENDING)],
        [("trial_end_date", ASCENDING)],
        [("refund_requested", ASCENDING)],
        [("refund_processed", ASCENDING)]
    ]
    
    for index in trial_indexes:
        try:
            await trial_collection.create_index(index)
            print(f"✅ Created trial membership index: {index}")
        except Exception as e:
            print(f"⚠️ Trial membership index creation warning for {index}: {e}")
    
    # Group access indexes
    group_access_collection = get_group_access_collection()
    group_indexes = [
        [("user_id", ASCENDING)],
        [("week_start_date", ASCENDING)],
        [("user_id", ASCENDING), ("week_start_date", ASCENDING)],  # Compound for unique week access
        [("last_access_date", DESCENDING)]
    ]
    
    for index in group_indexes:
        try:
            await group_access_collection.create_index(index)
            print(f"✅ Created group access index: {index}")
        except Exception as e:
            print(f"⚠️ Group access index creation warning for {index}: {e}")
    
    # Refund requests indexes
    refund_collection = get_refund_requests_collection()
    refund_indexes = [
        [("user_id", ASCENDING)],
        [("refund_id", ASCENDING)],
        [("status", ASCENDING)],
        [("requested_at", DESCENDING)],
        [("processed_at", DESCENDING)]
    ]
    
    for index in refund_indexes:
        try:
            await refund_collection.create_index(index)
            print(f"✅ Created refund request index: {index}")
        except Exception as e:
            print(f"⚠️ Refund request index creation warning for {index}: {e}")
    
    print("✅ Trial-related collection indexes created successfully")

async def create_payment_indexes():
    """Create indexes for payment and webhook collections"""
    # Club payments indexes
    payment_collection = get_club_payments_collection()
    payment_indexes = [
        [("user_id", ASCENDING)],
        [("club_id", ASCENDING)],
        [("subscription_id", ASCENDING)],
        [("stripe_customer_id", ASCENDING)],
        [("payment_intent_id", ASCENDING)],
        [("status", ASCENDING)],
        [("created_at", DESCENDING)],
        [("user_id", ASCENDING), ("club_id", ASCENDING)],
        [("subscription_id", ASCENDING), ("status", ASCENDING)]
    ]
    
    for index in payment_indexes:
        try:
            await payment_collection.create_index(index)
            print(f"✅ Created payment index: {index}")
        except Exception as e:
            print(f"⚠️ Payment index creation warning for {index}: {e}")
    
    # Webhook events indexes
    webhook_collection = get_webhook_events_collection()
    webhook_indexes = [
        [("event_id", ASCENDING)],
        [("event_type", ASCENDING)],
        [("subscription_id", ASCENDING)],
        [("customer_id", ASCENDING)],
        [("processed", ASCENDING)],
        [("created_at", DESCENDING)],
        [("event_type", ASCENDING), ("processed", ASCENDING)]
    ]
    
    for index in webhook_indexes:
        try:
            await webhook_collection.create_index(index)
            print(f"✅ Created webhook index: {index}")
        except Exception as e:
            print(f"⚠️ Webhook index creation warning for {index}: {e}")
    
    print("✅ Payment and webhook collection indexes created successfully")

async def ensure_database_setup():
    """Ensure database and indexes are properly set up"""
    try:
        # Test connection
        await client.admin.command('ping')
        print("✅ MongoDB connection successful")
        
        # Create indexes
        await create_club_indexes()
        await create_membership_indexes()
        await create_trial_indexes()
        await create_payment_indexes()
        
        return True
    except Exception as e:
        print(f"❌ Database setup failed: {e}")
        return False

# Health check function
async def check_db_health():
    """Check if database is healthy and accessible"""
    try:
        # Test club collection
        club_collection = get_club_collection()
        await club_collection.count_documents({})
        
        # Test user collection 
        user_collection = get_user_collection()
        await user_collection.count_documents({})
        
        # Test membership collection
        membership_collection = get_membership_collection()
        await membership_collection.count_documents({})
        
        # Test trial collections
        trial_collection = get_trial_membership_collection()
        await trial_collection.count_documents({})
        
        group_access_collection = get_group_access_collection()
        await group_access_collection.count_documents({})
        
        refund_collection = get_refund_requests_collection()
        await refund_collection.count_documents({})
        
        return {"status": "healthy", "databases": ["clubs", "users", "memberships", "trial_memberships", "group_access", "refund_requests"]}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# Initialize database on import
async def init_db():
    """Initialize database connection and setup"""
    success = await ensure_database_setup()
    if not success:
        print("⚠️ Database initialization failed")
        return False
    
    # Check if database is empty and seed if needed
    await auto_seed_database()
    
    return True

async def auto_seed_database():
    """Automatically seed the database if it's empty"""
    if not AUTO_SEED_ENABLED:
        print("⏭️ Auto-seeding is disabled. Set AUTO_SEED_ENABLED=true to enable.")
        return
        
    try:
        clubs_collection = get_club_collection()
        club_count = await clubs_collection.count_documents({})
        
        if club_count == 0:
            print("🌱 Database is empty. Running automatic seeding...")
            await run_seeder()
        else:
            print(f"✅ Database already contains {club_count} clubs. Skipping seeding.")
            
    except Exception as e:
        print(f"⚠️ Auto-seeding check failed: {e}")

async def run_seeder():
    """Run the seeder to populate the database with sample data"""
    try:
        import sys
        import os
        
        # Get the path to the seeder.py file
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        seeder_path = os.path.join(current_dir, "seeder.py")
        
        if os.path.exists(seeder_path):
            print(f"🚀 Running seeder from: {seeder_path}")
            
            # Import and run the seeder
            sys.path.append(current_dir)
            
            try:
                from seeder import main as seeder_main
                await seeder_main()
                print("✅ Automatic seeding completed successfully!")
            except ImportError as e:
                print(f"⚠️ Could not import seeder: {e}")
            except Exception as e:
                print(f"⚠️ Seeder execution failed: {e}")
        else:
            print(f"⚠️ Seeder file not found at: {seeder_path}")
            
    except Exception as e:
        print(f"❌ Error running automatic seeder: {e}")

# ============================================================================
# HUB DATABASE FUNCTIONS
# ============================================================================

class HubDatabase:
    """Database operations for hub entries"""
    
    def __init__(self, database):
        self.database = database
        self.hub_collection = database.hubs
        self.club_collection = database.clubs
        
    async def create_hub_indexes(self):
        """Create indexes for hub collection"""
        try:
            indexes = [
                [("club_id", 1)],
                [("club_name_based_id", 1)],
                [("hub_name_based_id", 1)],  # Unique index for hub name based ID
                [("captain_id", 1)],
                [("section", 1)],
                [("created_at", -1)],
                [("is_active", 1)],
                [("title", "text")],
                [("description", "text")],
                # Compound indexes for common query patterns
                [("club_id", 1), ("is_active", 1)],
                [("captain_id", 1), ("is_active", 1)],
                [("section", 1), ("is_active", 1)],
                [("club_id", 1), ("section", 1), ("is_active", 1)],
            ]
            
            for index in indexes:
                try:
                    await self.hub_collection.create_index(index)
                    logger.info(f"Created hub index: {index}")
                except Exception as e:
                    logger.warning(f"Index {index} might already exist: {e}")
                    
            logger.info("Hub indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating hub indexes: {e}")
            
    async def insert_hub(self, hub_data) -> Optional[str]:
        """Insert a new hub entry"""
        try:
            # Convert to dict and exclude the id field, but include _id for MongoDB
            hub_dict = hub_data.model_dump(exclude={"id"})
            result = await self.hub_collection.insert_one(hub_dict)
            if result.inserted_id:
                logger.info(f"Hub entry created with ID: {result.inserted_id}")
                return str(result.inserted_id)
            else:
                logger.error("Failed to create hub entry")
                return None
        except Exception as e:
            logger.error(f"Error inserting hub entry: {e}")
            return None
            
    async def get_hub_by_id(self, hub_id: str):
        """Get hub entry by ID"""
        try:
            if not ObjectId.is_valid(hub_id):
                logger.warning(f"Invalid hub ID format: {hub_id}")
                return None
                
            hub_doc = await self.hub_collection.find_one({"_id": ObjectId(hub_id)})
            if hub_doc:
                from .models import HubDocument
                return HubDocument(**hub_doc)
            return None
        except Exception as e:
            logger.error(f"Error getting hub by ID: {e}")
            return None
            
    async def get_hub_by_name_based_id(self, hub_name_based_id: str):
        """Get hub entry by name_based_id"""
        try:
            hub_doc = await self.hub_collection.find_one({"hub_name_based_id": hub_name_based_id})
            if hub_doc:
                from .models import HubDocument
                return HubDocument(**hub_doc)
            return None
        except Exception as e:
            logger.error(f"Error getting hub by name_based_id: {e}")
            return None
            
    async def get_hubs_by_club(self, club_id: str, limit: int = 50) -> list:
        """Get all hub entries for a specific club"""
        try:
            cursor = self.hub_collection.find({"club_id": club_id, "is_active": True})
            cursor = cursor.sort("created_at", -1).limit(limit)
            hubs = await cursor.to_list(length=limit)
            from .models import HubDocument
            return [HubDocument(**hub) for hub in hubs]
        except Exception as e:
            logger.error(f"Error getting hubs by club: {e}")
            return []
            
    async def get_hubs_by_captain(self, captain_id: str, limit: int = 50) -> list:
        """Get all hub entries created by a specific captain"""
        try:
            cursor = self.hub_collection.find({"captain_id": captain_id, "is_active": True})
            cursor = cursor.sort("created_at", -1).limit(limit)
            hubs = await cursor.to_list(length=limit)
            from .models import HubDocument
            return [HubDocument(**hub) for hub in hubs]
        except Exception as e:
            logger.error(f"Error getting hubs by captain: {e}")
            return []
            
    async def update_hub(self, hub_id: str, update_data: dict) -> bool:
        """Update a hub entry"""
        try:
            if not ObjectId.is_valid(hub_id):
                logger.warning(f"Invalid hub ID format: {hub_id}")
                return False
                
            update_data["updated_at"] = datetime.now(timezone.utc)
            result = await self.hub_collection.update_one(
                {"_id": ObjectId(hub_id)},
                {"$set": update_data}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating hub: {e}")
            return False
            
    async def delete_hub(self, hub_id: str) -> bool:
        """Soft delete a hub entry (set is_active to False)"""
        try:
            if not ObjectId.is_valid(hub_id):
                logger.warning(f"Invalid hub ID format: {hub_id}")
                return False
                
            result = await self.hub_collection.update_one(
                {"_id": ObjectId(hub_id)},
                {"$set": {"is_active": False, "deleted_at": datetime.now(timezone.utc)}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error deleting hub: {e}")
            return False
            
    async def hard_delete_hub(self, hub_id: str) -> bool:
        """Hard delete a hub entry from database"""
        try:
            if not ObjectId.is_valid(hub_id):
                logger.warning(f"Invalid hub ID format: {hub_id}")
                return False
                
            result = await self.hub_collection.delete_one({"_id": ObjectId(hub_id)})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error hard deleting hub: {e}")
            return False

    async def get_filtered_hubs(
        self,
        search: Optional[str] = None,
        club_name_based_id: Optional[str] = None,
        section: Optional[str] = None,
        captain_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        accessible_clubs: Optional[List[str]] = None
    ) -> Tuple[List, int]:
        """
        Get filtered hubs with search, filtering, and pagination
        
        Returns:
            Tuple[List, int]: (hubs_list, total_count)
        """
        try:
            logger.info(f"Database get_filtered_hubs called with: search={search}, club={club_name_based_id}, section={section}, captain_id={captain_id}, page={page}, page_size={page_size}")
            
            # First, let's check if there are any hubs in the collection at all
            total_hubs_in_collection = await self.hub_collection.count_documents({})
            logger.info(f"Total hubs in collection (all): {total_hubs_in_collection}")
            
            # Also check active hubs
            active_hubs_count = await self.hub_collection.count_documents({"is_active": True})
            logger.info(f"Total active hubs in collection: {active_hubs_count}")
            
            # Build filter query
            filter_query = {"is_active": True}
            
            # Add search filter (case-insensitive search in title and description)
            if search:
                # Use regex for case-insensitive search
                search_regex = {"$regex": search, "$options": "i"}
                filter_query["$or"] = [
                    {"title": search_regex},
                    {"description": search_regex}
                ]
            
            # Add club filter
            if club_name_based_id:
                filter_query["club_name_based_id"] = club_name_based_id
            
            # Add section filter
            if section:
                filter_query["section"] = section
            
            # Add captain filter (for authorization)
            if captain_id:
                filter_query["captain_id"] = captain_id
            
            # Add accessible clubs filter (for user access control)
            if accessible_clubs:
                filter_query["club_name_based_id"] = {"$in": accessible_clubs}
                logger.info(f"Filtering by accessible clubs: {accessible_clubs}")
            
            logger.info(f"Final database filter query: {filter_query}")
            
            # Get total count for pagination
            total_count = await self.hub_collection.count_documents(filter_query)
            logger.info(f"Total hubs found with filters: {total_count}")
            
            if total_count == 0:
                logger.info("No hubs found matching the filter criteria")
                return [], 0
            
            # Calculate skip value for pagination
            skip = (page - 1) * page_size
            logger.info(f"Pagination: skip={skip}, limit={page_size}")
            
            # Execute query with pagination
            cursor = self.hub_collection.find(filter_query)
            cursor = cursor.skip(skip).limit(page_size)
            
            # Sort by created_at (newest first by default)
            cursor = cursor.sort("created_at", -1)
            
            # Convert to list
            hubs = await cursor.to_list(length=page_size)
            logger.info(f"Retrieved {len(hubs)} hubs from database")
            
            if not hubs:
                logger.warning("Query returned no results despite total_count > 0")
                return [], total_count
            
            # Convert to HubDocument objects
            from .models import HubDocument
            hub_documents = []
            for i, hub in enumerate(hubs):
                try:
                    hub_doc = HubDocument(**hub)
                    hub_documents.append(hub_doc)
                    logger.debug(f"Successfully converted hub {i+1}: {hub.get('title', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error converting hub {i+1} to HubDocument: {e}")
                    logger.error(f"Hub data: {hub}")
                    # Continue with other hubs instead of failing completely
                    continue
            
            logger.info(f"Successfully converted {len(hub_documents)} out of {len(hubs)} hubs to HubDocument objects")
            return hub_documents, total_count
            
        except Exception as e:
            logger.error(f"Error getting filtered hubs: {e}", exc_info=True)
            return [], 0
            
    async def get_hub_statistics(self, club_name_based_id: Optional[str] = None) -> dict:
        """
        Get hub statistics (counts by section type)
        
        Args:
            club_name_based_id: Optional club filter
            
        Returns:
            dict: Statistics with counts for each section type
        """
        try:
            logger.info(f"Getting hub statistics for club: {club_name_based_id or 'all clubs'}")
            
            # Build filter query
            filter_query = {"is_active": True}
            
            # Add club filter if provided
            if club_name_based_id:
                filter_query["club_name_based_id"] = club_name_based_id
            
            # Get counts for each section type
            strategy_videos_count = await self.hub_collection.count_documents({
                **filter_query,
                "section": "strategy video"
            })
            
            training_videos_count = await self.hub_collection.count_documents({
                **filter_query,
                "section": "training video"
            })
            
            partner_links_count = await self.hub_collection.count_documents({
                **filter_query,
                "section": "partner links"
            })
            
            total_content = strategy_videos_count + training_videos_count + partner_links_count
            
            stats = {
                "total_strategy_videos": strategy_videos_count,
                "total_training_videos": training_videos_count,
                "total_partner_links": partner_links_count,
                "total_content": total_content,
                "club_name_based_id": club_name_based_id
            }
            
            logger.info(f"Hub statistics: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error getting hub statistics: {e}")
            return {
                "total_strategy_videos": 0,
                "total_training_videos": 0,
                "total_partner_links": 0,
                "total_content": 0,
                "club_name_based_id": club_name_based_id
            }

    async def get_hub_statistics_for_captain_clubs(self, club_name_based_ids: List[str]) -> dict:
        """
        Get hub statistics for multiple clubs (captain's clubs)
        
        Args:
            club_name_based_ids: List of club name-based IDs
            
        Returns:
            dict: Statistics with counts for each section type across all captain's clubs
        """
        try:
            logger.info(f"Getting hub statistics for captain's clubs: {club_name_based_ids}")
            
            # Build filter query for captain's clubs
            filter_query = {
                "is_active": True,
                "club_name_based_id": {"$in": club_name_based_ids}
            }
            
            # Get counts for each section type across all captain's clubs
            strategy_videos_count = await self.hub_collection.count_documents({
                **filter_query,
                "section": "strategy video"
            })
            
            training_videos_count = await self.hub_collection.count_documents({
                **filter_query,
                "section": "training video"
            })
            
            partner_links_count = await self.hub_collection.count_documents({
                **filter_query,
                "section": "partner links"
            })
            
            total_content = strategy_videos_count + training_videos_count + partner_links_count
            
            stats = {
                "total_strategy_videos": strategy_videos_count,
                "total_training_videos": training_videos_count,
                "total_partner_links": partner_links_count,
                "total_content": total_content,
                "club_name_based_id": None  # None indicates all captain's clubs
            }
            
            logger.info(f"Hub statistics for captain's clubs: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error getting hub statistics for captain's clubs: {e}")
            return {
                "total_strategy_videos": 0,
                "total_training_videos": 0,
                "total_partner_links": 0,
                "total_content": 0,
                "club_name_based_id": None
            }

    async def get_captain_club_statistics(self, captain_id: str) -> dict:
        """
        Get comprehensive statistics for a captain's clubs (OPTIMIZED)
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            dict: Statistics including total clubs, members, revenue, and win percentage
        """
        try:
            logger.info(f"Getting club statistics for captain: {captain_id}")
            
            # OPTIMIZATION 1: Use aggregation pipeline to calculate club stats in single query
            club_stats_pipeline = [
                {
                    "$match": {
                        "captain_id": captain_id,
                        "is_permanently_deleted": {"$ne": True},
                        "status": {"$ne": "deleted"}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_clubs": {"$sum": 1},
                        "total_members": {
                            "$sum": {
                                "$cond": [
                                    {"$gt": ["$total_members", 0]},
                                    "$total_members",
                                    {"$add": [
                                        {"$ifNull": ["$member_count", 0]},
                                        {"$ifNull": ["$paid_member_count", 0]}
                                    ]}
                                ]
                            }
                        }
                    }
                }
            ]
            
            # OPTIMIZATION 2: Run club stats, revenue, and win percentage in parallel
            import asyncio
            
            # Execute all queries in parallel for better performance
            club_stats_task = self.club_collection.aggregate(club_stats_pipeline).to_list(1)
            revenue_task = self._get_captain_revenue_optimized(captain_id)
            win_percentage_task = self._calculate_captain_win_percentage(captain_id)
            
            # Wait for all tasks to complete
            club_stats_result, total_revenue, average_win_percentage = await asyncio.gather(
                club_stats_task,
                revenue_task,
                win_percentage_task,
                return_exceptions=True
            )
            
            # Handle club stats result
            if isinstance(club_stats_result, Exception):
                logger.error(f"Error in club stats aggregation: {club_stats_result}")
                total_clubs = 0
                total_members = 0
            elif club_stats_result and len(club_stats_result) > 0:
                total_clubs = club_stats_result[0].get("total_clubs", 0)
                total_members = club_stats_result[0].get("total_members", 0)
                logger.info(f"Found {total_clubs} active clubs with {total_members} total members for captain: {captain_id}")
            else:
                logger.info(f"No active clubs found for captain: {captain_id}")
                total_clubs = 0
                total_members = 0
            
            # Handle revenue result
            if isinstance(total_revenue, Exception):
                logger.error(f"Error getting revenue: {total_revenue}")
                total_revenue = 0.0
            
            # Handle win percentage result
            if isinstance(average_win_percentage, Exception):
                logger.error(f"Error calculating win percentage: {average_win_percentage}")
                average_win_percentage = 0.0
            
            stats = {
                "total_clubs": total_clubs,
                "total_members": total_members,
                "total_revenue": round(total_revenue, 2),
                "average_win_percentage": round(average_win_percentage, 2)
            }
            
            logger.info(f"Captain {captain_id} statistics: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error getting captain club statistics: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "total_clubs": 0,
                "total_members": 0,
                "total_revenue": 0.0,
                "average_win_percentage": 0.0
            }
    
    async def _get_captain_revenue_optimized(self, captain_id: str) -> float:
        """
        Optimized method to get captain's revenue from Stripe Connect account
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            float: Total revenue
        """
        try:
            # OPTIMIZATION: Fetch only needed fields from user document
            from .db import get_user_collection
            user_collection = get_user_collection()
            captain = await user_collection.find_one(
                {"_id": ObjectId(captain_id)},
                {"stripe_connect_account_id": 1}  # Projection: only fetch this field
            )
            
            if captain and captain.get("stripe_connect_account_id"):
                stripe_connect_account_id = captain["stripe_connect_account_id"]
                logger.info(f"Captain {captain_id} has Stripe Connect account: {stripe_connect_account_id}")
                
                # Get revenue from Stripe Connect account
                import stripe
                import os
                stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
                
                try:
                    # Get balance from Stripe Connect account
                    balance = stripe.Balance.retrieve(
                        stripe_account=stripe_connect_account_id
                    )
                    
                    # Available balance in cents, convert to dollars
                    available_balance = sum([bal["amount"] for bal in balance.get("available", [])])
                    pending_balance = sum([bal["amount"] for bal in balance.get("pending", [])])
                    
                    total_revenue = (available_balance + pending_balance) / 100
                    logger.info(f"Captain {captain_id} Stripe revenue: ${total_revenue} (available: ${available_balance/100}, pending: ${pending_balance/100})")
                    return total_revenue
                    
                except stripe.error.StripeError as stripe_error:
                    logger.warning(f"Could not retrieve Stripe balance for account {stripe_connect_account_id}: {stripe_error}")
                    # Fallback: Calculate from club_payments collection
                    return await self._calculate_revenue_from_payments_optimized(captain_id)
            else:
                logger.info(f"Captain {captain_id} does not have Stripe Connect account, calculating from payments")
                # Fallback: Calculate from club_payments collection
                return await self._calculate_revenue_from_payments_optimized(captain_id)
                
        except Exception as revenue_error:
            logger.error(f"Error getting Stripe revenue for captain {captain_id}: {revenue_error}")
            # Fallback: Calculate from club_payments collection
            return await self._calculate_revenue_from_payments_optimized(captain_id)
    
    async def _calculate_captain_win_percentage(self, captain_id: str) -> float:
        """
        Calculate captain's average win percentage from club_picks
        Formula: avg_win_rate = (wins / total_picks) * 100
        where total_picks includes both completed and pending picks
        Uses picks from all clubs created by the captain (not just picks submitted by captain)
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            float: Average win percentage
        """
        try:
            from services.admin.db import club_picks_collection
            
            # Get all clubs created by this captain
            clubs = await self.club_collection.find({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            }, {"_id": 1, "name_based_id": 1}).to_list(None)
            
            if not clubs:
                logger.info(f"Captain {captain_id} has no clubs yet")
                return 0.0
            
            # Get club name-based IDs for querying picks
            club_name_based_ids = [club["name_based_id"] for club in clubs if club.get("name_based_id")]
            
            if not club_name_based_ids:
                logger.warning(f"⚠️ No valid club name-based IDs found for captain: {captain_id}")
                return 0.0
            
            # Get all picks (completed + pending) from all captain's clubs
            pipeline = [
                {
                    "$match": {
                        "club_id": {"$in": club_name_based_ids},
                        "is_active": True  # Only count active picks
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_picks": {"$sum": 1},  # Count all picks (completed + pending)
                        "total_wins": {
                            "$sum": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {"$eq": ["$status", "completed"]},
                                            {"$eq": ["$result", "win"]}
                                        ]
                                    },
                                    1,
                                    0
                                ]
                            }
                        }
                    }
                }
            ]
            
            result = await club_picks_collection.aggregate(pipeline).to_list(1)
            
            if result and result[0].get("total_picks", 0) > 0:
                total_picks = result[0]["total_picks"]
                total_wins = result[0]["total_wins"]
                win_percentage = (total_wins / total_picks) * 100
                
                logger.info(f"Captain {captain_id} win stats: {total_wins} wins out of {total_picks} total picks = {win_percentage:.2f}%")
                return win_percentage
            
            logger.info(f"Captain {captain_id} has no picks yet")
            return 0.0
            
        except Exception as e:
            logger.error(f"Error calculating captain win percentage: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return 0.0
    
    async def _calculate_revenue_from_payments_optimized(self, captain_id: str) -> float:
        """
        Optimized fallback method to calculate revenue from club_payments collection
        Uses $lookup to join clubs and payments in single aggregation pipeline
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            float: Total revenue from payments
        """
        try:
            from services.admin.db import club_payments_collection
            
            # OPTIMIZATION: Use aggregation with $lookup to avoid fetching all clubs first
            pipeline = [
                # Stage 1: Match payments with succeeded status
                {
                    "$match": {
                        "payment_status": "succeeded"
                    }
                },
                # Stage 2: Convert club_id string to ObjectId for lookup
                {
                    "$addFields": {
                        "club_object_id": {"$toObjectId": "$club_id"}
                    }
                },
                # Stage 3: Lookup club to check captain_id
                {
                    "$lookup": {
                        "from": "clubs",
                        "localField": "club_object_id",
                        "foreignField": "_id",
                        "as": "club"
                    }
                },
                # Stage 4: Unwind club array
                {
                    "$unwind": {
                        "path": "$club",
                        "preserveNullAndEmptyArrays": False
                    }
                },
                # Stage 5: Match captain_id and non-deleted clubs
                {
                    "$match": {
                        "club.captain_id": captain_id,
                        "club.status": {"$ne": "deleted"}
                    }
                },
                # Stage 6: Group and sum amounts
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": "$amount"}
                    }
                }
            ]
            
            result = await club_payments_collection.aggregate(pipeline).to_list(1)
            
            if result:
                total_revenue = result[0].get("total", 0.0)
                logger.info(f"Calculated revenue from payments for captain {captain_id}: ${total_revenue}")
                return total_revenue
            
            return 0.0
            
        except Exception as e:
            logger.error(f"Error calculating revenue from payments: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return 0.0
    
    async def _calculate_revenue_from_payments(self, captain_id: str) -> float:
        """
        Legacy method - calls optimized version
        Kept for backward compatibility
        """
        return await self._calculate_revenue_from_payments_optimized(captain_id) 