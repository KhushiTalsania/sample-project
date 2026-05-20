"""
Captain Members Service

This service handles retrieving all members across Captain's created clubs
with pagination, filtering, and search capabilities.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List
from bson import ObjectId

from core.database.collections import get_collections
from core.utils.response_utils import create_response

logger = logging.getLogger(__name__)

def _safe_isoformat(value):
    """Safely convert datetime to ISO format string"""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)

class CaptainMembersService:
    """Service for managing Captain's club members"""
    
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
    
    async def get_captain_members(
        self, 
        captain_id: str,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        status_filter: str = "all",
        plan_type: str = "all",
        club_filter: str = "all",
        role_filter: str = "Member",
        moderator_type_filter: str = "all",
        sort_by: str = "newest"
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get all members or moderators across Captain's created clubs with filtering and pagination
        
        Args:
            captain_id: ID of the Captain
            page: Page number (starts from 1)
            page_size: Number of items per page
            search: Search term for email, club name, or member/moderator name
            status_filter: Filter by status (all, active, inactive)
            plan_type: Filter by plan type (all, trial, paid) - only for members
            club_filter: Filter by specific club (club_id or 'all')
            role_filter: Filter by role (Member, Moderator)
            moderator_type_filter: Filter by moderator type (all, free, paid) - only for moderators
            sort_by: Sort order (newest, oldest, name_az, name_za, club_name)
        
        Returns:
            Tuple of (success, data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            
            # Validate captain_id
            try:
                captain_object_id = ObjectId(captain_id)
            except Exception:
                return False, None, "Invalid captain ID format"
            
            logger.info(f"Getting members for Captain: {captain_id}")
            
            # First, get all clubs created by this captain
            captain_clubs = await self._get_captain_clubs(captain_id, role_filter)
            if not captain_clubs:
                return True, {
                    "members": [],
                    "pagination": {
                        "current_page": page,
                        "page_size": page_size,
                        "total_pages": 0,
                        "total_members": 0,
                        "has_next_page": False,
                        "has_previous_page": False
                    },
                    "summary": {
                        "total_clubs": 0,
                        "total_members": 0,
                        "active_members": 0,
                        "inactive_members": 0,
                        "trial_members": 0,
                        "paid_members": 0
                    }
                }, None
            
            # Apply club filter if specified
            if club_filter != "all":
                # Support both ObjectId and name_based_id for club filtering
                filtered_clubs = []
                for club in captain_clubs:
                    # Check if club_filter matches ObjectId
                    if str(club["_id"]) == club_filter:
                        filtered_clubs.append(club)
                    # Check if club_filter matches name_based_id
                    elif club.get("name_based_id") == club_filter:
                        filtered_clubs.append(club)
                
                captain_clubs = filtered_clubs
                if not captain_clubs:
                    return False, None, f"Club '{club_filter}' not found or not owned by this captain"
            
            logger.info(f"Found {len(captain_clubs)} clubs for captain")
            
            # Get data based on role filter
            if role_filter.lower() == "moderator":
                all_data = await self._get_all_club_moderators(captain_clubs)
                logger.info(f"Found {len(all_data)} total moderators across all clubs")
                # Apply filters for moderators
                filtered_data = self._apply_moderator_filters(all_data, search, status_filter, club_filter, moderator_type_filter)
                logger.info(f"After filtering: {len(filtered_data)} moderators")
            else:  # Default to Member
                all_data = await self._get_all_club_members(captain_clubs)
                logger.info(f"Found {len(all_data)} total members across all clubs")
                # Apply filters for members
                filtered_data = self._apply_filters(all_data, search, status_filter, plan_type)
                logger.info(f"After filtering: {len(filtered_data)} members")
            
            # Apply sorting
            sorted_data = self._apply_sorting(filtered_data, sort_by)
            
            # Calculate pagination
            total_items = len(sorted_data)
            total_pages = (total_items + page_size - 1) // page_size
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_data = sorted_data[start_index:end_index]
            
            # Generate summary statistics
            summary = self._generate_summary(all_data, role_filter)
            
            # Prepare response data
            response_data = {
                "members" if role_filter.lower() != "moderator" else "moderators": paginated_data,
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    f"total_{'members' if role_filter.lower() != 'moderator' else 'moderators'}": total_items,
                    "has_next_page": page < total_pages,
                    "has_previous_page": page > 1
                },
                "summary": summary,
                "filters_applied": {
                    "search": search,
                    "status_filter": status_filter,
                    "plan_type": plan_type,
                    "club_filter": club_filter,
                    "role_filter": role_filter,
                    "moderator_type_filter": moderator_type_filter,
                    "sort_by": sort_by
                }
            }
            
            logger.info(f"Successfully retrieved {len(paginated_data)} {role_filter.lower()}s for page {page}")
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error getting captain members: {e}")
            return False, None, f"Failed to retrieve captain members: {str(e)}"
    
    async def _get_captain_clubs(self, captain_id: str, role_filter: str = "Member") -> List[Dict[str, Any]]:
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
                clubs_cursor = self._clubs_collection.find(query)
                query_clubs = await clubs_cursor.to_list(length=None)
                if query_clubs:
                    logger.info(f"Found {len(query_clubs)} clubs with query: {query}")
                    clubs.extend(query_clubs)
                    break
            
            # If no clubs found with specific queries, try to get all clubs and filter
            if not clubs:
                logger.info("No clubs found with specific queries, trying to get all clubs...")
                all_clubs_cursor = self._clubs_collection.find({})
                all_clubs = await all_clubs_cursor.to_list(length=None)
                logger.info(f"Total clubs in database: {len(all_clubs)}")
                
                # Log the structure of first few clubs to understand the schema
                for i, club in enumerate(all_clubs[:3]):
                    logger.info(f"Club {i} structure: {list(club.keys())}")
                    if 'captain_id' in club:
                        logger.info(f"Club {i} captain_id: {club['captain_id']} (type: {type(club['captain_id'])})")
                    if 'created_by' in club:
                        logger.info(f"Club {i} created_by: {club['created_by']} (type: {type(club['created_by'])})")
            
            # Filter clubs based on role_filter
            if role_filter == "Moderator":
                # For moderators, only return approved clubs
                approved_clubs = [club for club in clubs if club.get("status") == "approved"]
                logger.info(f"Filtered to {len(approved_clubs)} approved clubs for moderator filter")
                return approved_clubs
            else:
                # For members, return all clubs
                logger.info(f"Found {len(clubs)} clubs for captain {captain_id}")
                return clubs
            
        except Exception as e:
            logger.error(f"Error getting captain clubs: {e}")
            return []
    
    async def _get_all_club_members(self, clubs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get all members from the given clubs"""
        all_members = []
        
        try:
            for club in clubs:
                club_id = str(club["_id"])
                club_name = club.get("name", "Unknown Club")
                club_name_based_id = club.get("name_based_id", "unknown-club")
                
                logger.info(f"Processing club: {club_name} ({club_id})")
                logger.info(f"Club keys: {list(club.keys())}")
                
                # Get trial members
                trial_members = club.get("members", [])
                logger.info(f"Found {len(trial_members)} trial members in club {club_name}")
                
                # Debug: Log first trial member structure if exists
                if trial_members:
                    logger.info(f"First trial member structure: {list(trial_members[0].keys()) if trial_members else 'No members'}")
                for member in trial_members:
                    member_data = await self._get_member_details(member.get("user_id"))
                    if member_data:
                        member_item = {
                            "member_id": member.get("user_id"),
                            "member_name": member_data.get("full_name", "Unknown"),
                            "member_email": member_data.get("email", ""),
                            "member_phone": member_data.get("phone"),
                            "member_avatar_url": member_data.get("avatar_url"),
                            "club_id": club_id,
                            "club_name": club_name,
                            "club_name_based_id": club_name_based_id,
                            "membership_type": "trial",
                            "membership_status": member.get("membership_status", "active"),
                            "join_date": _safe_isoformat(member.get("join_date")) or "",
                            "start_date": _safe_isoformat(member.get("start_date")),
                            "end_date": _safe_isoformat(member.get("end_date")),
                            "amount_paid": None,  # Trial members don't pay
                            "pricing_plan": None,
                            "is_active": member.get("is_active", True),
                            "is_temporarily_deleted": member.get("is_temporarily_deleted", False),
                            "created_at": _safe_isoformat(member.get("created_at")) or "",
                            "updated_at": _safe_isoformat(member.get("updated_at")) or ""
                        }
                        all_members.append(member_item)
                
                # Get paid members
                paid_members = club.get("paid_members", [])
                logger.info(f"Found {len(paid_members)} paid members in club {club_name}")
                
                # Debug: Log first paid member structure if exists
                if paid_members:
                    logger.info(f"First paid member structure: {list(paid_members[0].keys()) if paid_members else 'No members'}")
                for member in paid_members:
                    member_data = await self._get_member_details(member.get("user_id"))
                    if member_data:
                        member_item = {
                            "member_id": member.get("user_id"),
                            "member_name": member_data.get("full_name", "Unknown"),
                            "member_email": member_data.get("email", ""),
                            "member_phone": member_data.get("phone"),
                            "member_avatar_url": member_data.get("avatar_url"),
                            "club_id": club_id,
                            "club_name": club_name,
                            "club_name_based_id": club_name_based_id,
                            "membership_type": "paid",
                            "membership_status": member.get("membership_status", "active"),
                            "join_date": _safe_isoformat(member.get("join_date")) or "",
                            "start_date": _safe_isoformat(member.get("start_date")),
                            "end_date": _safe_isoformat(member.get("end_date")),
                            "amount_paid": member.get("amount_paid"),
                            "pricing_plan": member.get("pricing_plan"),
                            "is_active": member.get("is_active", True),
                            "is_temporarily_deleted": member.get("is_temporarily_deleted", False),
                            "created_at": _safe_isoformat(member.get("created_at")) or "",
                            "updated_at": _safe_isoformat(member.get("updated_at")) or ""
                        }
                        all_members.append(member_item)
                
                logger.info(f"Club {club_name}: {len(trial_members)} trial members, {len(paid_members)} paid members")
            
            return all_members
            
        except Exception as e:
            logger.error(f"Error getting club members: {e}")
            return []
    
    async def _get_member_details(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get member details from users collection"""
        try:
            if not user_id:
                return None
            
            user_object_id = ObjectId(user_id)
            user = await self._users_collection.find_one({"_id": user_object_id})
            
            if user:
                return {
                    "full_name": user.get("full_name", ""),
                    "email": user.get("email", ""),
                    "phone": user.get("phone"),
                    "avatar_url": user.get("avatar_url")
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting member details for {user_id}: {e}")
            return None
    
    def _apply_filters(self, members: List[Dict[str, Any]], search: Optional[str], status_filter: str, plan_type: str) -> List[Dict[str, Any]]:
        """Apply search and filter criteria to members list"""
        filtered_members = members.copy()
        
        # Apply search filter
        if search and search.strip():
            search_term = search.strip().lower()
            filtered_members = [
                member for member in filtered_members
                if (
                    search_term in member.get("member_email", "").lower() or
                    search_term in member.get("member_name", "").lower() or
                    search_term in member.get("club_name", "").lower()
                )
            ]
        
        # Apply status filter
        if status_filter != "all":
            filtered_members = [
                member for member in filtered_members
                if member.get("membership_status", "").lower() == status_filter.lower()
            ]
        
        # Apply plan type filter
        if plan_type != "all":
            filtered_members = [
                member for member in filtered_members
                if member.get("membership_type", "").lower() == plan_type.lower()
            ]
        
        return filtered_members
    
    def _apply_sorting(self, members: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
        """Apply sorting to members list"""
        if sort_by == "newest":
            return sorted(members, key=lambda x: x.get("join_date", ""), reverse=True)
        elif sort_by == "oldest":
            return sorted(members, key=lambda x: x.get("join_date", ""), reverse=False)
        elif sort_by == "name_az":
            return sorted(members, key=lambda x: x.get("member_name", "").lower())
        elif sort_by == "name_za":
            return sorted(members, key=lambda x: x.get("member_name", "").lower(), reverse=True)
        elif sort_by == "club_name":
            return sorted(members, key=lambda x: x.get("club_name", "").lower())
        else:
            return members
    
    def _generate_member_summary(self, members: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate summary statistics for all members"""
        total_members = len(members)
        active_members = len([m for m in members if m.get("membership_status", "").lower() == "active"])
        inactive_members = len([m for m in members if m.get("membership_status", "").lower() == "inactive"])
        trial_members = len([m for m in members if m.get("membership_type", "").lower() == "trial"])
        paid_members = len([m for m in members if m.get("membership_type", "").lower() == "paid"])
        
        # Get unique club count
        unique_clubs = len(set(m.get("club_id", "") for m in members))
        
        return {
            "total_clubs": unique_clubs,
            "total_members": total_members,
            "active_members": active_members,
            "inactive_members": inactive_members,
            "trial_members": trial_members,
            "paid_members": paid_members
        }
    
    async def _get_all_club_moderators(self, clubs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get all moderators from the given clubs"""
        all_moderators = []
        
        try:
            for club in clubs:
                club_id = str(club["_id"])
                club_name = club.get("name", "Unknown Club")
                club_name_based_id = club.get("name_based_id", "unknown-club")
                
                logger.info(f"Processing moderators for club: {club_name} ({club_id})")
                
                # Get moderators from detailed_moderators array
                detailed_moderators = club.get("detailed_moderators", [])
                logger.info(f"Found {len(detailed_moderators)} moderators in club {club_name}")
                
                for moderator in detailed_moderators:
                    moderator_item = {
                        "moderator_id": moderator.get("user_id"),
                        "moderator_name": moderator.get("full_name", "Unknown"),
                        "moderator_email": moderator.get("email", ""),
                        "club_id": club_id,
                        "club_name": club_name,
                        "club_name_based_id": club_name_based_id,
                        "type_of_moderator": moderator.get("type_of_moderator", "free"),
                        "status": moderator.get("status", "active"),
                        "price": moderator.get("price", 0),
                        "invited_at": _safe_isoformat(moderator.get("invited_at")) or "",
                        "responded_at": _safe_isoformat(moderator.get("responded_at")),
                        "response": moderator.get("response"),
                        "is_active": moderator.get("status", "active").lower() == "active",
                        "is_temporarily_deleted": moderator.get("is_temporarily_deleted", False)
                    }
                    all_moderators.append(moderator_item)
                
                logger.info(f"Club {club_name}: {len(detailed_moderators)} moderators")
            
            return all_moderators
        except Exception as e:
            logger.error(f"Error getting all club moderators: {e}")
            return []
    
    def _apply_moderator_filters(
        self, 
        moderators: List[Dict[str, Any]], 
        search: Optional[str], 
        status_filter: str,
        club_filter: str,
        moderator_type_filter: str
    ) -> List[Dict[str, Any]]:
        """Apply filters to moderators list"""
        filtered = moderators
        
        # Search filter
        if search:
            search_lower = search.lower()
            filtered = [
                m for m in filtered
                if (search_lower in m.get("moderator_email", "").lower() or
                    search_lower in m.get("moderator_name", "").lower() or
                    search_lower in m.get("club_name", "").lower())
            ]
        
        # Status filter
        if status_filter != "all":
            filtered = [
                m for m in filtered
                if m.get("status", "").lower() == status_filter.lower()
            ]
        
        # Club filter (already applied at club level, but double-check)
        if club_filter != "all":
            filtered = [
                m for m in filtered
                if m.get("club_id") == club_filter
            ]
        
        # Moderator type filter
        if moderator_type_filter != "all":
            filtered = [
                m for m in filtered
                if m.get("type_of_moderator", "").lower() == moderator_type_filter.lower()
            ]
        
        return filtered
    
    def _generate_summary(self, data: List[Dict[str, Any]], role_filter: str = "Member") -> Dict[str, Any]:
        """Generate summary statistics for members or moderators"""
        if not data:
            return {
                "total_clubs": 0,
                "total_members": 0,
                "active_members": 0,
                "inactive_members": 0,
                "trial_members": 0,
                "paid_members": 0
            }
        
        if role_filter.lower() == "moderator":
            # Summary for moderators
            total_moderators = len(data)
            active_moderators = len([m for m in data if m.get("status", "").lower() == "active"])
            inactive_moderators = len([m for m in data if m.get("status", "").lower() == "inactive"])
            free_moderators = len([m for m in data if m.get("type_of_moderator", "").lower() == "free"])
            paid_moderators = len([m for m in data if m.get("type_of_moderator", "").lower() == "paid"])
            
            # Get unique club count
            unique_clubs = len(set(m.get("club_id", "") for m in data))
            
            return {
                "total_clubs": unique_clubs,
                "total_moderators": total_moderators,
                "active_moderators": active_moderators,
                "inactive_moderators": inactive_moderators,
                "free_moderators": free_moderators,
                "paid_moderators": paid_moderators
            }
        else:
            # Summary for members (existing logic)
            return self._generate_member_summary(data)

# Global service instance with lazy initialization
_captain_members_service: CaptainMembersService = None

def get_captain_members_service() -> CaptainMembersService:
    """Get the global captain members service instance"""
    global _captain_members_service
    if _captain_members_service is None:
        _captain_members_service = CaptainMembersService()
    return _captain_members_service
