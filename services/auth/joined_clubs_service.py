"""
Joined Clubs Service

This service handles retrieving clubs that a user has joined from the users.clubs_joined array.
It provides pagination, sorting, and filtering capabilities.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from core.database.collections import get_collections
from core.utils.response_utils import create_response
from services.auth.order_history_service import _get_stripe_receipt_url

logger = logging.getLogger(__name__)

def _safe_isoformat(value):
    """Safely convert datetime to ISO format string"""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)

class JoinedClubsService:
    """Service for managing joined clubs data"""
    
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
    
    async def get_joined_clubs(
        self, 
        user_id: str, 
        page: int = 1, 
        page_size: int = 10,
        sort_by: str = "join_date",
        sort_order: str = "desc",
        status_filter: str = "all"
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get clubs joined by a user with pagination and filtering
        
        Args:
            user_id: The user ID
            page: Page number (1-based)
            page_size: Number of items per page
            sort_by: Sort field (join_date, club_name, status)
            sort_order: Sort order (asc, desc)
            status_filter: Filter by status (all, active, inactive, upcoming)
        
        Returns:
            Tuple of (success, data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            
            # Validate parameters
            if sort_by not in ["join_date", "club_name", "status"]:
                return False, None, f"Invalid sort_by parameter. Must be one of: join_date, club_name, status"
            
            if sort_order not in ["asc", "desc"]:
                return False, None, f"Invalid sort_order parameter. Must be one of: asc, desc"
            
            if status_filter not in ["all", "active", "inactive", "upcoming"]:
                return False, None, f"Invalid status_filter parameter. Must be one of: all, active, inactive, upcoming"
            
            # Get user data
            user = await self._users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False, None, "User not found"
            
            # Validate user role
            user_role = user.get("role")
            if user_role != "Member":
                return False, None, "Only Members can view their joined clubs"
            
            # Get clubs_joined array from user document
            clubs_joined = user.get("clubs_joined", [])
            logger.info(f"Found {len(clubs_joined)} clubs joined for user {user_id}")
            
            if not clubs_joined:
                # Return empty result with pagination info
                return True, {
                    "user_id": user_id,
                    "user_name": user.get("full_name", "Unknown"),
                    "pagination": {
                        "current_page": page,
                        "page_size": page_size,
                        "total_pages": 0,
                        "total_clubs": 0,
                        "has_next_page": False,
                        "has_previous_page": False
                    },
                "total_clubs": 0,
                "active_clubs": 0,
                "inactive_clubs": 0,
                "upcoming_clubs": 0,
                "trial_clubs": 0,
                "paid_clubs": 0,
                    "clubs": [],
                    "retrieved_at": datetime.now(timezone.utc).isoformat()
                }, None
            
            # Process clubs_joined array and get club details
            joined_clubs_data = []
            active_count = 0
            inactive_count = 0
            upcoming_count = 0
            trial_count = 0
            paid_count = 0
            
            for club_joined in clubs_joined:
                club_id = str(club_joined.get("club_id"))
                membership_status = club_joined.get("membership_status", "inactive")
                membership_type = club_joined.get("membership_type", "trial")
                is_active = club_joined.get("is_active", False)
                
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
                
                # Get club details from clubs collection
                club_details = await self._clubs_collection.find_one({"_id": ObjectId(club_id)})
                
                if club_details:
                    # Convert amount from cents to dollars if needed
                    amount_paid = club_joined.get("amount_paid", 0)
                    if amount_paid and amount_paid > 100:  # Assume amounts > 100 are in cents
                        amount_paid = amount_paid 
                    
                    # Get receipt URL for paid memberships
                    receipt_url = None
                    payment_id = club_joined.get("payment_id")
                    if payment_id and membership_type == "paid":
                        try:
                            receipt_url = _get_stripe_receipt_url(payment_id)
                        except Exception as e:
                            logger.warning(f"Failed to get receipt URL for payment_id {payment_id}: {e}")
                            receipt_url = None
                    
                    # Check if club has multiple pricing plans
                    pricing_plans = club_details.get("pricing_plans", [])
                    is_multiple_plan = len(pricing_plans) > 1 if pricing_plans else False
                    
                    club_data = {
                        "club_id": club_id,
                        "club_name": club_details.get("name", "Unknown Club"),
                        "name_based_id": club_details.get("name_based_id", ""),
                        "description": club_details.get("description"),
                        "club_status": club_details.get("status", "unknown"),
                        "membership_type": membership_type,
                        "membership_status": membership_status,
                        "join_date": _safe_isoformat(club_joined.get("join_date")) or "",
                        "start_date": _safe_isoformat(club_joined.get("start_date")),
                        "end_date": _safe_isoformat(club_joined.get("end_date")),
                        "pricing_plan": club_joined.get("pricing_plan"),
                        "amount_paid": amount_paid,
                        "payment_id": payment_id,
                        "receipt_url": receipt_url,
                        "is_multiple_plan": is_multiple_plan,  # ✅ New field
                        "is_active": is_active,
                        "created_at": _safe_isoformat(club_joined.get("created_at")) or "",
                        "updated_at": _safe_isoformat(club_joined.get("updated_at")) or ""
                    }
                    joined_clubs_data.append(club_data)
                else:
                    logger.warning(f"Club not found for club_id: {club_id}")
            
            # Apply status filter
            if status_filter == "active":
                joined_clubs_data = [club for club in joined_clubs_data if club["membership_status"] == "active"]
            elif status_filter == "inactive":
                joined_clubs_data = [club for club in joined_clubs_data if club["membership_status"] == "inactive"]
            elif status_filter == "upcoming":
                joined_clubs_data = [club for club in joined_clubs_data if club["membership_status"] == "upcoming"]
            
            # Sort the data
            reverse_sort = sort_order == "desc"
            
            if sort_by == "join_date":
                joined_clubs_data.sort(key=lambda x: x.get("join_date", ""), reverse=reverse_sort)
            elif sort_by == "club_name":
                joined_clubs_data.sort(key=lambda x: x.get("club_name", "").lower(), reverse=reverse_sort)
            elif sort_by == "status":
                joined_clubs_data.sort(key=lambda x: x.get("membership_status", ""), reverse=reverse_sort)
            
            # Apply pagination
            total_clubs = len(joined_clubs_data)
            total_pages = (total_clubs + page_size - 1) // page_size  # Ceiling division
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_clubs = joined_clubs_data[start_index:end_index]
            
            # Prepare response data
            response_data = {
                "user_id": user_id,
                "user_name": user.get("full_name", "Unknown"),
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "total_clubs": total_clubs,
                    "has_next_page": page < total_pages,
                    "has_previous_page": page > 1
                },
                "total_clubs": total_clubs,
                "active_clubs": active_count,
                "inactive_clubs": inactive_count,
                "upcoming_clubs": upcoming_count,
                "trial_clubs": trial_count,
                "paid_clubs": paid_count,
                "clubs": paginated_clubs,
                "retrieved_at": datetime.now(timezone.utc).isoformat()
            }
            
            logger.info(f"Retrieved {len(paginated_clubs)} clubs for user {user_id} (page {page}/{total_pages})")
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error getting joined clubs for user {user_id}: {e}")
            return False, None, f"Internal server error: {str(e)}"

# Global service instance with lazy initialization
_joined_clubs_service: JoinedClubsService = None

def get_joined_clubs_service() -> JoinedClubsService:
    """Get the global joined clubs service instance"""
    global _joined_clubs_service
    if _joined_clubs_service is None:
        _joined_clubs_service = JoinedClubsService()
    return _joined_clubs_service
