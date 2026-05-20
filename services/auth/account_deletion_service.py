"""
Account Deletion Service

This service handles account deletion with two options:
1. Temporary Delete (Soft Delete): 
   - membership_status becomes inactive
   - All joined clubs become inactive
   - Track usage days and remaining days
   - Can reactivate later

2. Permanent Delete:
   - status becomes deleted
   - membership_status becomes deleted
   - All joined clubs become deleted
   - No refund provided
"""

from typing import Tuple, Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class AccountDeletionService:
    """Service for handling account deletion (temporary and permanent)"""
    
    def __init__(self):
        # Initialize collections when needed to avoid import issues
        self.users_collection = None
        self.clubs_collection = None
        self.club_memberships_collection = None
        self.account_deletions_collection = None
    
    def _ensure_collections_initialized(self):
        """Initialize collections using centralized database connection"""
        if self.users_collection is None:
            from core.database.connection import get_database_manager
            
            # Get database manager
            db_manager = get_database_manager()
            logger.info(f"Account deletion service using database manager: {db_manager}")
            
            # Initialize collections using centralized connection
            self.users_collection = db_manager.get_collection("users")
            self.clubs_collection = db_manager.get_collection("clubs")
            self.club_memberships_collection = db_manager.get_collection("club_memberships")
            self.account_deletions_collection = db_manager.get_collection("account_deletions")
            
            logger.info(f"Collections initialized - users: {self.users_collection}")
    
    async def delete_account(self, user_id: str, deletion_type: str, reason: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Delete user account (temporary or permanent)
        
        Args:
            user_id: User ID to delete
            deletion_type: 'temporary' or 'permanent'
            reason: Optional reason for deletion
            
        Returns:
            Tuple of (success, error_message, deletion_data)
        """
        try:
            self._ensure_collections_initialized()
            
            # Validate deletion type
            if deletion_type not in ['temporary', 'permanent']:
                return False, "Invalid deletion type. Must be 'temporary' or 'permanent'", None
            
            # Get user data
            logger.info(f"Looking for user with ID: {user_id}")
            
            try:
                user_object_id = ObjectId(user_id)
                logger.info(f"Converted user_id to ObjectId: {user_object_id}")
            except Exception as e:
                logger.error(f"Invalid user_id format: {user_id}, error: {str(e)}")
                return False, "Invalid user ID format", None
            
            user = await self.users_collection.find_one({"_id": user_object_id})
            if not user:
                logger.error(f"User not found in database with ID: {user_id}")
                return False, "User not found", None
            
            logger.info(f"Found user: {user.get('email', 'Unknown')} with status: {user.get('status', 'Unknown')}")
            
            # Check if user is already deleted
            if user.get("status") == "deleted":
                return False, "Account is already permanently deleted", None
            
            # Check if user is already temporarily deleted
            if user.get("membership_status") == "inactive" and deletion_type == "temporary":
                return False, "Account is already temporarily deactivated", None
            
            # Process deletion based on type
            if deletion_type == "temporary":
                return await self._process_temporary_deletion(user_id, user, reason)
            else:
                return await self._process_permanent_deletion(user_id, user, reason)
                
        except Exception as e:
            logger.error(f"Error in delete_account: {str(e)}")
            return False, f"Internal error: {str(e)}", None
    
    async def _process_temporary_deletion(self, user_id: str, user: Dict, reason: Optional[str]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Process temporary account deletion"""
        try:
            now = datetime.now(timezone.utc)
            
            # Calculate usage statistics
            usage_stats = await self._calculate_usage_stats(user)
            
            # Update user record
            user_update_data = {
                "membership_status": "inactive",
                "status": "inactive",  # Also update status to inactive
                "deletion_type": "temporary",
                "deleted_at": now,
                "deletion_reason": reason,
                "usage_stats": usage_stats,
                "is_temporary_deactivate": True,
                "is_permanent_deactivate": False,
                "updated_at": now
            }
            
            # Update user
            await self.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": user_update_data}
            )
            
            # Update club memberships
            clubs_updated = await self._update_club_memberships(user_id, "inactive")
            
            # Create deletion record
            deletion_record = {
                "user_id": user_id,
                "user_email": user.get("email"),
                "user_name": user.get("full_name"),
                "deletion_type": "temporary",
                "deletion_reason": reason,
                "usage_stats": usage_stats,
                "clubs_affected": clubs_updated,
                "status": "completed",
                "processed_at": now,
                "created_at": now,
                "updated_at": now
            }
            
            await self.account_deletions_collection.insert_one(deletion_record)
            
            logger.info(f"Temporary deletion completed for user {user_id}")
            return True, None, {
                "deletion_type": "temporary",
                "user_id": user_id,
                "usage_stats": usage_stats,
                "clubs_affected": clubs_updated,
                "deleted_at": now.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in _process_temporary_deletion: {str(e)}")
            return False, f"Error processing temporary deletion: {str(e)}", None
    
    async def _process_permanent_deletion(self, user_id: str, user: Dict, reason: Optional[str]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Process permanent account deletion"""
        try:
            now = datetime.now(timezone.utc)
            
            # Calculate usage statistics
            usage_stats = await self._calculate_usage_stats(user)
            
            # Update user record
            user_update_data = {
                "status": "deleted",
                "membership_status": "deleted",
                "deletion_type": "permanent",
                "deleted_at": now,
                "deletion_reason": reason,
                "usage_stats": usage_stats,
                "is_temporary_deactivate": False,
                "is_permanent_deactivate": True,
                "updated_at": now
            }
            
            # Update user
            await self.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": user_update_data}
            )
            
            # Update club memberships
            clubs_updated = await self._update_club_memberships(user_id, "deleted")
            
            # Create deletion record
            deletion_record = {
                "user_id": user_id,
                "user_email": user.get("email"),
                "user_name": user.get("full_name"),
                "deletion_type": "permanent",
                "deletion_reason": reason,
                "usage_stats": usage_stats,
                "clubs_affected": clubs_updated,
                "status": "completed",
                "processed_at": now,
                "created_at": now,
                "updated_at": now
            }
            
            await self.account_deletions_collection.insert_one(deletion_record)
            
            logger.info(f"Permanent deletion completed for user {user_id}")
            return True, None, {
                "deletion_type": "permanent",
                "user_id": user_id,
                "usage_stats": usage_stats,
                "clubs_affected": clubs_updated,
                "deleted_at": now.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in _process_permanent_deletion: {str(e)}")
            return False, f"Error processing permanent deletion: {str(e)}", None
    
    async def _calculate_usage_stats(self, user: Dict) -> Dict[str, Any]:
        """Calculate usage statistics for the user"""
        try:
            plan_start_date = user.get("plan_start_date")
            plan_end_date = user.get("plan_end_date")
            
            if not plan_start_date or not plan_end_date:
                return {
                    "plan_start_date": plan_start_date,
                    "plan_end_date": plan_end_date,
                    "total_days": 0,
                    "used_days": 0,
                    "remaining_days": 0,
                    "usage_percentage": 0
                }
            
            # Ensure dates are timezone-aware
            if plan_start_date.tzinfo is None:
                plan_start_date = plan_start_date.replace(tzinfo=timezone.utc)
            if plan_end_date.tzinfo is None:
                plan_end_date = plan_end_date.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            
            # Calculate total days
            total_days = (plan_end_date - plan_start_date).days
            
            # Calculate used days
            if now <= plan_start_date:
                used_days = 0
            elif now >= plan_end_date:
                used_days = total_days
            else:
                used_days = (now - plan_start_date).days
            
            # Calculate remaining days
            remaining_days = max(0, total_days - used_days)
            
            # Calculate usage percentage
            usage_percentage = (used_days / total_days * 100) if total_days > 0 else 0
            
            return {
                "plan_start_date": plan_start_date.isoformat(),
                "plan_end_date": plan_end_date.isoformat(),
                "total_days": total_days,
                "used_days": used_days,
                "remaining_days": remaining_days,
                "usage_percentage": round(usage_percentage, 2)
            }
            
        except Exception as e:
            logger.error(f"Error calculating usage stats: {str(e)}")
            return {
                "plan_start_date": None,
                "plan_end_date": None,
                "total_days": 0,
                "used_days": 0,
                "remaining_days": 0,
                "usage_percentage": 0
            }
    
    async def _update_club_memberships(self, user_id: str, new_status: str) -> List[Dict[str, Any]]:
        """Update club memberships status in both users and clubs tables"""
        try:
            clubs_updated = []
            now = datetime.now(timezone.utc)
            
            # Get user's clubs_joined array
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                logger.error(f"User not found for club membership update: {user_id}")
                return clubs_updated
            
            clubs_joined = user.get("clubs_joined", [])
            logger.info(f"Updating {len(clubs_joined)} club memberships for user {user_id}")
            
            # Update each club in clubs_joined array
            for club_data in clubs_joined:
                club_id = club_data.get("club_id")
                if not club_id:
                    continue
                
                try:
                    # Calculate usage statistics for this club membership
                    club_usage_stats = await self._calculate_club_usage_stats(club_data, new_status)
                    
                    # Update in clubs table - members array
                    club_update_result = await self.clubs_collection.update_one(
                        {
                            "_id": ObjectId(club_id),
                            "members.user_id": user_id
                        },
                        {
                            "$set": {
                                "members.$.membership_status": new_status,
                                "members.$.status": new_status,
                                "members.$.updated_at": now,
                                "members.$.usage_stats": club_usage_stats
                            }
                        }
                    )
                    
                    # Also update in paid_members array if user is there
                    paid_member_update_result = await self.clubs_collection.update_one(
                        {
                            "_id": ObjectId(club_id),
                            "paid_members.user_id": user_id
                        },
                        {
                            "$set": {
                                "paid_members.$.membership_status": new_status,
                                "paid_members.$.status": new_status,
                                "paid_members.$.updated_at": now,
                                "paid_members.$.usage_stats": club_usage_stats
                            }
                        }
                    )
                    
                    # Update in users table - clubs_joined array
                    user_club_update_result = await self.users_collection.update_one(
                        {
                            "_id": ObjectId(user_id),
                            "clubs_joined.club_id": club_id
                        },
                        {
                            "$set": {
                                "clubs_joined.$.membership_status": new_status,
                                "clubs_joined.$.status": new_status,
                                "clubs_joined.$.updated_at": now,
                                "clubs_joined.$.usage_stats": club_usage_stats
                            }
                        }
                    )
                    
                    if club_update_result.modified_count > 0 or paid_member_update_result.modified_count > 0 or user_club_update_result.modified_count > 0:
                        clubs_updated.append({
                            "club_id": str(club_id),
                            "club_name": club_data.get("club_name", "Unknown"),
                            "membership_type": club_data.get("membership_type", "unknown"),
                            "status": new_status,
                            "usage_stats": club_usage_stats,
                            "updated_at": now.isoformat()
                        })
                        
                        logger.info(f"Updated club {club_id} membership for user {user_id} to status: {new_status}")
                        
                except Exception as e:
                    logger.error(f"Error updating club {club_id}: {str(e)}")
                    continue
            
            # Also update club_memberships collection
            await self.club_memberships_collection.update_many(
                {"user_id": ObjectId(user_id)},
                {
                    "$set": {
                        "status": new_status,
                        "membership_status": new_status,
                        "updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            logger.info(f"Updated {len(clubs_updated)} clubs for user {user_id}")
            return clubs_updated
            
        except Exception as e:
            logger.error(f"Error updating club memberships: {str(e)}")
            return []
    
    async def _calculate_club_usage_stats(self, club_data: Dict, new_status: str) -> Dict[str, Any]:
        """Calculate usage statistics for a specific club membership"""
        try:
            join_date = club_data.get("join_date")
            end_date = club_data.get("end_date")
            
            # Use club-specific join_date and end_date for accurate calculation
            if not join_date or not end_date:
                logger.warning(f"Missing join_date or end_date for club {club_data.get('club_id', 'unknown')}")
                return {
                    "total_days": 0,
                    "used_days": 0,
                    "remaining_days": 0,
                    "usage_percentage": 0,
                    "status": new_status,
                    "error": "Missing join_date or end_date"
                }
            
            # Ensure dates are timezone-aware
            if join_date.tzinfo is None:
                join_date = join_date.replace(tzinfo=timezone.utc)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            
            # Calculate total days for this specific club membership (inclusive of both start and end dates)
            # Add 1 to include both start and end dates in the count
            total_days = (end_date - join_date).days + 1
            
            # Calculate used days based on current time or deletion time
            if new_status in ["inactive", "deleted"]:
                # If being deactivated/deleted, calculate used days up to now (inclusive)
                if now <= join_date:
                    used_days = 0
                elif now >= end_date:
                    used_days = total_days
                else:
                    # Calculate days used (inclusive of start date)
                    # Add 1 to include the join date as a used day
                    used_days = (now.date() - join_date.date()).days + 1
            else:
                # If being reactivated, use the original usage
                used_days = club_data.get("usage_stats", {}).get("used_days", 0)
            
            # Calculate remaining days
            remaining_days = max(0, total_days - used_days)
            
            # Calculate usage percentage
            usage_percentage = (used_days / total_days * 100) if total_days > 0 else 0
            
            logger.info(f"Club {club_data.get('club_id', 'unknown')} usage calculation:")
            logger.info(f"  Join date: {join_date}, End date: {end_date}")
            logger.info(f"  Total days: {total_days}, Used days: {used_days}, Remaining: {remaining_days}")
            logger.info(f"  Current time: {now}")
            
            return {
                "total_days": total_days,
                "used_days": used_days,
                "remaining_days": remaining_days,
                "usage_percentage": round(usage_percentage, 2),
                "status": new_status,
                "calculated_at": now.isoformat(),
                "join_date": join_date.isoformat(),
                "end_date": end_date.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error calculating club usage stats: {str(e)}")
            return {
                "total_days": 0,
                "used_days": 0,
                "remaining_days": 0,
                "usage_percentage": 0,
                "status": new_status,
                "error": str(e)
            }
    
    async def reactivate_account(self, user_id: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Reactivate temporarily deleted account
        
        Args:
            user_id: User ID to reactivate
            
        Returns:
            Tuple of (success, error_message, reactivation_data)
        """
        try:
            self._ensure_collections_initialized()
            
            # Get user data
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False, "User not found", None
            
            # Check if user is temporarily deleted
            if user.get("deletion_type") != "temporary":
                return False, "Account is not temporarily deleted or cannot be reactivated", None
            
            # Check if subscription is still valid
            plan_end_date = user.get("plan_end_date")
            if plan_end_date:
                if plan_end_date.tzinfo is None:
                    plan_end_date = plan_end_date.replace(tzinfo=timezone.utc)
                
                if datetime.now(timezone.utc) > plan_end_date:
                    return False, "Subscription has expired. Cannot reactivate account", None
            
            now = datetime.now(timezone.utc)
            
            # Update user record
            user_update_data = {
                "status": "active",
                "membership_status": "active",
                "deletion_type": None,
                "deleted_at": None,
                "deletion_reason": None,
                "is_temporary_deactivate": False,
                "is_permanent_deactivate": False,
                "reactivated_at": now,
                "updated_at": now
            }
            
            # Update user
            await self.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": user_update_data}
            )
            
            # Reactivate club memberships
            clubs_reactivated = await self._update_club_memberships(user_id, "active")
            
            # Update deletion record
            await self.account_deletions_collection.update_one(
                {"user_id": user_id, "deletion_type": "temporary"},
                {
                    "$set": {
                        "status": "reactivated",
                        "reactivated_at": now,
                        "updated_at": now
                    }
                }
            )
            
            logger.info(f"Account reactivated for user {user_id}")
            return True, None, {
                "user_id": user_id,
                "clubs_reactivated": clubs_reactivated,
                "reactivated_at": now.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in reactivate_account: {str(e)}")
            return False, f"Internal error: {str(e)}", None
    
    async def get_deletion_status(self, user_id: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Get account deletion status
        
        Args:
            user_id: User ID to check
            
        Returns:
            Tuple of (success, error_message, status_data)
        """
        try:
            self._ensure_collections_initialized()
            
            # Get user data
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False, "User not found", None
            
            status = user.get("status")
            membership_status = user.get("membership_status")
            deletion_type = user.get("deletion_type")
            
            status_data = {
                "user_id": user_id,
                "status": status,
                "membership_status": membership_status,
                "deletion_type": deletion_type,
                "deleted_at": user.get("deleted_at"),
                "deletion_reason": user.get("deletion_reason"),
                "usage_stats": user.get("usage_stats"),
                "can_reactivate": False
            }
            
            # Check if can reactivate
            if deletion_type == "temporary":
                plan_end_date = user.get("plan_end_date")
                if plan_end_date:
                    if plan_end_date.tzinfo is None:
                        plan_end_date = plan_end_date.replace(tzinfo=timezone.utc)
                    
                    if datetime.now(timezone.utc) <= plan_end_date:
                        status_data["can_reactivate"] = True
            
            return True, None, status_data
            
        except Exception as e:
            logger.error(f"Error in get_deletion_status: {str(e)}")
            return False, f"Internal error: {str(e)}", None
