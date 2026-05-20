"""
Member Details API Routes

This module provides API endpoints for captains to view member details.
It includes comprehensive member information including joined clubs and payment history.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from typing import Optional

from services.auth.member_details_service import get_member_details_service
from services.auth.models import MemberDetailsResponse
from core.auth.auth_middleware import get_current_user
from core.utils.response_utils import create_response

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/member-details/{member_id}", response_model=MemberDetailsResponse)
async def get_member_details(
    member_id: str = Path(..., description="The member ID to get details for"),
    club_id: Optional[str] = Query(None, description="Specific club ID or name_based_id to get club information"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get comprehensive member details for a captain
    
    **Features:**
    - **Authentication Required**: Only authenticated users can access
    - **Role Validation**: Only users with role "Captain" can view member details
    - **Authorization**: Captains can only view members who have joined their clubs
    - **Comprehensive Data**: Includes member profile, joined clubs, payment history
    
    **Parameters:**
    - **member_id**: The ID of the member to get details for
    - **club_id**: Optional club ID or name_based_id to get specific club information
    
    **Response includes:**
    - Member profile information (name, email, phone, status)
    - Specific club information (if club_id provided)
    - Member's status in the specific club
    - List of clubs the member has joined (filtered by captain's clubs)
    - Membership details for each club (type, status, pricing, dates)
    - Payment information (amount paid, payment IDs)
    - Captain's clubs information
    - Summary statistics (counts, totals)
    
    **Business Logic:**
    - Only Captains can access member details
    - Captains can only view members who have joined their clubs
    - Data comes from users.clubs_joined array filtered by captain's clubs
    - Includes both trial and paid memberships
    - Shows plan changes and upcoming memberships
    - Provides comprehensive payment history
    
    **Example Usage:**
    ```
    GET /auth/member-details/68b963121a1911ad2e750488?club_id=new-test-club
    Authorization: Bearer <captain_jwt_token>
    ```
    """
    try:
        captain_id = current_user.get("user_id")
        captain_role = current_user.get("role")
        
        logger.info(f"Member details request from captain {captain_id} for member {member_id}")
        
        # Validate captain role
        if captain_role != "Captain":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Captains can view member details. Members and Moderators cannot access this feature."
            )
        
        # Get member details
        member_details_service = get_member_details_service()
        success, member_data, error_message = await member_details_service.get_member_details(
            member_id, captain_id, club_id
        )
        
        if not success:
            if "not found" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=error_message
                )
            elif "not authorized" in error_message.lower() or "no clubs" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=error_message
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_message or "Failed to retrieve member details"
                )
        
        logger.info(f"Successfully retrieved member details for member {member_id} by captain {captain_id}")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Member details retrieved successfully for {member_data.get('full_name', 'Unknown')}.",
            data=member_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_member_details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )
