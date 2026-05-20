# """
# Notification Service Routes

# API endpoints for notification management including:
# - Device token registration
# - Push notification sending
# - Notification retrieval
# - Notification actions (mark as read, delete)
# - Notification preferences
# """

# from fastapi import APIRouter, Depends, HTTPException, status
# from typing import Optional
# from datetime import datetime, timezone

# from core.auth.auth_middleware import get_current_user_or_admin
# from core.utils.response_utils import create_success_response, create_error_response
# from .models import (
#     # Device Token Models
#     RegisterDeviceTokenRequest,
#     RegisterDeviceTokenResponse,
#     RemoveDeviceTokenRequest,
#     RemoveDeviceTokenResponse,
#     UserDeviceTokensResponse,
    
#     # Notification Sending Models
#     SendNotificationRequest,
#     SendNotificationResponse,
    
#     # Notification Retrieval Models
#     GetNotificationsRequest,
#     GetNotificationsResponse,
#     NotificationCountResponse,
#     NotificationItem,
    
#     # Notification Action Models
#     MarkNotificationReadRequest,
#     MarkNotificationReadResponse,
#     MarkAllNotificationsReadResponse,
#     DeleteNotificationRequest,
#     DeleteNotificationResponse,
#     ClearAllNotificationsResponse,
    
#     # Notification Preferences Models
#     NotificationPreferencesRequest,
#     NotificationPreferencesResponse,
    
#     # Broadcast Models
#     BroadcastNotificationRequest,
#     BroadcastNotificationResponse
# )
# from .notification_service import (
#     register_device_token,
#     remove_device_token,
#     get_user_device_tokens,
#     send_notification_to_users,
#     get_user_notifications,
#     get_unread_count,
#     mark_notifications_as_read,
#     mark_all_notifications_as_read,
#     delete_notifications,
#     clear_all_notifications,
#     get_user_preferences,
#     update_user_preferences
# )
# from core.database.collections import get_collections

# import logging

# logger = logging.getLogger(__name__)

# # Create router
# router = APIRouter(prefix="/notifications", tags=["Notifications"])

# # ========================================
# # DEVICE TOKEN MANAGEMENT ENDPOINTS
# # ========================================

# @router.post("/device-token/register", response_model=RegisterDeviceTokenResponse)
# async def register_device_token_endpoint(
#     request: RegisterDeviceTokenRequest,
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Register a device token for push notifications.
    
#     - **device_token**: FCM device token
#     - **device_type**: Type of device (ios, android, web)
#     - **device_name**: Device name/model (optional)
#     - **device_id**: Unique device identifier (optional)
    
#     Returns the registration status and token ID.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         result = await register_device_token(
#             user_id=user_id,
#             device_token=request.device_token,
#             device_type=request.device_type,
#             device_name=request.device_name,
#             device_id=request.device_id
#         )
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to register device token"),
#                 error="registration_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             result["message"],
#             data={
#                 "token_id": result["token_id"],
#                 "user_id": user_id,
#                 "device_type": request.device_type,
#                 "is_new": result.get("is_new", True),
#                 "registered_at": datetime.now(timezone.utc).isoformat() + "Z"
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in register device token endpoint: {e}")
#         return create_error_response(
#             "Failed to register device token",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# @router.delete("/device-token/remove", response_model=RemoveDeviceTokenResponse)
# async def remove_device_token_endpoint(
#     request: RemoveDeviceTokenRequest,
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Remove a device token.
    
#     - **device_token**: FCM device token to remove
    
#     Returns the removal status.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         result = await remove_device_token(
#             user_id=user_id,
#             device_token=request.device_token
#         )
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to remove device token"),
#                 error="removal_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             result["message"],
#             data={
#                 "removed_at": datetime.now(timezone.utc).isoformat() + "Z"
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in remove device token endpoint: {e}")
#         return create_error_response(
#             "Failed to remove device token",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# @router.get("/device-tokens", response_model=UserDeviceTokensResponse)
# async def get_device_tokens_endpoint(
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Get all registered device tokens for the current user.
    
#     Returns a list of all active device tokens.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         tokens = await get_user_device_tokens(user_id, active_only=True)
        
#         # Format tokens
#         formatted_tokens = []
#         for token in tokens:
#             formatted_tokens.append({
#                 "token_id": str(token["_id"]),
#                 "device_token": token["device_token"],
#                 "device_type": token["device_type"],
#                 "device_name": token.get("device_name"),
#                 "device_id": token.get("device_id"),
#                 "is_active": token["is_active"],
#                 "created_at": token["created_at"].isoformat() + "Z",
#                 "updated_at": token["updated_at"].isoformat() + "Z"
#             })
        
#         return create_success_response(
#             "Device tokens retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "total_devices": len(formatted_tokens),
#                 "devices": formatted_tokens
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in get device tokens endpoint: {e}")
#         return create_error_response(
#             "Failed to retrieve device tokens",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# # ========================================
# # NOTIFICATION SENDING ENDPOINTS
# # ========================================

# @router.post("/send", response_model=SendNotificationResponse)
# async def send_notification_endpoint(
#     request: SendNotificationRequest,
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Send a notification to specific users.
    
#     **Note:** This endpoint is typically used by the system or captains/moderators.
#     For now, any authenticated user can send notifications for testing.
    
#     - **user_ids**: List of user IDs to send notification to
#     - **title**: Notification title
#     - **body**: Notification body/message
#     - **notification_type**: Type of notification
#     - **data**: Additional data payload (optional)
#     - **priority**: Notification priority (optional)
#     - **image_url**: Image URL for rich notification (optional)
    
#     Returns the sending status with success/failure counts.
#     """
#     try:
#         result = await send_notification_to_users(
#             user_ids=request.user_ids,
#             title=request.title,
#             body=request.body,
#             notification_type=request.notification_type.value,
#             data=request.data,
#             image_url=request.image_url,
#             sound=request.sound,
#             badge=request.badge,
#             priority=request.priority,
#             click_action=request.click_action,
#             save_to_db=True
#         )
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to send notifications"),
#                 error="send_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             "Notifications sent successfully",
#             data={
#                 "sent_to_count": result["sent_count"],
#                 "failed_count": result["failed_count"],
#                 "total_tokens": result.get("total_tokens", 0),
#                 "scheduled": False,
#                 "details": {
#                     "notification_type": request.notification_type.value,
#                     "priority": request.priority,
#                     "has_image": request.image_url is not None
#                 }
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in send notification endpoint: {e}")
#         return create_error_response(
#             "Failed to send notifications",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# # ========================================
# # NOTIFICATION RETRIEVAL ENDPOINTS
# # ========================================

# @router.get("/", response_model=GetNotificationsResponse)
# async def get_notifications_endpoint(
#     page: int = 1,
#     page_size: int = 20,
#     filter_type: Optional[str] = None,
#     filter_read: Optional[bool] = None,
#     sort_order: str = "desc",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Get notifications for the current user with pagination and filtering.
    
#     Query Parameters:
#     - **page**: Page number (starts from 1, default: 1)
#     - **page_size**: Number of items per page (max 100, default: 20)
#     - **filter_type**: Filter by notification type (optional)
#     - **filter_read**: Filter by read status (true=read, false=unread, null=all)
#     - **sort_order**: Sort order by date ("desc" or "asc", default: "desc")
    
#     Returns a paginated list of notifications.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         # Validate pagination
#         if page < 1:
#             page = 1
#         if page_size < 1 or page_size > 100:
#             page_size = 20
        
#         result = await get_user_notifications(
#             user_id=user_id,
#             page=page,
#             page_size=page_size,
#             filter_type=filter_type,
#             filter_read=filter_read,
#             sort_order=sort_order
#         )
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to retrieve notifications"),
#                 error="retrieval_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             "Notifications retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "total_count": result["total_count"],
#                 "unread_count": result["unread_count"],
#                 "page": result["page"],
#                 "page_size": result["page_size"],
#                 "total_pages": result["total_pages"],
#                 "notifications": result["notifications"]
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in get notifications endpoint: {e}")
#         return create_error_response(
#             "Failed to retrieve notifications",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# @router.get("/count", response_model=NotificationCountResponse)
# async def get_notification_count_endpoint(
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Get unread notification count for the current user.
    
#     Returns the count of unread notifications.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         unread_count = await get_unread_count(user_id)
        
#         # Get total count
#         result = await get_user_notifications(user_id=user_id, page=1, page_size=1)
#         total_count = result.get("total_count", 0)
        
#         return create_success_response(
#             "Notification count retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "unread_count": unread_count,
#                 "total_count": total_count
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in get notification count endpoint: {e}")
#         return create_error_response(
#             "Failed to retrieve notification count",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# # ========================================
# # NOTIFICATION ACTION ENDPOINTS
# # ========================================

# @router.post("/mark-read", response_model=MarkNotificationReadResponse)
# async def mark_notifications_read_endpoint(
#     request: MarkNotificationReadRequest,
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Mark specific notifications as read.
    
#     - **notification_ids**: List of notification IDs to mark as read
    
#     Returns the count of notifications marked as read.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         result = await mark_notifications_as_read(
#             user_id=user_id,
#             notification_ids=request.notification_ids
#         )
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to mark notifications as read"),
#                 error="mark_read_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             f"Successfully marked {result['marked_count']} notification(s) as read",
#             data={
#                 "marked_count": result["marked_count"],
#                 "failed_count": result.get("failed_count", 0),
#                 "read_at": datetime.now(timezone.utc).isoformat() + "Z"
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in mark notifications read endpoint: {e}")
#         return create_error_response(
#             "Failed to mark notifications as read",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# @router.post("/mark-all-read", response_model=MarkAllNotificationsReadResponse)
# async def mark_all_notifications_read_endpoint(
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Mark all notifications as read for the current user.
    
#     Returns the count of notifications marked as read.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         result = await mark_all_notifications_as_read(user_id=user_id)
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to mark all notifications as read"),
#                 error="mark_all_read_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             f"Successfully marked all {result['marked_count']} notification(s) as read",
#             data={
#                 "user_id": user_id,
#                 "marked_count": result["marked_count"],
#                 "read_at": datetime.now(timezone.utc).isoformat() + "Z"
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in mark all notifications read endpoint: {e}")
#         return create_error_response(
#             "Failed to mark all notifications as read",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# @router.delete("/delete", response_model=DeleteNotificationResponse)
# async def delete_notifications_endpoint(
#     request: DeleteNotificationRequest,
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Delete specific notifications.
    
#     - **notification_ids**: List of notification IDs to delete
    
#     Returns the count of notifications deleted.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         result = await delete_notifications(
#             user_id=user_id,
#             notification_ids=request.notification_ids
#         )
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to delete notifications"),
#                 error="delete_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             f"Successfully deleted {result['deleted_count']} notification(s)",
#             data={
#                 "deleted_count": result["deleted_count"],
#                 "failed_count": result.get("failed_count", 0)
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in delete notifications endpoint: {e}")
#         return create_error_response(
#             "Failed to delete notifications",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# @router.delete("/clear-all", response_model=ClearAllNotificationsResponse)
# async def clear_all_notifications_endpoint(
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Clear all notifications for the current user.
    
#     Returns the count of notifications deleted.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         result = await clear_all_notifications(user_id=user_id)
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to clear all notifications"),
#                 error="clear_all_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             f"Successfully cleared all {result['deleted_count']} notification(s)",
#             data={
#                 "user_id": user_id,
#                 "deleted_count": result["deleted_count"]
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in clear all notifications endpoint: {e}")
#         return create_error_response(
#             "Failed to clear all notifications",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# # ========================================
# # NOTIFICATION PREFERENCES ENDPOINTS
# # ========================================

# @router.get("/preferences", response_model=NotificationPreferencesResponse)
# async def get_notification_preferences_endpoint(
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Get notification preferences for the current user.
    
#     Returns the user's notification preferences.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         preferences = await get_user_preferences(user_id)
        
#         return create_success_response(
#             "Notification preferences retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "preferences": preferences
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in get notification preferences endpoint: {e}")
#         return create_error_response(
#             "Failed to retrieve notification preferences",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# @router.put("/preferences", response_model=NotificationPreferencesResponse)
# async def update_notification_preferences_endpoint(
#     request: NotificationPreferencesRequest,
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Update notification preferences for the current user.
    
#     - **enable_push_notifications**: Enable/disable push notifications (optional)
#     - **enable_email_notifications**: Enable/disable email notifications (optional)
#     - **enable_sms_notifications**: Enable/disable SMS notifications (optional)
#     - **club_notifications**: Enable/disable club-related notifications (optional)
#     - **payment_notifications**: Enable/disable payment-related notifications (optional)
#     - **membership_notifications**: Enable/disable membership-related notifications (optional)
#     - **system_notifications**: Enable/disable system notifications (optional)
#     - **quiet_hours_enabled**: Enable quiet hours (optional)
#     - **quiet_hours_start**: Quiet hours start time in HH:MM format (optional)
#     - **quiet_hours_end**: Quiet hours end time in HH:MM format (optional)
    
#     Returns the updated notification preferences.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         # Convert request to dict, excluding None values
#         preferences_dict = request.dict(exclude_none=True)
        
#         result = await update_user_preferences(
#             user_id=user_id,
#             preferences=preferences_dict
#         )
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to update notification preferences"),
#                 error="update_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             "Notification preferences updated successfully",
#             data={
#                 "user_id": user_id,
#                 "preferences": result["preferences"],
#                 "updated_at": datetime.now(timezone.utc).isoformat() + "Z"
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in update notification preferences endpoint: {e}")
#         return create_error_response(
#             "Failed to update notification preferences",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

# # ========================================
# # BROADCAST NOTIFICATIONS (ADMIN ONLY)
# # ========================================

# @router.post("/broadcast", response_model=BroadcastNotificationResponse)
# async def broadcast_notification_endpoint(
#     request: BroadcastNotificationRequest,
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Broadcast a notification to all users or a specific role.
    
#     **Note:** This endpoint requires admin privileges.
    
#     - **title**: Notification title
#     - **body**: Notification body/message
#     - **notification_type**: Type of notification
#     - **data**: Additional data payload (optional)
#     - **image_url**: Image URL for rich notification (optional)
#     - **target_role**: Target user role (all, Member, Captain, Moderator)
    
#     Returns the broadcast status with success/failure counts.
#     """
#     try:
#         # Check if user is admin (basic check - you may want to enhance this)
#         user_role = current_user.get("role", "Member")
#         if user_role not in ["Admin", "SuperAdmin"]:
#             return create_error_response(
#                 "Insufficient permissions. Admin access required.",
#                 error="permission_denied",
#                 status_code=status.HTTP_403_FORBIDDEN
#             )
        
#         # Get all users based on target role
#         collections = get_collections()
#         users_collection = collections.get_users_collection()
        
#         query = {}
#         if request.target_role and request.target_role != "all":
#             query["role"] = request.target_role
        
#         users = await users_collection.find(query, {"_id": 1}).to_list(length=None)
#         user_ids = [str(user["_id"]) for user in users]
        
#         if not user_ids:
#             return create_error_response(
#                 "No users found for the specified target role",
#                 error="no_users_found",
#                 status_code=status.HTTP_404_NOT_FOUND
#             )
        
#         # Send notification to all users
#         result = await send_notification_to_users(
#             user_ids=user_ids,
#             title=request.title,
#             body=request.body,
#             notification_type=request.notification_type.value,
#             data=request.data,
#             image_url=request.image_url,
#             priority="high",
#             save_to_db=True
#         )
        
#         if not result["success"]:
#             return create_error_response(
#                 result.get("error", "Failed to broadcast notifications"),
#                 error="broadcast_failed",
#                 status_code=status.HTTP_400_BAD_REQUEST
#             )
        
#         return create_success_response(
#             "Broadcast notification sent successfully",
#             data={
#                 "target_user_count": len(user_ids),
#                 "sent_count": result["sent_count"],
#                 "failed_count": result["failed_count"],
#                 "target_role": request.target_role,
#                 "scheduled": False
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"❌ Error in broadcast notification endpoint: {e}")
#         return create_error_response(
#             "Failed to broadcast notifications",
#             error="internal_error",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )



"""
Notification Service Routes
Optimized version with reduced redundancy and cleaner structure.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Optional, List
from datetime import datetime, timezone

from core.auth.auth_middleware import get_current_user_or_admin
from .models import *
from .notification_service import *
from core.database.collections import get_collections

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


# Helper function to get current UTC time in ISO format
def now_iso():
    return datetime.now(timezone.utc).isoformat() + "Z"

def create_response(status_code: int, status: str, message: str, data=None):
    """Create a common response body with status code"""
    logger.debug(
        f"Creating API response - Status: {status_code}, Type: {status}, Message: {message}"
    )

    # Use jsonable_encoder to handle datetime and other non-JSON serializable objects
    encoded_data = jsonable_encoder(data) if data is not None else None

    return JSONResponse(
        status_code=status_code,
        content={"status": status, "message": message, "data": encoded_data},
    )
# ========================================
# DEVICE TOKEN MANAGEMENT
# ========================================

@router.post("/device-token/register", response_model=RegisterDeviceTokenResponse)
async def register_device_token_endpoint(request: RegisterDeviceTokenRequest, current_user: dict = Depends(get_current_user_or_admin)):
    """Register a device token for push notifications."""
    try:
        user_id = current_user["user_id"]
        result = await register_device_token(user_id, request.device_token, request.device_type, request.device_name, request.device_id)
        if not result["success"]:
            return create_response(status.HTTP_400_BAD_REQUEST, "error", result.get("error", "Failed to register device token"))

        return create_response(
            status.HTTP_200_OK,
            "success",
            result["message"],
            data={
                "token_id": result["token_id"],
                "user_id": user_id,
                "device_type": request.device_type,
                "is_new": result.get("is_new", True),
                "registered_at": now_iso()
            }
        )
    except Exception as e:
        logger.error(f"Error in register device token: {e}")
        return create_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "error", "Failed to register device token")


@router.delete("/device-token/remove", response_model=RemoveDeviceTokenResponse)
async def remove_device_token_endpoint(request: RemoveDeviceTokenRequest, current_user: dict = Depends(get_current_user_or_admin)):
    """Remove a device token."""
    try:
        user_id = current_user["user_id"]
        result = await remove_device_token(user_id, request.device_token)
        if not result["success"]:
            return create_response(status.HTTP_400_BAD_REQUEST, "error", result.get("error", "Failed to remove device token"))

        return create_response(status.HTTP_200_OK, "success", result["message"], data={"removed_at": now_iso()})
    except Exception as e:
        logger.error(f"Error in remove device token: {e}")
        return create_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "error", "Failed to remove device token")


@router.get("/device-tokens", response_model=UserDeviceTokensResponse)
async def get_device_tokens_endpoint(current_user: dict = Depends(get_current_user_or_admin)):
    """Get all registered device tokens for the current user."""
    try:
        user_id = current_user["user_id"]
        tokens = await get_user_device_tokens(user_id, active_only=True)
        formatted_tokens = [
            {
                "token_id": str(token["_id"]),
                "device_token": token["device_token"],
                "device_type": token["device_type"],
                "device_name": token.get("device_name"),
                "device_id": token.get("device_id"),
                "is_active": token["is_active"],
                "created_at": token["created_at"].isoformat() + "Z",
                "updated_at": token["updated_at"].isoformat() + "Z"
            }
            for token in tokens
        ]
        return create_response(status.HTTP_200_OK, "success", "Device tokens retrieved successfully", data={"user_id": user_id, "total_devices": len(formatted_tokens), "devices": formatted_tokens})
    except Exception as e:
        logger.error(f"Error in get device tokens: {e}")
        return create_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "error", "Failed to retrieve device tokens")


# ========================================
# NOTIFICATION SENDING
# ========================================

# @router.post("/send", response_model=SendNotificationResponse)
# async def send_notification_endpoint(request: SendNotificationRequest, current_user: dict = Depends(get_current_user_or_admin)):
#     """Send a notification to specific users."""
#     try:
#         result = await send_notification_to_users(
#             user_ids=request.user_ids,
#             title=request.title,
#             body=request.body,
#             notification_type=request.notification_type.value,
#             data=request.data,
#             image_url=request.image_url,
#             sound=request.sound,
#             badge=request.badge,
#             priority=request.priority,
#             click_action=request.click_action,
#             save_to_db=True
#         )
#         if not result["success"]:
#             return create_error_response(result.get("error", "Failed to send notifications"), error="send_failed", status_code=status.HTTP_400_BAD_REQUEST)

#         return create_success_response(
#             "Notifications sent successfully",
#             data={
#                 "sent_to_count": result["sent_count"],
#                 "failed_count": result["failed_count"],
#                 "total_tokens": result.get("total_tokens", 0),
#                 "scheduled": False,
#                 "details": {
#                     "notification_type": request.notification_type.value,
#                     "priority": request.priority,
#                     "has_image": request.image_url is not None
#                 }
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error in send notification: {e}")
#         return create_error_response("Failed to send notifications", error="internal_error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# # ========================================
# # NOTIFICATION RETRIEVAL
# # ========================================

# @router.get("/", response_model=GetNotificationsResponse)
# async def get_notifications_endpoint(
#     page: int = 1, page_size: int = 20, filter_type: Optional[str] = None,
#     filter_read: Optional[bool] = None, sort_order: str = "desc",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """Get notifications for the current user with pagination and filtering."""
#     try:
#         user_id = current_user["user_id"]
#         page = max(1, page)
#         page_size = min(max(1, page_size), 100)

#         result = await get_user_notifications(user_id, page, page_size, filter_type, filter_read, sort_order)
#         if not result["success"]:
#             return create_error_response(result.get("error", "Failed to retrieve notifications"), error="retrieval_failed", status_code=status.HTTP_400_BAD_REQUEST)

#         return create_success_response(
#             "Notifications retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "total_count": result["total_count"],
#                 "unread_count": result["unread_count"],
#                 "page": result["page"],
#                 "page_size": result["page_size"],
#                 "total_pages": result["total_pages"],
#                 "notifications": result["notifications"]
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error in get notifications: {e}")
#         return create_error_response("Failed to retrieve notifications", error="internal_error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# @router.get("/count", response_model=NotificationCountResponse)
# async def get_notification_count_endpoint(current_user: dict = Depends(get_current_user_or_admin)):
#     """Get unread notification count for the current user."""
#     try:
#         user_id = current_user["user_id"]
#         unread_count = await get_unread_count(user_id)
#         total_count = (await get_user_notifications(user_id=user_id, page=1, page_size=1)).get("total_count", 0)
#         return create_success_response("Notification count retrieved successfully", data={"user_id": user_id, "unread_count": unread_count, "total_count": total_count})
#     except Exception as e:
#         logger.error(f"Error in get notification count: {e}")
#         return create_error_response("Failed to retrieve notification count", error="internal_error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# # ========================================
# # NOTIFICATION ACTIONS
# # ========================================

# @router.post("/mark-read", response_model=MarkNotificationReadResponse)
# async def mark_notifications_read_endpoint(request: MarkNotificationReadRequest, current_user: dict = Depends(get_current_user_or_admin)):
#     try:
#         user_id = current_user["user_id"]
#         result = await mark_notifications_as_read(user_id, request.notification_ids)
#         if not result["success"]:
#             return create_error_response(result.get("error", "Failed to mark notifications as read"), error="mark_read_failed", status_code=status.HTTP_400_BAD_REQUEST)
#         return create_success_response(f"Marked {result['marked_count']} notification(s) as read", data={"marked_count": result["marked_count"], "failed_count": result.get("failed_count", 0), "read_at": now_iso()})
#     except Exception as e:
#         logger.error(f"Error in mark notifications read: {e}")
#         return create_error_response("Failed to mark notifications as read", error="internal_error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# @router.post("/mark-all-read", response_model=MarkAllNotificationsReadResponse)
# async def mark_all_notifications_read_endpoint(current_user: dict = Depends(get_current_user_or_admin)):
#     try:
#         user_id = current_user["user_id"]
#         result = await mark_all_notifications_as_read(user_id)
#         if not result["success"]:
#             return create_error_response(result.get("error", "Failed to mark all notifications as read"), error="mark_all_read_failed", status_code=status.HTTP_400_BAD_REQUEST)
#         return create_success_response(f"Marked all {result['marked_count']} notification(s) as read", data={"user_id": user_id, "marked_count": result["marked_count"], "read_at": now_iso()})
#     except Exception as e:
#         logger.error(f"Error in mark all notifications read: {e}")
#         return create_error_response("Failed to mark all notifications as read", error="internal_error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.delete("/delete", response_model=DeleteNotificationResponse)
async def delete_notifications_endpoint(request: DeleteNotificationRequest, current_user: dict = Depends(get_current_user_or_admin)):
    try:
        user_id = current_user["user_id"]
        result = await delete_notifications(user_id, request.notification_ids)
        if not result["success"]:
            return create_response(status.HTTP_400_BAD_REQUEST, "error", result.get("error", "Failed to delete notifications"))
        return create_response(status.HTTP_200_OK, "success", f"Deleted {result['deleted_count']} notification(s)", data={"deleted_count": result["deleted_count"], "failed_count": result.get("failed_count", 0)})
    except Exception as e:
        logger.error(f"Error in delete notifications: {e}")
        return create_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "error", "Failed to delete notifications")


@router.delete("/clear-all", response_model=ClearAllNotificationsResponse)
async def clear_all_notifications_endpoint(current_user: dict = Depends(get_current_user_or_admin)):
    try:
        user_id = current_user["user_id"]
        result = await clear_all_notifications(user_id)
        if not result["success"]:
            return create_response(status.HTTP_400_BAD_REQUEST, "error", result.get("error", "Failed to clear all notifications"))
        return create_response(status.HTTP_200_OK, "success", f"Cleared all {result['deleted_count']} notification(s)", data={"user_id": user_id, "deleted_count": result["deleted_count"]})
    except Exception as e:
        logger.error(f"Error in clear all notifications: {e}")
        return create_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "error", "Failed to clear all notifications")


# ========================================
# NOTIFICATION PREFERENCES
# ========================================

# @router.get("/preferences", response_model=NotificationPreferencesResponse)
# async def get_notification_preferences_endpoint(current_user: dict = Depends(get_current_user_or_admin)):
#     try:
#         user_id = current_user["user_id"]
#         preferences = await get_user_preferences(user_id)
#         return create_success_response("Notification preferences retrieved successfully", data={"user_id": user_id, "preferences": preferences})
#     except Exception as e:
#         logger.error(f"Error in get preferences: {e}")
#         return create_error_response("Failed to retrieve notification preferences", error="internal_error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# @router.put("/preferences", response_model=NotificationPreferencesResponse)
# async def update_notification_preferences_endpoint(request: NotificationPreferencesRequest, current_user: dict = Depends(get_current_user_or_admin)):
#     try:
#         user_id = current_user["user_id"]
#         preferences_dict = request.dict(exclude_none=True)
#         result = await update_user_preferences(user_id, preferences_dict)
#         if not result["success"]:
#             return create_error_response(result.get("error", "Failed to update notification preferences"), error="update_failed", status_code=status.HTTP_400_BAD_REQUEST)
#         return create_success_response("Notification preferences updated successfully", data={"user_id": user_id, "preferences": result["preferences"], "updated_at": now_iso()})
#     except Exception as e:
#         logger.error(f"Error in update preferences: {e}")
#         return create_error_response("Failed to update notification preferences", error="internal_error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ========================================
# PICK OUTCOME ALERT PREFERENCES
# ========================================

# @router.get("/pick-outcome-alerts", response_model=NotificationPreferencesResponse)
# async def get_pick_outcome_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's pick outcome alert preference.
    
#     Returns whether the user has pick outcome alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
#         preferences = await get_user_preferences(user_id)
        
#         # Extract just the pick outcome alerts preference
#         pick_outcome_alerts = preferences.get("pick_outcome_alerts", True)
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "Pick outcome alert preference retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "preferences": {
#                     "pick_outcome_alerts": pick_outcome_alerts
#                 }
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error getting pick outcome alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to retrieve pick outcome alert preference"
#         )


@router.put("/pick-outcome-alerts", response_model=NotificationPreferencesResponse)
async def update_pick_outcome_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's pick outcome alert preference.
    
    - **enabled**: Whether to enable (true) or disable (false) pick outcome alerts
    
    Returns the updated preference.
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "pick_outcome_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"Pick outcome alerts {'enabled' if enabled else 'disabled'} successfully",
            data={
                "user_id": user_id,
                "pick_outcome_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
    except Exception as e:
        logger.error(f"Error updating pick outcome alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update pick outcome alert preference"
        )


# ========================================
# NEW PICK ALERT PREFERENCES
# ========================================

# @router.get("/new-pick-alerts", response_model=NotificationPreferencesResponse)
# async def get_new_pick_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's new pick alert preference.
    
#     Returns whether the user has new pick alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
#         c = get_collections()
#         preferences_collection = c.get_notification_preferences_collection()
        
#         prefs = await preferences_collection.find_one({"user_id": user_id})
        
#         # Default to True if no preferences found
#         new_pick_alerts = True
#         if prefs and "new_pick_alerts" in prefs:
#             new_pick_alerts = prefs["new_pick_alerts"]
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "New pick alert preference retrieved successfully",
#             data={
#                 "new_pick_alerts": new_pick_alerts
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error getting new pick alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get new pick alert preference"
#         )


@router.put("/new-pick-alerts", response_model=NotificationPreferencesResponse)
async def update_new_pick_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's new pick alert preference.
    
    Args:
        enabled: Whether to enable or disable new pick alerts
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "new_pick_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            "New pick alert preference updated successfully",
            data={
                "new_pick_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
    except Exception as e:
        logger.error(f"Error updating new pick alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update new pick alert preference"
        )


# ========================================
# CLUB JOIN ALERT PREFERENCES
# ========================================

# @router.get("/club-join-alerts", response_model=NotificationPreferencesResponse)
# async def get_club_join_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's club join alert preference.
    
#     Returns whether the user has club join alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
#         c = get_collections()
#         preferences_collection = c.get_notification_preferences_collection()
        
#         prefs = await preferences_collection.find_one({"user_id": user_id})
        
#         # Default to True if no preferences found
#         club_join_alerts = True
#         if prefs and "club_join_alerts" in prefs:
#             club_join_alerts = prefs["club_join_alerts"]
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "Club join alert preference retrieved successfully",
#             data={
#                 "club_join_alerts": club_join_alerts
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error getting club join alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get club join alert preference"
#         )


@router.put("/club-join-alerts", response_model=NotificationPreferencesResponse)
async def update_club_join_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's club join alert preference.
    
    Args:
        enabled: Whether to enable or disable club join alerts
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "club_join_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            "Club join alert preference updated successfully",
            data={
                "club_join_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
    except Exception as e:
        logger.error(f"Error updating club join alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update club join alert preference"
        )


# ========================================
# CLUB STATUS ALERT PREFERENCES
# ========================================

# @router.get("/club-status-alerts", response_model=NotificationPreferencesResponse)
# async def get_club_status_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's club status alert preference.
    
#     Returns whether the user has club status alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
#         c = get_collections()
#         preferences_collection = c.get_notification_preferences_collection()
        
#         prefs = await preferences_collection.find_one({"user_id": user_id})
        
#         # Default to True if no preferences found
#         club_status_alerts = True
#         if prefs and "club_status_alerts" in prefs:
#             club_status_alerts = prefs["club_status_alerts"]
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "Club status alert preference retrieved successfully",
#             data={
#                 "club_status_alerts": club_status_alerts
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error getting club status alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get club status alert preference"
#         )


@router.put("/club-status-alerts", response_model=NotificationPreferencesResponse)
async def update_club_status_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's club status alert preference.
    
    Args:
        enabled: Whether to enable or disable club status alerts
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "club_status_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            "Club status alert preference updated successfully",
            data={
                "club_status_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
    except Exception as e:
        logger.error(f"Error updating club status alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update club status alert preference"
        )


# ========================================
# TESTING ENDPOINTS (DEVELOPMENT ONLY)
# ========================================

# @router.post("/test/pick-outcome")
# async def test_pick_outcome_notification(
#     club_id: str,
#     pick_id: str = "test_pick_123",
#     outcome: str = "win",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger pick outcome notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             get_club_members,
#             filter_users_by_notification_preference,
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing pick outcome notification for club {club_id}")
        
#         # Get all club members
#         all_members = await get_club_members(club_id)
#         logger.info(f"🧪 Found {len(all_members)} total club members")
        
#         # Filter by pick outcome alerts
#         users_with_alerts = await filter_users_by_notification_preference(
#             all_members, 
#             "pick_outcome_alerts"
#         )
#         logger.info(f"🧪 Found {len(users_with_alerts)} users with pick outcome alerts enabled")
        
#         if not users_with_alerts:
#             return create_response(
#                 status.HTTP_200_OK,
#                 "success",
#                 "No users with pick outcome alerts found",
#                 data={
#                     "club_id": club_id,
#                     "total_members": len(all_members),
#                     "users_with_alerts": 0,
#                     "notification_sent": False
#                 }
#             )
        
#         # Prepare test notification
#         title = "🧪 Test: Pick Won!" if outcome == "win" else "🧪 Test: Pick Lost"
#         body = f"TEST NOTIFICATION - Pick has resulted in a {outcome.upper()}!"
        
#         notification_data = {
#             "pick_id": pick_id,
#             "club_id": club_id,
#             "outcome": outcome,
#             "submitted_by": "Test User",
#             "pick_title": "Test Pick",
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=users_with_alerts,
#             title=title,
#             body=body,
#             notification_type="club_pick_outcome",
#             data=notification_data,
#             click_action=f"club/{club_id}/picks/{pick_id}",
#             priority="high"
#         )
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             f"Test notification sent to {result.get('sent_count', 0)} users",
#             data={
#                 "club_id": club_id,
#                 "total_members": len(all_members),
#                 "users_with_alerts": len(users_with_alerts),
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test pick outcome notification: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             f"Test failed: {str(e)}"
#         )


# @router.post("/test/new-pick")
# async def test_new_pick_notification(
#     club_id: str,
#     pick_id: str = "test_new_pick_456",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger new pick notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             get_club_members,
#             filter_users_by_notification_preference,
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing new pick notification for club {club_id}")
        
#         # Get all club members
#         all_members = await get_club_members(club_id)
#         logger.info(f"🧪 Found {len(all_members)} total club members")
        
#         # Filter by new pick alerts
#         users_with_alerts = await filter_users_by_notification_preference(
#             all_members, 
#             "new_pick_alerts"
#         )
#         logger.info(f"🧪 Found {len(users_with_alerts)} users with new pick alerts enabled")
        
#         if not users_with_alerts:
#             return create_success_response(
#                 "No users with new pick alerts found",
#                 data={
#                     "club_id": club_id,
#                     "total_members": len(all_members),
#                     "users_with_alerts": 0,
#                     "notification_sent": False
#                 }
#             )
        
#         # Prepare test notification
#         title = "🧪 Test: New Pick Posted!"
#         body = "TEST NOTIFICATION - Captain has posted a new pick!"
        
#         notification_data = {
#             "pick_id": pick_id,
#             "club_id": club_id,
#             "submitted_by": "Test Captain",
#             "pick_title": "Test New Pick",
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=users_with_alerts,
#             title=title,
#             body=body,
#             notification_type="club_new_pick",
#             data=notification_data,
#             click_action=f"club/{club_id}/picks/{pick_id}",
#             priority="normal"
#         )
        
#         return create_success_response(
#             f"Test new pick notification sent to {result.get('sent_count', 0)} users",
#             data={
#                 "club_id": club_id,
#                 "total_members": len(all_members),
#                 "users_with_alerts": len(users_with_alerts),
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test new pick notification: {e}")
#         return create_error_response(
#             f"Test failed: {str(e)}",
#             error="test_failed",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )


# @router.post("/test/club-join")
# async def test_club_join_notification(
#     club_id: str,
#     new_member_name: str = "Test New Member",
#     membership_type: str = "paid",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger club join notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             get_club_members,
#             filter_users_by_notification_preference,
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing club join notification for club {club_id}")
        
#         # Get all club members (captains and moderators)
#         all_members = await get_club_members(club_id)
#         logger.info(f"🧪 Found {len(all_members)} total club members")
        
#         # Filter by club join alerts
#         users_with_alerts = await filter_users_by_notification_preference(
#             all_members, 
#             "club_join_alerts"
#         )
#         logger.info(f"🧪 Found {len(users_with_alerts)} users with club join alerts enabled")
        
#         if not users_with_alerts:
#             return create_success_response(
#                 "No users with club join alerts found",
#                 data={
#                     "club_id": club_id,
#                     "total_members": len(all_members),
#                     "users_with_alerts": 0,
#                     "notification_sent": False
#                 }
#             )
        
#         # Prepare test notification
#         title = "🧪 Test: New Member Joined!"
#         body = f"TEST NOTIFICATION - {new_member_name} has joined the club ({membership_type} member)!"
        
#         notification_data = {
#             "club_id": club_id,
#             "new_member_name": new_member_name,
#             "membership_type": membership_type,
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=users_with_alerts,
#             title=title,
#             body=body,
#             notification_type="club_member_join",
#             data=notification_data,
#             click_action=f"club/{club_id}/members",
#             priority="normal"
#         )
        
#         return create_success_response(
#             f"Test club join notification sent to {result.get('sent_count', 0)} users",
#             data={
#                 "club_id": club_id,
#                 "total_members": len(all_members),
#                 "users_with_alerts": len(users_with_alerts),
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test club join notification: {e}")
#         return create_error_response(
#             f"Test failed: {str(e)}",
#             error="test_failed",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )


# @router.post("/test/club-status")
# async def test_club_status_notification(
#     club_id: str,
#     new_status: str = "inactive",
#     changed_by: str = "Admin",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger club status change notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             get_club_members,
#             filter_users_by_notification_preference,
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing club status notification for club {club_id}")
        
#         # Get all club members
#         all_members = await get_club_members(club_id)
#         logger.info(f"🧪 Found {len(all_members)} total club members")
        
#         # Filter by club status alerts
#         users_with_alerts = await filter_users_by_notification_preference(
#             all_members, 
#             "club_status_alerts"
#         )
#         logger.info(f"🧪 Found {len(users_with_alerts)} users with club status alerts enabled")
        
#         if not users_with_alerts:
#             return create_success_response(
#                 "No users with club status alerts found",
#                 data={
#                     "club_id": club_id,
#                     "total_members": len(all_members),
#                     "users_with_alerts": 0,
#                     "notification_sent": False
#                 }
#             )
        
#         # Prepare test notification
#         title = f"🧪 Test: Club Status Changed!"
#         body = f"TEST NOTIFICATION - Club has been {new_status} by {changed_by}!"
        
#         notification_data = {
#             "club_id": club_id,
#             "new_status": new_status,
#             "changed_by": changed_by,
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=users_with_alerts,
#             title=title,
#             body=body,
#             notification_type="club_status_change",
#             data=notification_data,
#             click_action=f"club/{club_id}",
#             priority="high"
#         )
        
#         return create_success_response(
#             f"Test club status notification sent to {result.get('sent_count', 0)} users",
#             data={
#                 "club_id": club_id,
#                 "total_members": len(all_members),
#                 "users_with_alerts": len(users_with_alerts),
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test club status notification: {e}")
#         return create_error_response(
#             f"Test failed: {str(e)}",
#             error="test_failed",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )


# @router.get("/test/device-tokens/{user_id}")
# async def test_user_device_tokens(user_id: str):
#     """
#     Test endpoint to check user's device tokens.
#     Development/testing only - remove in production.
#     """
#     try:
#         tokens = await get_user_device_tokens(user_id, active_only=True)
        
#         return create_success_response(
#             f"Found {len(tokens)} active device tokens for user {user_id}",
#             data={
#                 "user_id": user_id,
#                 "active_tokens": len(tokens),
#                 "tokens": [
#                     {
#                         "token_id": str(token["_id"]),
#                         "device_type": token["device_type"],
#                         "device_name": token.get("device_name"),
#                         "is_active": token["is_active"],
#                         "created_at": token["created_at"].isoformat() + "Z"
#                     }
#                     for token in tokens
#                 ]
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error getting user device tokens: {e}")
#         return create_error_response(
#             f"Failed to get device tokens: {str(e)}",
#             error="test_failed",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )


# @router.get("/test/club-members/{club_id}")
# async def test_club_members(club_id: str):
#     """
#     Test endpoint to check club members and their preferences.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import get_club_members
        
#         all_members = await get_club_members(club_id)
        
#         # Get preferences for each member
#         members_with_prefs = []
#         for user_id in all_members:
#             prefs = await get_user_preferences(user_id)
#             members_with_prefs.append({
#                 "user_id": user_id,
#                 "pick_outcome_alerts": prefs.get("pick_outcome_alerts", True),
#                 "enable_push_notifications": prefs.get("enable_push_notifications", True)
#             })
        
#         return create_success_response(
#             f"Found {len(all_members)} club members",
#             data={
#                 "club_id": club_id,
#                 "total_members": len(all_members),
#                 "members": members_with_prefs
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error getting club members: {e}")
#         return create_error_response(
#             f"Failed to get club members: {str(e)}",
#             error="test_failed",
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )


# ========================================
# BROADCAST NOTIFICATIONS (ADMIN ONLY)
# ========================================

@router.post("/broadcast", response_model=BroadcastNotificationResponse)
async def broadcast_notification_endpoint(request: BroadcastNotificationRequest, current_user: dict = Depends(get_current_user_or_admin)):
    try:
        if current_user.get("role") not in ["Admin", "SuperAdmin"]:
            return create_response(status.HTTP_403_FORBIDDEN, "error", "Admin access required")

        collections = get_collections()
        users_collection = collections.get_users_collection()

        query = {} if request.target_role in [None, "all"] else {"role": request.target_role}
        users = await users_collection.find(query, {"_id": 1}).to_list(length=None)
        user_ids = [str(user["_id"]) for user in users]
        if not user_ids:
            return create_response(status.HTTP_404_NOT_FOUND, "error", "No users found for target role")

        result = await send_notification_to_users(user_ids=user_ids, title=request.title, body=request.body, notification_type=request.notification_type.value, data=request.data, image_url=request.image_url, priority="high", save_to_db=True)
        if not result["success"]:
            return create_response(status.HTTP_400_BAD_REQUEST, "error", result.get("error", "Failed to broadcast notifications"))

        return create_response(status.HTTP_200_OK, "success", "Broadcast sent successfully", data={"target_user_count": len(user_ids), "sent_count": result["sent_count"], "failed_count": result["failed_count"], "target_role": request.target_role, "scheduled": False})
    except Exception as e:
        logger.error(f"Error in broadcast notification: {e}")
        return create_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "error", "Failed to broadcast notifications")


# ========================================
# DM BLOCK ALERT PREFERENCES
# ========================================

# @router.get("/dm-block-alerts", response_model=NotificationPreferencesResponse)
# async def get_dm_block_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's DM block alert preference.
    
#     Returns whether the user has DM block alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
#         c = get_collections()
#         preferences_collection = c.get_notification_preferences_collection()
        
#         prefs = await preferences_collection.find_one({"user_id": user_id})
        
#         # Default to True if no preferences found
#         dm_block_alerts = True
#         if prefs and "dm_block_alerts" in prefs:
#             dm_block_alerts = prefs["dm_block_alerts"]
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "DM block alert preference retrieved successfully",
#             data={
#                 "dm_block_alerts": dm_block_alerts
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error getting DM block alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get DM block alert preference"
#         )


@router.put("/dm-block-alerts", response_model=NotificationPreferencesResponse)
async def update_dm_block_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's DM block alert preference.
    
    Args:
        enabled: Whether to enable or disable DM block alerts
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "dm_block_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"DM block alerts {'enabled' if enabled else 'disabled'} successfully",
            data={
                "user_id": user_id,
                "dm_block_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating DM block alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update DM block alert preference"
        )


# ========================================
# NOTIFICATION PREFERENCES STATUS
# ========================================

@router.get("/preferences-status", response_model=dict)
async def get_all_notification_preferences_status(current_user: dict = Depends(get_current_user_or_admin)):
    """
    Get notification types with their enabled/disabled status based on user role.
    
    **Role-based preferences:**
    - **Captain/Moderator**: club_member_join, club_message, club_pick_outcome, subscription_alerts
    - **Member**: club_status_change, club_message, club_new_pick, club_pick_outcome, dm_block, subscription_alerts
    
    Returns:
        dict: List of notification types with their enabled status
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role", "Member")
        
        # Get user's notification preferences
        collections = get_collections()
        preferences_col = collections.get_notification_preferences_collection()
        
        user_prefs = await preferences_col.find_one({"user_id": user_id})
        
        # Define notification preferences based on user role
        if user_role.lower() in ["captain", "moderator"]:
            # Captain/Moderator preferences
            notification_preferences = [
                {
                    "notification_type": "club_member_join",
                    "preference_field": "club_join_alerts",
                    "description": "New member join alerts"
                },
                {
                    "notification_type": "club_message",
                    "preference_field": "message_alerts",
                    "description": "New message alerts"
                },
                {
                    "notification_type": "club_pick_outcome",
                    "preference_field": "pick_outcome_alerts",
                    "description": "Pick outcome alerts (wins/losses)"
                },
                {
                    "notification_type": "subscription_alerts",
                    "preference_field": "subscription_alerts",
                    "description": "Subscription and payment alerts"
                }
            ]
        else:
            # Member preferences
            notification_preferences = [
                {
                    "notification_type": "club_status_change",
                    "preference_field": "club_status_alerts",
                    "description": "Club status change alerts"
                },
                {
                    "notification_type": "club_message",
                    "preference_field": "message_alerts",
                    "description": "New message alerts"
                },
                {
                    "notification_type": "club_new_pick",
                    "preference_field": "new_pick_alerts",
                    "description": "New pick alerts from captains/moderators"
                },
                {
                    "notification_type": "club_pick_outcome",
                    "preference_field": "pick_outcome_alerts",
                    "description": "Pick outcome alerts (wins/losses)"
                },
                {
                    "notification_type": "dm_block",
                    "preference_field": "dm_block_alerts",
                    "description": "DM block/unblock alerts"
                },
                {
                    "notification_type": "subscription_alerts",
                    "preference_field": "subscription_alerts",
                    "description": "Subscription and payment alerts"
                }
            ]
        
        # Build response with status for each notification type
        preferences_status = []
        for pref in notification_preferences:
            is_enabled = True  # Default to enabled
            
            if user_prefs and pref["preference_field"] in user_prefs:
                is_enabled = user_prefs[pref["preference_field"]]
            
            preferences_status.append({
                "notification_type": pref["notification_type"],
                "is_enabled": is_enabled,
                "description": pref["description"]
            })
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            "Notification preferences status retrieved successfully",
            data={
                "user_id": user_id,
                "user_role": user_role,
                "preferences": preferences_status
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting notification preferences status: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to get notification preferences status"
        )


# ========================================
# BELL ICON STATUS (NOTIFICATION CENTER OPEN/CLOSE)
# ========================================

@router.get("/bell-icon-status", response_model=dict)
async def get_bell_icon_status(current_user: dict = Depends(get_current_user_or_admin)):
    """
    Get the user's bell icon status (whether notification center is currently open).
    
    Returns:
        dict: Contains is_open status (default: False) and unread_count
        - If is_open=True, unread_count=0
        - If is_open=False, unread_count=count of notifications where is_read=False
    """
    try:
        user_id = current_user["user_id"]
        
        # Get user's bell icon status from users collection
        collections = get_collections()
        users_collection = collections.get_users_collection()
        notifications_collection = collections.get_notifications_collection()
        
        user = await users_collection.find_one(
            {"_id": ObjectId(user_id)},
            {"is_open": 1}
        )
        
        if not user:
            return create_response(
                status.HTTP_404_NOT_FOUND,
                "error",
                "User not found"
            )
        
        # Default to False if not set
        is_open = user.get("is_open", False)
        
        # Calculate unread count
        if is_open:
            # If notification center is open, unread count is 0
            unread_count = 0
        else:
            # If closed, count unread notifications
            unread_count = await notifications_collection.count_documents({
                "user_id": user_id,
                "is_read": False
            })
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            "Bell icon status retrieved successfully",
            data={
                "user_id": user_id,
                "is_open": is_open,
                "unread_count": unread_count
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting bell icon status: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to get bell icon status"
        )


@router.put("/bell-icon-status", response_model=dict)
async def update_bell_icon_status(
    is_open: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's bell icon status (notification center open/closed).
    
    This endpoint tracks when users open or close the notification center (bell icon).
    
    **Behavior:**
    - When bell icon is opened (`is_open=True`):
      - Marks ALL unread notifications as read
      - Sets `unread_count = 0`
      - Updates `read_at` timestamp for all notifications
    
    - When bell icon is closed (`is_open=False`):
      - Calculates current unread count from `is_read=False` notifications
    
    - When a new notification arrives (automatic):
      - Bell icon automatically closes (`is_open=False`)
      - `unread_count` reflects total unread notifications
    
    Args:
        is_open: True if notification center is open, False if closed
    
    Returns:
        dict: Updated status with timestamp and unread_count
    """
    try:
        user_id = current_user["user_id"]
        
        # Update user's bell icon status in users collection
        collections = get_collections()
        users_collection = collections.get_users_collection()
        notifications_collection = collections.get_notifications_collection()
        
        now = datetime.now(timezone.utc)
        
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "is_open": is_open,
                    "notification_center_last_opened_at": now if is_open else None,
                    "notification_center_last_closed_at": now if not is_open else None,
                    "updated_at": now
                }
            }
        )
        
        if result.modified_count == 0:
            return create_response(
                status.HTTP_400_BAD_REQUEST,
                "error",
                "Failed to update bell icon status"
            )
        
        # Calculate unread count and mark notifications as read when bell is opened
        if is_open:
            # When notification center is opened, mark ALL unread notifications as read
            from services.notifications.notification_service import mark_all_notifications_as_read
            mark_result = await mark_all_notifications_as_read(user_id)
            
            if mark_result.get("success", False):
                marked_count = mark_result.get("marked_count", 0)
                logger.info(f"✅ Marked {marked_count} notifications as read when bell icon opened for user {user_id}")
            
            # Unread count is 0 after marking all as read
            unread_count = 0
        else:
            # If closed, count unread notifications
            unread_count = await notifications_collection.count_documents({
                "user_id": user_id,
                "is_read": False
            })
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"Bell icon status updated: notification center is now {'open' if is_open else 'closed'}",
            data={
                "user_id": user_id,
                "is_open": is_open,
                "unread_count": unread_count,
                "updated_at": now.isoformat() + "Z"
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating bell icon status: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update bell icon status"
        )


# @router.post("/test/dm-block")
# async def test_dm_block_notification(
#     target_user_id: str,
#     action: str = "block",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger DM block/unblock notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing DM block notification for user {target_user_id}")
        
#         # Prepare test notification
#         action_text = "blocked" if action == "block" else "unblocked"
#         title = f"🧪 Test: User {action_text.title()}!"
#         body = f"TEST NOTIFICATION - You have been {action_text} in DMs!"
        
#         notification_data = {
#             "target_user_id": target_user_id,
#             "action": action,
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=[target_user_id],
#             title=title,
#             body=body,
#             notification_type="dm_block",
#             data=notification_data,
#             click_action="dm/conversations",
#             priority="normal"
#         )
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             f"Test DM block notification sent",
#             data={
#                 "target_user_id": target_user_id,
#                 "action": action,
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test DM block notification: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             f"Test failed: {str(e)}"
#         )


# ========================================
# MENTION ALERT PREFERENCES
# ========================================

# @router.get("/mention-alerts", response_model=NotificationPreferencesResponse)
# async def get_mention_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's mention alert preference.
    
#     Returns whether the user has mention alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
#         c = get_collections()
#         preferences_collection = c.get_notification_preferences_collection()
        
#         prefs = await preferences_collection.find_one({"user_id": user_id})
        
#         # Default to True if no preferences found
#         mention_alerts = True
#         if prefs and "mention_alerts" in prefs:
#             mention_alerts = prefs["mention_alerts"]
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "Mention alert preference retrieved successfully",
#             data={
#                 "mention_alerts": mention_alerts
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error getting mention alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get mention alert preference"
#         )


@router.put("/mention-alerts", response_model=NotificationPreferencesResponse)
async def update_mention_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's mention alert preference.
    
    Args:
        enabled: Whether to enable or disable mention alerts
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "mention_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"Mention alerts {'enabled' if enabled else 'disabled'} successfully",
            data={
                "user_id": user_id,
                "mention_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating mention alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update mention alert preference"
        )


# @router.post("/test/mention")
# async def test_mention_notification(
#     target_user_id: str,
#     club_id: str = "test-club",
#     sender_name: str = "Test User",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger mention notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing mention notification for user {target_user_id}")
        
#         # Prepare test notification
#         title = f"🧪 Test: You were mentioned!"
#         body = f"TEST NOTIFICATION - {sender_name} mentioned you in {club_id}!"
        
#         notification_data = {
#             "message_id": "test-message-id",
#             "club_id": club_id,
#             "club_name": "Test Club",
#             "sender_id": current_user["user_id"],
#             "sender_name": sender_name,
#             "message_preview": "This is a test mention message...",
#             "mentioned_user_id": target_user_id,
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=[target_user_id],
#             title=title,
#             body=body,
#             notification_type="club_message",
#             data=notification_data,
#             click_action=f"club/{club_id}/messages/test-message-id",
#             priority="normal"
#         )
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             f"Test mention notification sent",
#             data={
#                 "target_user_id": target_user_id,
#                 "club_id": club_id,
#                 "sender_name": sender_name,
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test mention notification: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             f"Test failed: {str(e)}"
#         )


# ========================================
# MUTE ALERT PREFERENCES
# ========================================

# @router.get("/mute-alerts", response_model=NotificationPreferencesResponse)
# async def get_mute_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's mute alert preference.
    
#     Returns whether the user has mute alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         # Get user's notification preferences
#         collections = get_collections()
#         users_collection = collections.get_users_collection()
        
#         user = await users_collection.find_one({"_id": ObjectId(user_id)})
#         if not user:
#             return create_response(
#                 status.HTTP_404_NOT_FOUND,
#                 "error",
#                 "User not found"
#             )
        
#         # Get mute alerts preference (default to True if not set)
#         mute_alerts = user.get("notification_preferences", {}).get("mute_alerts", True)
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "Mute alert preference retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "mute_alerts": mute_alerts,
#                 "updated_at": user.get("updated_at")
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error getting mute alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get mute alert preference"
#         )


@router.put("/mute-alerts", response_model=NotificationPreferencesResponse)
async def update_mute_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's mute alert preference.
    
    Args:
        enabled: Whether to enable or disable mute alerts
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "mute_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"Mute alerts {'enabled' if enabled else 'disabled'} successfully",
            data={
                "user_id": user_id,
                "mute_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating mute alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update mute alert preference"
        )


# @router.post("/test/mute")
# async def test_mute_notification(
#     target_user_id: str,
#     club_id: str = "test-club",
#     moderator_name: str = "Test Moderator",
#     action: str = "mute",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger mute/unmute notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing mute notification for user {target_user_id}")
        
#         # Prepare test notification
#         action_text = "muted" if action == "mute" else "unmuted"
#         title = f"🧪 Test: You've Been {action_text.title()}!"
#         body = f"TEST NOTIFICATION - You have been {action_text} in {club_id} by {moderator_name}!"
        
#         notification_data = {
#             "target_user_id": target_user_id,
#             "target_user_name": "Test User",
#             "club_id": club_id,
#             "club_name": "Test Club",
#             "moderator_id": current_user["user_id"],
#             "moderator_name": moderator_name,
#             "reason": "Test reason",
#             "duration_hours": 24 if action == "mute" else None,
#             "muted_until": "2024-12-31T23:59:59Z" if action == "mute" else None,
#             "action": action,
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=[target_user_id],
#             title=title,
#             body=body,
#             notification_type="club_message",
#             data=notification_data,
#             click_action=f"club/{club_id}",
#             priority="normal"
#         )
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             f"Test mute notification sent",
#             data={
#                 "target_user_id": target_user_id,
#                 "club_id": club_id,
#                 "moderator_name": moderator_name,
#                 "action": action,
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test mute notification: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             f"Test failed: {str(e)}"
#         )


# ========================================
# MESSAGE ALERT PREFERENCES
# ========================================

# @router.get("/message-alerts", response_model=NotificationPreferencesResponse)
# async def get_message_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's message alert preference.
    
#     Returns whether the user has message alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         # Get user's notification preferences
#         collections = get_collections()
#         users_collection = collections.get_users_collection()
        
#         user = await users_collection.find_one({"_id": ObjectId(user_id)})
#         if not user:
#             return create_response(
#                 status.HTTP_404_NOT_FOUND,
#                 "error",
#                 "User not found"
#             )
        
#         # Get message alerts preference (default to True if not set)
#         message_alerts = user.get("notification_preferences", {}).get("message_alerts", True)
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "Message alert preference retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "message_alerts": message_alerts,
#                 "updated_at": user.get("updated_at")
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error getting message alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get message alert preference"
#         )


@router.put("/message-alerts", response_model=NotificationPreferencesResponse)
async def update_message_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's message alert preference.
    
    Args:
        enabled: Whether to enable or disable message alerts
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "message_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"Message alerts {'enabled' if enabled else 'disabled'} successfully",
            data={
                "user_id": user_id,
                "message_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating message alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update message alert preference"
        )


# @router.post("/test/message")
# async def test_message_notification(
#     target_user_id: str,
#     club_id: str = "test-club",
#     sender_name: str = "Test User",
#     message_type: str = "message",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger message notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing message notification for user {target_user_id}")
        
#         # Prepare test notification
#         if message_type == "thread_reply":
#             title = f"🧪 Test: New Thread Reply!"
#             body = f"TEST NOTIFICATION - {sender_name} replied in {club_id}!"
#         else:
#             title = f"🧪 Test: New Message!"
#             body = f"TEST NOTIFICATION - {sender_name} sent a message in {club_id}!"
        
#         notification_data = {
#             "message_id": "test-message-id",
#             "club_id": club_id,
#             "club_name": "Test Club",
#             "sender_id": current_user["user_id"],
#             "sender_name": sender_name,
#             "message_preview": "This is a test message...",
#             "message_type": message_type,
#             "is_thread_reply": message_type == "thread_reply",
#             "reply_to_message_id": "parent-message-id" if message_type == "thread_reply" else None,
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=[target_user_id],
#             title=title,
#             body=body,
#             notification_type="club_message",
#             data=notification_data,
#             click_action=f"club/{club_id}/messages/test-message-id",
#             priority="normal"
#         )
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             f"Test message notification sent",
#             data={
#                 "target_user_id": target_user_id,
#                 "club_id": club_id,
#                 "sender_name": sender_name,
#                 "message_type": message_type,
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test message notification: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             f"Test failed: {str(e)}"
#         )


# ========================================
# FRIEND REQUEST ALERT PREFERENCES
# ========================================

# @router.get("/friend-request-alerts", response_model=NotificationPreferencesResponse)
# async def get_friend_request_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's friend request alert preference.
    
#     Returns whether the user has friend request alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         # Get user's notification preferences
#         collections = get_collections()
#         users_collection = collections.get_users_collection()
        
#         user = await users_collection.find_one({"_id": ObjectId(user_id)})
#         if not user:
#             return create_response(
#                 status.HTTP_404_NOT_FOUND,
#                 "error",
#                 "User not found"
#             )
        
#         # Get friend request alerts preference (default to True if not set)
#         friend_request_alerts = user.get("notification_preferences", {}).get("friend_request_alerts", True)
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "Friend request alert preference retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "friend_request_alerts": friend_request_alerts,
#                 "updated_at": user.get("updated_at")
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error getting friend request alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get friend request alert preference"
#         )


@router.put("/friend-request-alerts", response_model=NotificationPreferencesResponse)
async def update_friend_request_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's friend request alert preference.
    
    Args:
        enabled: Whether to enable or disable friend request alerts
    """
    try:
        user_id = current_user["user_id"]
        c = get_collections()
        preferences_collection = c.get_notification_preferences_collection()
        
        await preferences_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "friend_request_alerts": enabled,
                    "updated_at": now_iso()
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"Friend request alerts {'enabled' if enabled else 'disabled'} successfully",
            data={
                "user_id": user_id,
                "friend_request_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now_iso()
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating friend request alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update friend request alert preference"
        )


# @router.post("/test/friend-request")
# async def test_friend_request_notification(
#     target_user_id: str,
#     club_id: str = "test-club",
#     sender_name: str = "Test User",
#     action: str = "sent",
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger friend request notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing friend request notification for user {target_user_id}")
        
#         # Prepare test notification
#         if action == "sent":
#             title = f"🧪 Test: New Friend Request!"
#             body = f"TEST NOTIFICATION - {sender_name} sent you a friend request in {club_id}!"
#         elif action == "accepted":
#             title = f"🧪 Test: Friend Request Accepted!"
#             body = f"TEST NOTIFICATION - {sender_name} accepted your friend request!"
#         elif action == "rejected":
#             title = f"🧪 Test: Friend Request Declined"
#             body = f"TEST NOTIFICATION - {sender_name} declined your friend request!"
#         else:
#             title = f"🧪 Test: Friend Request Update!"
#             body = f"TEST NOTIFICATION - Friend request {action}!"
        
#         notification_data = {
#             "request_id": "test-request-id",
#             "sender_id": current_user["user_id"],
#             "sender_name": sender_name,
#             "receiver_id": target_user_id,
#             "receiver_name": "Test User",
#             "club_id": club_id,
#             "club_name": "Test Club",
#             "message": "This is a test friend request message...",
#             "action": f"friend_request_{action}",
#             "response_action": action if action in ["accepted", "rejected"] else None,
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=[target_user_id],
#             title=title,
#             body=body,
#             notification_type="club_message",
#             data=notification_data,
#             click_action=f"club/{club_id}/dm-requests",
#             priority="normal"
#         )
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             f"Test friend request notification sent",
#             data={
#                 "target_user_id": target_user_id,
#                 "club_id": club_id,
#                 "sender_name": sender_name,
#                 "action": action,
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test friend request notification: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             f"Test failed: {str(e)}"
#         )


# ========================================
# SUBSCRIPTION ALERT PREFERENCES
# ========================================

# @router.get("/subscription-alerts", response_model=NotificationPreferencesResponse)
# async def get_subscription_alert_preference(current_user: dict = Depends(get_current_user_or_admin)):
#     """
#     Get the user's subscription alert preference.
    
#     Returns whether the user has subscription alerts enabled or disabled.
#     """
#     try:
#         user_id = current_user["user_id"]
        
#         # Get user's notification preferences
#         collections = get_collections()
#         users_collection = collections.get_users_collection()
        
#         user = await users_collection.find_one({"_id": ObjectId(user_id)})
#         if not user:
#             return create_response(
#                 status.HTTP_404_NOT_FOUND,
#                 "error",
#                 "User not found"
#             )
        
#         # Get subscription alerts preference (default to True if not set)
#         subscription_alerts = user.get("notification_preferences", {}).get("subscription_alerts", True)
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             "Subscription alert preference retrieved successfully",
#             data={
#                 "user_id": user_id,
#                 "subscription_alerts": subscription_alerts,
#                 "updated_at": user.get("updated_at")
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error getting subscription alert preference: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             "Failed to get subscription alert preference"
#         )


@router.put("/subscription-alerts", response_model=NotificationPreferencesResponse)
async def update_subscription_alert_preference(
    enabled: bool,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update the user's subscription alert preference.
    
    Args:
        enabled: Whether to enable or disable subscription alerts
    """
    try:
        user_id = current_user["user_id"]
        
        # Update user's notification preferences in both collections
        collections = get_collections()
        users_collection = collections.get_users_collection()
        preferences_col = collections.get_notification_preferences_collection()
        
        now = datetime.now(timezone.utc)
        
        # Update in users collection
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "notification_preferences.subscription_alerts": enabled,
                    "updated_at": now
                }
            }
        )
        
        if result.matched_count == 0:
            return create_response(
                status.HTTP_404_NOT_FOUND,
                "error",
                "User not found"
            )
        
        # Update in notification_preferences collection (upsert to ensure it exists)
        await preferences_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "subscription_alerts": enabled,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "created_at": now
                }
            },
            upsert=True
        )
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"Subscription alerts {'enabled' if enabled else 'disabled'} successfully",
            data={
                "user_id": user_id,
                "subscription_alerts": enabled,
                "is_notify": enabled,
                "updated_at": now.isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating subscription alert preference: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update subscription alert preference"
        )


# @router.post("/test/subscription")
# async def test_subscription_notification(
#     target_user_id: str,
#     club_id: str = "test-club",
#     club_name: str = "Test Club",
#     action: str = "success",
#     pricing_plan: str = "monthly",
#     amount: float = 29.99,
#     current_user: dict = Depends(get_current_user_or_admin)
# ):
#     """
#     Test endpoint to trigger subscription notifications.
#     Development/testing only - remove in production.
#     """
#     try:
#         from services.notifications.notification_service import (
#             send_notification_to_users
#         )
        
#         logger.info(f"🧪 Testing subscription notification for user {target_user_id}")
        
#         # Prepare test notification
#         if action == "success":
#             title = f"🧪 Test: Subscription Successful!"
#             body = f"TEST NOTIFICATION - Welcome to {club_name}! Your {pricing_plan} subscription is now active"
#         elif action == "upgrade":
#             title = f"🧪 Test: Subscription Upgraded!"
#             body = f"TEST NOTIFICATION - Your trial has been upgraded to {pricing_plan} subscription in {club_name}!"
#         elif action == "failure":
#             title = f"🧪 Test: Subscription Failed!"
#             body = f"TEST NOTIFICATION - Payment failed for {club_name}. Please try again or contact support."
#         else:
#             title = f"🧪 Test: Subscription Update!"
#             body = f"TEST NOTIFICATION - Subscription {action}!"
        
#         notification_data = {
#             "user_id": target_user_id,
#             "user_name": "Test User",
#             "club_id": club_id,
#             "club_name": club_name,
#             "club_name_based_id": club_id,
#             "subscription_type": "paid" if action in ["success", "upgrade"] else "failed",
#             "pricing_plan": pricing_plan,
#             "amount_paid": amount if action != "failure" else 0,
#             "amount_attempted": amount,
#             "payment_id": "test-payment-id",
#             "subscription_id": "test-subscription-id",
#             "start_date": "2024-01-01T00:00:00Z",
#             "end_date": "2024-02-01T00:00:00Z",
#             "error_message": "Test error message" if action == "failure" else None,
#             "action": f"subscription_{action}",
#             "is_test": True
#         }
        
#         # Send test notification
#         result = await send_notification_to_users(
#             user_ids=[target_user_id],
#             title=title,
#             body=body,
#             notification_type="club_message",
#             data=notification_data,
#             click_action=f"club/{club_id}",
#             priority="high"
#         )
        
#         return create_response(
#             status.HTTP_200_OK,
#             "success",
#             f"Test subscription notification sent",
#             data={
#                 "target_user_id": target_user_id,
#                 "club_id": club_id,
#                 "club_name": club_name,
#                 "action": action,
#                 "pricing_plan": pricing_plan,
#                 "amount": amount,
#                 "notification_result": result,
#                 "test_data": notification_data
#             }
#         )
        
#     except Exception as e:
#         logger.error(f"Error in test subscription notification: {e}")
#         return create_response(
#             status.HTTP_500_INTERNAL_SERVER_ERROR,
#             "error",
#             f"Test failed: {str(e)}"
#         )


# ========================================
# NOTIFICATION CENTER / LIST
# ========================================

@router.get("/list", response_model=dict)
async def get_notification_list(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Number of notifications per page"),
    filter_type: Optional[str] = Query(None, description="Filter by notification type"),
    filter_read: Optional[bool] = Query(None, description="Filter by read status (true=read, false=unread)"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order (asc or desc)"),
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Get paginated list of notifications for the current user.
    
    This endpoint provides a comprehensive notification center with:
    - Paginated results with configurable page size
    - Filtering by notification type and read status
    - Sorting by creation date
    - Rich notification data including click actions
    
    **Query Parameters:**
    - `page`: Page number (default: 1)
    - `page_size`: Notifications per page (default: 20, max: 100)
    - `filter_type`: Filter by notification type (optional)
    - `filter_read`: Filter by read status (optional)
    - `sort_order`: Sort order - "asc" or "desc" (default: "desc")
    
    **Response includes:**
    - Paginated notifications with full details
    - Unread count for badge display
    - Pagination metadata
    - Click actions for navigation
    """
    try:
        user_id = current_user["user_id"]
        
        # Get notifications using existing service function
        from services.notifications.notification_service import get_user_notifications
        
        result = await get_user_notifications(
            user_id=user_id,
            page=page,
            page_size=page_size,
            filter_type=filter_type,
            filter_read=filter_read,
            sort_order=sort_order
        )
        
        if result.get("success", False):
            # Return full result with pagination metadata
            return create_response(
                status.HTTP_200_OK,
                "success",
                "Notifications retrieved successfully",
                data={
                    "notifications": result.get("notifications", []),
                    "total_count": result.get("total_count", 0),
                    "unread_count": result.get("unread_count", 0),
                    "page": result.get("page", page),
                    "page_size": result.get("page_size", page_size),
                    "total_pages": result.get("total_pages", 0)
                }
            )
        else:
            return create_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error",
                result.get("error", "Failed to retrieve notifications")
            )
        
    except Exception as e:
        logger.error(f"Error getting notification list: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to retrieve notifications"
        )


@router.get("/unread-count", response_model=dict)
async def get_unread_notification_count(
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Get the count of unread notifications for the current user.
    
    This endpoint is useful for:
    - Displaying notification badges
    - Showing unread count in UI
    - Quick status checks
    
    **Response includes:**
    - Total unread count
    - User ID for verification
    """
    try:
        user_id = current_user["user_id"]
        
        # Get unread count using existing service function
        from services.notifications.notification_service import get_unread_count
        
        unread_count = await get_unread_count(user_id)
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            "Unread count retrieved successfully",
            data={
                "user_id": user_id,
                "unread_count": unread_count,
                "has_unread": unread_count > 0
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to get unread count"
        )


@router.put("/mark-read", response_model=dict)
async def mark_notifications_as_read(
    notification_ids: List[str],
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Mark specific notifications as read.
    
    **Request Body:**
    - `notification_ids`: List of notification IDs to mark as read
    
    **Response includes:**
    - Number of notifications marked as read
    - Success status
    """
    try:
        user_id = current_user["user_id"]
        
        if not notification_ids:
            return create_response(
                status.HTTP_400_BAD_REQUEST,
                "error",
                "No notification IDs provided"
            )
        
        # Mark notifications as read using existing service function
        from services.notifications.notification_service import mark_notifications_as_read
        
        result = await mark_notifications_as_read(user_id, notification_ids)
        
        if result.get("success", False):
            return create_response(
                status.HTTP_200_OK,
                "success",
                f"Marked {result.get('marked_count', 0)} notifications as read",
                data={
                    "user_id": user_id,
                    "marked_count": result.get("marked_count", 0),
                    "notification_ids": notification_ids
                }
            )
        else:
            return create_response(
                status.HTTP_400_BAD_REQUEST,
                "error",
                result.get("error", "Failed to mark notifications as read")
            )
        
    except Exception as e:
        logger.error(f"Error marking notifications as read: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to mark notifications as read"
        )


@router.put("/mark-all-read", response_model=dict)
async def mark_all_notifications_as_read(
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Mark all notifications as read for the current user.
    
    **Response includes:**
    - Number of notifications marked as read
    - Success status
    """
    try:
        user_id = current_user["user_id"]
        
        # Mark all notifications as read using existing service function
        from services.notifications.notification_service import mark_all_notifications_as_read
        
        result = await mark_all_notifications_as_read(user_id)
        
        if result.get("success", False):
            return create_response(
                status.HTTP_200_OK,
                "success",
                f"Marked {result.get('marked_count', 0)} notifications as read",
                data={
                    "user_id": user_id,
                    "marked_count": result.get("marked_count", 0)
                }
            )
        else:
            return create_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error",
                result.get("error", "Failed to mark all notifications as read")
            )
        
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to mark all notifications as read"
        )


@router.delete("/delete", response_model=dict)
async def delete_notifications(
    notification_ids: List[str],
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Delete specific notifications.
    
    **Request Body:**
    - `notification_ids`: List of notification IDs to delete
    
    **Response includes:**
    - Number of notifications deleted
    - Success status
    """
    try:
        user_id = current_user["user_id"]
        
        if not notification_ids:
            return create_response(
                status.HTTP_400_BAD_REQUEST,
                "error",
                "No notification IDs provided"
            )
        
        # Delete notifications using existing service function
        from services.notifications.notification_service import delete_notifications
        
        result = await delete_notifications(user_id, notification_ids)
        
        if result.get("success", False):
            return create_response(
                status.HTTP_200_OK,
                "success",
                f"Deleted {result.get('deleted_count', 0)} notifications",
                data={
                    "user_id": user_id,
                    "deleted_count": result.get("deleted_count", 0),
                    "notification_ids": notification_ids
                }
            )
        else:
            return create_response(
                status.HTTP_400_BAD_REQUEST,
                "error",
                result.get("error", "Failed to delete notifications")
            )
        
    except Exception as e:
        logger.error(f"Error deleting notifications: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to delete notifications"
        )


@router.delete("/clear-all", response_model=dict)
async def clear_all_notifications(
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Clear all notifications for the current user.
    
    **Response includes:**
    - Number of notifications deleted
    - Success status
    """
    try:
        user_id = current_user["user_id"]
        
        # Clear all notifications using existing service function
        from services.notifications.notification_service import clear_all_notifications
        
        result = await clear_all_notifications(user_id)
        
        if result.get("success", False):
            return create_response(
                status.HTTP_200_OK,
                "success",
                f"Cleared {result.get('deleted_count', 0)} notifications",
                data={
                    "user_id": user_id,
                    "deleted_count": result.get("deleted_count", 0)
                }
            )
        else:
            return create_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error",
                result.get("error", "Failed to clear all notifications")
            )
        
    except Exception as e:
        logger.error(f"Error clearing all notifications: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to clear all notifications"
        )


@router.post("/chat-status/{club_id}", response_model=dict)
async def update_chat_open_status(
    club_id: str,
    is_chat_open: Optional[bool] = Query(None, description="True to open chat, False to close chat"),
    is_dm_chat_open: Optional[bool] = Query(None, description="True to open DM chat, False to close DM chat"),
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Update is_chat_open and/or is_dm_chat_open status for a specific club.
    
    **Behavior:**
    - When user opens a club's chat (`is_chat_open=True`), saves club_id with is_chat_open=True
    - When user closes a club's chat (`is_chat_open=False`), sets is_chat_open=False
    - When user opens DM chat (`is_dm_chat_open=True`), sets is_dm_chat_open=True
    - When user closes DM chat (`is_dm_chat_open=False`), sets is_dm_chat_open=False
    - Automatically sets to False when new notification arrives for that club
    
    **Parameters:**
    - **club_id**: Club name_based_id
    - **is_chat_open**: (Optional) True to open group chat, False to close group chat
    - **is_dm_chat_open**: (Optional) True to open DM chat, False to close DM chat
    
    **Response includes:**
    - is_chat_open status
    - is_dm_chat_open status
    - club_id
    - timestamp
    """
    try:
        user_id = current_user["user_id"]
        
        if is_chat_open is None and is_dm_chat_open is None:
            return create_response(
                status.HTTP_400_BAD_REQUEST,
                "error",
                "At least one of is_chat_open or is_dm_chat_open must be provided"
            )
        
        collections = get_collections()
        users_col = collections.get_users_collection()
        
        from bson import ObjectId
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        # Build update fields
        update_fields = {"chat_open_clubs.$.updated_at": now}
        if is_chat_open is not None:
            update_fields["chat_open_clubs.$.is_chat_open"] = is_chat_open
        if is_dm_chat_open is not None:
            update_fields["chat_open_clubs.$.is_dm_chat_open"] = is_dm_chat_open
        
        # Update existing entry
        result = await users_col.update_one(
            {
                "_id": ObjectId(user_id),
                "chat_open_clubs.club_id": club_id
            },
            {"$set": update_fields}
        )
        
        # If no existing entry, add new one with defaults
        if result.matched_count == 0:
            new_entry = {
                "club_id": club_id,
                "is_chat_open": is_chat_open if is_chat_open is not None else True,
                "is_dm_chat_open": is_dm_chat_open if is_dm_chat_open is not None else True,
                "created_at": now,
                "updated_at": now
            }
            await users_col.update_one(
                {"_id": ObjectId(user_id)},
                {"$push": {"chat_open_clubs": new_entry}}
            )
        
        # Get current values for response
        user = await users_col.find_one(
            {"_id": ObjectId(user_id)},
            {"chat_open_clubs": 1}
        )
        
        current_is_chat_open = True
        current_is_dm_chat_open = True
        if user and "chat_open_clubs" in user:
            for club_status in user["chat_open_clubs"]:
                if club_status.get("club_id") == club_id:
                    current_is_chat_open = club_status.get("is_chat_open", True)
                    current_is_dm_chat_open = club_status.get("is_dm_chat_open", True)
                    break
        
        status_msg = []
        if is_chat_open is not None:
            status_msg.append(f"Group chat {'opened' if is_chat_open else 'closed'}")
        if is_dm_chat_open is not None:
            status_msg.append(f"DM chat {'opened' if is_dm_chat_open else 'closed'}")
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            f"{' and '.join(status_msg)} for club {club_id}",
            data={
                "user_id": user_id,
                "club_id": club_id,
                "is_chat_open": current_is_chat_open,
                "is_dm_chat_open": current_is_dm_chat_open,
                "updated_at": now.isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Error updating chat open status: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to update chat open status"
        )


@router.get("/chat-status/{club_id}", response_model=dict)
async def get_chat_open_status(
    club_id: str,
    current_user: dict = Depends(get_current_user_or_admin)
):
    """
    Get is_chat_open and is_dm_chat_open status for a specific club.
    
    Returns the current chat open status for the specified club.
    Defaults to True for both if not set.
    
    **Parameters:**
    - **club_id**: Club name_based_id
    
    **Response includes:**
    - is_chat_open status (defaults to True)
    - is_dm_chat_open status (defaults to True)
    - club_id
    """
    try:
        user_id = current_user["user_id"]
        
        collections = get_collections()
        users_col = collections.get_users_collection()
        
        from bson import ObjectId
        
        # Get user's chat_open_clubs array
        user = await users_col.find_one(
            {"_id": ObjectId(user_id)},
            {"chat_open_clubs": 1}
        )
        
        is_chat_open = True  # Default to True
        is_dm_chat_open = True  # Default to True
        if user and "chat_open_clubs" in user:
            # Find this club's entry
            for club_entry in user["chat_open_clubs"]:
                if club_entry.get("club_id") == club_id:
                    is_chat_open = club_entry.get("is_chat_open", True)
                    is_dm_chat_open = club_entry.get("is_dm_chat_open", True)
                    break
        
        return create_response(
            status.HTTP_200_OK,
            "success",
            "Chat status retrieved successfully",
            data={
                "user_id": user_id,
                "club_id": club_id,
                "is_chat_open": is_chat_open,
                "is_dm_chat_open": is_dm_chat_open
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting chat open status: {e}")
        return create_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error",
            "Failed to get chat open status"
        )
