"""
Centralized Database Connection Manager

This module provides a unified database connection manager that handles
connections to all databases used by the monolithic application.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
import os
from dotenv import load_dotenv
import asyncio
from pymongo import ASCENDING, DESCENDING, TEXT
import logging
from typing import Dict, Optional
from datetime import datetime, timezone

# Setup logging
logger = logging.getLogger(__name__)

load_dotenv()

class DatabaseManager:
    """
    Centralized database manager for all services.
    
    This class manages connections to a single database for optimal performance.
    All services now use the same database with different collections.
    """
    
    def __init__(self):
        # Database configuration
        self.mongo_url = os.getenv("MONGO_URL", "mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main")
        
        # Extract database name from MONGO_URL (primary method)
        if '/' in self.mongo_url and not self.mongo_url.endswith('/'):
            # Extract database name from URL path
            url_parts = self.mongo_url.split('/')
            if len(url_parts) > 3:  # mongodb://host:port/dbname
                self.main_db_name = url_parts[-1].split('?')[0]  # Remove query params
            else:
                self.main_db_name = os.getenv("DATABASE_NAME", "betting_main")  # Default fallback
        else:
            # Fallback to environment variable or default
            self.main_db_name = os.getenv("DATABASE_NAME", "betting_main")
        
        # Optimized MongoDB client settings for single database
        
        # Fallback to individual database names if DATABASE_NAME not set
        if not os.getenv("DATABASE_NAME"):
            # Use admin database as main if no DATABASE_NAME specified
            self.main_db_name = os.getenv("DATABASE_NAME", "betting_main")
        
        # Optimized MongoDB client settings for single database
        self.client = AsyncIOMotorClient(
            self.mongo_url,
            tls=True,
            tlsAllowInvalidCertificates=True,
            # Optimized timeouts for single database
            serverSelectionTimeoutMS=2000,  # Reduced from 5000
            connectTimeoutMS=2000,          # Reduced from 5000
            socketTimeoutMS=5000,           # Reduced from 10000
            # Increased pool size for single database
            maxPoolSize=100,                # Increased from 50
            minPoolSize=20,                 # Increased from 10
            maxIdleTimeMS=60000,           # Increased from 30000
            waitQueueTimeoutMS=1000,        # Reduced from 2500
            # Additional optimizations
            maxConnecting=10,
            heartbeatFrequencyMS=10000,
            retryWrites=True,
            retryReads=True,
            # Connection pooling optimizations
            directConnection=False,
            readPreference='primaryPreferred'
        )
        
        # Single database instance
        self._main_database = self.client[self.main_db_name]
        self._collections = {}
        self._initialize_collections()
        
        logger.info("✅ Single Database Manager initialized successfully")
        logger.info(f"🔌 Connected to single database: {self.main_db_name}")
    
    def get_database_name(self):
        """Get the current database name"""
        return self.main_db_name
    
    def _initialize_collections(self):
        """Initialize all collections in single database with ORIGINAL names"""
        self._collections = {
            # Auth collections (ORIGINAL names)
            "users": self._main_database["users"],
            "webhook_events": self._main_database["webhook_events"],
            "session_blacklist": self._main_database["session_blacklist"],
            "active_sessions": self._main_database["active_sessions"],
            "session_activity": self._main_database["session_activity"],
            "otp_codes": self._main_database["otps"],
            "password_reset_tokens": self._main_database["password_reset_tokens"],
            "payments": self._main_database["payments"],
            "refunds": self._main_database["refunds"],
            "support_feedback": self._main_database["support_feedback"],
            "club_payments": self._main_database["club_payments"],
            "clubs": self._main_database["clubs"],
            "account_deletions": self._main_database["account_deletions"],
            "group_access": self._main_database["group_access"],
            "trial_memberships": self._main_database["trial_memberships"],
            "club_memberships": self._main_database["club_memberships"],
            "refund_requests": self._main_database["refund_requests"],
            "social_login_logs": self._main_database["social_login_logs"],
            "payment_cards": self._main_database["payment_cards"],
            
            # Admin collections (ORIGINAL names)
            "admins": self._main_database["admins"],
            "admin_sessions": self._main_database["admin_sessions"],
            "admin_reset_tokens": self._main_database["reset_tokens"],
            "audit_logs": self._main_database["audit_logs"],
            "search_logs": self._main_database["search_logs"],
            "export_logs": self._main_database["export_logs"],
            "club_admin_logs": self._main_database["club_admin_logs"],
            "inclusions": self._main_database["inclusions"],
            "sports": self._main_database["sports"],
            
            # Club collections (MIXED - some original, some prefixed due to conflicts)
            "club_clubs": self._main_database["club_clubs"],  # PREFIXED due to conflict with auth.clubs
            "club_memberships": self._main_database["club_memberships"],  # PREFIXED due to conflict
            "trial_club_access": self._main_database["trial_club_access"],
            "club_payments": self._main_database["club_payments"],  # PREFIXED due to conflict with auth.payments
            "club_picks": self._main_database["club_picks"],
            "club_refunds": self._main_database["club_refund_requests"],  # PREFIXED due to conflict
            "club_activity": self._main_database["club_activity"],
            "club_performance": self._main_database["club_performance"],
            "hubs": self._main_database["hubs"],
            "trial_memberships": self._main_database["club_trial_memberships"],  # PREFIXED due to conflict
            "subscription_plans": self._main_database["subscription_plans"],
            "subscription_admin_logs": self._main_database["subscription_admin_logs"],
            
            # Chat collections (ORIGINAL names)
            "chat_messages": self._main_database["chat_messages"],
            "chat_rooms": self._main_database["chat_rooms"],
            "message_reactions": self._main_database["message_reactions"],
            "user_mentions": self._main_database["user_mentions"],
            "chat_files": self._main_database["chat_files"],
            "user_access": self._main_database["user_access"],
            "unread_tracking": self._main_database["unread_tracking"],
            "connected_users": self._main_database["connected_users"],
            "messages": self._main_database["messages"],  # ORIGINAL name
            
            # Additional collections
            "locker_room_logs": self._main_database["locker_room_logs"],
            "moderator_requests": self._main_database["moderator_requests"],
            "moderator_audit_logs": self._main_database["moderator_audit_logs"],
            "subscriptions": self._main_database["subscriptions"],
            "subscription_analytics": self._main_database["subscription_analytics"]
        }
        
        logger.info(f"📊 Initialized {len(self._collections)} collections in single database")
        logger.info("✅ Using ORIGINAL collection names for maximum API compatibility")
    
    def get_database(self, service: str = "main") -> AsyncIOMotorDatabase:
        """Get the main database instance (all services use same database now)"""
        return self._main_database
    
    def get_collection(self, collection_name: str) -> AsyncIOMotorCollection:
        """Get collection from the main database"""
        if collection_name not in self._collections:
            # Create collection if it doesn't exist
            self._collections[collection_name] = self._main_database[collection_name]
            logger.info(f"📝 Created new collection: {collection_name}")
        return self._collections[collection_name]
    
    def get_collection_by_name(self, collection_name: str) -> AsyncIOMotorCollection:
        """Get collection by name (alias for get_collection)"""
        return self.get_collection(collection_name)
    
    async def close_connections(self):
        """Close all database connections"""
        if self.client:
            self.client.close()
            logger.info("🔌 Database connections closed")
    
    async def health_check(self) -> Dict[str, bool]:
        """Check health of the database connection"""
        try:
            await self._main_database.command("ping")
            return {"main": True}
        except Exception as e:
            logger.error(f"❌ Database health check failed: {e}")
            return {"main": False}

# Global database manager instance
_db_manager: Optional[DatabaseManager] = None

def get_database_manager() -> DatabaseManager:
    """Get the global database manager instance"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager

async def initialize_database_manager() -> DatabaseManager:
    """Initialize and return the database manager"""
    return get_database_manager()

async def close_database_connections():
    """Close all database connections"""
    global _db_manager
    if _db_manager:
        await _db_manager.close_connections()
        _db_manager = None
