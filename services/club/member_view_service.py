"""
Member View Service

This service handles viewing detailed member information for clubs.
It provides pagination and ensures captains can only view members of their own clubs.
"""

import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from bson import ObjectId
import math

from .db import get_club_collection
from .models import MemberViewRequest, MemberViewResponse, DetailedMemberInfo
from .id_utils import is_valid_name_based_id

# Configure logging
logger = logging.getLogger(__name__)

class MemberViewService:
    """Service for viewing club members with pagination"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
    
    async def get_club_members(self, request: MemberViewRequest, captain_id: str) -> Tuple[bool, Optional[MemberViewResponse], str]:
        """
        Get detailed member information for a club with pagination
        
        Args:
            request: MemberViewRequest with club_id and pagination parameters
            captain_id: ID of the captain requesting the data
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"Getting members for club: {request.club_id}, captain: {captain_id}")
            
            # Step 1: Find the club and validate ownership
            club = await self._find_club_by_id(request.club_id, captain_id)
            if not club:
                return False, None, "Club not found or you don't have permission to view its members"
            
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            club_name_based_id = club.get("name_based_id", "")
            
            # Step 2: Get all members from the club (both trial and paid)
            all_members = await self._get_all_club_members(club)
            
            if not all_members:
                logger.info(f"No members found for club: {club_name}")
                # Return empty response with stats
                return True, self._create_empty_response(
                    club_id, club_name, club_name_based_id, request.page, request.page_size
                ), ""
            
            # Step 3: Apply pagination
            total_members = len(all_members)
            total_pages = math.ceil(total_members / request.page_size)
            
            # Validate page number
            if request.page > total_pages and total_pages > 0:
                return False, None, f"Page {request.page} does not exist. Total pages: {total_pages}"
            
            # Calculate pagination
            start_index = (request.page - 1) * request.page_size
            end_index = start_index + request.page_size
            paginated_members = all_members[start_index:end_index]
            
            # Step 4: Convert to DetailedMemberInfo objects
            member_objects = []
            for member_data in paginated_members:
                try:
                    member = DetailedMemberInfo(
                        user_id=member_data.get("user_id", ""),
                        full_name=member_data.get("full_name", "Unknown"),
                        email=member_data.get("email", ""),
                        phone=member_data.get("phone"),
                        avatar_url=member_data.get("avatar_url"),
                        membership_type=member_data.get("membership_type", "trial"),
                        membership_status=member_data.get("membership_status", "active"),
                        pricing_plan=member_data.get("pricing_plan", "trial"),
                        join_date=member_data.get("join_date", datetime.utcnow()),
                        end_date=member_data.get("end_date", datetime.utcnow()),
                        is_trial=member_data.get("is_trial", True),
                        is_active=member_data.get("is_active", True),
                        is_temporarily_deleted=member_data.get("is_temporarily_deleted", False),
                        last_seen=member_data.get("last_seen", datetime.utcnow()),
                        payment_id=member_data.get("payment_id"),
                        amount_paid=member_data.get("amount_paid", 0.0),
                        created_at=member_data.get("created_at", datetime.utcnow()),
                        updated_at=member_data.get("updated_at", datetime.utcnow())
                    )
                    member_objects.append(member)
                except Exception as e:
                    logger.warning(f"Error parsing member data: {e}")
                    continue
            
            # Step 5: Get member statistics
            member_stats = self._calculate_member_stats(all_members)
            
            # Step 6: Create pagination info
            pagination_info = {
                "current_page": request.page,
                "page_size": request.page_size,
                "total_items": total_members,
                "total_pages": total_pages,
                "has_next": request.page < total_pages,
                "has_previous": request.page > 1,
                "items_on_current_page": len(member_objects)
            }
            
            # Step 7: Create response
            response = MemberViewResponse(
                success=True,
                message="Members retrieved successfully",
                club_id=club_id,
                club_name=club_name,
                club_name_based_id=club_name_based_id,
                members=member_objects,
                pagination=pagination_info,
                member_stats=member_stats
            )
            
            logger.info(f"Successfully retrieved {len(member_objects)} members for club {club_name}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"Error in get_club_members: {e}")
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
    
    async def _get_all_club_members(self, club: Dict) -> List[Dict]:
        """Get all members from the club (both trial and paid)"""
        try:
            all_members = []
            
            # Get trial members
            trial_members = club.get("members", [])
            logger.info(f"Found {len(trial_members)} trial members")
            
            # Get paid members
            paid_members = club.get("paid_members", [])
            logger.info(f"Found {len(paid_members)} paid members")
            
            # Combine all members
            all_members.extend(trial_members)
            all_members.extend(paid_members)
            
            logger.info(f"Total members found: {len(all_members)}")
            return all_members
            
        except Exception as e:
            logger.error(f"Error getting club members: {e}")
            return []
    
    def _calculate_member_stats(self, all_members: List[Dict]) -> Dict:
        """Calculate member statistics"""
        try:
            total_members = len(all_members)
            trial_members = 0
            paid_members = 0
            active_members = 0
            total_revenue = 0.0
            
            for member in all_members:
                membership_type = member.get("membership_type", "trial")
                is_active = member.get("is_active", True)
                amount_paid = member.get("amount_paid", 0.0)
                
                if membership_type == "trial":
                    trial_members += 1
                else:
                    paid_members += 1
                    total_revenue += amount_paid
                
                if is_active:
                    active_members += 1
            
            return {
                "total_members": total_members,
                "trial_members": trial_members,
                "paid_members": paid_members,
                "active_members": active_members,
                "inactive_members": total_members - active_members,
                "total_revenue": round(total_revenue, 2),
                "average_revenue_per_paid_member": round(total_revenue / paid_members, 2) if paid_members > 0 else 0.0
            }
            
        except Exception as e:
            logger.error(f"Error calculating member stats: {e}")
            return {
                "total_members": 0,
                "trial_members": 0,
                "paid_members": 0,
                "active_members": 0,
                "inactive_members": 0,
                "total_revenue": 0.0,
                "average_revenue_per_paid_member": 0.0
            }
    
    def _create_empty_response(self, club_id: str, club_name: str, club_name_based_id: str, page: int, page_size: int) -> MemberViewResponse:
        """Create empty response when no members are found"""
        pagination_info = {
            "current_page": page,
            "page_size": page_size,
            "total_items": 0,
            "total_pages": 0,
            "has_next": False,
            "has_previous": False,
            "items_on_current_page": 0
        }
        
        member_stats = {
            "total_members": 0,
            "trial_members": 0,
            "paid_members": 0,
            "active_members": 0,
            "inactive_members": 0,
            "total_revenue": 0.0,
            "average_revenue_per_paid_member": 0.0
        }
        
        return MemberViewResponse(
            success=True,
            message="No members found for this club",
            club_id=club_id,
            club_name=club_name,
            club_name_based_id=club_name_based_id,
            members=[],
            pagination=pagination_info,
            member_stats=member_stats
        )
