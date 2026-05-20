"""
Moderator Details Service

This module handles fetching detailed moderator information for captains.
Provides moderator details from a specific club and all club assignments.
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


class ModeratorDetailsService:
    """Service for fetching detailed moderator information"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
    
    async def get_moderator_details(
        self, 
        club_name_based_id: str, 
        moderator_user_id: str, 
        captain_id: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Get detailed moderator information for a specific club
        
        Args:
            club_name_based_id: Club's name_based_id (e.g., "new-club")
            moderator_user_id: User ID of the moderator
            captain_id: Captain's user ID
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"🔍 Getting moderator details: club={club_name_based_id}, moderator={moderator_user_id}, captain={captain_id}")
            
            # Step 1: Find the club by name_based_id and verify captain ownership
            club = await self._find_club_by_name_based_id(club_name_based_id, captain_id)
            if not club:
                return False, None, "Club not found or you don't have permission to view moderators in this club"
            
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            
            # Step 2: Find the moderator in detailed_moderators array
            detailed_moderators = club.get("detailed_moderators", [])
            moderator_info = None
            
            for moderator in detailed_moderators:
                if str(moderator.get("user_id")) == moderator_user_id:
                    moderator_info = moderator
                    break
            
            if not moderator_info:
                return False, None, "Moderator not found in this club"
            
            # Step 3: Get moderator's basic information from users table
            moderator_details = await self._get_moderator_user_details(moderator_user_id)
            if not moderator_details:
                return False, None, "Moderator user information not found"
            
            # Step 4: Get all clubs where this moderator is assigned (created by this captain)
            all_club_assignments = await self._get_moderator_all_club_assignments(moderator_user_id, captain_id)
            
            # Step 5: Get captain's total clubs count
            captain_clubs_count = await self._get_captain_clubs_count(captain_id)
            
            # Step 6: Prepare current club assignment info
            current_club_info = {
                "club_id": club_id,
                "club_name": club_name,
                "club_name_based_id": club_name_based_id,
                "logo_url": club.get("logo_url"),
                "banner_url": club.get("banner_url"),
                "moderator_status": moderator_info.get("status", "unknown"),
                "moderator_type": moderator_info.get("type_of_moderator", "unknown"),
                "joined_date": moderator_info.get("invited_at"),
                "invited_at": moderator_info.get("invited_at")
            }
            
            # Step 7: Prepare response data
            response_data = {
                "success": True,
                "message": f"Moderator details retrieved successfully for {club_name}",
                "moderator_details": moderator_details,
                "current_club_info": current_club_info,
                "all_club_assignments": all_club_assignments,
                "total_club_assignments": len(all_club_assignments),
                "captain_clubs_count": captain_clubs_count
            }
            
            logger.info(f"✅ Successfully retrieved moderator details for {moderator_user_id} in club {club_name}")
            return True, response_data, ""
            
        except Exception as e:
            logger.error(f"Error getting moderator details: {e}")
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
    
    async def _get_moderator_user_details(self, moderator_user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get moderator's basic information from users table
        
        Args:
            moderator_user_id: Moderator's user ID
            
        Returns:
            Moderator user details or None
        """
        try:
            moderator = await self.user_collection.find_one({"_id": ObjectId(moderator_user_id)})
            
            if not moderator:
                logger.warning(f"Moderator user not found: {moderator_user_id}")
                return None
            
            moderator_details = {
                "user_id": moderator_user_id,
                "full_name": moderator.get("full_name", "Unknown"),
                "email": moderator.get("email", ""),
                "avatar_url": moderator.get("avatar_url"),
                "bio": moderator.get("bio"),
                "phone_number": moderator.get("phone_number"),
                "created_at": moderator.get("created_at"),
                "last_login": moderator.get("last_login")
            }
            
            logger.info(f"✅ Retrieved moderator user details for {moderator_user_id}")
            return moderator_details
            
        except Exception as e:
            logger.error(f"Error getting moderator user details: {e}")
            return None
    
    async def _get_moderator_all_club_assignments(
        self, 
        moderator_user_id: str, 
        captain_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all clubs where moderator is assigned (created by this captain)
        
        Args:
            moderator_user_id: Moderator's user ID
            captain_id: Captain's user ID
            
        Returns:
            List of club assignment information
        """
        try:
            # Find all clubs created by this captain
            captain_clubs = await self.club_collection.find({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            }).to_list(length=None)
            
            club_assignments = []
            
            for club in captain_clubs:
                detailed_moderators = club.get("detailed_moderators", [])
                
                # Check if moderator is assigned to this club
                for moderator in detailed_moderators:
                    if str(moderator.get("user_id")) == moderator_user_id:
                        assignment_info = {
                            "club_id": str(club["_id"]),
                            "club_name": club.get("name", "Unknown"),
                            "club_name_based_id": club.get("name_based_id", ""),
                            "logo_url": club.get("logo_url"),
                            "banner_url": club.get("banner_url"),
                            "moderator_status": moderator.get("status", "unknown"),
                            "moderator_type": moderator.get("type_of_moderator", "unknown"),
                            "joined_date": moderator.get("invited_at"),
                            "invited_at": moderator.get("invited_at")
                        }
                        club_assignments.append(assignment_info)
                        break
            
            logger.info(f"✅ Found {len(club_assignments)} club assignments for moderator {moderator_user_id}")
            return club_assignments
            
        except Exception as e:
            logger.error(f"Error getting moderator club assignments: {e}")
            return []
    
    async def _get_captain_clubs_count(self, captain_id: str) -> int:
        """
        Get total number of clubs created by the captain
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            Number of clubs created by captain
        """
        try:
            count = await self.club_collection.count_documents({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            })
            
            logger.info(f"✅ Captain {captain_id} has created {count} clubs")
            return count
            
        except Exception as e:
            logger.error(f"Error getting captain clubs count: {e}")
            return 0


# Create service instance
moderator_details_service = ModeratorDetailsService()
