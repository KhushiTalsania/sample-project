"""
Admin Service Database Interface

This module provides database access using centralized database components.
"""

from core.database.collections import get_collections

# Get centralized collections instance
collections = get_collections()

# Admin-specific collections
def get_admin_collection():
    """Get admins collection using centralized database manager"""
    return collections.get_admins_collection()

def get_admin_sessions_collection():
    """Get admin sessions collection using centralized database manager"""
    return collections.get_admin_sessions_collection()

def get_admin_reset_tokens_collection():
    """Get admin reset tokens collection using centralized database manager"""
    return collections.get_admin_reset_tokens_collection()

def get_audit_logs_collection():
    """Get audit logs collection using centralized database manager"""
    return collections.get_audit_logs_collection()

def get_search_logs_collection():
    """Get search logs collection using centralized database manager"""
    return collections.get_search_logs_collection()

def get_export_logs_collection():
    """Get export logs collection using centralized database manager"""
    return collections.get_export_logs_collection()

def get_club_admin_logs_collection():
    """Get club admin logs collection using centralized database manager"""
    return collections.get_club_admin_logs_collection()

# Cross-service collections access
def get_users_collection():
    """Get users collection from auth service"""
    return collections.get_users_collection()

def get_clubs_collection():
    """Get clubs collection from club service"""
    return collections.get_clubs_collection()

def get_club_memberships_collection():
    """Get club memberships collection from club service"""
    return collections.get_club_memberships_collection()

def get_club_payments_collection():
    """Get club payments collection from club service"""
    return collections.get_club_payments_collection()

def get_club_picks_collection():
    """Get club picks collection from club service"""
    return collections.get_club_picks_collection()

def get_club_refunds_collection():
    """Get club refunds collection from club service"""
    return collections.get_club_refunds_collection()

def get_club_activity_collection():
    """Get club activity collection from club service"""
    return collections.get_club_activity_collection()

def get_club_performance_collection():
    """Get club performance collection from club service"""
    return collections.get_club_performance_collection()

# For backward compatibility, create collection variables
admin_collection = get_admin_collection()
sessions_collection = get_admin_sessions_collection()
reset_tokens_collection = get_admin_reset_tokens_collection()
users_collection = get_users_collection()
audit_logs_collection = get_audit_logs_collection()
search_logs_collection = get_search_logs_collection()
export_logs_collection = get_export_logs_collection()
clubs_collection = get_clubs_collection()
club_memberships_collection = get_club_memberships_collection()
club_picks_collection = get_club_picks_collection()
club_payments_collection = get_club_payments_collection()
club_refunds_collection = get_club_refunds_collection()
club_activity_collection = get_club_activity_collection()
club_performance_collection = get_club_performance_collection()
club_admin_logs_collection = get_club_admin_logs_collection()

# For backward compatibility, expose database instances
from core.database.connection import get_database_manager
db_manager = get_database_manager()
client = db_manager.client
db = db_manager.get_database("admin")
auth_db = db_manager.get_database("auth")
club_db = db_manager.get_database("club")

# Locker room moderation logs collection
locker_room_logs_collection = club_db.get_collection("locker_room_logs")  # Moderation actions

# Moderator management collections (CRUD with Captain approval)
moderator_requests_collection = club_db.get_collection("moderator_requests")  # Captain requests for moderator actions
moderator_audit_logs_collection = club_db.get_collection("moderator_audit_logs")  # Admin action audit logs


# Subscription plan management collections
subscription_plans_collection = club_db.get_collection("subscription_plans")  # Subscription plans
subscriptions_collection = club_db.get_collection("subscriptions")  # User subscriptions
subscription_analytics_collection = club_db.get_collection("subscription_analytics")  # Analytics data
subscription_admin_logs_collection = club_db.get_collection("subscription_admin_logs")  # Admin audit logs for plans

# Inclusions and Sports collections
inclusions_collection = db.get_collection("inclusions")  # Club inclusions/benefits
sports_collection = db.get_collection("sports")  # Available sports


