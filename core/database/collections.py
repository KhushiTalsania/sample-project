"""
Centralized Collections Interface

This module provides a unified interface to access all collections
in a single database for optimal performance.
"""

from motor.motor_asyncio import AsyncIOMotorCollection
from .connection import get_database_manager

class Collections:
    """
    Centralized collections manager that provides access to all
    collections in a single database for optimal performance.
    """
    
    def __init__(self):
        self.db_manager = get_database_manager()
    
    # ========================================
    # AUTH SERVICE COLLECTIONS
    # ========================================
    
    def get_users_collection(self) -> AsyncIOMotorCollection:
        """Get users collection from main database"""
        return self.db_manager.get_collection("users")
    
    def get_webhook_events_collection(self) -> AsyncIOMotorCollection:
        """Get webhook events collection from main database"""
        return self.db_manager.get_collection("webhook_events")
    
    def get_session_blacklist_collection(self) -> AsyncIOMotorCollection:
        """Get session blacklist collection from main database"""
        return self.db_manager.get_collection("session_blacklist")
    
    def get_active_sessions_collection(self) -> AsyncIOMotorCollection:
        """Get active sessions collection from main database"""
        return self.db_manager.get_collection("active_sessions")
    
    def get_session_activity_collection(self) -> AsyncIOMotorCollection:
        """Get session activity collection from main database"""
        return self.db_manager.get_collection("session_activity")
    
    def get_otp_collection(self) -> AsyncIOMotorCollection:
        """Get OTP collection from main database"""
        return self.db_manager.get_collection("otp_codes")
    
    def get_password_reset_tokens_collection(self) -> AsyncIOMotorCollection:
        """Get password reset tokens collection from main database"""
        return self.db_manager.get_collection("password_reset_tokens")
    
    def get_payments_collection(self) -> AsyncIOMotorCollection:
        """Get payments collection from main database"""
        return self.db_manager.get_collection("payments")
    
    def get_refunds_collection(self) -> AsyncIOMotorCollection:
        """Get refunds collection from main database"""
        return self.db_manager.get_collection("refunds")
    
    def get_support_feedback_collection(self) -> AsyncIOMotorCollection:
        """Get support feedback collection from main database"""
        return self.db_manager.get_collection("support_feedback")
    
    def get_payment_cards_collection(self) -> AsyncIOMotorCollection:
        """Get payment cards collection from main database"""
        return self.db_manager.get_collection("payment_cards")
    
    # ========================================
    # CLUB SERVICE COLLECTIONS
    # ========================================
    
    def get_clubs_collection(self) -> AsyncIOMotorCollection:
        """Get clubs collection from main database"""
        return self.db_manager.get_collection("clubs")
    
    def get_club_memberships_collection(self) -> AsyncIOMotorCollection:
        """Get club memberships collection from main database"""
        return self.db_manager.get_collection("club_memberships")
    
    def get_trial_club_access_collection(self) -> AsyncIOMotorCollection:
        """Get trial club access collection from main database"""
        return self.db_manager.get_collection("trial_club_access")
    
    def get_club_payments_collection(self) -> AsyncIOMotorCollection:
        """Get club payments collection from main database"""
        return self.db_manager.get_collection("club_payments")
    
    def get_membership_collection(self) -> AsyncIOMotorCollection:
        """Get club memberships collection from main database"""
        return self.db_manager.get_collection("club_memberships")
    
    def get_club_picks_collection(self) -> AsyncIOMotorCollection:
        """Get club picks collection from main database"""
        return self.db_manager.get_collection("club_picks")
    
    def get_club_refunds_collection(self) -> AsyncIOMotorCollection:
        """Get club refunds collection from main database"""
        return self.db_manager.get_collection("club_refunds")
    
    def get_club_activity_collection(self) -> AsyncIOMotorCollection:
        """Get club activity collection from main database"""
        return self.db_manager.get_collection("club_activity")
    
    def get_club_performance_collection(self) -> AsyncIOMotorCollection:
        """Get club performance collection from main database"""
        return self.db_manager.get_collection("club_performance")
    
    def get_hubs_collection(self) -> AsyncIOMotorCollection:
        """Get hubs collection from main database"""
        return self.db_manager.get_collection("hubs")
    
    # ========================================
    # CHAT SERVICE COLLECTIONS
    # ========================================
    
    def get_chat_messages_collection(self) -> AsyncIOMotorCollection:
        """Get chat messages collection from main database"""
        return self.db_manager.get_collection("chat_messages")
    
    def get_chat_rooms_collection(self) -> AsyncIOMotorCollection:
        """Get chat rooms collection from main database"""
        return self.db_manager.get_collection("chat_rooms")
    
    def get_message_reactions_collection(self) -> AsyncIOMotorCollection:
        """Get message reactions collection from main database"""
        return self.db_manager.get_collection("message_reactions")
    
    def get_user_mentions_collection(self) -> AsyncIOMotorCollection:
        """Get user mentions collection from main database"""
        return self.db_manager.get_collection("user_mentions")
    
    def get_chat_files_collection(self) -> AsyncIOMotorCollection:
        """Get chat files collection from main database"""
        return self.db_manager.get_collection("chat_files")
    
    def get_user_access_collection(self) -> AsyncIOMotorCollection:
        """Get user access collection from main database"""
        return self.db_manager.get_collection("user_access")
    
    def get_unread_tracking_collection(self) -> AsyncIOMotorCollection:
        """Get unread tracking collection from main database"""
        return self.db_manager.get_collection("unread_tracking")
    
    # ========================================
    # ADMIN SERVICE COLLECTIONS
    # ========================================
    
    def get_admins_collection(self) -> AsyncIOMotorCollection:
        """Get admins collection from main database"""
        return self.db_manager.get_collection("admins")
    
    def get_admin_sessions_collection(self) -> AsyncIOMotorCollection:
        """Get admin sessions collection from main database"""
        return self.db_manager.get_collection("admin_sessions")
    
    def get_admin_reset_tokens_collection(self) -> AsyncIOMotorCollection:
        """Get admin reset tokens collection from main database"""
        return self.db_manager.get_collection("admin_reset_tokens")
    
    def get_audit_logs_collection(self) -> AsyncIOMotorCollection:
        """Get audit logs collection from main database"""
        return self.db_manager.get_collection("audit_logs")
    
    def get_search_logs_collection(self) -> AsyncIOMotorCollection:
        """Get search logs collection from main database"""
        return self.db_manager.get_collection("search_logs")
    
    def get_export_logs_collection(self) -> AsyncIOMotorCollection:
        """Get export logs collection from main database"""
        return self.db_manager.get_collection("export_logs")
    
    def get_club_admin_logs_collection(self) -> AsyncIOMotorCollection:
        """Get club admin logs collection from main database"""
        return self.db_manager.get_collection("club_admin_logs")
    
    # ========================================
    # ADDITIONAL COLLECTIONS
    # ========================================
    
    def get_locker_room_logs_collection(self) -> AsyncIOMotorCollection:
        """Get locker room logs collection from main database"""
        return self.db_manager.get_collection("locker_room_logs")
    
    def get_moderator_requests_collection(self) -> AsyncIOMotorCollection:
        """Get moderator requests collection from main database"""
        return self.db_manager.get_collection("moderator_requests")
    
    def get_moderator_audit_logs_collection(self) -> AsyncIOMotorCollection:
        """Get moderator audit logs collection from main database"""
        return self.db_manager.get_collection("moderator_audit_logs")
    
    def get_subscription_plans_collection(self) -> AsyncIOMotorCollection:
        """Get subscription plans collection from main database"""
        return self.db_manager.get_collection("subscription_plans")
    
    def get_subscriptions_collection(self) -> AsyncIOMotorCollection:
        """Get subscriptions collection from main database"""
        return self.db_manager.get_collection("subscriptions")
    
    def get_subscription_analytics_collection(self) -> AsyncIOMotorCollection:
        """Get subscription analytics collection from main database"""
        return self.db_manager.get_collection("subscription_analytics")
    
    def get_subscription_admin_logs_collection(self) -> AsyncIOMotorCollection:
        """Get subscription admin logs collection from main database"""
        return self.db_manager.get_collection("subscription_admin_logs")
    
    def get_inclusions_collection(self) -> AsyncIOMotorCollection:
        """Get inclusions collection from main database"""
        return self.db_manager.get_collection("inclusions")
    
    def get_sports_collection(self) -> AsyncIOMotorCollection:
        """Get sports collection from main database"""
        return self.db_manager.get_collection("sports")
    
    def get_account_deletions_collection(self) -> AsyncIOMotorCollection:
        """Get account_deletions collection from main database"""
        return self.db_manager.get_collection("account_deletions")
    
    # ========================================
    # NOTIFICATION SERVICE COLLECTIONS
    # ========================================
    
    def get_notifications_collection(self) -> AsyncIOMotorCollection:
        """Get notifications collection from main database"""
        return self.db_manager.get_collection("notifications")
    
    def get_user_tokens_collection(self) -> AsyncIOMotorCollection:
        """Get user tokens collection from main database"""
        return self.db_manager.get_collection("user_tokens")
    
    def get_notification_preferences_collection(self) -> AsyncIOMotorCollection:
        """Get notification preferences collection from main database"""
        return self.db_manager.get_collection("notification_preferences")

# Global collections instance
_collections: Collections = None

def get_collections() -> Collections:
    """Get the global collections instance"""
    global _collections
    if _collections is None:
        _collections = Collections()
    return _collections
