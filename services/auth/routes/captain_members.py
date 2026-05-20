"""
Captain Members API Routes

This module provides API endpoints for Captains to view all members
across their created clubs with pagination, filtering, and search.
"""

import logging
from fastapi import APIRouter, HTTPException, Query, Depends, status

from services.auth.captain_members_service import get_captain_members_service
from services.auth.models import CaptainMembersResponse
from services.auth.utils import get_current_user
from core.utils.response_utils import create_response

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/captain-members", response_model=CaptainMembersResponse)
async def get_captain_members(
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page (max 100)"),
    search: str = Query(None, description="Search by email, club name, or member/moderator name"),
    status_filter: str = Query("all", description="Filter by status: 'all', 'active', or 'inactive'"),
    plan_type: str = Query("all", description="Filter by plan type: 'all', 'trial', or 'paid'"),
    club_filter: str = Query("all", description="Filter by specific club (club_id, name_based_id, or 'all')"),
    role_filter: str = Query("Member", description="Filter by role: 'Member' or 'Moderator'"),
    moderator_type_filter: str = Query("all", description="Filter by moderator type: 'all', 'free', or 'paid' (only when role_filter=Moderator)"),
    sort_by: str = Query("newest", description="Sort by: 'newest', 'oldest', 'name_az', 'name_za', 'club_name'"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get all members across Captain's created clubs with pagination and filtering
    
    **Features:**
    - **Captain Only**: Only Captains can access this endpoint
    - **Comprehensive Data**: Shows all members from all clubs created by the Captain
    - **Advanced Filtering**: Filter by status, plan type, and specific clubs
    - **Search Functionality**: Search by member email, name, or club name
    - **Multiple Sorting**: Sort by date, name, or club name
    - **Pagination**: Efficient pagination with configurable page size
    - **Summary Statistics**: Provides overview of all members across clubs
    
    **Query Parameters:**
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 10, max: 100)
    - **search**: Search term for email, club name, or member name
    - **status_filter**: Filter by membership status ('all', 'active', 'inactive')
    - **plan_type**: Filter by plan type ('all', 'trial', 'paid')
    - **club_filter**: Filter by specific club ID or name_based_id ('all' for all clubs)
    - **sort_by**: Sort order ('newest', 'oldest', 'name_az', 'name_za', 'club_name')
    
    **Response includes:**
    - List of members with detailed information
    - Pagination metadata
    - Summary statistics across all clubs
    - Applied filters information
    
    **Business Logic:**
    - Retrieves all clubs created by the authenticated Captain
    - Combines members from both 'members' (trial) and 'paid_members' arrays
    - Applies filters and search criteria efficiently
    - Provides comprehensive member details including payment information
    - Generates summary statistics for dashboard overview
    
    **Performance Optimizations:**
    - Lazy loading of member details
    - Efficient filtering and sorting
    - Pagination to limit response size
    - Optimized database queries
    """
    try:
        # Validate user role
        user_role = current_user.get("role")
        if user_role != "Captain":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Captains can access this endpoint"
            )
        
        captain_id = current_user.get("user_id")  # User ID from JWT token
        if not captain_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Captain ID not found in token"
            )
        
        logger.info(f"Captain members request from {captain_id}: page={page}, search='{search}', status='{status_filter}', plan='{plan_type}', club='{club_filter}', role='{role_filter}', moderator_type='{moderator_type_filter}', sort='{sort_by}'")
        
        # Validate filter parameters
        valid_status_filters = ["all", "active", "inactive"]
        if status_filter not in valid_status_filters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status_filter. Must be one of: {valid_status_filters}"
            )
        
        valid_plan_types = ["all", "trial", "paid"]
        if plan_type not in valid_plan_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid plan_type. Must be one of: {valid_plan_types}"
            )
        
        valid_role_filters = ["Member", "Moderator"]
        if role_filter not in valid_role_filters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role_filter. Must be one of: {valid_role_filters}"
            )
        
        valid_moderator_type_filters = ["all", "free", "paid"]
        if moderator_type_filter not in valid_moderator_type_filters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid moderator_type_filter. Must be one of: {valid_moderator_type_filters}"
            )
        
        valid_sort_options = ["newest", "oldest", "name_az", "name_za", "club_name"]
        if sort_by not in valid_sort_options:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort_by. Must be one of: {valid_sort_options}"
            )
        
        # Get captain members service
        captain_members_service = get_captain_members_service()
        
        # Retrieve captain members with filters
        success, members_data, error_message = await captain_members_service.get_captain_members(
            captain_id=captain_id,
            page=page,
            page_size=page_size,
            search=search,
            status_filter=status_filter,
            plan_type=plan_type,
            club_filter=club_filter,
            role_filter=role_filter,
            moderator_type_filter=moderator_type_filter,
            sort_by=sort_by
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message or "Failed to retrieve captain members"
            )
        
        # Prepare success message
        pagination = members_data.get("pagination", {})
        summary = members_data.get("summary", {})
        
        success_message = f"Captain members retrieved successfully. Page {page} of {pagination.get('total_pages', 1)} with {pagination.get('total_members', 0)} total members across {summary.get('total_clubs', 0)} clubs."
        
        logger.info(f"Successfully retrieved {len(members_data.get('members', []))} members for Captain {captain_id}")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=success_message,
            data=members_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_captain_members: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )
