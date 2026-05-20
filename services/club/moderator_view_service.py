"""
Moderator View Service

This service handles viewing detailed moderator information for clubs.
It provides pagination and ensures captains can only view moderators of their own clubs.
"""

import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from bson import ObjectId
import math

from .db import get_club_collection
from .models import ModeratorViewRequest, ModeratorViewResponse, DetailedModeratorInfo
from .id_utils import is_valid_name_based_id

# Configure logging
logger = logging.getLogger(__name__)

class ModeratorViewService:
    """Service for viewing club moderators with pagination"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
    
    async def get_club_moderators(self, request: ModeratorViewRequest, captain_id: str) -> Tuple[bool, Optional[ModeratorViewResponse], str]:
        """
        Get detailed moderator information for a club with pagination
        
        Args:
            request: ModeratorViewRequest with club_id and pagination parameters
            captain_id: ID of the captain requesting the data
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"Getting moderators for club: {request.club_id}, captain: {captain_id}")
            
            # Step 1: Find the club and validate ownership
            club = await self._find_club_by_id(request.club_id, captain_id)
            if not club:
                return False, None, "Club not found or you don't have permission to view its moderators"
            
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            club_name_based_id = club.get("name_based_id", "")
            
            # Step 2: Get detailed moderators from the club
            detailed_moderators = club.get("detailed_moderators", [])
            
            if not detailed_moderators:
                logger.info(f"No moderators found for club: {club_name}")
                # Return empty response with stats
                return True, self._create_empty_response(
                    club_id, club_name, club_name_based_id, request.page, request.page_size
                ), ""
            
            # Step 3: Apply pagination
            total_moderators = len(detailed_moderators)
            total_pages = math.ceil(total_moderators / request.page_size)
            
            # Validate page number
            if request.page > total_pages and total_pages > 0:
                return False, None, f"Page {request.page} does not exist. Total pages: {total_pages}"
            
            # Calculate pagination
            start_index = (request.page - 1) * request.page_size
            end_index = start_index + request.page_size
            paginated_moderators = detailed_moderators[start_index:end_index]
            
            # Step 4: Convert to DetailedModeratorInfo objects
            moderator_objects = []
            for mod_data in paginated_moderators:
                try:
                    moderator = DetailedModeratorInfo(
                        email=mod_data.get("email", ""),
                        full_name=mod_data.get("full_name", "Unknown"),
                        user_id=mod_data.get("user_id", ""),
                        status=mod_data.get("status", "active"),
                        type_of_moderator=mod_data.get("type_of_moderator", "free"),
                        price=mod_data.get("price", 0.0),
                        invited_at=mod_data.get("invited_at", datetime.utcnow()),
                        responded_at=mod_data.get("responded_at"),
                        response=mod_data.get("response")
                    )
                    moderator_objects.append(moderator)
                except Exception as e:
                    logger.warning(f"Error parsing moderator data: {e}")
                    continue
            
            # Step 5: Get moderator statistics
            moderator_stats = self._calculate_moderator_stats(detailed_moderators)
            
            # Step 6: Create pagination info
            pagination_info = {
                "current_page": request.page,
                "page_size": request.page_size,
                "total_items": total_moderators,
                "total_pages": total_pages,
                "has_next": request.page < total_pages,
                "has_previous": request.page > 1,
                "items_on_current_page": len(moderator_objects)
            }
            
            # Step 7: Create response
            response = ModeratorViewResponse(
                success=True,
                message="Moderators retrieved successfully",
                club_id=club_id,
                club_name=club_name,
                club_name_based_id=club_name_based_id,
                moderators=moderator_objects,
                pagination=pagination_info,
                moderator_stats=moderator_stats
            )
            
            logger.info(f"Successfully retrieved {len(moderator_objects)} moderators for club {club_name}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"Error in get_club_moderators: {e}")
            import traceback
            traceback.print_exc()
            return False, None, f"Internal server error: {str(e)}"
    
    async def _find_club_by_id(self, club_id: str, captain_id: str) -> Optional[Dict]:
        """Find club by ID and validate captain ownership"""
        try:
            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(club_id):
                logger.info(f"Searching by name_based_id: {club_id}")
                club = await self.club_collection.find_one({
                    "name_based_id": club_id,
                    "captain_id": captain_id
                })
            else:
                logger.info(f"Searching by ObjectId: {club_id}")
                try:
                    club_object_id = ObjectId(club_id)
                except Exception as e:
                    logger.error(f"Invalid ObjectId format: {club_id}, error: {e}")
                    return None
                
                club = await self.club_collection.find_one({
                    "_id": club_object_id,
                    "captain_id": captain_id
                })
            
            if club:
                logger.info(f"Found club: {club.get('name', 'Unknown')} for captain: {captain_id}")
            else:
                logger.warning(f"Club not found or captain mismatch for club_id: {club_id}, captain_id: {captain_id}")
            
            return club
            
        except Exception as e:
            logger.error(f"Error finding club: {e}")
            return None
    
    def _calculate_moderator_stats(self, detailed_moderators: List[Dict]) -> Dict:
        """Calculate moderator statistics"""
        try:
            total_moderators = len(detailed_moderators)
            free_moderators = 0
            paid_moderators = 0
            total_price = 0.0
            
            for moderator in detailed_moderators:
                moderator_type = moderator.get("type_of_moderator", "free")
                price = moderator.get("price", 0.0)
                
                if moderator_type == "free":
                    free_moderators += 1
                else:
                    paid_moderators += 1
                    total_price += price
            
            return {
                "total_moderators": total_moderators,
                "free_moderators": free_moderators,
                "paid_moderators": paid_moderators,
                "total_price": round(total_price, 2),
                "average_price": round(total_price / paid_moderators, 2) if paid_moderators > 0 else 0.0
            }
            
        except Exception as e:
            logger.error(f"Error calculating moderator stats: {e}")
            return {
                "total_moderators": 0,
                "free_moderators": 0,
                "paid_moderators": 0,
                "total_price": 0.0,
                "average_price": 0.0
            }
    
    def _create_empty_response(self, club_id: str, club_name: str, club_name_based_id: str, page: int, page_size: int) -> ModeratorViewResponse:
        """Create empty response when no moderators are found"""
        pagination_info = {
            "current_page": page,
            "page_size": page_size,
            "total_items": 0,
            "total_pages": 0,
            "has_next": False,
            "has_previous": False,
            "items_on_current_page": 0
        }
        
        moderator_stats = {
            "total_moderators": 0,
            "free_moderators": 0,
            "paid_moderators": 0,
            "total_price": 0.0,
            "average_price": 0.0
        }
        
        return ModeratorViewResponse(
            success=True,
            message="No moderators found for this club",
            club_id=club_id,
            club_name=club_name,
            club_name_based_id=club_name_based_id,
            moderators=[],
            pagination=pagination_info,
            moderator_stats=moderator_stats
        )
