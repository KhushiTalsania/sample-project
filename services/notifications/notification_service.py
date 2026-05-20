# """
# Notification Service

# This module provides comprehensive notification management functionality including:
# - Sending push notifications via Firebase Cloud Messaging
# - Managing user device tokens
# - Notification history tracking
# - Notification preferences management
# """

# import logging
# from datetime import datetime, timezone
# from typing import List, Optional, Dict, Any
# from bson import ObjectId
# import asyncio

# from core.database.collections import get_collections
# from .firebase_config import (
#     send_push_notification,
#     send_multicast_notification,
#     send_topic_notification
# )

# logger = logging.getLogger(__name__)

# # ========================================
# # DEVICE TOKEN MANAGEMENT
# # ========================================

# async def register_device_token(
#     user_id: str,
#     device_token: str,
#     device_type: str,
#     device_name: Optional[str] = None,
#     device_id: Optional[str] = None
# ) -> dict:
#     """
#     Register a device token for push notifications.
    
#     Args:
#         user_id: User ID
#         device_token: FCM device token
#         device_type: Type of device (ios, android, web)
#         device_name: Device name/model (optional)
#         device_id: Unique device identifier (optional)
        
#     Returns:
#         dict: Registration result with token_id
#     """
#     try:
#         logger.info(f"🔍 Registering device token for user {user_id}")
#         logger.info(f"   Device type: {device_type}, Device name: {device_name}")
        
#         collections = get_collections()
#         user_tokens_collection = collections.get_user_tokens_collection()
        
#         logger.info(f"🔍 Checking for existing token...")
        
#         # Check if token already exists for this user
#         existing_token = await user_tokens_collection.find_one({
#             "user_id": user_id,
#             "device_token": device_token
#         })
        
#         if existing_token:
#             logger.info(f"🔍 Found existing token, updating...")
#             # Update existing token
#             await user_tokens_collection.update_one(
#                 {"_id": existing_token["_id"]},
#                 {
#                     "$set": {
#                         "device_type": device_type,
#                         "device_name": device_name,
#                         "device_id": device_id,
#                         "is_active": True,
#                         "updated_at": datetime.now(timezone.utc)
#                     }
#                 }
#             )
            
#             logger.info(f"✅ Updated device token for user {user_id}")
            
#             return {
#                 "success": True,
#                 "message": "Device token updated successfully",
#                 "token_id": str(existing_token["_id"]),
#                 "is_new": False
#             }
        
#         # Create new token entry
#         logger.info(f"🔍 Creating new token entry...")
        
#         token_document = {
#             "user_id": user_id,
#             "device_token": device_token,
#             "device_type": device_type,
#             "device_name": device_name,
#             "device_id": device_id,
#             "is_active": True,
#             "created_at": datetime.now(timezone.utc),
#             "updated_at": datetime.now(timezone.utc)
#         }
        
#         logger.info(f"🔍 Token document to insert: {token_document}")
        
#         result = await user_tokens_collection.insert_one(token_document)
        
#         logger.info(f"✅ Registered new device token for user {user_id}")
#         logger.info(f"   Token ID: {str(result.inserted_id)}")
#         logger.info(f"   Inserted into collection: user_tokens")
        
#         return {
#             "success": True,
#             "message": "Device token registered successfully",
#             "token_id": str(result.inserted_id),
#             "is_new": True
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Error registering device token: {e}")
#         return {
#             "success": False,
#             "error": str(e)
#         }

# async def remove_device_token(user_id: str, device_token: str) -> dict:
#     """
#     Remove a device token.
    
#     Args:
#         user_id: User ID
#         device_token: FCM device token to remove
        
#     Returns:
#         dict: Removal result
#     """
#     try:
#         collections = get_collections()
#         user_tokens_collection = collections.get_user_tokens_collection()
        
#         result = await user_tokens_collection.delete_one({
#             "user_id": user_id,
#             "device_token": device_token
#         })
        
#         if result.deleted_count > 0:
#             logger.info(f"✅ Removed device token for user {user_id}")
#             return {
#                 "success": True,
#                 "message": "Device token removed successfully"
#             }
#         else:
#             return {
#                 "success": False,
#                 "error": "Device token not found"
#             }
        
#     except Exception as e:
#         logger.error(f"❌ Error removing device token: {e}")
#         return {
#             "success": False,
#             "error": str(e)
#         }

# async def get_user_device_tokens(user_id: str, active_only: bool = True) -> List[dict]:
#     """
#     Get all device tokens for a user.
    
#     Args:
#         user_id: User ID
#         active_only: Return only active tokens (default: True)
        
#     Returns:
#         List[dict]: List of device token documents
#     """
#     try:
#         collections = get_collections()
#         user_tokens_collection = collections.get_user_tokens_collection()
        
#         query = {"user_id": user_id}
#         if active_only:
#             query["is_active"] = True
        
#         tokens = await user_tokens_collection.find(query).to_list(length=None)
        
#         return tokens
        
#     except Exception as e:
#         logger.error(f"❌ Error getting user device tokens: {e}")
#         return []

# async def deactivate_invalid_tokens(invalid_tokens: List[str]) -> int:
#     """
#     Deactivate invalid/unregistered tokens.
    
#     Args:
#         invalid_tokens: List of invalid device tokens
        
#     Returns:
#         int: Number of tokens deactivated
#     """
#     try:
#         if not invalid_tokens:
#             return 0
        
#         collections = get_collections()
#         user_tokens_collection = collections.get_user_tokens_collection()
        
#         result = await user_tokens_collection.update_many(
#             {"device_token": {"$in": invalid_tokens}},
#             {
#                 "$set": {
#                     "is_active": False,
#                     "updated_at": datetime.now(timezone.utc)
#                 }
#             }
#         )
        
#         logger.info(f"✅ Deactivated {result.modified_count} invalid tokens")
        
#         return result.modified_count
        
#     except Exception as e:
#         logger.error(f"❌ Error deactivating invalid tokens: {e}")
#         return 0

# # ========================================
# # NOTIFICATION SENDING
# # ========================================

# async def send_notification_to_users(
#     user_ids: List[str],
#     title: str,
#     body: str,
#     notification_type: str = "general",
#     data: Optional[Dict[str, Any]] = None,
#     image_url: Optional[str] = None,
#     sound: str = "default",
#     badge: Optional[int] = None,
#     priority: str = "high",
#     click_action: Optional[str] = None,
#     save_to_db: bool = True
# ) -> dict:
#     """
#     Send push notifications to multiple users.
    
#     Args:
#         user_ids: List of user IDs
#         title: Notification title
#         body: Notification body
#         notification_type: Type of notification
#         data: Additional data payload
#         image_url: Image URL for rich notification
#         sound: Notification sound
#         badge: Badge count for iOS
#         priority: Notification priority
#         click_action: Action on notification click
#         save_to_db: Save notification to database (default: True)
        
#     Returns:
#         dict: Sending result with success/failure counts
#     """
#     try:
#         collections = get_collections()
        
#         # Get all active device tokens for the users
#         all_tokens = []
#         user_token_map = {}  # Map tokens to user_ids
        
#         for user_id in user_ids:
#             tokens = await get_user_device_tokens(user_id, active_only=True)
#             for token_doc in tokens:
#                 token = token_doc["device_token"]
#                 all_tokens.append(token)
#                 user_token_map[token] = user_id
        
#         if not all_tokens:
#             logger.warning(f"⚠️ No active device tokens found for {len(user_ids)} users")
            
#             # Still save to database if requested
#             if save_to_db:
#                 await save_notifications_to_db(
#                     user_ids=user_ids,
#                     title=title,
#                     body=body,
#                     notification_type=notification_type,
#                     data=data,
#                     image_url=image_url,
#                     click_action=click_action
#                 )
            
#             return {
#                 "success": True,
#                 "sent_count": 0,
#                 "failed_count": 0,
#                 "message": "No active device tokens found for users"
#             }
        
#         # Prepare data payload
#         notification_data = data or {}
#         notification_data["type"] = notification_type
#         if click_action:
#             notification_data["click_action"] = click_action
        
#         # Convert all data values to strings (FCM requirement)
#         notification_data = {k: str(v) for k, v in notification_data.items()}
        
#         # Send multicast notification (up to 500 tokens at once)
#         sent_count = 0
#         failed_count = 0
#         invalid_tokens = []
        
#         # Split tokens into batches of 500 (FCM limit)
#         batch_size = 500
#         for i in range(0, len(all_tokens), batch_size):
#             batch_tokens = all_tokens[i:i + batch_size]
            
#             result = send_multicast_notification(
#                 tokens=batch_tokens,
#                 title=title,
#                 body=body,
#                 data=notification_data,
#                 image_url=image_url,
#                 sound=sound,
#                 badge=badge,
#                 priority=priority
#             )
            
#             sent_count += result.get("success_count", 0)
#             failed_count += result.get("failure_count", 0)
#             invalid_tokens.extend(result.get("invalid_tokens", []))
        
#         # Deactivate invalid tokens
#         if invalid_tokens:
#             await deactivate_invalid_tokens(invalid_tokens)
        
#         # Save notifications to database
#         if save_to_db:
#             await save_notifications_to_db(
#                 user_ids=user_ids,
#                 title=title,
#                 body=body,
#                 notification_type=notification_type,
#                 data=data,
#                 image_url=image_url,
#                 click_action=click_action
#             )
        
#         logger.info(
#             f"✅ Notification sent: {sent_count} succeeded, {failed_count} failed "
#             f"out of {len(all_tokens)} tokens for {len(user_ids)} users"
#         )
        
#         return {
#             "success": True,
#             "sent_count": sent_count,
#             "failed_count": failed_count,
#             "total_tokens": len(all_tokens),
#             "invalid_tokens_count": len(invalid_tokens)
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Error sending notifications: {e}")
#         return {
#             "success": False,
#             "error": str(e),
#             "sent_count": 0,
#             "failed_count": len(user_ids)
#         }

# async def save_notifications_to_db(
#     user_ids: List[str],
#     title: str,
#     body: str,
#     notification_type: str,
#     data: Optional[Dict[str, Any]] = None,
#     image_url: Optional[str] = None,
#     click_action: Optional[str] = None
# ) -> List[str]:
#     """
#     Save notifications to database for history tracking.
    
#     Args:
#         user_ids: List of user IDs
#         title: Notification title
#         body: Notification body
#         notification_type: Type of notification
#         data: Additional data payload
#         image_url: Image URL
#         click_action: Click action
        
#     Returns:
#         List[str]: List of notification IDs created
#     """
#     try:
#         logger.info(f"🔍 Saving notifications to database for {len(user_ids)} user(s)")
        
#         collections = get_collections()
#         notifications_collection = collections.get_notifications_collection()
        
#         # Create notification documents for each user
#         notification_documents = []
#         for user_id in user_ids:
#             notification_documents.append({
#                 "user_id": user_id,
#                 "title": title,
#                 "body": body,
#                 "notification_type": notification_type,
#                 "data": data,
#                 "image_url": image_url,
#                 "click_action": click_action,
#                 "is_read": False,
#                 "read_at": None,
#                 "created_at": datetime.now(timezone.utc),
#                 "updated_at": datetime.now(timezone.utc)
#             })
        
#         logger.info(f"🔍 Inserting {len(notification_documents)} notification(s) into collection")
        
#         # Insert all notifications
#         result = await notifications_collection.insert_many(notification_documents)
        
#         notification_ids = [str(id) for id in result.inserted_ids]
        
#         logger.info(f"✅ Saved {len(notification_ids)} notifications to database")
#         logger.info(f"   Notification IDs: {notification_ids}")
        
#         return notification_ids
        
#     except Exception as e:
#         logger.error(f"❌ Error saving notifications to database: {e}")
#         return []

# # ========================================
# # NOTIFICATION RETRIEVAL
# # ========================================

# async def get_user_notifications(
#     user_id: str,
#     page: int = 1,
#     page_size: int = 20,
#     filter_type: Optional[str] = None,
#     filter_read: Optional[bool] = None,
#     sort_order: str = "desc"
# ) -> dict:
#     """
#     Get user's notifications with pagination and filtering.
    
#     Args:
#         user_id: User ID
#         page: Page number (starts from 1)
#         page_size: Number of items per page
#         filter_type: Filter by notification type
#         filter_read: Filter by read status
#         sort_order: Sort order ("asc" or "desc")
        
#     Returns:
#         dict: Paginated notifications with metadata
#     """
#     try:
#         collections = get_collections()
#         notifications_collection = collections.get_notifications_collection()
        
#         # Build query
#         query = {"user_id": user_id}
        
#         if filter_type:
#             query["notification_type"] = filter_type
        
#         if filter_read is not None:
#             query["is_read"] = filter_read
        
#         # Get total count
#         total_count = await notifications_collection.count_documents(query)
        
#         # Get unread count
#         unread_count = await notifications_collection.count_documents({
#             "user_id": user_id,
#             "is_read": False
#         })
        
#         # Calculate pagination
#         skip = (page - 1) * page_size
#         sort_direction = -1 if sort_order == "desc" else 1
        
#         # Get notifications
#         cursor = notifications_collection.find(query).sort("created_at", sort_direction).skip(skip).limit(page_size)
#         notifications = await cursor.to_list(length=page_size)
        
#         # Format notifications
#         formatted_notifications = []
#         for notification in notifications:
#             formatted_notifications.append({
#                 "notification_id": str(notification["_id"]),
#                 "user_id": notification["user_id"],
#                 "title": notification["title"],
#                 "body": notification["body"],
#                 "notification_type": notification["notification_type"],
#                 "is_read": notification["is_read"],
#                 "data": notification.get("data"),
#                 "image_url": notification.get("image_url"),
#                 "click_action": notification.get("click_action"),
#                 "created_at": notification["created_at"].isoformat() + "Z",
#                 "read_at": notification["read_at"].isoformat() + "Z" if notification.get("read_at") else None
#             })
        
#         # Calculate total pages
#         total_pages = (total_count + page_size - 1) // page_size
        
#         return {
#             "success": True,
#             "notifications": formatted_notifications,
#             "total_count": total_count,
#             "unread_count": unread_count,
#             "page": page,
#             "page_size": page_size,
#             "total_pages": total_pages
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Error getting user notifications: {e}")
#         return {
#             "success": False,
#             "error": str(e),
#             "notifications": [],
#             "total_count": 0,
#             "unread_count": 0,
#             "page": page,
#             "page_size": page_size,
#             "total_pages": 0
#         }

# async def get_unread_count(user_id: str) -> int:
#     """
#     Get count of unread notifications for a user.
    
#     Args:
#         user_id: User ID
        
#     Returns:
#         int: Count of unread notifications
#     """
#     try:
#         collections = get_collections()
#         notifications_collection = collections.get_notifications_collection()
        
#         count = await notifications_collection.count_documents({
#             "user_id": user_id,
#             "is_read": False
#         })
        
#         return count
        
#     except Exception as e:
#         logger.error(f"❌ Error getting unread count: {e}")
#         return 0

# # ========================================
# # NOTIFICATION ACTIONS
# # ========================================

# async def mark_notifications_as_read(
#     user_id: str,
#     notification_ids: List[str]
# ) -> dict:
#     """
#     Mark specific notifications as read.
    
#     Args:
#         user_id: User ID
#         notification_ids: List of notification IDs to mark as read
        
#     Returns:
#         dict: Result with count of marked notifications
#     """
#     try:
#         collections = get_collections()
#         notifications_collection = collections.get_notifications_collection()
        
#         # Convert string IDs to ObjectId
#         object_ids = [ObjectId(id) for id in notification_ids if ObjectId.is_valid(id)]
        
#         if not object_ids:
#             return {
#                 "success": False,
#                 "error": "No valid notification IDs provided",
#                 "marked_count": 0
#             }
        
#         # Update notifications
#         result = await notifications_collection.update_many(
#             {
#                 "_id": {"$in": object_ids},
#                 "user_id": user_id,
#                 "is_read": False
#             },
#             {
#                 "$set": {
#                     "is_read": True,
#                     "read_at": datetime.now(timezone.utc),
#                     "updated_at": datetime.now(timezone.utc)
#                 }
#             }
#         )
        
#         logger.info(f"✅ Marked {result.modified_count} notifications as read for user {user_id}")
        
#         return {
#             "success": True,
#             "marked_count": result.modified_count,
#             "failed_count": len(notification_ids) - result.modified_count
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Error marking notifications as read: {e}")
#         return {
#             "success": False,
#             "error": str(e),
#             "marked_count": 0
#         }

# async def mark_all_notifications_as_read(user_id: str) -> dict:
#     """
#     Mark all notifications as read for a user.
    
#     Args:
#         user_id: User ID
        
#     Returns:
#         dict: Result with count of marked notifications
#     """
#     try:
#         collections = get_collections()
#         notifications_collection = collections.get_notifications_collection()
        
#         result = await notifications_collection.update_many(
#             {
#                 "user_id": user_id,
#                 "is_read": False
#             },
#             {
#                 "$set": {
#                     "is_read": True,
#                     "read_at": datetime.now(timezone.utc),
#                     "updated_at": datetime.now(timezone.utc)
#                 }
#             }
#         )
        
#         logger.info(f"✅ Marked all {result.modified_count} notifications as read for user {user_id}")
        
#         return {
#             "success": True,
#             "marked_count": result.modified_count
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Error marking all notifications as read: {e}")
#         return {
#             "success": False,
#             "error": str(e),
#             "marked_count": 0
#         }

# async def delete_notifications(
#     user_id: str,
#     notification_ids: List[str]
# ) -> dict:
#     """
#     Delete specific notifications.
    
#     Args:
#         user_id: User ID
#         notification_ids: List of notification IDs to delete
        
#     Returns:
#         dict: Result with count of deleted notifications
#     """
#     try:
#         collections = get_collections()
#         notifications_collection = collections.get_notifications_collection()
        
#         # Convert string IDs to ObjectId
#         object_ids = [ObjectId(id) for id in notification_ids if ObjectId.is_valid(id)]
        
#         if not object_ids:
#             return {
#                 "success": False,
#                 "error": "No valid notification IDs provided",
#                 "deleted_count": 0
#             }
        
#         # Delete notifications
#         result = await notifications_collection.delete_many({
#             "_id": {"$in": object_ids},
#             "user_id": user_id
#         })
        
#         logger.info(f"✅ Deleted {result.deleted_count} notifications for user {user_id}")
        
#         return {
#             "success": True,
#             "deleted_count": result.deleted_count,
#             "failed_count": len(notification_ids) - result.deleted_count
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Error deleting notifications: {e}")
#         return {
#             "success": False,
#             "error": str(e),
#             "deleted_count": 0
#         }

# async def clear_all_notifications(user_id: str) -> dict:
#     """
#     Clear all notifications for a user.
    
#     Args:
#         user_id: User ID
        
#     Returns:
#         dict: Result with count of deleted notifications
#     """
#     try:
#         collections = get_collections()
#         notifications_collection = collections.get_notifications_collection()
        
#         result = await notifications_collection.delete_many({
#             "user_id": user_id
#         })
        
#         logger.info(f"✅ Cleared all {result.deleted_count} notifications for user {user_id}")
        
#         return {
#             "success": True,
#             "deleted_count": result.deleted_count
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Error clearing all notifications: {e}")
#         return {
#             "success": False,
#             "error": str(e),
#             "deleted_count": 0
#         }

# # ========================================
# # NOTIFICATION PREFERENCES
# # ========================================

# async def get_user_preferences(user_id: str) -> dict:
#     """
#     Get user's notification preferences.
    
#     Args:
#         user_id: User ID
        
#     Returns:
#         dict: User's notification preferences
#     """
#     try:
#         collections = get_collections()
#         preferences_collection = collections.get_notification_preferences_collection()
        
#         preferences = await preferences_collection.find_one({"user_id": user_id})
        
#         if not preferences:
#             # Return default preferences
#             return {
#                 "user_id": user_id,
#                 "enable_push_notifications": True,
#                 "enable_email_notifications": True,
#                 "enable_sms_notifications": False,
#                 "club_notifications": True,
#                 "payment_notifications": True,
#                 "membership_notifications": True,
#                 "system_notifications": True,
#                 "quiet_hours_enabled": False,
#                 "quiet_hours_start": None,
#                 "quiet_hours_end": None
#             }
        
#         # Remove MongoDB _id
#         preferences.pop("_id", None)
        
#         return preferences
        
#     except Exception as e:
#         logger.error(f"❌ Error getting user preferences: {e}")
#         return {}

# async def update_user_preferences(user_id: str, preferences: dict) -> dict:
#     """
#     Update user's notification preferences.
    
#     Args:
#         user_id: User ID
#         preferences: Preferences to update
        
#     Returns:
#         dict: Update result with updated preferences
#     """
#     try:
#         collections = get_collections()
#         preferences_collection = collections.get_notification_preferences_collection()
        
#         # Add metadata
#         preferences["user_id"] = user_id
#         preferences["updated_at"] = datetime.now(timezone.utc)
        
#         # Upsert preferences
#         await preferences_collection.update_one(
#             {"user_id": user_id},
#             {"$set": preferences},
#             upsert=True
#         )
        
#         logger.info(f"✅ Updated notification preferences for user {user_id}")
        
#         # Get updated preferences
#         updated_preferences = await get_user_preferences(user_id)
        
#         return {
#             "success": True,
#             "preferences": updated_preferences
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Error updating user preferences: {e}")
#         return {
#             "success": False,
#             "error": str(e)
#         }

"""
Notification Service

Handles:
- Push notifications (Firebase)
- Device token management
- Notification history
- User preferences
"""

import logging
import copy
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from bson import ObjectId

from core.database.collections import get_collections
from .firebase_config import (
    send_push_notification,
    send_multicast_notification,
    send_topic_notification
)

logger = logging.getLogger(__name__)

# ========================================
# DEVICE TOKEN MANAGEMENT
# ========================================

async def register_device_token(
    user_id: str,
    device_token: str,
    device_type: str,
    device_name: Optional[str] = None,
    device_id: Optional[str] = None
) -> dict:
    """Register or update a device token for push notifications."""
    try:
        c = get_collections()
        col = c.get_user_tokens_collection()

        now = datetime.now(timezone.utc)

        existing = None
        if device_id:
            existing = await col.find_one({"user_id": user_id, "device_id": device_id})
        if not existing:
            existing = await col.find_one({"user_id": user_id, "device_token": device_token})

        update_data = {
            "device_token": device_token,
            "device_type": device_type,
            "device_name": device_name,
            "device_id": device_id,
            "is_active": True,
            "updated_at": now
        }

        if existing:
            await col.update_one(
                {"_id": existing["_id"]},
                {"$set": update_data}
            )
            return {
                "success": True,
                "message": "Token updated",
                "token_id": str(existing["_id"]),
                "is_new": False
            }

        doc = {
            "user_id": user_id,
            "created_at": now,
            **update_data,
        }
        result = await col.insert_one(doc)
        return {
            "success": True,
            "message": "Token registered",
            "token_id": str(result.inserted_id),
            "is_new": True
        }

    except Exception as e:
        logger.error(f"Error registering token: {e}")
        return {"success": False, "error": str(e)}


async def remove_device_token(
    user_id: str,
    device_token: Optional[str] = None,
    device_id: Optional[str] = None
) -> dict:
    """Deactivate a device token."""
    try:
        c = get_collections()
        col = c.get_user_tokens_collection()
        print(user_id,device_token,"user_id,device_token")

        if not device_token and not device_id:
            return {"success": False, "error": "device_token or device_id required"}

        query = {"user_id": user_id}
        if device_id:
            query["device_id"] = device_id
        if device_token:
            query["device_token"] = device_token

        result = await col.update_one(
            query,
            {
                "$set": {
                    "is_active": False,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        if result.modified_count:
            return {"success": True, "message": "Token deactivated"}
        return {"success": False, "error": "Token not found"}
    except Exception as e:
        logger.error(f"Error removing token: {e}")
        return {"success": False, "error": str(e)}


async def get_user_device_tokens(user_id: str, active_only: bool = True) -> List[dict]:
    """Get all device tokens for a user."""
    try:
        c = get_collections()
        col = c.get_user_tokens_collection()
        query = {"user_id": user_id}
        if active_only:
            query["is_active"] = True
        return await col.find(query).to_list(length=None)
    except Exception as e:
        logger.error(f"Error getting tokens: {e}")
        return []


async def deactivate_invalid_tokens(invalid_tokens: List[str]) -> int:
    """Deactivate invalid/unregistered tokens."""
    try:
        if not invalid_tokens:
            return 0
        c = get_collections()
        col = c.get_user_tokens_collection()
        result = await col.update_many(
            {"device_token": {"$in": invalid_tokens}},
            {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}}
        )
        if result.modified_count > 0:
            logger.info(f"✅ Deactivated {result.modified_count} invalid device token(s)")
        return result.modified_count
    except Exception as e:
        logger.error(f"❌ Error deactivating tokens: {e}")
        return 0


# ========================================
# NOTIFICATION SENDING
# ========================================

# async def send_notification_to_users(
#     user_ids: List[str],
#     title: str,
#     body: str,
#     notification_type: str = "general",
#     data: Optional[Dict[str, Any]] = None,
#     image_url: Optional[str] = None,
#     sound: str = "default",
#     badge: Optional[int] = None,
#     priority: str = "high",
#     click_action: Optional[str] = None,
#     save_to_db: bool = True
# ) -> dict:
#     """Send push notifications to multiple users."""
#     try:
#         c = get_collections()
#         all_tokens, token_user_map = [], {}

#         for user_id in user_ids:
#             tokens = await get_user_device_tokens(user_id)
#             for t in tokens:
#                 token = t["device_token"]
#                 all_tokens.append(token)
#                 token_user_map[token] = user_id
#         print(all_tokens,"all_tokensall_tokensall_tokensall_tokens")
#         if not all_tokens:
#             if save_to_db:
#                 await save_notifications_to_db(user_ids, title, body, notification_type, data, image_url, click_action)
#             return {"success": True, "sent_count": 0, "failed_count": 0, "message": "No tokens found"}

#         payload = {**(data or {}), "type": notification_type}
#         if click_action:
#             payload["click_action"] = click_action
#         payload = {k: str(v) for k, v in payload.items()}
#         print(payload,"payloadpayloadpayloadpayload")
#         sent, failed, invalid = 0, 0, []
#         print(sent,failed,invalid,"sent,failed,invalid")
#         for i in range(0, len(all_tokens), 500):
#             batch = all_tokens[i:i + 500]
#             print(batch,"batchbatchbatchbatch")
#             res = send_multicast_notification(
#                 tokens=batch, title=title, body=body, data=payload,
#                 image_url=image_url, sound=sound, badge=badge, priority=priority
#             )
#             sent += res.get("success_count", 0)
#             failed += res.get("failure_count", 0)
#             invalid += res.get("invalid_tokens", [])

#         if invalid:
#             await deactivate_invalid_tokens(invalid)

#         if save_to_db:
#             await save_notifications_to_db(user_ids, title, body, notification_type, data, image_url, click_action)

#         return {"success": True, "sent_count": sent, "failed_count": failed, "invalid_count": len(invalid)}

#     except Exception as e:
#         logger.error(f"Error sending notifications: {e}")
#         return {"success": False, "error": str(e)}


import asyncio
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=5)  # background thread pool


async def get_user_chat_status(user_id: str, club_id: str) -> dict:
    """
    Get chat status flags for a specific user and club.
    Returns: dict with is_chat_open and is_dm_chat_open flags
    """
    try:
        from bson import ObjectId
        c = get_collections()
        users_col = c.get_users_collection()
        
        user = await users_col.find_one({"_id": ObjectId(user_id)})
        if not user:
            return {"is_chat_open": True, "is_dm_chat_open": True}  # Default
        
        # Check if user has this club in chat_open_clubs
        chat_open_clubs = user.get("chat_open_clubs", [])
        for club_status in chat_open_clubs:
            if club_status.get("club_id") == club_id:
                return {
                    "is_chat_open": club_status.get("is_chat_open", True),
                    "is_dm_chat_open": club_status.get("is_dm_chat_open", True)
                }
        
        # If club not found in chat_open_clubs, return defaults
        return {"is_chat_open": True, "is_dm_chat_open": True}
    except Exception as e:
        logger.error(f"Error getting user chat status: {e}")
        return {"is_chat_open": True, "is_dm_chat_open": True}  # Default on error


async def send_notification_to_users(
    user_ids: List[str],
    title: str,
    body: str,
    notification_type: str = "general",
    data: Optional[Dict[str, Any]] = None,
    image_url: Optional[str] = None,
    sound: str = "default",
    badge: Optional[int] = None,
    priority: str = "high",
    click_action: Optional[str] = None,
    save_to_db: bool = True,
    all_user_ids: Optional[List[str]] = None,
) -> dict:
    """Asynchronously send push notifications to multiple users via FCM."""
    try:
        c = get_collections()
        all_tokens, token_user_map = [], {}

        # Determine lists for push vs persistence
        push_user_ids = user_ids or []
        db_user_ids = all_user_ids if all_user_ids is not None else user_ids
        print(push_user_ids,"push_user_idspush_user_idspush_user_ids")
        # 🔹 Collect all FCM tokens
        for user_id in push_user_ids:
            tokens = await get_user_device_tokens(user_id)
            for t in tokens:
                token = t.get("device_token")
                if token:
                    all_tokens.append(token)
                    token_user_map[token] = user_id
        print(all_tokens,"all_tokensall_tokensall_tokensall_tokens")
        print(token_user_map,"token_user_maptoken_user_maptoken_user_map")
        if not all_tokens:
            if save_to_db and db_user_ids:
                await save_notifications_to_db(
                    db_user_ids, title, body, notification_type, data, image_url, click_action
                )
            return {"success": True, "sent_count": 0, "failed_count": 0, "message": "No tokens found"}

        # 🔹 Prepare FCM payload with chat status flags
        payload = {**(data or {}), "type": notification_type}
        if click_action:
            payload["click_action"] = click_action
        
        # Add chat status flags based on notification type and data
        # These flags are BEFORE sending, will be updated in DB after notification arrives
        if data and "is_dm" in data:
            # Flags already set in data by caller
            pass
        else:
            # Set default flags if not provided
            payload["is_dm"] = str(data.get("is_dm", "false") if data else "false")
            payload["is_chat_open"] = str(data.get("is_chat_open", "true") if data else "true")
            payload["is_dm_chat_open"] = str(data.get("is_dm_chat_open", "true") if data else "true")
        
        payload = {k: str(v) for k, v in payload.items()}

        sent, failed, invalid = 0, 0, []

        # 🔹 Process tokens in 500-sized batches
        for i in range(0, len(all_tokens), 500):
            batch = all_tokens[i:i + 500]

            # Run sync FCM send inside executor (non-blocking)
            res = await asyncio.get_event_loop().run_in_executor(
                _executor,
                lambda: send_multicast_notification(
                    tokens=batch,
                    title=title,
                    body=body,
                    data=payload,
                    image_url=image_url,
                    sound=sound,
                    badge=badge,
                    priority=priority
                )
            )

            sent += res.get("success_count", 0)
            failed += res.get("failure_count", 0)
            invalid.extend(res.get("invalid_tokens", []))

        # 🔹 Deactivate invalid tokens
        if invalid:
            await deactivate_invalid_tokens(invalid)

        # 🔹 Save to DB
        if save_to_db and db_user_ids:
            await save_notifications_to_db(
                db_user_ids, title, body, notification_type, data, image_url, click_action
            )

        logger.info(f"✅ Notification summary: Sent={sent}, Failed={failed}, Invalid={len(invalid)}")
        return {"success": True, "sent_count": sent, "failed_count": failed, "invalid_count": len(invalid)}

    except Exception as e:
        logger.error(f"❌ Error sending notifications: {e}")
        return {"success": False, "error": str(e)}


async def save_notifications_to_db(
    user_ids: List[str],
    title: str,
    body: str,
    notification_type: str,
    data: Optional[Dict[str, Any]] = None,
    image_url: Optional[str] = None,
    click_action: Optional[str] = None
) -> List[str]:
    """Save notifications in DB and automatically close bell icon for recipients."""
    try:
        c = get_collections()
        col = c.get_notifications_collection()
        users_col = c.get_users_collection()
        now = datetime.now(timezone.utc)
        
        # Extract push_type from data (default to "")
        push_type = ""
        club_id = None
        if data:
            push_type = data.get("push_type", "")
            club_id = data.get("club_id", None)
        
        # Map notification types to user preference fields
        notification_type_to_pref = {
            "club_new_pick": "new_pick_alerts",
            "club_pick": "new_pick_alerts",
            "club_pick_outcome": "pick_outcome_alerts",
            "club_member_join": "club_join_alerts",
            "club_join": "club_join_alerts",
            "club_status_change": "club_status_alerts",
            "dm_block": "dm_block_alerts",
            "club_message": "message_alerts",
            "mention": "mention_alerts",
            "subscription_alerts": "subscription_alerts",
            "friend_request": "friend_request_alerts",
            "mute_alert": "mute_alerts",
        }

        preferences_col = c.get_notification_preferences_collection()
        prefs_list = await preferences_col.find({"user_id": {"$in": user_ids}}).to_list(None)
        prefs_map = {pref.get("user_id"): pref for pref in prefs_list}

        def determine_is_notify(user_id: str) -> bool:
            pref_field = notification_type_to_pref.get(notification_type)
            if not pref_field:
                return True
            user_pref = prefs_map.get(user_id, {})
            return user_pref.get(pref_field, True)

        # Save notification documents
        docs = []
        for u in user_ids:
            doc_data = copy.deepcopy(data) if data else {}
            doc_data["is_notify"] = determine_is_notify(u)

            docs.append({
                "user_id": u,
                "title": title,
                "body": body,
                "notification_type": notification_type,
                "push_type": push_type,
                "data": doc_data,
                "image_url": image_url,
                "click_action": click_action,
                "is_read": False,
                "read_at": None,
                "created_at": now,
                "updated_at": now
            })

        res = await col.insert_many(docs)
        
        # Automatically close bell icon (set is_open = false) for all recipients
        # This ensures bell icon closes when new notification arrives
        from bson import ObjectId
        user_object_ids = []
        for user_id in user_ids:
            try:
                user_object_ids.append(ObjectId(user_id))
            except:
                logger.warning(f"Invalid user_id format: {user_id}")
        
        if user_object_ids:
            await users_col.update_many(
                {"_id": {"$in": user_object_ids}},
                {"$set": {"is_open": False}}
            )
            logger.info(f"✅ Bell icon automatically closed for {len(user_object_ids)} users after new notification")
            
            # Extract is_dm flag from data
            is_dm = False
            if data:
                is_dm_str = data.get("is_dm", "false")
                is_dm = is_dm_str in ["true", "True", True, "1", 1]
            
            # If this is a chat message notification, close appropriate chat icon
            if push_type == "chat_message" and club_id:
                if is_dm:
                    # For DM notifications: close is_dm_chat_open
                    await users_col.update_many(
                        {
                            "_id": {"$in": user_object_ids},
                            "chat_open_clubs.club_id": club_id
                        },
                        {
                            "$set": {
                                "chat_open_clubs.$.is_dm_chat_open": False,
                                "chat_open_clubs.$.updated_at": now
                            }
                        }
                    )
                    logger.info(f"✅ DM chat icon automatically closed for club {club_id} for {len(user_object_ids)} users after new DM notification")
                else:
                    # For group chat notifications: close is_chat_open
                    await users_col.update_many(
                        {
                            "_id": {"$in": user_object_ids},
                            "chat_open_clubs.club_id": club_id
                        },
                        {
                            "$set": {
                                "chat_open_clubs.$.is_chat_open": False,
                                "chat_open_clubs.$.updated_at": now
                            }
                        }
                    )
                    logger.info(f"✅ Chat icon automatically closed for club {club_id} for {len(user_object_ids)} users after new chat notification")
        
        return [str(i) for i in res.inserted_ids]
    except Exception as e:
        logger.error(f"Error saving notifications: {e}")
        return []


# ========================================
# NOTIFICATION RETRIEVAL
# ========================================

async def get_user_notifications(
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    filter_type: Optional[str] = None,
    filter_read: Optional[bool] = None,
    sort_order: str = "desc"
) -> dict:
    """Fetch paginated user notifications, filtered by user's enabled notification types."""
    try:
        c = get_collections()
        col = c.get_notifications_collection()
        preferences_col = c.get_notification_preferences_collection()

        # Get user's notification preferences
        user_prefs = await preferences_col.find_one({"user_id": user_id})
        
        # Map notification types to preference fields with default values
        notification_type_to_pref = {
            "club_new_pick": "new_pick_alerts",
            "club_pick": "new_pick_alerts",
            "club_pick_outcome": "pick_outcome_alerts",
            "club_member_join": "club_join_alerts",
            "club_join": "club_join_alerts",
            "club_status_change": "club_status_alerts",
            "dm_block": "dm_block_alerts",
            "club_message": "message_alerts",
            "mention": "mention_alerts",
        }
        
        # Build query - show ALL notifications regardless of preferences
        query = {"user_id": user_id}
        
        if filter_type:
            query["notification_type"] = filter_type
            
        if filter_read is not None:
            query["is_read"] = filter_read

        total = await col.count_documents(query)
        unread_query = {"user_id": user_id, "is_read": False}
        unread = await col.count_documents(unread_query)

        skip = (page - 1) * page_size
        direction = -1 if sort_order == "desc" else 1
        cursor = col.find(query).sort("created_at", direction).skip(skip).limit(page_size)
        notifications = await cursor.to_list(length=page_size)

        # Helper function to determine if a notification type is enabled
        def is_notification_enabled(notification_type: str) -> bool:
            """Check if notification type is enabled in user preferences"""
            # Get the preference field name for this notification type
            pref_field = notification_type_to_pref.get(notification_type)
            
            if pref_field and user_prefs:
                # If preference field exists, return its value (default True if not set)
                return user_prefs.get(pref_field, True)
            
            # Default to True if no mapping found
            return True

        formatted = [{
            "notification_id": str(n["_id"]),
            "title": n["title"],
            "body": n["body"],
            "click_action": n["click_action"],
            "type": n["notification_type"],
            "is_read": n["is_read"],
            "data": n.get("data"),
            "created_at": n["created_at"].isoformat() + "Z",
            "read_at": n["read_at"].isoformat() + "Z" if n.get("read_at") else None,
            "is_enable": is_notification_enabled(n["notification_type"])
        } for n in notifications]

        return {
            "success": True,
            "notifications": formatted,
            "total_count": total,
            "unread_count": unread,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    except Exception as e:
        logger.error(f"Error fetching notifications: {e}")
        return {"success": False, "error": str(e), "notifications": []}


async def update_notification_setting(user_id: str, notification_type: str, is_enabled: bool) -> dict:
    """
    Update user's notification setting for a specific type.
    Stores in notification_preferences collection.
    
    Args:
        user_id: User ID
        notification_type: Type of notification (e.g., 'pick_outcome_alerts', 'message_alerts')
        is_enabled: Whether the notification type is enabled
    
    Returns:
        dict with success status
    """
    try:
        c = get_collections()
        settings_col = c.notification_preferences()
        
        now = datetime.now(timezone.utc)
        
        # Upsert the setting
        result = await settings_col.update_one(
            {"user_id": user_id, "notification_type": notification_type},
            {
                "$set": {
                    "user_id": user_id,
                    "notification_type": notification_type,
                    "is_enabled": is_enabled,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "created_at": now
                }
            },
            upsert=True
        )
        
        logger.info(f"Updated notification setting for user {user_id}: {notification_type} = {is_enabled}")
        
        return {
            "success": True,
            "message": f"Notification setting updated: {notification_type} = {is_enabled}",
            "modified": result.modified_count > 0,
            "upserted": result.upserted_id is not None
        }
    except Exception as e:
        logger.error(f"Error updating notification setting: {e}")
        return {"success": False, "error": str(e)}


async def get_notification_preferences(user_id: str) -> dict:
    """
    Get all notification settings for a user.
    
    Returns:
        dict with notification_type as key and is_enabled as value
    """
    try:
        c = get_collections()
        settings_col = c.get_notification_preferences_collection()
        
        settings = await settings_col.find({"user_id": user_id}).to_list(length=None)
        
        # Convert to dictionary
        settings_dict = {
            setting["notification_type"]: setting["is_enabled"]
            for setting in settings
        }
        
        return {
            "success": True,
            "settings": settings_dict
        }
    except Exception as e:
        logger.error(f"Error fetching notification settings: {e}")
        return {"success": False, "error": str(e), "settings": {}}


async def get_unread_count(user_id: str) -> int:
    """Get unread notifications count, excluding disabled notification types."""
    try:
        c = get_collections()
        col = c.get_notifications_collection()
        settings_col = c.get_collection("notification_preferences")
        
        # Get disabled notification types
        disabled_settings = await settings_col.find({"user_id": user_id, "is_enabled": False}).to_list(length=None)
        disabled_types = [setting["notification_type"] for setting in disabled_settings]
        
        # Build query
        query = {"user_id": user_id, "is_read": False}
        if disabled_types:
            query["notification_type"] = {"$nin": disabled_types}
        
        return await col.count_documents(query)
    except Exception as e:
        logger.error(f"Error counting unread: {e}")
        return 0


# ========================================
# NOTIFICATION ACTIONS
# ========================================

async def mark_notifications_as_read(user_id: str, ids: List[str]) -> dict:
    """Mark specific notifications as read."""
    try:
        c = get_collections()
        col = c.get_notifications_collection()
        valid_ids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
        if not valid_ids:
            return {"success": False, "error": "No valid IDs"}
        res = await col.update_many(
            {"_id": {"$in": valid_ids}, "user_id": user_id, "is_read": False},
            {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
        )
        return {"success": True, "marked_count": res.modified_count}
    except Exception as e:
        logger.error(f"Error marking read: {e}")
        return {"success": False, "error": str(e)}


async def mark_all_notifications_as_read(user_id: str) -> dict:
    """Mark all user's notifications as read."""
    try:
        c = get_collections()
        col = c.get_notifications_collection()
        res = await col.update_many(
            {"user_id": user_id, "is_read": False},
            {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
        )
        return {"success": True, "marked_count": res.modified_count}
    except Exception as e:
        logger.error(f"Error marking all read: {e}")
        return {"success": False, "error": str(e)}


async def delete_notifications(user_id: str, ids: List[str]) -> dict:
    """Delete specific notifications."""
    try:
        c = get_collections()
        col = c.get_notifications_collection()
        valid_ids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
        if not valid_ids:
            return {"success": False, "error": "No valid IDs"}
        res = await col.delete_many({"_id": {"$in": valid_ids}, "user_id": user_id})
        return {"success": True, "deleted_count": res.deleted_count}
    except Exception as e:
        logger.error(f"Error deleting notifications: {e}")
        return {"success": False, "error": str(e)}


async def clear_all_notifications(user_id: str) -> dict:
    """Clear all notifications for a user."""
    try:
        c = get_collections()
        col = c.get_notifications_collection()
        res = await col.delete_many({"user_id": user_id})
        return {"success": True, "deleted_count": res.deleted_count}
    except Exception as e:
        logger.error(f"Error clearing all notifications: {e}")
        return {"success": False, "error": str(e)}


# ========================================
# NOTIFICATION PREFERENCES
# ========================================

async def get_user_preferences(user_id: str) -> dict:
    """Fetch user's notification preferences."""
    try:
        c = get_collections()
        col = c.get_notification_preferences_collection()
        prefs = await col.find_one({"user_id": user_id})
        if not prefs:
            return {
                "user_id": user_id,
                "enable_push_notifications": True,
                "enable_email_notifications": True,
                "enable_sms_notifications": False,
                "club_notifications": True,
                "payment_notifications": True,
                "membership_notifications": True,
                "system_notifications": True,
                "pick_outcome_alerts": True,
                "quiet_hours_enabled": False,
                "quiet_hours_start": None,
                "quiet_hours_end": None
            }
        prefs.pop("_id", None)
        return prefs
    except Exception as e:
        logger.error(f"Error fetching preferences: {e}")
        return {}


async def update_user_preferences(user_id: str, prefs: dict) -> dict:
    """Update user's notification preferences."""
    try:
        c = get_collections()
        col = c.get_notification_preferences_collection()
        prefs.update({"user_id": user_id, "updated_at": datetime.now(timezone.utc)})
        await col.update_one({"user_id": user_id}, {"$set": prefs}, upsert=True)
        updated = await get_user_preferences(user_id)
        return {"success": True, "preferences": updated}
    except Exception as e:
        logger.error(f"Error updating preferences: {e}")
        return {"success": False, "error": str(e)}


# ========================================
# PICK OUTCOME NOTIFICATIONS
# ========================================

async def get_club_members(club_id: str) -> List[str]:
    """
    Get all club members (captain, moderators, members) for a specific club.
    
    Args:
        club_id: Club ID to get members from
        
    Returns:
        List[str]: List of user IDs who are members of the club
    """
    try:
        c = get_collections()
        clubs_collection = c.get_clubs_collection()
        
        # Get club details
        club = await clubs_collection.find_one({"name_based_id": club_id})
        if not club:
            logger.warning(f"Club {club_id} not found")
            return []
        
        # Collect all user IDs from the club
        user_ids: List[str] = []
        
        # Add captain
        captain_id = club.get("captain_id")
        if captain_id:
            user_ids.append(captain_id)
        
        # Add moderators
        moderators = club.get("detailed_moderators", [])
        for mod in moderators:
            if isinstance(mod, dict) and mod.get("user_id") and mod.get("status") == "active":
                user_ids.append(mod.get("user_id"))
        
        # Fallback for legacy moderator array
        legacy_moderators = club.get("detailed_moderators", [])
        for mod in legacy_moderators:
            if isinstance(mod, dict):
                if mod.get("user_id") and mod.get("status", "active") == "active":
                    user_ids.append(mod.get("user_id"))
            elif isinstance(mod, str):
                user_ids.append(mod)
        
        # Add members (both free and paid)
        members = club.get("members", [])
        for member in members:
            if isinstance(member, dict) and member.get("user_id") and member.get("is_active", True):
                user_ids.append(member.get("user_id"))
        
        paid_members = club.get("paid_members", [])
        for member in paid_members:
            if isinstance(member, dict) and member.get("user_id") and member.get("is_active", True):
                user_ids.append(member.get("user_id"))
        
        # Add members from club_memberships collection (handles paid/trial/legacy records)
        memberships_collection = c.get_club_memberships_collection()
        club_object_id = club.get("_id")
        membership_query = {
            "club_id": str(club_object_id) if club_object_id else club_id,
            "subscription_status": {
                "$in": ["active", "trial", "paid", "subscribed", "pending"]
            }
        }
        membership_docs = await memberships_collection.find(membership_query, {"user_id": 1}).to_list(length=None)
        for membership in membership_docs:
            member_user_id = membership.get("user_id")
            if member_user_id:
                user_ids.append(member_user_id)
        
        # Remove duplicates
        user_ids = list(set(user_ids))
        
        logger.info(f"Found {len(user_ids)} total members in club {club_id}")
        return user_ids
        
    except Exception as e:
        logger.error(f"Error getting club members: {e}")
        return []


async def filter_users_by_notification_preference(
    user_ids: List[str], 
    preference_key: str, 
    default_value: bool = True
) -> List[str]:
    """
    Filter users by a specific notification preference.
    
    Args:
        user_ids: List of user IDs to filter
        preference_key: The preference key to check (e.g., 'pick_outcome_alerts')
        default_value: Default value if preference is not set (default: True)
        
    Returns:
        List[str]: List of user IDs who have the preference enabled
    """
    try:
        if not user_ids:
            return []
        
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        users_with_preference = []
        
        # Check each user's preferences
        for user_id in user_ids:
            prefs = await preferences_collection.find_one({"user_id": user_id})
            
            # Check the specific preference
            has_preference = default_value
            if prefs:
                has_preference = prefs.get(preference_key, default_value)
            
            # Also check if push notifications are enabled (global setting)
            push_enabled = True
            if prefs:
                push_enabled = prefs.get("enable_push_notifications", True)
            
            if has_preference and push_enabled:
                users_with_preference.append(user_id)
        
        logger.info(f"Found {len(users_with_preference)} users with {preference_key} enabled out of {len(user_ids)} total users")
        return users_with_preference
        
    except Exception as e:
        logger.error(f"Error filtering users by notification preference: {e}")
        return []