"""
Moderator Management Service

This module handles moderator deletion and reactivation by captains.
Allows captains to manage moderators in their clubs using club name_based_id.
"""

from fastapi import HTTPException, status
from bson import ObjectId
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List
import logging

from .db import get_club_collection, get_user_collection
from .id_utils import is_valid_name_based_id
from core.utils.response_utils import create_response

logger = logging.getLogger(__name__)


class ModeratorManagementService:
    """Service for managing moderator deletion and reactivation by captains"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
    
    async def delete_moderator(
        self, 
        club_name_based_id: str, 
        moderator_user_id: str, 
        captain_id: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Delete (deactivate) a moderator from a club
        
        Args:
            club_name_based_id: Club's name_based_id (e.g., "new-test")
            moderator_user_id: User ID of the moderator to delete
            captain_id: Captain's user ID
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"🗑️ Processing moderator deletion: club={club_name_based_id}, moderator={moderator_user_id}, captain={captain_id}")
            
            # Step 1: Find the club by name_based_id and verify captain ownership
            club = await self._find_club_by_name_based_id(club_name_based_id, captain_id)
            if not club:
                return False, None, "Club not found or you don't have permission to manage moderators in this club"
            
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            
            # Step 2: Find the moderator in detailed_moderators array
            detailed_moderators = club.get("detailed_moderators", [])
            moderator_found = False
            moderator_info = None
            updated_moderators = []
            
            for moderator in detailed_moderators:
                if str(moderator.get("user_id")) == moderator_user_id:
                    if moderator.get("status") == "inactive":
                        return False, None, "Moderator is already deleted/inactive"
                    
                    # Store moderator info for response
                    moderator_info = {
                        "user_id": moderator.get("user_id"),
                        "full_name": moderator.get("full_name"),
                        "email": moderator.get("email"),
                        "type_of_moderator": moderator.get("type_of_moderator"),
                        "status": "inactive",
                        "deleted_at": datetime.now(timezone.utc),
                        "deleted_by": captain_id
                    }
                    
                    # Update moderator status
                    moderator["status"] = "inactive"
                    moderator["deleted_at"] = datetime.now(timezone.utc)
                    moderator["deleted_by"] = captain_id
                    moderator_found = True
                    
                    logger.info(f"✅ Moderator {moderator.get('full_name')} marked as inactive")
                
                updated_moderators.append(moderator)
            
            if not moderator_found:
                return False, None, "Moderator not found in this club"
            
            # Step 3: Calculate updated counts
            active_moderators = [m for m in updated_moderators if m.get("status") == "active"]
            active_free_moderators = [m for m in active_moderators if m.get("type_of_moderator") == "free"]
            active_paid_moderators = [m for m in active_moderators if m.get("type_of_moderator") == "paid"]
            
            # Step 4: Update the club document
            update_result = await self.club_collection.update_one(
                {"_id": club["_id"]},
                {
                    "$set": {
                        "detailed_moderators": updated_moderators,
                        "moderator_count": len(active_moderators),
                        "free_moderators": len(active_free_moderators),
                        "paid_moderators": len(active_paid_moderators),
                        "updated_at": datetime.now(timezone.utc),
                    }
                }
            )
            
            if update_result.modified_count > 0:
                logger.info(f"✅ Successfully deleted moderator from club {club_name}")
                
                response_data = {
                    "success": True,
                    "message": "Moderator deleted successfully",
                    "club_id": club_id,
                    "club_name": club_name,
                    "club_name_based_id": club_name_based_id,
                    "moderator_info": moderator_info,
                    "updated_counts": {
                        "total_moderators": len(active_moderators),
                        "free_moderators": len(active_free_moderators),
                        "paid_moderators": len(active_paid_moderators)
                    },
                    "deleted_at": datetime.now(timezone.utc).isoformat()
                }
                
                return True, response_data, ""
            else:
                return False, None, "Failed to update club document"
                
        except Exception as e:
            logger.error(f"Error deleting moderator: {e}")
            return False, None, f"Internal server error: {str(e)}"
    
    async def reactivate_moderator(
        self, 
        club_name_based_id: str, 
        moderator_user_id: str, 
        captain_id: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Reactivate a deleted moderator in a club
        
        Args:
            club_name_based_id: Club's name_based_id (e.g., "new-test")
            moderator_user_id: User ID of the moderator to reactivate
            captain_id: Captain's user ID
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"🔄 Processing moderator reactivation: club={club_name_based_id}, moderator={moderator_user_id}, captain={captain_id}")
            
            # Step 1: Find the club by name_based_id and verify captain ownership
            club = await self._find_club_by_name_based_id(club_name_based_id, captain_id)
            if not club:
                return False, None, "Club not found or you don't have permission to manage moderators in this club"
            
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            
            # Step 2: Find the moderator in detailed_moderators array
            detailed_moderators = club.get("detailed_moderators", [])
            moderator_found = False
            moderator_info = None
            updated_moderators = []
            
            for moderator in detailed_moderators:
                if str(moderator.get("user_id")) == moderator_user_id:
                    if moderator.get("status") == "active":
                        return False, None, "Moderator is already active"
                    
                    # Store moderator info for response
                    moderator_info = {
                        "user_id": moderator.get("user_id"),
                        "full_name": moderator.get("full_name"),
                        "email": moderator.get("email"),
                        "type_of_moderator": moderator.get("type_of_moderator"),
                        "status": "active",
                        "reactivated_at": datetime.now(timezone.utc),
                        "reactivated_by": captain_id
                    }
                    
                    # Update moderator status
                    moderator["status"] = "active"
                    moderator["reactivated_at"] = datetime.now(timezone.utc)
                    moderator["reactivated_by"] = captain_id
                    # Clear deletion info
                    moderator.pop("deleted_at", None)
                    moderator.pop("deleted_by", None)
                    moderator_found = True
                    
                    logger.info(f"✅ Moderator {moderator.get('full_name')} reactivated")
                
                updated_moderators.append(moderator)
            
            if not moderator_found:
                return False, None, "Moderator not found in this club"
            
            # Step 3: Calculate updated counts
            active_moderators = [m for m in updated_moderators if m.get("status") == "active"]
            active_free_moderators = [m for m in active_moderators if m.get("type_of_moderator") == "free"]
            active_paid_moderators = [m for m in active_moderators if m.get("type_of_moderator") == "paid"]
            
            # Step 4: Update the club document
            update_result = await self.club_collection.update_one(
                {"_id": club["_id"]},
                {
                    "$set": {
                        "detailed_moderators": updated_moderators,
                        "moderator_count": len(active_moderators),
                        "free_moderators": len(active_free_moderators),
                        "paid_moderators": len(active_paid_moderators),
                        "updated_at": datetime.now(timezone.utc),
                    }
                }
            )
            
            if update_result.modified_count > 0:
                logger.info(f"✅ Successfully reactivated moderator in club {club_name}")
                
                # Send moderator reactivation notification to all club members
                try:
                    from services.notifications.notification_service import (
                        send_notification_to_users,
                        get_club_members,
                        filter_users_by_notification_preference,
                        get_collections,
                    )
                    
                    if club_name_based_id:
                        # Get all club members
                        all_club_members = await get_club_members(club_name_based_id)
                        
                        if all_club_members:
                            # Filter by club status alerts
                            enabled_user_ids = await filter_users_by_notification_preference(
                                all_club_members,
                                "club_status_alerts"
                            )
                            enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]
                            
                            collections = get_collections()
                            user_tokens_collection = collections.get_user_tokens_collection()
                            
                            users_with_tokens = []
                            if enabled_user_ids:
                                token_cursor = user_tokens_collection.find(
                                    {
                                        "user_id": {"$in": enabled_user_ids},
                                        "is_active": True,
                                    },
                                    {"user_id": 1},
                                )
                                token_docs = await token_cursor.to_list(length=None)
                                users_with_tokens = list({
                                    doc.get("user_id") for doc in token_docs if doc.get("user_id")
                                })
                            
                            db_user_ids = [uid for uid in all_club_members if uid]
                            push_user_ids = [
                                uid for uid in users_with_tokens if uid in enabled_user_ids
                            ]
                            
                            if db_user_ids:
                                # Prepare notification content
                                moderator_name = moderator_info.get("full_name", "A moderator") if moderator_info else "A moderator"
                                title = f"Moderator Reinstated!"
                                body = f"{moderator_name} has been reinstated as moderator by Captain"
                                
                                notification_data = {
                                    "club_id": club_name_based_id,
                                    "club_name": club_name,
                                    "moderator_name": moderator_name,
                                    "moderator_id": moderator_user_id,
                                    "action_type": "moderator_reactivation",
                                    "changed_by": "Captain"
                                }
                                
                                notification_result = await send_notification_to_users(
                                    user_ids=push_user_ids,
                                    title=title,
                                    body=body,
                                    notification_type="club_status_change",
                                    data=notification_data,
                                    click_action=f"club/{club_name_based_id}/moderators",
                                    priority="normal",
                                    all_user_ids=db_user_ids,
                                )
                                logger.info(
                                    f"✅ Moderator reactivation notification stored for club {club_name_based_id}: {notification_result}"
                                )
                            else:
                                logger.info(f"ℹ️ No eligible club members found for club {club_name_based_id}")
                        else:
                            logger.info(f"ℹ️ No club members found for club {club_name_based_id}")
                            
                except Exception as e:
                    logger.error(f"⚠️ Failed to send moderator reactivation notification: {e}")
                
                response_data = {
                    "success": True,
                    "message": "Moderator reactivated successfully",
                    "club_id": club_id,
                    "club_name": club_name,
                    "club_name_based_id": club_name_based_id,
                    "moderator_info": moderator_info,
                    "updated_counts": {
                        "total_moderators": len(active_moderators),
                        "free_moderators": len(active_free_moderators),
                        "paid_moderators": len(active_paid_moderators)
                    },
                    "reactivated_at": datetime.now(timezone.utc).isoformat()
                }
                
                return True, response_data, ""
            else:
                return False, None, "Failed to update club document"
                
        except Exception as e:
            logger.error(f"Error reactivating moderator: {e}")
            return False, None, f"Internal server error: {str(e)}"
    
    async def _find_club_by_name_based_id(
        self, 
        club_name_based_id: str, 
        captain_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find club by name_based_id and verify captain ownership
        
        Args:
            club_name_based_id: Club's name_based_id
            captain_id: Captain's user ID
            
        Returns:
            Club document if found and owned by captain, None otherwise
        """
        try:
            # Validate name_based_id format
            if not is_valid_name_based_id(club_name_based_id):
                logger.warning(f"Invalid name_based_id format: {club_name_based_id}")
                return None
            
            # Find club by name_based_id and captain_id
            club = await self.club_collection.find_one({
                "name_based_id": club_name_based_id,
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}  # Exclude permanently deleted clubs
            })
            
            if club:
                logger.info(f"✅ Found club: {club.get('name')} (ID: {club.get('_id')})")
            else:
                logger.warning(f"❌ Club not found: {club_name_based_id} for captain {captain_id}")
            
            return club
            
        except Exception as e:
            logger.error(f"Error finding club by name_based_id: {e}")
            return None


# Create service instance
moderator_management_service = ModeratorManagementService()
