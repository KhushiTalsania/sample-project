"""
Joined Clubs API Routes

This module provides API endpoints for retrieving clubs that a user has joined.
It includes pagination, sorting, and filtering capabilities.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional

from services.auth.joined_clubs_service import get_joined_clubs_service
from services.auth.models import JoinedClubsResponse
from core.auth.auth_middleware import get_current_user
from core.utils.response_utils import create_response

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/joined-clubs", response_model=JoinedClubsResponse)
async def get_joined_clubs(
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page (max 100)"),
    sort_by: str = Query("join_date", description="Sort by: 'join_date', 'club_name', or 'status'"),
    sort_order: str = Query("desc", description="Sort order: 'asc' or 'desc'"),
    status_filter: str = Query("all", description="Filter by status: 'all', 'active', 'inactive', or 'upcoming'"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get clubs that the authenticated user has joined with pagination and filtering
    
    **Features:**
    - **Authentication Required**: Only authenticated users can access
    - **Role Validation**: Only users with role "Member" can view their joined clubs
    - **Data Source**: Gets clubs from users.clubs_joined array
    - **Pagination Support**: Supports page and page_size parameters
    - **Sorting**: Sort by join_date, club_name, or status (asc/desc)
    - **Filtering**: Filter by membership status (all, active, inactive, upcoming)
    - **Club Details**: Includes club information from clubs collection
    
    **Parameters:**
    - **page**: Page number (default: 1, minimum: 1)
    - **page_size**: Number of items per page (default: 10, minimum: 1, maximum: 100)
    - **sort_by**: Sort field - 'join_date', 'club_name', or 'status' (default: 'join_date')
    - **sort_order**: Sort order - 'asc' or 'desc' (default: 'desc')
    - **status_filter**: Filter by status - 'all', 'active', 'inactive', or 'upcoming' (default: 'all')
    
    **Response includes:**
    - Club details (name, description, status, membership info)
    - Pagination information (current page, total pages, has next/previous)
    - Summary statistics (total clubs, active/inactive/upcoming counts, trial/paid counts)
    - Membership details (type, status, join date, payment info)
    - Receipt URL for paid memberships (generated from Stripe)
    - Multiple pricing plan indicator (is_multiple_plan flag)
    
    **Business Logic:**
    - Only Members can access their joined clubs
    - Data comes from users.clubs_joined array
    - Club details are enriched from clubs collection
    - Supports comprehensive filtering and sorting
    - Amounts are converted from cents to dollars
    - Receipt URLs are fetched from Stripe for paid memberships
    - Multiple pricing plan detection based on pricing_plans array length
    """
    try:
        user_id = current_user.get("user_id")
        user_role = current_user.get("role")
        
        logger.info(f"Joined clubs request from user {user_id} with role {user_role}")
        
        # Validate user role
        if user_role != "Member":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Members can view their joined clubs. Captains and Moderators cannot access this feature."
            )
        
        # Get joined clubs
        joined_clubs_service = get_joined_clubs_service()
        success, clubs_data, error_message = await joined_clubs_service.get_joined_clubs(
            user_id, page, page_size, sort_by, sort_order, status_filter
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message or "Failed to retrieve joined clubs"
            )
        
        pagination_info = clubs_data.get("pagination", {})
        total_clubs = pagination_info.get("total_clubs", 0)
        
        logger.info(f"Successfully retrieved joined clubs for user {user_id}: {total_clubs} total clubs")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Joined clubs retrieved successfully. Page {page} of {pagination_info.get('total_pages', 1)} with {total_clubs} total clubs.",
            data=clubs_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_joined_clubs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )
