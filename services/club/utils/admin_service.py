"""
Admin Service

This service handles fetching admin information from the betting_main_db database.
It provides functionality to get all admin email addresses for notifications.
"""

import logging
from typing import List, Dict, Optional
import motor.motor_asyncio
import os
from bson import ObjectId

# Configure logging
logger = logging.getLogger(__name__)

class AdminService:
    """Service for managing admin data"""
    
    def __init__(self):
        # Admin database configuration
        self.admin_db_url = os.getenv("MONGO_URL", os.getenv("MONGO_URL", "mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main"))
        self.admin_db_name = "betting_main"
        self.admin_collection_name = "admins"
        
        # Initialize MongoDB connection
        self.client = None
        self.database = None
        self.admin_collection = None
    
    async def _get_connection(self):
        """Get MongoDB connection for admin database"""
        try:
            if not self.client:
                self.client = motor.motor_asyncio.AsyncIOMotorClient(self.admin_db_url)
                self.database = self.client[self.admin_db_name]
                self.admin_collection = self.database[self.admin_collection_name]
                logger.info(f"Connected to admin database: {self.admin_db_name}")
            
            return self.admin_collection
            
        except Exception as e:
            logger.error(f"Error connecting to admin database: {e}")
            return None
    
    async def get_all_admin_emails(self) -> List[str]:
        """
        Get all admin email addresses from the admin database
        
        Returns:
            List[str]: List of admin email addresses
        """
        try:
            admin_collection = await self._get_connection()
            if not admin_collection:
                logger.error("Failed to connect to admin database")
                return []
            
            # Find all admins and extract email addresses
            cursor = admin_collection.find(
                {"email": {"$exists": True, "$ne": None}},
                {"email": 1, "full_name": 1, "status": 1}
            )
            
            admin_emails = []
            async for admin in cursor:
                email = admin.get("email")
                full_name = admin.get("name", "Unknown")
                status = admin.get("status", "unknown")
                
                if email and isinstance(email, str) and email.strip():
                    admin_emails.append(email.strip())
                    logger.debug(f"Found admin: {full_name} ({email}) - Status: {status}")
            
            logger.info(f"Retrieved {len(admin_emails)} admin email addresses")
            return admin_emails
            
        except Exception as e:
            logger.error(f"Error fetching admin emails: {e}")
            return []
    
    async def get_all_admins(self) -> List[Dict]:
        """
        Get all admin information from the admin database
        
        Returns:
            List[Dict]: List of admin information dictionaries
        """
        try:
            admin_collection = await self._get_connection()
            if not admin_collection:
                logger.error("Failed to connect to admin database")
                return []
            
            # Find all admins
            cursor = admin_collection.find({})
            
            admins = []
            async for admin in cursor:
                admin_info = {
                    "admin_id": str(admin.get("_id", "")),
                    "email": admin.get("email", ""),
                    "full_name": admin.get("full_name", "Unknown"),
                    "status": admin.get("status", "unknown"),
                    "role": admin.get("role", "admin"),
                    "created_at": admin.get("created_at"),
                    "updated_at": admin.get("updated_at")
                }
                admins.append(admin_info)
            
            logger.info(f"Retrieved {len(admins)} admin records")
            return admins
            
        except Exception as e:
            logger.error(f"Error fetching admin information: {e}")
            return []
    
    async def get_active_admin_emails(self) -> List[str]:
        """
        Get email addresses of active admins only
        
        Returns:
            List[str]: List of active admin email addresses
        """
        try:
            admin_collection = await self._get_connection()
            if not admin_collection:
                logger.error("Failed to connect to admin database")
                return []
            
            # Find only active admins
            cursor = admin_collection.find(
                {
                    "email": {"$exists": True, "$ne": None},
                    "status": {"$in": ["active", "Active", "ACTIVE"]}
                },
                {"email": 1, "full_name": 1, "status": 1}
            )
            
            admin_emails = []
            async for admin in cursor:
                email = admin.get("email")
                full_name = admin.get("full_name", "Unknown")
                status = admin.get("status", "unknown")
                
                if email and isinstance(email, str) and email.strip():
                    admin_emails.append(email.strip())
                    logger.debug(f"Found active admin: {full_name} ({email}) - Status: {status}")
            
            logger.info(f"Retrieved {len(admin_emails)} active admin email addresses")
            return admin_emails
            
        except Exception as e:
            logger.error(f"Error fetching active admin emails: {e}")
            return []
    
    async def close_connection(self):
        """Close MongoDB connection"""
        try:
            if self.client:
                self.client.close()
                self.client = None
                self.database = None
                self.admin_collection = None
                logger.info("Admin database connection closed")
        except Exception as e:
            logger.error(f"Error closing admin database connection: {e}")

# Global admin service instance
admin_service = AdminService()

async def get_all_admin_emails() -> List[str]:
    """
    Convenience function to get all admin email addresses
    
    Returns:
        List[str]: List of admin email addresses
    """
    return await admin_service.get_all_admin_emails()

async def get_active_admin_emails() -> List[str]:
    """
    Convenience function to get active admin email addresses
    
    Returns:
        List[str]: List of active admin email addresses
    """
    return await admin_service.get_active_admin_emails()

async def get_all_admins() -> List[Dict]:
    """
    Convenience function to get all admin information
    
    Returns:
        List[Dict]: List of admin information dictionaries
    """
    return await admin_service.get_all_admins()
