from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
import os
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, TEXT
from datetime import datetime, timedelta

load_dotenv()

# Database configuration
MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DATABASE_NAME", "betting_main")

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

def get_database():
    """Get the database instance"""
    return db

# Collection getters
def get_messages_collection() -> AsyncIOMotorCollection:
    """Get the chat messages collection"""
    return db["chat_messages"]

def get_user_access_collection() -> AsyncIOMotorCollection:
    """Get the user access collection for club chat permissions"""
    return db["user_access"]

def get_users_collection() -> AsyncIOMotorCollection:
    """Get the users collection"""
    return db["users"]

def get_unread_tracking_collection() -> AsyncIOMotorCollection:
    """Get the unread message tracking collection"""
    return db["unread_tracking"]

def get_connected_users_collection() -> AsyncIOMotorCollection:
    """Get the connected users collection (moved to core/socket)"""
    return db["connected_users"]

def get_threads_collection() -> AsyncIOMotorCollection:
    """Get the threads collection for club chat threads"""
    return db["threads"]

def get_thread_messages_collection() -> AsyncIOMotorCollection:
    """Get the thread messages collection for thread-specific messages"""
    return db["thread_messages"]

def get_dm_requests_collection() -> AsyncIOMotorCollection:
    """Get the DM requests collection for direct message requests"""
    return db["dm_requests"]

def get_dm_messages_collection() -> AsyncIOMotorCollection:
    """Get the DM messages collection for direct messages"""
    return db["dm_messages"]

def get_dm_blocks_collection() -> AsyncIOMotorCollection:
    """Get the DM blocks collection for blocked users"""
    return db["dm_blocks"]

def get_user_collection() -> AsyncIOMotorCollection:
    """Get the users collection from auth service database"""
    auth_db_name = os.getenv("AUTH_DATABASE_NAME", "betting_main")
    print(f"🔍 Using auth database: {auth_db_name}")
    auth_db = client[auth_db_name]
    return auth_db["users"]

def get_club_collection() -> AsyncIOMotorCollection:
    """Get the clubs collection from club service database"""
    club_db_name = os.getenv("CLUB_DATABASE_NAME", "betting_main")
    print(f"🔍 Using club database: {club_db_name}")
    club_db = client[club_db_name]
    return club_db["clubs"]

def get_club_memberships_collection() -> AsyncIOMotorCollection:
    """Get the club memberships collection"""
    club_db_name = os.getenv("CLUB_DATABASE_NAME", "betting_main")
    print(f"🔍 Using club database for memberships: {club_db_name}")
    club_db = client[club_db_name]
    print(f"🔍 Using club database for memberships: {club_db_name}")
    return club_db["club_memberships"]

def get_membership_collection() -> AsyncIOMotorCollection:
    """Get the membership collection (alias for club_memberships_collection)"""
    return get_club_memberships_collection()

async def create_chat_indexes():
    """Create necessary indexes for chat collections"""
    
    # Messages collection indexes
    messages_collection = get_messages_collection()
    message_indexes = [
        # Basic queries
        [("club_id", ASCENDING), ("created_at", DESCENDING)],
        [("message_id", ASCENDING)],
        [("sender_id", ASCENDING)],
        
        # Pagination and filtering
        [("club_id", ASCENDING), ("is_deleted", ASCENDING), ("created_at", DESCENDING)],
        [("club_id", ASCENDING), ("message_type", ASCENDING)],
        
        # Pinned messages
        [("club_id", ASCENDING), ("pinned", ASCENDING)],
        
        # Reply threads
        [("reply_to_message_id", ASCENDING)],
        
        # Text search for mentions and content
        [("content.text", TEXT)],
        
        # Reactions
        [("reactions.user_id", ASCENDING)],
        
        # Cleanup queries
        [("created_at", ASCENDING)],  # For TTL or cleanup
    ]
    
    for index in message_indexes:
        try:
            await messages_collection.create_index(index)
            print(f"✅ Created messages index: {index}")
        except Exception as e:
            print(f"⚠️ Messages index creation warning for {index}: {e}")
    
    # User access collection indexes
    user_access_collection = get_user_access_collection()
    access_indexes = [
        # Primary access queries
        [("user_id", ASCENDING), ("club_id", ASCENDING)],
        [("club_id", ASCENDING), ("role", ASCENDING)],
        [("club_id", ASCENDING), ("is_muted", ASCENDING)],
        
        # Mute management
        [("user_id", ASCENDING), ("is_muted", ASCENDING)],
        [("muted_until", ASCENDING)],  # For automatic unmuting
        
        # Activity tracking
        [("last_seen", DESCENDING)],
        [("club_id", ASCENDING), ("last_seen", DESCENDING)],
    ]
    
    for index in access_indexes:
        try:
            await user_access_collection.create_index(index)
            print(f"✅ Created user access index: {index}")
        except Exception as e:
            print(f"⚠️ User access index creation warning for {index}: {e}")
    
    # Unread tracking collection indexes
    unread_collection = get_unread_tracking_collection()
    unread_indexes = [
        # Primary unread queries
        [("user_id", ASCENDING), ("club_id", ASCENDING)],
        [("user_id", ASCENDING), ("unread_count", DESCENDING)],
        
        # Cleanup and maintenance
        [("last_read_at", ASCENDING)],
        [("updated_at", ASCENDING)],
    ]
    
    for index in unread_indexes:
        try:
            await unread_collection.create_index(index)
            print(f"✅ Created unread tracking index: {index}")
        except Exception as e:
            print(f"⚠️ Unread tracking index creation warning for {index}: {e}")
    
    # Connected users collection indexes
    connected_collection = get_connected_users_collection()
    connected_indexes = [
        # Socket.IO management (moved to core/socket)
        [("socket_id", ASCENDING)],
        [("user_id", ASCENDING), ("club_id", ASCENDING)],
        [("club_id", ASCENDING)],
        
        # Cleanup inactive connections
        [("last_activity", ASCENDING)],
        [("connected_at", ASCENDING)],
    ]
    
    for index in connected_indexes:
        try:
            await connected_collection.create_index(index)
            print(f"✅ Created connected users index: {index}")
        except Exception as e:
            print(f"⚠️ Connected users index creation warning for {index}: {e}")
    
    print("✅ Chat collection indexes created successfully")

async def create_ttl_indexes():
    """Create TTL (Time To Live) indexes for automatic cleanup"""
    
    try:
        # Connected users TTL - cleanup after 1 hour of inactivity
        connected_collection = get_connected_users_collection()
        await connected_collection.create_index(
            "last_activity", 
            expireAfterSeconds=3600  # 1 hour
        )
        print("✅ Created TTL index for connected users (1 hour)")
        
    except Exception as e:
        print(f"⚠️ TTL index creation warning: {e}")

async def create_thread_indexes():
    """Create indexes for thread collections"""
    try:
        # Threads collection indexes
        threads_collection = get_threads_collection()
        
        # Index for club_id and status for efficient filtering
        await threads_collection.create_index([
            ("club_id", ASCENDING),
            ("status", ASCENDING)
        ])
        
        # Index for sorting by last_message_at
        await threads_collection.create_index([
            ("club_id", ASCENDING),
            ("last_message_at", DESCENDING)
        ])
        
        # Index for sorting by created_at
        await threads_collection.create_index([
            ("club_id", ASCENDING),
            ("created_at", DESCENDING)
        ])
        
        # Index for sorting by message_count
        await threads_collection.create_index([
            ("club_id", ASCENDING),
            ("message_count", DESCENDING)
        ])
        
        # Index for parent_message_id lookup
        await threads_collection.create_index("parent_message_id")
        
        print("✅ Thread indexes created successfully")
        
        # Thread messages collection indexes
        thread_messages_collection = get_thread_messages_collection()
        
        # Index for thread_id and created_at for efficient message retrieval
        await thread_messages_collection.create_index([
            ("thread_id", ASCENDING),
            ("created_at", ASCENDING)
        ])
        
        # Index for club_id and created_at for cross-thread queries
        await thread_messages_collection.create_index([
            ("club_id", ASCENDING),
            ("created_at", ASCENDING)
        ])
        
        print("✅ Thread message indexes created successfully")
        
    except Exception as e:
        print(f"⚠️ Thread index creation warning: {e}")

async def create_dm_indexes():
    """Create indexes for DM collections"""
    try:
        # DM Requests indexes
        dm_requests_collection = get_dm_requests_collection()
        await dm_requests_collection.create_index([("sender_id", ASCENDING), ("club_id", ASCENDING)])
        await dm_requests_collection.create_index([("receiver_id", ASCENDING), ("club_id", ASCENDING)])
        await dm_requests_collection.create_index([("club_id", ASCENDING), ("status", ASCENDING)])
        await dm_requests_collection.create_index([("club_id", ASCENDING), ("created_at", DESCENDING)])
        await dm_requests_collection.create_index([("sender_id", ASCENDING), ("receiver_id", ASCENDING), ("club_id", ASCENDING)], unique=True)
        print("✅ DM requests indexes created successfully")
        
        # DM Messages indexes
        dm_messages_collection = get_dm_messages_collection()
        await dm_messages_collection.create_index([("sender_id", ASCENDING), ("receiver_id", ASCENDING), ("club_id", ASCENDING)])
        await dm_messages_collection.create_index([("receiver_id", ASCENDING), ("sender_id", ASCENDING), ("club_id", ASCENDING)])
        await dm_messages_collection.create_index([("club_id", ASCENDING), ("created_at", DESCENDING)])
        await dm_messages_collection.create_index([("sender_id", ASCENDING), ("club_id", ASCENDING), ("created_at", DESCENDING)])
        await dm_messages_collection.create_index([("receiver_id", ASCENDING), ("club_id", ASCENDING), ("created_at", DESCENDING)])
        
        # Additional indexes for optimized aggregation queries
        await dm_messages_collection.create_index([("club_id", ASCENDING), ("sender_id", ASCENDING), ("receiver_id", ASCENDING), ("created_at", DESCENDING)])
        await dm_messages_collection.create_index([("club_id", ASCENDING), ("receiver_id", ASCENDING), ("sender_id", ASCENDING), ("created_at", DESCENDING)])
        await dm_messages_collection.create_index([("club_id", ASCENDING), ("receiver_id", ASCENDING), ("read_at", ASCENDING)])
        print("✅ DM messages indexes created successfully")
        
        # DM Blocks indexes
        dm_blocks_collection = get_dm_blocks_collection()
        await dm_blocks_collection.create_index([("blocker_id", ASCENDING), ("blocked_id", ASCENDING), ("club_id", ASCENDING)], unique=True)
        await dm_blocks_collection.create_index([("blocked_id", ASCENDING), ("club_id", ASCENDING)])
        await dm_blocks_collection.create_index([("club_id", ASCENDING), ("created_at", DESCENDING)])
        print("✅ DM blocks indexes created successfully")
        
        # Users collection indexes for DM lookups (from auth database)
        try:
            users_collection = get_user_collection()
            await users_collection.create_index([("username", ASCENDING)])
            await users_collection.create_index([("full_name", ASCENDING)])
            # Text index for search functionality
            await users_collection.create_index([("username", TEXT), ("full_name", TEXT)])
            print("✅ Users collection indexes created successfully")
        except Exception as e:
            print(f"⚠️ Users collection index creation warning: {e}")
    except Exception as e:
        print(f"⚠️ DM index creation warning: {e}")

async def ensure_database_setup():
    """Ensure database and indexes are properly set up"""
    try:
        # Test connection
        await client.admin.command('ping')
        print("✅ MongoDB connection successful")
        
        # Create indexes
        await create_chat_indexes()
        await create_ttl_indexes()
        await create_thread_indexes()
        await create_dm_indexes()
        
        # Create unique constraints
        await create_unique_constraints()
        
        return True
    except Exception as e:
        print(f"❌ Database setup failed: {e}")
        return False

async def create_unique_constraints():
    """Create unique constraints for data integrity"""
    try:
        # Unique message IDs
        messages_collection = get_messages_collection()
        await messages_collection.create_index("message_id", unique=True)
        
        # Unique user access per club
        user_access_collection = get_user_access_collection()
        await user_access_collection.create_index(
            [("user_id", ASCENDING), ("club_id", ASCENDING)], 
            unique=True
        )
        
        # Unique unread tracking per user per club
        unread_collection = get_unread_tracking_collection()
        await unread_collection.create_index(
            [("user_id", ASCENDING), ("club_id", ASCENDING)], 
            unique=True
        )
        
        # Unique socket connections (moved to core/socket)
        connected_collection = get_connected_users_collection()
        await connected_collection.create_index("socket_id", unique=True)
        
        print("✅ Unique constraints created successfully")
        
    except Exception as e:
        print(f"⚠️ Unique constraints creation warning: {e}")

async def check_db_health():
    """Check if database is healthy and accessible"""
    try:
        # Test all collections
        collections_to_test = [
            ("chat_messages", get_messages_collection()),
            ("user_access", get_user_access_collection()),
            ("unread_tracking", get_unread_tracking_collection()),
            ("connected_users", get_connected_users_collection()),
            ("threads", get_threads_collection()),
            ("thread_messages", get_thread_messages_collection()),
            ("users", get_user_collection()),
            ("clubs", get_club_collection()),
            ("club_memberships", get_club_memberships_collection()),
        ]
        
        for name, collection in collections_to_test:
            await collection.count_documents({})
            
        return {
            "status": "healthy", 
            "databases": [
                "chat_messages", "user_access", "unread_tracking", 
                "connected_users", "threads", "thread_messages",
                "users", "clubs", "club_memberships"
            ]
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# Initialize database on import
async def init_db():
    """Initialize database connection and setup"""
    success = await ensure_database_setup()
    if not success:
        print("⚠️ Database initialization failed")
    return success

# Utility functions for database operations
async def cleanup_inactive_connections():
    """Cleanup inactive socket connections (moved to core/socket)"""
    try:
        connected_collection = get_connected_users_collection()
        
        # Remove connections older than 1 hour
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        result = await connected_collection.delete_many({
            "last_activity": {"$lt": cutoff_time}
        })
        
        print(f"🧹 Cleaned up {result.deleted_count} inactive connections")
        return result.deleted_count
        
    except Exception as e:
        print(f"❌ Connection cleanup failed: {e}")
        return 0

async def cleanup_old_unread_tracking():
    """Cleanup old unread tracking records"""
    try:
        unread_collection = get_unread_tracking_collection()
        
        # Remove tracking for users who haven't been active in 30 days
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        result = await unread_collection.delete_many({
            "updated_at": {"$lt": cutoff_time},
            "unread_count": 0
        })
        
        print(f"🧹 Cleaned up {result.deleted_count} old unread tracking records")
        return result.deleted_count
        
    except Exception as e:
        print(f"❌ Unread tracking cleanup failed: {e}")
        return 0 