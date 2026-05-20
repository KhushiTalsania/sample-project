# """
# Database Setup for Notification Service

# This module creates indexes and ensures proper database setup
# for the notification collections.
# """

# import logging
# from core.database.collections import get_collections

# logger = logging.getLogger(__name__)

# async def create_notification_indexes():
#     """
#     Create necessary indexes for notification collections.
    
#     This function should be called during application startup to ensure
#     optimal query performance for notifications.
#     """
#     try:
#         collections = get_collections()
        
#         # ========================================
#         # NOTIFICATIONS COLLECTION INDEXES
#         # ========================================
        
#         notifications_collection = collections.get_notifications_collection()
        
#         # Index for user_id + created_at (most common query)
#         await notifications_collection.create_index([
#             ("user_id", 1),
#             ("created_at", -1)
#         ], name="user_created_idx")
#         logger.info("✅ Created index: notifications.user_created_idx")
        
#         # Index for user_id + is_read (for unread count)
#         await notifications_collection.create_index([
#             ("user_id", 1),
#             ("is_read", 1)
#         ], name="user_read_idx")
#         logger.info("✅ Created index: notifications.user_read_idx")
        
#         # Index for notification_type (for filtering)
#         await notifications_collection.create_index([
#             ("notification_type", 1)
#         ], name="type_idx")
#         logger.info("✅ Created index: notifications.type_idx")
        
#         # ========================================
#         # USER_TOKENS COLLECTION INDEXES
#         # ========================================
        
#         user_tokens_collection = collections.get_user_tokens_collection()
        
#         # Index for user_id
#         await user_tokens_collection.create_index([
#             ("user_id", 1)
#         ], name="user_idx")
#         logger.info("✅ Created index: user_tokens.user_idx")
        
#         # Unique index for device_token
#         await user_tokens_collection.create_index([
#             ("device_token", 1)
#         ], name="token_idx", unique=True)
#         logger.info("✅ Created index: user_tokens.token_idx (unique)")
        
#         # Index for is_active
#         await user_tokens_collection.create_index([
#             ("is_active", 1)
#         ], name="active_idx")
#         logger.info("✅ Created index: user_tokens.active_idx")
        
#         # ========================================
#         # NOTIFICATION_PREFERENCES COLLECTION INDEXES
#         # ========================================
        
#         preferences_collection = collections.get_notification_preferences_collection()
        
#         # Unique index for user_id
#         await preferences_collection.create_index([
#             ("user_id", 1)
#         ], name="user_idx", unique=True)
#         logger.info("✅ Created index: notification_preferences.user_idx (unique)")
        
#         logger.info("✅ All notification indexes created successfully")
        
#     except Exception as e:
#         logger.error(f"❌ Error creating notification indexes: {e}")
#         # Don't fail the application if index creation fails
#         # Indexes might already exist

# async def verify_notification_collections():
#     """
#     Verify that notification collections exist and are accessible.
    
#     Returns:
#         dict: Status of each collection
#     """
#     try:
#         collections = get_collections()
        
#         status = {
#             "notifications": False,
#             "user_tokens": False,
#             "notification_preferences": False
#         }
        
#         # Check notifications collection
#         try:
#             notifications_collection = collections.get_notifications_collection()
#             count = await notifications_collection.count_documents({})
#             status["notifications"] = True
#             logger.info(f"✅ Notifications collection accessible ({count} documents)")
#         except Exception as e:
#             logger.error(f"❌ Notifications collection error: {e}")
        
#         # Check user_tokens collection
#         try:
#             user_tokens_collection = collections.get_user_tokens_collection()
#             count = await user_tokens_collection.count_documents({})
#             status["user_tokens"] = True
#             logger.info(f"✅ User tokens collection accessible ({count} documents)")
#         except Exception as e:
#             logger.error(f"❌ User tokens collection error: {e}")
        
#         # Check notification_preferences collection
#         try:
#             preferences_collection = collections.get_notification_preferences_collection()
#             count = await preferences_collection.count_documents({})
#             status["notification_preferences"] = True
#             logger.info(f"✅ Notification preferences collection accessible ({count} documents)")
#         except Exception as e:
#             logger.error(f"❌ Notification preferences collection error: {e}")
        
#         return status
        
#     except Exception as e:
#         logger.error(f"❌ Error verifying notification collections: {e}")
#         return {
#             "notifications": False,
#             "user_tokens": False,
#             "notification_preferences": False
#         }



"""
Notification Service - Database Setup

Creates indexes and verifies collections for optimal performance.
"""

import logging
from core.database.collections import get_collections

logger = logging.getLogger(__name__)

async def create_notification_indexes():
    """Create necessary indexes for all notification-related collections."""
    try:
        c = get_collections()

        # ========== Notifications ==========
        n = c.get_notifications_collection()
        await n.create_index([("user_id", 1), ("created_at", -1)], name="user_created_idx")
        await n.create_index([("user_id", 1), ("is_read", 1)], name="user_read_idx")
        await n.create_index([("notification_type", 1)], name="type_idx")
        logger.info("✅ Notifications indexes created")

        # ========== User Tokens ==========
        t = c.get_user_tokens_collection()
        await t.create_index([("user_id", 1)], name="user_idx")
        await t.create_index([("device_token", 1)], name="token_idx", unique=True)
        await t.create_index([("is_active", 1)], name="active_idx")
        logger.info("✅ User tokens indexes created")

        # ========== Preferences ==========
        p = c.get_notification_preferences_collection()
        await p.create_index([("user_id", 1)], name="user_idx", unique=True)
        logger.info("✅ Notification preferences indexes created")

    except Exception as e:
        logger.error(f"❌ Error creating notification indexes: {e}")


async def verify_notification_collections():
    """Verify that all notification collections exist and are accessible."""
    status = {}
    try:
        c = get_collections()

        for name, getter in {
            "notifications": c.get_notifications_collection,
            "user_tokens": c.get_user_tokens_collection,
            "notification_preferences": c.get_notification_preferences_collection,
        }.items():
            try:
                count = await getter().count_documents({})
                status[name] = True
                logger.info(f"✅ {name} collection accessible ({count} docs)")
            except Exception as e:
                status[name] = False
                logger.error(f"❌ {name} collection error: {e}")

    except Exception as e:
        logger.error(f"❌ Error verifying collections: {e}")
        status = {k: False for k in ["notifications", "user_tokens", "notification_preferences"]}

    return status
