"""
Authentication Service Database Interface

This module provides database access using centralized database components.
"""

from core.database.collections import get_collections

# Get centralized collections instance
collections = get_collections()

def get_user_collection():
    """Get users collection using centralized database manager"""
    return collections.get_users_collection()

def get_webhook_events_collection():
    """Get webhook events collection using centralized database manager"""
    return collections.get_webhook_events_collection()

def get_session_blacklist_collection():
    """Get session blacklist collection using centralized database manager"""
    return collections.get_session_blacklist_collection()

def get_active_sessions_collection():
    """Get active sessions collection using centralized database manager"""
    return collections.get_active_sessions_collection()

def get_session_activity_collection():
    """Get session activity collection using centralized database manager"""
    return collections.get_session_activity_collection()

def get_otp_collection():
    """Get OTP collection using centralized database manager"""
    return collections.get_otp_collection()

def get_password_reset_tokens_collection():
    """Get password reset tokens collection using centralized database manager"""
    return collections.get_password_reset_tokens_collection()

# For backward compatibility, expose the database instance
from core.database.connection import get_database_manager
db = get_database_manager().get_database("auth")

def get_payment_records_collection():
    """Get payment records collection"""
    return db["payment_records"]

def get_session_blacklist_collection():
    """Get session blacklist collection for invalidated tokens"""
    return db["session_blacklist"]

def get_active_sessions_collection():
    """Get active sessions collection for tracking user sessions"""
    return db["active_sessions"]

def get_session_activity_collection():
    """Get session activity collection for tracking user activity"""
    return db["session_activity"]
 