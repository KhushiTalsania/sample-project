"""
Member Details Service

This service handles retrieving comprehensive member details for captains.
It provides information about a member's joined clubs, payment history, and membership details.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from core.database.collections import get_collections

logger = logging.getLogger(__name__)

def _safe_isoformat(value):
    """Safely convert datetime to ISO format string"""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)

class MemberDetailsService:
    """Service for managing member details data"""
    
    def __init__(self):
        self._collections = None
        self._users_collection = None
        self._clubs_collection = None
    
    def _ensure_collections_initialized(self):
        """Lazy initialization of collections to prevent circular imports"""
        if self._collections is None:
            self._collections = get_collections()
            self._users_collection = self._collections.get_users_collection()
            self._clubs_collection = self._collections.get_clubs_collection()
    
    async def get_member_details(
        self, 
        member_id: str,
        captain_id: str,
        club_id: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get comprehensive member details for a captain
        
        Args:
            member_id: The member ID to get details for
            captain_id: The captain ID requesting the details
            club_id: Optional specific club ID or name_based_id to get club information
        
        Returns:
            Tuple of (success, data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            
            # Validate member ID format
            try:
                member_object_id = ObjectId(member_id)
            except Exception:
                return False, None, "Invalid member ID format"
            
            # Validate captain ID format
            try:
                captain_object_id = ObjectId(captain_id)
            except Exception:
                return False, None, "Invalid captain ID format"
            
            # Get member data
            member = await self._users_collection.find_one({"_id": member_object_id})
            if not member:
                return False, None, "Member not found"
            
            # Verify member role
            if member.get("role") != "Member":
                return False, None, "User is not a member"
            
            # Get captain's clubs to filter relevant memberships
            captain_clubs = await self._get_captain_clubs(captain_id)
            
            if not captain_clubs:
                return False, None, "Captain has no clubs or not authorized to view this member"
            
            # Create a set of captain's club IDs for filtering
            captain_club_ids = {str(club["_id"]) for club in captain_clubs}
            
            # Handle specific club information if club_id provided
            specific_club_info = None
            member_club_status = None
            
            if club_id:
                specific_club = await self._find_club_by_id_or_name(captain_clubs, club_id)
                if specific_club:
                    # Check if member is in this specific club
                    member_in_club = await self._check_member_in_club(member, str(specific_club["_id"]))
                    if member_in_club:
                        specific_club_info = {
                            "club_id": str(specific_club["_id"]),
                            "club_name": specific_club.get("name", "Unknown"),
                            "club_name_based_id": specific_club.get("name_based_id", ""),
                            "club_status": specific_club.get("status", "pending"),
                            "membership_status": member_in_club.get("membership_status", "unknown"),
                            "membership_type": member_in_club.get("membership_type", "unknown"),
                            "pricing_plan": member_in_club.get("pricing_plan", "unknown"),
                            "join_date": _safe_isoformat(member_in_club.get("join_date")),
                            "end_date": _safe_isoformat(member_in_club.get("end_date")),
                            "amount_paid": member_in_club.get("amount_paid"),
                            "payment_id": member_in_club.get("payment_id"),
                            "created_at": _safe_isoformat(specific_club.get("created_at")),
                            "member_count": len(specific_club.get("members", [])) + len(specific_club.get("paid_members", [])),
                            "paid_member_count": len(specific_club.get("paid_members", [])),
                        }
                        member_club_status = member_in_club.get("membership_status", "unknown")
            
            # Get member's joined clubs
            clubs_joined = member.get("clubs_joined", [])
            
            # Filter clubs that belong to this captain
            relevant_clubs = []
            for club_joined in clubs_joined:
                club_id = str(club_joined.get("club_id", ""))
                if club_id in captain_club_ids:
                    relevant_clubs.append(club_joined)
            
            # Process joined clubs data
            joined_clubs_data = []
            active_count = 0
            inactive_count = 0
            upcoming_count = 0
            trial_count = 0
            paid_count = 0
            total_amount_paid = 0.0
            
            for club_joined in relevant_clubs:
                club_id = str(club_joined.get("club_id"))
                membership_status = club_joined.get("membership_status", "inactive")
                membership_type = club_joined.get("membership_type", "trial")
                
                # Count statistics
                if membership_status == "active":
                    active_count += 1
                elif membership_status == "upcoming":
                    upcoming_count += 1
                else:
                    inactive_count += 1
                
                if membership_type == "trial":
                    trial_count += 1
                else:
                    paid_count += 1
                
                # Add to total amount paid
                amount_paid = club_joined.get("amount_paid", 0)
                if amount_paid:
                    total_amount_paid += float(amount_paid)
                
                # Get club details
                club_details = await self._clubs_collection.find_one({"_id": ObjectId(club_id)})
                
                if club_details:
                    club_data = {
                        "club_id": club_id,
                        "club_name": club_joined.get("club_name", club_details.get("name", "Unknown")),
                        "club_name_based_id": club_joined.get("club_name_based_id", club_details.get("name_based_id", "")),
                        "captain_name": club_joined.get("captain_name", club_details.get("captain_name", "")),
                        "membership_type": membership_type,
                        "membership_status": membership_status,
                        "pricing_plan": club_joined.get("pricing_plan", "trial"),
                        "join_date": _safe_isoformat(club_joined.get("join_date")),
                        "end_date": _safe_isoformat(club_joined.get("end_date")),
                        "amount_paid": float(club_joined.get("amount_paid", 0)) if club_joined.get("amount_paid") else None,
                        "payment_id": club_joined.get("payment_id"),
                        "is_active": club_joined.get("is_active", True),
                        "is_trial": club_joined.get("is_trial", membership_type == "trial"),
                        "created_at": _safe_isoformat(club_joined.get("created_at")),
                        "updated_at": _safe_isoformat(club_joined.get("updated_at")),
                        "status": club_joined.get("status"),
                        "previous_plan": club_joined.get("previous_plan"),
                        "is_upgraded": club_joined.get("is_upgraded")
                    }
                    joined_clubs_data.append(club_data)
            
            # Process captain's clubs
            captain_clubs_data = []
            for club in captain_clubs:
                # Count members in this club
                members = club.get("members", [])
                paid_members = club.get("paid_members", [])
                member_count = len(members) + len(paid_members)
                paid_member_count = len(paid_members)
                
                club_data = {
                    "club_id": str(club["_id"]),
                    "club_name": club.get("name", "Unknown"),
                    "club_name_based_id": club.get("name_based_id", ""),
                    "club_status": club.get("status", "pending"),
                    "created_at": _safe_isoformat(club.get("created_at")),
                    "member_count": member_count,
                    "paid_member_count": paid_member_count
                }
                captain_clubs_data.append(club_data)
            
            # Prepare response data
            response_data = {
                "member_id": member_id,
                "full_name": member.get("full_name", "Unknown"),
                "email": member.get("email", ""),
                "phone": member.get("phone", ""),
                "user_status": member.get("status", "active"),
                "membership_status": member.get("membership_status", "active"),
                "profile_created_at": _safe_isoformat(member.get("created_at")),
                
                "club_info": specific_club_info,
                "member_club_status": member_club_status,
                
                "joined_clubs": joined_clubs_data,
                # "total_clubs_joined": len(joined_clubs_data),
                # "active_clubs_count": active_count,
                # "inactive_clubs_count": inactive_count,
                # "upcoming_clubs_count": upcoming_count,
                # "trial_clubs_count": trial_count,
                # "paid_clubs_count": paid_count,
                
                # "captain_clubs": captain_clubs_data,
                # "total_captain_clubs": len(captain_clubs_data),
                
                # "total_amount_paid": round(total_amount_paid, 2),
                # "total_payments_count": paid_count,
                
                "retrieved_at": datetime.now(timezone.utc).isoformat()
            }
            
            logger.info(f"Retrieved member details for member {member_id} by captain {captain_id}: {len(joined_clubs_data)} relevant clubs")
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error getting member details for member {member_id}: {e}")
            return False, None, f"Internal server error: {str(e)}"
    
    async def _get_captain_clubs(self, captain_id: str) -> List[Dict[str, Any]]:
        """Get all clubs created by the captain"""
        try:
            captain_object_id = ObjectId(captain_id)
            
            logger.info(f"Searching for clubs with captain_id: {captain_id} (ObjectId: {captain_object_id})")
            
            # Try different possible field names for captain identification
            possible_queries = [
                {"captain_id": captain_object_id},
                {"captain_id": captain_id},  # Try as string
                {"created_by": captain_object_id},
                {"created_by": captain_id},
                {"owner_id": captain_object_id},
                {"owner_id": captain_id},
                {"user_id": captain_object_id},
                {"user_id": captain_id}
            ]
            
            clubs = []
            for query in possible_queries:
                logger.info(f"Trying query: {query}")
                found_clubs = await self._clubs_collection.find(query).to_list(length=None)
                if found_clubs:
                    clubs.extend(found_clubs)
                    logger.info(f"Found {len(found_clubs)} clubs with query: {query}")
                    break
            
            # If no clubs found with any query, try to get all clubs to debug
            if not clubs:
                logger.warning("No clubs found with any captain identification query")
                all_clubs = await self._clubs_collection.find({}).to_list(length=10)
                logger.info(f"Total clubs in database: {len(all_clubs)}")
                
                # Log the structure of first few clubs to understand the schema
                for i, club in enumerate(all_clubs[:3]):
                    logger.info(f"Club {i} structure: {list(club.keys())}")
                    if 'captain_id' in club:
                        logger.info(f"Club {i} captain_id: {club['captain_id']} (type: {type(club['captain_id'])})")
                    if 'created_by' in club:
                        logger.info(f"Club {i} created_by: {club['created_by']} (type: {type(club['created_by'])})")
            
            logger.info(f"Found {len(clubs)} clubs for captain {captain_id}")
            return clubs
            
        except Exception as e:
            logger.error(f"Error getting captain clubs: {e}")
            return []
    
    async def _find_club_by_id_or_name(self, captain_clubs: List[Dict], club_id: str) -> Optional[Dict]:
        """Find a club by ID or name_based_id"""
        try:
            # First try to find by ObjectId
            try:
                club_object_id = ObjectId(club_id)
                for club in captain_clubs:
                    if club["_id"] == club_object_id:
                        return club
            except Exception:
                pass  # Not a valid ObjectId, try name_based_id
            
            # Try to find by name_based_id
            for club in captain_clubs:
                if club.get("name_based_id") == club_id:
                    return club
            
            logger.warning(f"Club not found with ID or name: {club_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding club: {e}")
            return None
    
    async def _check_member_in_club(self, member: Dict, club_id: str) -> Optional[Dict]:
        """Check if member is in a specific club and return membership details"""
        try:
            clubs_joined = member.get("clubs_joined", [])
            for club_joined in clubs_joined:
                if str(club_joined.get("club_id", "")) == club_id:
                    return club_joined
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking member in club: {e}")
            return None

# Global service instance with lazy initialization
_member_details_service: MemberDetailsService = None

def get_member_details_service() -> MemberDetailsService:
    """Get the global member details service instance"""
    global _member_details_service
    if _member_details_service is None:
        _member_details_service = MemberDetailsService()
    return _member_details_service
