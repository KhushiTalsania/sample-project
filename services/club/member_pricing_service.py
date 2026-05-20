"""
Member Pricing Service

This service handles fetching pricing details for clubs that members have joined.
It provides pricing information including Stripe product and price IDs.
"""

import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from bson import ObjectId

from .db import get_club_collection, get_user_collection
from .models import MemberPricingRequest, MemberPricingResponse, PricingPlanDetails
from .id_utils import is_valid_name_based_id

# Configure logging
logger = logging.getLogger(__name__)

class MemberPricingService:
    """Service for fetching member pricing details"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
    
    async def get_public_pricing(self, request: MemberPricingRequest) -> Tuple[bool, Optional[MemberPricingResponse], str]:
        """
        Get pricing details for any club (public access)
        
        Args:
            request: MemberPricingRequest with club_id and frequency
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"Getting public pricing details for club: {request.club_id}, frequency: {request.frequency}")
            
            # Step 1: Find the club
            club = await self._find_club_by_id(request.club_id)
            if not club:
                return False, None, "Club not found"
            
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            club_name_based_id = club.get("name_based_id", "")
            
            # Step 2: Get pricing plans from the club
            pricing_plans = club.get("pricing_plans", [])
            if not pricing_plans:
                return False, None, "No pricing plans available for this club"
            
            # Step 3: Find the specific pricing plan for the requested frequency
            requested_plan = None
            all_plans = []
            
            for plan in pricing_plans:
                plan_details = PricingPlanDetails(
                    frequency=plan.get("frequency", ""),
                    price=plan.get("price", 0.0),
                    currency=plan.get("currency", "USD"),
                    stripe_product_id=plan.get("stripe_product_id", ""),
                    stripe_price_id=plan.get("stripe_price_id", ""),
                    created_at=plan.get("created_at", datetime.utcnow()),
                    updated_at=plan.get("updated_at", datetime.utcnow())
                )
                all_plans.append(plan_details)
                
                # Check if this is the requested frequency
                if plan.get("frequency", "").lower() == request.frequency.lower():
                    requested_plan = plan_details
            
            # Step 4: Validate frequency
            valid_frequencies = ["monthly", "quarterly", "yearly","lifetime","daily","weekly"]
            if request.frequency.lower() not in valid_frequencies:
                return False, None, f"Invalid frequency. Valid options are: {', '.join(valid_frequencies)}"
            
            if not requested_plan:
                return False, None, f"No pricing plan found for frequency: {request.frequency}"
            
            # Step 5: Create response (no member-specific data for public access)
            response = MemberPricingResponse(
                success=True,
                message="Pricing details retrieved successfully",
                club_id=club_id,
                logo_url=club.get("logo_url"),  # Add club logo URL
                club_name=club_name,
                club_name_based_id=club_name_based_id,
                member_type="public",  # Public access
                current_frequency="public",  # Public access
                pricing_plan=requested_plan,
                all_pricing_plans=all_plans,
                member_join_date=None,  # Not available for public access
                member_end_date=None  # Not available for public access
            )
            
            logger.info(f"Successfully retrieved public pricing details for club {club_name}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"Error in get_public_pricing: {e}")
            import traceback
            traceback.print_exc()
            return False, None, f"Internal server error: {str(e)}"

    async def get_member_pricing(self, request: MemberPricingRequest, member_id: str) -> Tuple[bool, Optional[MemberPricingResponse], str]:
        """
        Get pricing details for a club that the member has joined
        
        Args:
            request: MemberPricingRequest with club_id and frequency
            member_id: ID of the member requesting the data
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"Getting pricing details for club: {request.club_id}, member: {member_id}, frequency: {request.frequency}")
            
            # Step 1: Find the club
            club = await self._find_club_by_id(request.club_id)
            if not club:
                return False, None, "Club not found"
            
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            club_name_based_id = club.get("name_based_id", "")
            
            # Step 2: Validate that the member has joined this club
            member_info = await self._validate_member_access(club, member_id)
            if not member_info:
                return False, None, "You are not a member of this club or don't have access to view pricing details"
            
            # Step 3: Get pricing plans from the club
            pricing_plans = club.get("pricing_plans", [])
            if not pricing_plans:
                return False, None, "No pricing plans available for this club"
            
            # Step 4: Find the specific pricing plan for the requested frequency
            requested_plan = None
            all_plans = []
            
            for plan in pricing_plans:
                plan_details = PricingPlanDetails(
                    frequency=plan.get("frequency", ""),
                    price=plan.get("price", 0.0),
                    currency=plan.get("currency", "USD"),
                    stripe_product_id=plan.get("stripe_product_id", ""),
                    stripe_price_id=plan.get("stripe_price_id", ""),
                    created_at=plan.get("created_at", datetime.utcnow()),
                    updated_at=plan.get("updated_at", datetime.utcnow())
                )
                all_plans.append(plan_details)
                
                # Check if this is the requested frequency
                if plan.get("frequency", "").lower() == request.frequency.lower():
                    requested_plan = plan_details
            
            # Step 5: Validate frequency
            valid_frequencies = ["monthly", "quarterly", "yearly"]
            if request.frequency.lower() not in valid_frequencies:
                return False, None, f"Invalid frequency. Valid options are: {', '.join(valid_frequencies)}"
            
            if not requested_plan:
                return False, None, f"No pricing plan found for frequency: {request.frequency}"
            
            # Step 6: Create response
            response = MemberPricingResponse(
                success=True,
                message="Pricing details retrieved successfully",
                club_id=club_id,
                logo_url=club.get("logo_url"),  # Add club logo URL
                club_name=club_name,
                club_name_based_id=club_name_based_id,
                member_type=member_info["member_type"],
                current_frequency=member_info["current_frequency"],
                pricing_plan=requested_plan,
                all_pricing_plans=all_plans,
                member_join_date=member_info["join_date"],
                member_end_date=member_info["end_date"]
            )
            
            logger.info(f"Successfully retrieved pricing details for member {member_id} in club {club_name}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"Error in get_member_pricing: {e}")
            import traceback
            traceback.print_exc()
            return False, None, f"Internal server error: {str(e)}"
    
    async def _find_club_by_id(self, club_id: str) -> Optional[Dict]:
        """Find club by ID or name_based_id"""
        try:
            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(club_id):
                logger.info(f"Searching by name_based_id: {club_id}")
                club = await self.club_collection.find_one({
                    "name_based_id": club_id
                })
            else:
                logger.info(f"Searching by ObjectId: {club_id}")
                try:
                    club_object_id = ObjectId(club_id)
                except Exception as e:
                    logger.error(f"Invalid ObjectId format: {club_id}, error: {e}")
                    return None
                
                club = await self.club_collection.find_one({
                    "_id": club_object_id
                })
            
            if club:
                logger.info(f"Found club: {club.get('name', 'Unknown')}")
            else:
                logger.warning(f"Club not found for club_id: {club_id}")
            
            return club
            
        except Exception as e:
            logger.error(f"Error finding club: {e}")
            return None
    
    async def _validate_member_access(self, club: Dict, member_id: str) -> Optional[Dict]:
        """Validate that the member has access to this club and get member info"""
        try:
            # Check trial members
            trial_members = club.get("members", [])
            for member in trial_members:
                if member.get("user_id") == member_id:
                    return {
                        "member_type": "trial",
                        "current_frequency": "trial",
                        "join_date": member.get("join_date"),
                        "end_date": member.get("end_date")
                    }
            
            # Check paid members
            paid_members = club.get("paid_members", [])
            for member in paid_members:
                if member.get("user_id") == member_id:
                    return {
                        "member_type": "paid",
                        "current_frequency": member.get("pricing_plan", "monthly"),
                        "join_date": member.get("join_date"),
                        "end_date": member.get("end_date")
                    }
            
            # If not found in club members, check user's clubs_joined array
            user = await self.user_collection.find_one({"_id": ObjectId(member_id)})
            if user:
                clubs_joined = user.get("clubs_joined", [])
                for club_info in clubs_joined:
                    if club_info.get("club_id") == str(club["_id"]):
                        return {
                            "member_type": club_info.get("membership_type", "trial"),
                            "current_frequency": club_info.get("pricing_plan", "trial"),
                            "join_date": club_info.get("join_date"),
                            "end_date": club_info.get("end_date")
                        }
            
            logger.warning(f"Member {member_id} not found in club {club.get('name', 'Unknown')}")
            return None
            
        except Exception as e:
            logger.error(f"Error validating member access: {e}")
            return None
