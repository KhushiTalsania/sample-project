"""
Notification Service Models

Pydantic models for notification-related API requests and responses.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum

# ========================================
# NOTIFICATION TYPES ENUM
# ========================================

class NotificationType(str, Enum):
    """Notification types for categorization"""
    CLUB_INVITE = "club_invite"
    CLUB_JOIN = "club_join"
    CLUB_LEAVE = "club_leave"
    CLUB_PICK = "club_pick"
    CLUB_PICK_OUTCOME = "club_pick_outcome"
    CLUB_NEW_PICK = "club_new_pick"  # New pick alerts
    CLUB_MEMBER_JOIN = "club_member_join"  # Member join alerts
    CLUB_STATUS_CHANGE = "club_status_change"  # Club status change alerts
    CLUB_MESSAGE = "club_message"
    CLUB_ANNOUNCEMENT = "club_announcement"
    DM_BLOCK = "dm_block"  # DM block/unblock notifications
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_RENEWAL = "subscription_renewal"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_ALERTS = "subscription_alerts"  # Subscription success/failure alerts
    TRIAL_EXPIRING = "trial_expiring"
    TRIAL_EXPIRED = "trial_expired"
    MEMBERSHIP_APPROVED = "membership_approved"
    MEMBERSHIP_REJECTED = "membership_rejected"
    REFUND_PROCESSED = "refund_processed"
    CAPTAIN_REQUEST_APPROVED = "captain_request_approved"
    CAPTAIN_REQUEST_REJECTED = "captain_request_rejected"
    MODERATOR_INVITE = "moderator_invite"
    MODERATOR_ACCEPTED = "moderator_accepted"
    MODERATOR_REJECTED = "moderator_rejected"
    SYSTEM_ANNOUNCEMENT = "system_announcement"
    ACCOUNT_SUSPENDED = "account_suspended"
    ACCOUNT_REACTIVATED = "account_reactivated"
    GENERAL = "general"

# ========================================
# DEVICE TOKEN MANAGEMENT MODELS
# ========================================

class RegisterDeviceTokenRequest(BaseModel):
    """Request model for registering a device token"""
    device_token: str = Field(..., min_length=1, description="FCM device token")
    device_type: Optional[str] = Field(..., description="Type of device")
    device_name: Optional[str] = Field(None, description="Device name/model")
    device_id: Optional[str] = Field(None, description="Unique device identifier")
    
    @validator('device_token')
    def validate_device_token(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Device token cannot be empty')
        return v.strip()

class RegisterDeviceTokenResponse(BaseModel):
    """Response model for device token registration"""
    success: bool
    message: str
    token_id: Optional[str] = None
    user_id: Optional[str] = None
    device_type: Optional[str] = None
    registered_at: Optional[str] = None
    error: Optional[str] = None

class RemoveDeviceTokenRequest(BaseModel):
    """Request model for removing a device token"""
    device_token: str = Field(..., min_length=1, description="FCM device token to remove")
    
    @validator('device_token')
    def validate_device_token(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Device token cannot be empty')
        return v.strip()

class RemoveDeviceTokenResponse(BaseModel):
    """Response model for device token removal"""
    success: bool
    message: str
    token_id: Optional[str] = None
    removed_at: Optional[str] = None
    error: Optional[str] = None

class UserDeviceTokensResponse(BaseModel):
    """Response model for listing user's device tokens"""
    success: bool
    message: str
    user_id: str
    total_devices: int
    devices: List[Dict[str, Any]]
    error: Optional[str] = None

# ========================================
# NOTIFICATION SENDING MODELS
# ========================================

class SendNotificationRequest(BaseModel):
    """Request model for sending a notification"""
    user_ids: List[str] = Field(..., min_items=1, description="List of user IDs to send notification to")
    title: str = Field(..., min_length=1, max_length=100, description="Notification title")
    body: str = Field(..., min_length=1, max_length=500, description="Notification body/message")
    notification_type: NotificationType = Field(NotificationType.GENERAL, description="Type of notification")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional data payload")
    priority: Literal["high", "normal"] = Field("normal", description="Notification priority")
    sound: Optional[str] = Field("default", description="Notification sound")
    badge: Optional[int] = Field(None, description="Badge count for iOS")
    click_action: Optional[str] = Field(None, description="Action on notification click")
    image_url: Optional[str] = Field(None, description="Image URL for rich notification")
    
    # Scheduling options
    schedule_at: Optional[str] = Field(None, description="ISO 8601 datetime to schedule notification")
    
    @validator('title')
    def validate_title(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Title cannot be empty')
        return v.strip()
    
    @validator('body')
    def validate_body(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Body cannot be empty')
        return v.strip()

class SendNotificationResponse(BaseModel):
    """Response model for sending notifications"""
    success: bool
    message: str
    notification_id: Optional[str] = None
    sent_to_count: int = 0
    failed_count: int = 0
    scheduled: bool = False
    schedule_at: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# ========================================
# NOTIFICATION RETRIEVAL MODELS
# ========================================

class NotificationItem(BaseModel):
    """Individual notification item"""
    notification_id: str
    user_id: str
    title: str
    body: str
    notification_type: str
    is_read: bool
    data: Optional[Dict[str, Any]] = None
    image_url: Optional[str] = None
    click_action: Optional[str] = None
    created_at: str
    read_at: Optional[str] = None

class GetNotificationsRequest(BaseModel):
    """Request model for getting notifications with pagination"""
    page: int = Field(1, ge=1, description="Page number (starts from 1)")
    page_size: int = Field(20, ge=1, le=100, description="Number of items per page (max 100)")
    filter_type: Optional[NotificationType] = Field(None, description="Filter by notification type")
    filter_read: Optional[bool] = Field(None, description="Filter by read status (true=read, false=unread, null=all)")
    sort_order: Literal["desc", "asc"] = Field("desc", description="Sort order by date")

class GetNotificationsResponse(BaseModel):
    """Response model for getting notifications"""
    success: bool
    message: str
    user_id: str
    total_count: int
    unread_count: int
    page: int
    page_size: int
    total_pages: int
    notifications: List[NotificationItem]
    error: Optional[str] = None

class NotificationCountResponse(BaseModel):
    """Response model for unread notification count"""
    success: bool
    message: str
    user_id: str
    unread_count: int
    total_count: int
    error: Optional[str] = None

# ========================================
# NOTIFICATION ACTION MODELS
# ========================================

class MarkNotificationReadRequest(BaseModel):
    """Request model for marking notification as read"""
    notification_ids: List[str] = Field(..., min_items=1, description="List of notification IDs to mark as read")
    
    @validator('notification_ids')
    def validate_notification_ids(cls, v):
        if not v or len(v) == 0:
            raise ValueError('At least one notification ID is required')
        return v

class MarkNotificationReadResponse(BaseModel):
    """Response model for marking notifications as read"""
    success: bool
    message: str
    marked_count: int
    failed_count: int
    read_at: str
    error: Optional[str] = None

class MarkAllNotificationsReadResponse(BaseModel):
    """Response model for marking all notifications as read"""
    success: bool
    message: str
    user_id: str
    marked_count: int
    read_at: str
    error: Optional[str] = None

class DeleteNotificationRequest(BaseModel):
    """Request model for deleting notifications"""
    notification_ids: List[str] = Field(..., min_items=1, description="List of notification IDs to delete")
    
    @validator('notification_ids')
    def validate_notification_ids(cls, v):
        if not v or len(v) == 0:
            raise ValueError('At least one notification ID is required')
        return v

class DeleteNotificationResponse(BaseModel):
    """Response model for deleting notifications"""
    success: bool
    message: str
    deleted_count: int
    failed_count: int
    error: Optional[str] = None

class ClearAllNotificationsResponse(BaseModel):
    """Response model for clearing all notifications"""
    success: bool
    message: str
    user_id: str
    deleted_count: int
    error: Optional[str] = None

# ========================================
# NOTIFICATION PREFERENCES MODELS
# ========================================

class NotificationPreferencesRequest(BaseModel):
    """Request model for updating notification preferences"""
    enable_push_notifications: Optional[bool] = Field(None, description="Enable/disable push notifications")
    enable_email_notifications: Optional[bool] = Field(None, description="Enable/disable email notifications")
    enable_sms_notifications: Optional[bool] = Field(None, description="Enable/disable SMS notifications")
    
    # Specific notification types preferences
    club_notifications: Optional[bool] = Field(None, description="Enable/disable club-related notifications")
    payment_notifications: Optional[bool] = Field(None, description="Enable/disable payment-related notifications")
    membership_notifications: Optional[bool] = Field(None, description="Enable/disable membership-related notifications")
    system_notifications: Optional[bool] = Field(None, description="Enable/disable system notifications")
    pick_outcome_alerts: Optional[bool] = Field(None, description="Enable/disable pick outcome alerts (wins/losses)")
    new_pick_alerts: Optional[bool] = Field(None, description="Enable/disable new pick alerts (when captains/moderators create new picks)")
    club_join_alerts: Optional[bool] = Field(None, description="Enable/disable club join alerts (when new members join the club)")
    club_status_alerts: Optional[bool] = Field(None, description="Enable/disable club status alerts (when club becomes active/inactive)")
    dm_block_alerts: Optional[bool] = Field(None, description="Enable/disable DM block/unblock alerts (when users block/unblock each other)")
    mention_alerts: Optional[bool] = Field(None, description="Enable/disable mention alerts (when users are tagged/mentioned in group chat)")
    mute_alerts: Optional[bool] = Field(None, description="Enable/disable mute/unmute alerts (when users are muted/unmuted in group chat)")
    message_alerts: Optional[bool] = Field(None, description="Enable/disable message alerts (when new messages are sent in group chat)")
    friend_request_alerts: Optional[bool] = Field(None, description="Enable/disable friend request alerts (when users send/respond to friend requests)")
    subscription_alerts: Optional[bool] = Field(None, description="Enable/disable subscription alerts (when subscription success/failure occurs)")
    
    # Quiet hours
    quiet_hours_enabled: Optional[bool] = Field(None, description="Enable quiet hours")
    quiet_hours_start: Optional[str] = Field(None, description="Quiet hours start time (HH:MM format)")
    quiet_hours_end: Optional[str] = Field(None, description="Quiet hours end time (HH:MM format)")

class NotificationPreferencesResponse(BaseModel):
    """Response model for notification preferences"""
    success: bool
    message: str
    user_id: str
    preferences: Dict[str, Any]
    updated_at: Optional[str] = None
    error: Optional[str] = None

# ========================================
# BROADCAST NOTIFICATION MODELS (ADMIN)
# ========================================

class BroadcastNotificationRequest(BaseModel):
    """Request model for broadcasting notifications to all users (admin only)"""
    title: str = Field(..., min_length=1, max_length=100, description="Notification title")
    body: str = Field(..., min_length=1, max_length=500, description="Notification body/message")
    notification_type: NotificationType = Field(NotificationType.SYSTEM_ANNOUNCEMENT, description="Type of notification")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional data payload")
    image_url: Optional[str] = Field(None, description="Image URL for rich notification")
    target_role: Optional[Literal["all", "Member", "Captain", "Moderator"]] = Field("all", description="Target user role")
    schedule_at: Optional[str] = Field(None, description="ISO 8601 datetime to schedule notification")
    
    @validator('title')
    def validate_title(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Title cannot be empty')
        return v.strip()
    
    @validator('body')
    def validate_body(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Body cannot be empty')
        return v.strip()

class BroadcastNotificationResponse(BaseModel):
    """Response model for broadcast notifications"""
    success: bool
    message: str
    notification_id: Optional[str] = None
    target_user_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    scheduled: bool = False
    schedule_at: Optional[str] = None
    error: Optional[str] = None

