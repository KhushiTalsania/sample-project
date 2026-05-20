from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    Query,
    Form,
    UploadFile,
    Request,
)
from typing import Optional, List, Literal
from bson import ObjectId
from datetime import datetime
import math
import re
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
import logging
import json
import os
import csv
import io

from .models import (
    ClubCreateRequest,
    ClubCreateResponse,
    ClubUpdateRequest,
    ClubUpdateResponse,
    ClubDeleteResponse,
    ClubResponse,
    ClubListResponse,
    ClubFilters,
    SortOption,
    PaginationParams,
    ClubCaptain,
    ClubSearchRequest,
    # New detailed models
    ClubDetailsResponse,
    ClubPreview,
    ClubFullDetails,
    CaptainDetails,
    CaptainInfoResponse,
    MembershipStatusResponse,
    ClubStats,
    MembershipInfo,
    # Trial membership models
    ClubJoinRequest,
    ClubJoinResponse,
    RefundRequest,
    RefundResponse,
    TrialStatusResponse,
    TrialLimits,
    GroupAccessInfo,
    # Join trial free models
    JoinTrialFreeRequest,
    JoinTrialFreeResponse,
    TrialClubAccess,
    # Join paid models
    JoinPaidRequest,
    JoinPaidResponse,
    PaidMemberDetails,
    # Moderator view models
    ModeratorViewRequest,
    ModeratorViewResponse,
    # Member view models
    MemberViewRequest,
    MemberViewResponse,
    DetailedMemberInfo,
    # Member pricing models
    MemberPricingRequest,
    MemberPricingResponse,
    PricingPlanDetails,
    # Club edit models
    # Moderator management models
    ModeratorDeleteRequest,
    ModeratorReactivateRequest,
    ModeratorDeleteResponse,
    ModeratorReactivateResponse,
    # Moderator details models
    ModeratorDetailsRequest,
    ModeratorDetailsResponse,
    ClubEditRequest,
    ClubEditResponse,
    # Simple club models
    SimpleClubResponse,
    SimpleClubListResponse,
    # Soft delete member models
    SoftDeleteMemberRequest,
    SoftDeleteMemberResponse,
    # Add moderators models
    AddModeratorsRequest,
    AddModeratorsResponse,
    # Enhanced member information models
    ClubMemberDetails,
    UserClubDetails,
    # My club detail models
    MyClubDetailResponse,
    ModeratorClubDetailResponse,
    CaptainClubDetailResponse,
    ModeratorDetail,
    CaptainDetail,
    HubContentSummary,
    HubContentItem,
    SportInfo,
    BettingStats,
    WhatsIncludedItem,
    # Ongoing membership models
    OngoingMembershipsResponse,
    MembershipSummary,
    OngoingMembershipDetails,
    # Past membership models
    PastMembershipsResponse,
    MembershipHistorySummary,
    # Image upload models
    ImageUploadResponse,
    ImageUploadError,
    ImageMetadata,
    # Club Step 1 models
    ClubStep1CreateRequest,
    ClubStep1Response,
    ClubStep1Document,
    ClubStatus,
    ClubStep2UpdateRequest,
    ClubStep2Response,
    ClubStep2UpdateSimpleRequest,
    # Club Step 3 models
    ClubStep3UpdateRequest,
    ClubStep3Response,
    # Club Step 4 models
    ClubStep4UpdateRequest,
    ClubStep4Response,
    # New models for my-clubs API
    MyClubsFilters,
    MyClubsSortOption,
    MyClubsResponse,
    MyClubItem,
    # Additional models
    PricingPlan,
    # Hub models
    CreateHubRequest,
    CreateHubResponse,
    HubResponse,
    HubSection,
    EditHubRequest,
    EditHubResponse,
    DeleteHubResponse,
    HubStatsResponse,
    # Club confirmation models
    ClubConfirmationFreeRequest,
    ClubConfirmationFreeResponse,
    ClubConfirmationPaidRequest,
    ClubConfirmationPaidResponse,
    HubFiltersResponse,
    HubSortOption,
    # User clubs models
    UserClubInfo,
    UserClubsResponse,
    # Club statistics models
    ClubStatsResponse,
)
from .id_utils import generate_unique_name_based_id, is_valid_name_based_id
from .db import (
    get_club_collection,
    get_user_collection,
    get_inclusions_collection,
    get_sports_collection,
    check_database_health,
    HubDatabase,
)
from .membership_service import (
    check_user_membership,
    get_captain_total_members,
    get_captain_stats,
    can_user_join_club,
    get_ongoing_memberships,
    get_membership_summary,
    cancel_membership_by_id,
    pause_membership_by_id,
    resume_membership_by_id,
    get_past_memberships,
    get_membership_history_summary,
    can_rejoin_club,
    get_rejoinable_clubs,
)
from .auth import (
    get_current_captain,
    get_current_user,
    get_club_owner,
    verify_club_ownership,
    get_current_user_or_captain,
)
from services.auth.captain_members_service import get_captain_members_service
from .trial_service import (
    get_trial_membership_status,
    can_join_club_trial,
    join_club_trial,
    request_refund,
    get_trial_joined_clubs,
    get_available_trial_actions,
    get_group_access_status,
    access_group,
    is_user_trial_member,
    TRIAL_LIMITS,
)
from .join_trial_free_service import JoinTrialFreeService
from .image_service import image_service
from .club_step1_service import (
    verify_captain_eligibility,
    create_club_step1,
    update_club_step1,
)
from .club_step2_service import ClubStep2Service
from .my_clubs_service import MyClubsService
from .club_step3_service import club_step3_service
from .club_step4_service import club_step4_service
from .club_confirmation_service import club_confirmation_service
from .club_edit_service import get_club_edit_service
from .soft_delete_member_service import get_soft_delete_member_service

# Setup logging
logger = logging.getLogger(__name__)

router = APIRouter()

# Note: Custom validation error handler will be added to the main FastAPI app
# APIRouter doesn't support exception handlers directly

# Service instances
club_step2_service = ClubStep2Service()
my_clubs_service = MyClubsService()


def create_response(status_code: int, status: str, message: str, data=None):
    """Create a common response body with status code"""
    logger.debug(
        f"Creating API response - Status: {status_code}, Type: {status}, Message: {message}"
    )

    # Use jsonable_encoder to handle datetime and other non-JSON serializable objects
    encoded_data = jsonable_encoder(data) if data is not None else None

    return JSONResponse(
        status_code=status_code,
        content={"status": status, "message": message, "data": encoded_data},
    )


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint to diagnose database connection issues"""
    try:
        # Check database health
        db_healthy = await check_database_health()

        if db_healthy:
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Service is healthy",
                data={
                    "service": "betting_club_service",
                    "database": "connected",
                    "timestamp": datetime.now().isoformat(),
                },
            )
        else:
            return create_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                status="error",
                message="Service is unhealthy - database connection failed",
                data={
                    "service": "betting_club_service",
                    "database": "disconnected",
                    "timestamp": datetime.now().isoformat(),
                },
            )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Health check failed: {str(e)}",
            data=None,
        )


@router.get("/captain-progress/{captain_id}", status_code=status.HTTP_200_OK)
async def get_captain_progress(
    captain_id: str, current_captain: dict = Depends(get_current_captain)
):
    """
    Get captain's club creation progress - shows all completed steps with details

    This endpoint returns comprehensive information about all steps the captain has completed:
    - Step 1: Club basic information
    - Step 2: What's included + Top 3 sports
    - Step 3: Pricing setup with Stripe integration
    - Step 4: Moderator setup

    The captain_id parameter accepts either the user ID or the captain's name_based_id.
    Only the club owner can access this endpoint.
    """
    try:
        # Verify the captain is requesting their own progress
        requesting_captain_id = current_captain["user_id"]

        # If captain_id is not the same as requesting_captain_id, check if it's a name_based_id
        if requesting_captain_id != captain_id:
            from .db import get_user_collection

            user_collection = get_user_collection()

            # Try to find captain by name_based_id
            captain_by_name = await user_collection.find_one(
                {"name_based_id": captain_id}
            )
            if captain_by_name and str(captain_by_name["_id"]) == requesting_captain_id:
                # This is the same captain using name_based_id
                captain_id = requesting_captain_id
            else:
                return create_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    status="error",
                    message="You can only view your own club creation progress",
                    data=None,
                )

        # Get captain's progress from service
        from .club_progress_service import get_captain_club_progress

        progress_data = await get_captain_club_progress(captain_id)

        if not progress_data:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="No clubs found for this captain",
                data=None,
            )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Captain progress retrieved successfully",
            data=progress_data,
        )

    except Exception as e:
        logger.error(f"Error getting captain progress: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error retrieving captain progress: {str(e)}",
            data=None,
        )


@router.get("/my-clubs", status_code=status.HTTP_200_OK)
async def get_my_clubs(
    search: Optional[str] = Query(
        None,
        description="Search by club name, description, or captain name (minimum 2 characters)",
    ),
    club_status: Optional[ClubStatus] = Query(
        None,
        description="Filter by club status (approved, inactive, rejected, pending)",
    ),
    member_status: Optional[str] = Query(
        None,
        description="Filter by member/moderator status (active, inactive)",
    ),
    # pricing_plan: Optional[PricingPlan] = Query(None, description="Filter by pricing plan (monthly, yearly, quarterly)"),
    sort_by: MyClubsSortOption = Query(
        MyClubsSortOption.NEWEST, description="Sort by: most_members, newest, oldest"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: dict = Depends(get_current_user),
):
    """
    Get user's clubs list with search, filtering, and pagination

    This endpoint allows:
    - **Captains**: View all their created clubs
    - **Members**: View clubs they have joined (with trial membership and active status)
    - **Moderators**: View clubs they are assigned to as moderators

    Features:
    - Search by club name or captain name
    - Filter by club status (approved, inactive, rejected)
    - Filter by member/moderator status (active, inactive)
    - Filter by pricing plan (monthly, yearly, quarterly)
    - Sort by most members, newest, or oldest
    - Pagination support

    Response includes:
    - Club name, ID, name_based_id
    - Creation date, status, pricing plan (with frequency, price, currency)
    - Total members, monthly revenue, logo URL
    - Total revenue (captain's 95% share) - only for captain's created clubs
    - Member/Moderator status fields: member_status, membership_status, member_combined_status
    """
    try:
        import time
        start_time = time.time()
        logger.info(f"🚀 Starting get_my_clubs API for user {current_user['user_id']}")
        
        user_id = current_user["user_id"]
        user_role = current_user.get("role", "Member")

        # Build filters
        filters = None
        if search or club_status or member_status:
            # Validate search term
            validated_search = None
            if search:
                search_term = search.strip()
                if len(search_term) >= 2:
                    validated_search = search_term
                else:
                    logger.warning(f"Search term too short, ignoring: '{search}'")

            # Validate member_status parameter
            validated_member_status = None
            if member_status:
                if member_status.lower() in ["active", "inactive"]:
                    validated_member_status = member_status.lower()
                else:
                    logger.warning(
                        f"Invalid member_status value: '{member_status}', ignoring"
                    )

            filters = MyClubsFilters(
                search=validated_search,
                status=club_status,
                member_status=validated_member_status,
            )

        # Get all accessible clubs for the user regardless of current role
        # This handles cases where users' roles have changed but they still have access to clubs
        logger.info(
            f"Getting all accessible clubs for user {user_id} (role: {user_role}) with filters: {filters}, sort_by: {sort_by}, page: {page}, page_size: {page_size}"
        )
        
        service_start_time = time.time()
        result = await my_clubs_service.get_user_accessible_clubs(
            user_id=user_id,
            user_role=user_role,
            filters=filters,
            sort_by=sort_by,
            page=page,
            page_size=page_size,
        )
        service_time = time.time() - service_start_time
        logger.info(f"⏱️ Service call took {service_time:.3f}s")

        if not result:
            logger.error(f"Failed to retrieve clubs for {user_role.lower()} {user_id}")
            return create_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Failed to retrieve clubs",
                data=None,
            )

        total_time = time.time() - start_time
        logger.info(f"✅ API completed in {total_time:.3f}s - Retrieved {len(result.clubs)} clubs for {user_role.lower()} {user_id}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"{user_role} clubs retrieved successfully",
            data=result,
        )

    except Exception as e:
        logger.error(f"Error getting my clubs: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error retrieving clubs: {str(e)}",
            data=None,
        )


@router.get("/moderator/my-clubs", status_code=status.HTTP_200_OK)
async def get_moderator_my_clubs(
    search: Optional[str] = Query(
        None,
        description="Search by club name, description, or captain name (minimum 2 characters)",
    ),
    club_status: Optional[ClubStatus] = Query(
        None,
        description="Filter by club status (approved, inactive, rejected, pending)",
    ),
    member_status: Optional[str] = Query(
        None,
        description="Filter by moderator status (active, inactive)",
    ),
    sort_by: MyClubsSortOption = Query(
        MyClubsSortOption.NEWEST, description="Sort by: most_members, newest, oldest"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: dict = Depends(get_current_user),
):
    """
    Get moderator's clubs list with search, filtering, and pagination

    This endpoint allows moderators to view all clubs they are assigned to as moderators.

    Features:
    - Search by club name or captain name
    - Filter by club status (approved, inactive, rejected)
    - Filter by moderator status (active, inactive)
    - Sort by most members, newest, or oldest
    - Pagination support

    Response includes:
    - Club name, ID, name_based_id
    - Creation date, status, pricing plan (with frequency, price, currency)
    - Total members, monthly revenue, logo URL
    - Moderator status fields: member_status, membership_status, member_combined_status
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role", "Member")

        # Note: This endpoint is now accessible to all users who have moderator assignments
        # regardless of their current role, as they may have been moderators before

        # Build filters
        filters = None
        if search or club_status or member_status:
            # Validate search term
            validated_search = None
            if search:
                search_term = search.strip()
                if len(search_term) >= 2:
                    validated_search = search_term
                else:
                    logger.warning(f"Search term too short, ignoring: '{search}'")

            # Validate member_status parameter
            validated_member_status = None
            if member_status:
                if member_status.lower() in ["active", "inactive"]:
                    validated_member_status = member_status.lower()
                else:
                    logger.warning(
                        f"Invalid member_status value: '{member_status}', ignoring"
                    )

            filters = MyClubsFilters(
                search=validated_search,
                status=club_status,
                member_status=validated_member_status,
            )

        # Get moderator's clubs using the new method that checks detailed_moderators array
        logger.info(
            f"Getting moderator clubs for user {user_id} with filters: {filters}, sort_by: {sort_by}, page: {page}, page_size: {page_size}"
        )

        result = await my_clubs_service._get_user_moderator_clubs(
            user_id=user_id,
            filters=filters,
            sort_by=sort_by,
            page=page,
            page_size=page_size,
        )

        if not result:
            logger.error(f"Failed to retrieve moderator clubs for user {user_id}")
            return create_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Failed to retrieve moderator clubs",
                data=None,
            )

        logger.info(
            f"Successfully retrieved {len(result.clubs)} moderator clubs for user {user_id}"
        )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Moderator clubs retrieved successfully",
            data=result,
        )

    except Exception as e:
        logger.error(f"Error getting moderator clubs: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error retrieving moderator clubs: {str(e)}",
            data=None,
        )


@router.get(
    "/moderator/my-club-detail/{club_name_based_id}",
    response_model=ModeratorClubDetailResponse,
)
async def get_moderator_my_club_detail(
    club_name_based_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Get detailed information about a specific club for a moderator

    This endpoint allows moderators to view comprehensive details about a club they are assigned to as moderators,
    including club information, moderator details, and captain information.

    **Access Control:**
    - Only moderators who are assigned to the club can access this endpoint
    - Validates moderator assignment before returning club details

    **Response includes:**
    - Club basic information (ID, name, description, status)
    - Moderator's join date for this club
    - Other moderator details (emails and names)
    - Captain information (ID, name, name-based ID)
    - Club statistics (member count, total bets, win percentage)
    - Top 3 sports for the club
    - Club rejection information (rejection_type, rejection_reason, rejected_by, is_resubmit, is_club_reject_temporary, is_club_reject_permanently)
    - User role (Member, Moderator, or Captain based on user's relationship to the club)

    **Example Usage:**
    ```
    GET /api/v1/moderator/my-club-detail/badminton-group
    ```

    Returns detailed club information for the authenticated moderator.
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role", "Member")
        user_name = current_user.get("full_name", "Unknown")

        # Note: This endpoint is now accessible to all users who have moderator assignments
        # regardless of their current role, as they may have been moderators before

        logger.info(
            f"Getting moderator club detail for user {user_id} ({user_name}), club {club_name_based_id}"
        )

        # Get moderator club detail using the moderators service
        from .moderators_service import moderators_service

        success, club_detail_data, error_message = (
            await moderators_service.get_moderator_club_detail(
                user_id, club_name_based_id
            )
        )

        if not success:
            logger.warning(f"Failed to get moderator club detail: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve club details",
                data=None,
            )

        # Convert to response model
        response_data = ModeratorClubDetailResponse(**club_detail_data)

        logger.info(
            f"Successfully retrieved moderator club detail for user {user_id}, club {club_name_based_id}"
        )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Moderator club details retrieved successfully",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"Unexpected error in get_moderator_my_club_detail: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/captain-progress-summary/{captain_id}", status_code=status.HTTP_200_OK)
async def get_captain_progress_summary(
    captain_id: str, current_captain: dict = Depends(get_current_captain)
):
    """
    Get captain's club creation progress summary - shows overall progress without detailed club info

    This endpoint returns a summary of the captain's progress:
    - Total clubs created
    - Overall completion percentage
    - Step-by-step completion status
    - Recent activity

    The captain_id parameter accepts either the user ID or the captain's name_based_id.
    Only the club owner can access this endpoint.
    """
    try:
        # Verify the captain is requesting their own progress
        requesting_captain_id = current_captain["user_id"]

        # If captain_id is not the same as requesting_captain_id, check if it's a name_based_id
        if requesting_captain_id != captain_id:
            from .db import get_user_collection

            user_collection = get_user_collection()

            # Try to find captain by name_based_id
            captain_by_name = await user_collection.find_one(
                {"name_based_id": captain_id}
            )
            if captain_by_name and str(captain_by_name["_id"]) == requesting_captain_id:
                # This is the same captain using name_based_id
                captain_id = requesting_captain_id
            else:
                return create_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    status="error",
                    message="You can only view your own club creation progress",
                    data=None,
                )

        # Get captain's progress summary from service
        from .club_progress_service import get_captain_progress_summary

        summary_data = await get_captain_progress_summary(captain_id)

        if not summary_data:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="No clubs found for this captain",
                data=None,
            )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Captain progress summary retrieved successfully",
            data=summary_data,
        )

    except Exception as e:
        logger.error(f"Error getting captain progress summary: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error retrieving captain progress summary: {str(e)}",
            data=None,
        )


@router.get("/club-progress/{club_id}", status_code=status.HTTP_200_OK)
async def get_club_progress(
    club_id: str, current_captain: dict = Depends(get_current_captain)
):
    """
    Get detailed progress for a specific club - shows all completed steps with details

    This endpoint returns comprehensive information about all steps completed for a specific club:
    - Step 1: Club basic information
    - Step 2: What's included + Top 3 sports
    - Step 3: Pricing setup with Stripe integration
    - Step 4: Moderator setup

    The club_id parameter accepts the name_based_id (e.g., "beta-group") instead of MongoDB ObjectId.
    Only the club owner can access this endpoint.
    """
    try:
        # Get club progress from service
        from .club_progress_service import get_club_step_details
        from .db import get_club_collection

        club_collection = get_club_collection()

        # First try to find club by name_based_id
        club = await club_collection.find_one({"name_based_id": club_id})

        # If not found by name_based_id, try by ObjectId (for backward compatibility)
        if not club:
            try:
                from bson import ObjectId

                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({"_id": club_object_id})
            except:
                pass

        if not club:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Club not found. Please check the club identifier.",
                data=None,
            )

        # Verify the captain owns this club
        requesting_captain_id = current_captain["user_id"]
        if club.get("captain_id") != requesting_captain_id:
            return create_response(
                status_code=status.HTTP_403_FORBIDDEN,
                status="error",
                message="You can only view progress for your own clubs",
                data=None,
            )

        # Get club progress
        club_progress = {
            "club_id": str(club["_id"]),
            "name": club.get("name", ""),
            "name_based_id": club.get("name_based_id", ""),
            "description": club.get("description", ""),
            "sub_description": club.get("sub_description"),
            "logo_url": club.get("logo_url"),
            "status": club.get("status", "pending"),
            "club_complete_step": club.get("club_complete_step", 0),
            "created_at": club.get("created_at"),
            "updated_at": club.get("updated_at"),
            "completed_steps": [],
        }

        # Get details for each step
        for step_number in range(1, 5):
            step_details = await get_club_step_details(str(club["_id"]), step_number)
            if step_details:
                club_progress["completed_steps"].append(step_details)

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Club progress retrieved successfully",
            data=club_progress,
        )

    except Exception as e:
        logger.error(f"Error getting club progress: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error retrieving club progress: {str(e)}",
            data=None,
        )


@router.post("/create-club-info", status_code=status.HTTP_201_CREATED)
async def create_club_info(
    club_data: ClubStep1CreateRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Create or update club information (Step 1) - Only for captains with active paid/trial membership

    This endpoint creates or updates the first step of club creation with:
    - name, description, sub_description, logo_url, banner_url
    - status = Pending (default, requires admin approval)
    - club_complete_step = 1

    If a club with the same name already exists, it will update the existing record.
    """
    try:
        captain_id = current_captain["user_id"]

        # Verify captain eligibility (active membership, paid or trial type)
        is_eligible = await verify_captain_eligibility(captain_id)

        if not is_eligible:
            return create_response(
                status_code=status.HTTP_403_FORBIDDEN,
                status="error",
                message="Captain is not eligible to create clubs. Must have active paid or trial membership.",
                data=None,
            )

        # Check if any club with the same name already exists (globally unique, case-insensitive)
        club_collection = get_club_collection()

        # Log the uniqueness check for debugging
        logger.info(f"Checking for existing club with name: '{club_data.name}'")

        # First, check if captain already has a club with this exact name (for updates)
        captain_club_query = {
            "name": {"$regex": f"^{club_data.name}$", "$options": "i"},
            "captain_id": captain_id,
            "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}],
        }

        captain_existing_club = await club_collection.find_one(captain_club_query)

        if captain_existing_club:
            # Captain already has a club with this name - check if it can be updated
            club_complete_step = captain_existing_club.get("club_complete_step", 0)

            if club_complete_step >= 5:
                # Club is fully completed - cannot be updated via create-club-info API
                logger.warning(
                    f"Captain's club '{club_data.name}' is fully completed (step {club_complete_step}) - cannot be updated"
                )
                return create_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    status="error",
                    message="This club is already completed. Please create a new club with a different name.",
                    data=None,
                )
            else:
                # Club is incomplete - can be updated
                logger.info(
                    f"Captain's club '{club_data.name}' is incomplete (step {club_complete_step}) - updating existing club"
                )

                # Update existing club
                try:
                    updated_club = await update_club_step1(
                        str(captain_existing_club["_id"]), club_data
                    )

                    if not updated_club:
                        logger.error(
                            f"Failed to update club step 1 for name: '{club_data.name}'"
                        )
                        return create_response(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            status="error",
                            message="Failed to update club. Please try again.",
                            data=None,
                        )

                    logger.info(
                        f"Successfully updated club step 1 with ID: {updated_club.get('id', 'unknown')}"
                    )

                    # Convert to response model and then to dict for JSON serialization
                    try:
                        club_response = ClubStep1Response(**updated_club)
                        club_response_dict = club_response.dict()

                        logger.debug(
                            f"Updated club response converted to dict: {club_response_dict}"
                        )

                        return create_response(
                            status_code=status.HTTP_200_OK,
                            status="success",
                            message="Club updated successfully.",
                            data=club_response_dict,
                        )
                    except Exception as conversion_error:
                        logger.error(
                            f"Error converting updated club response: {conversion_error}"
                        )
                        # Fallback: return the raw updated_club data
                        return create_response(
                            status_code=status.HTTP_200_OK,
                            status="success",
                            message="Club updated successfully.",
                            data=updated_club,
                        )

                except Exception as update_error:
                    logger.error(f"Error updating club step 1: {update_error}")
                    return create_response(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        status="error",
                        message="Failed to update club. Please try again.",
                        data=None,
                    )
        else:
            # Captain doesn't have a club with this name - check if name is globally unique
            logger.info(
                f"Captain doesn't have club '{club_data.name}' - checking global uniqueness"
            )

            # Check for global uniqueness (any club with this name)
            global_uniqueness_query = {
                "name": {"$regex": f"^{club_data.name}$", "$options": "i"},
                "$or": [
                    {"is_deleted": {"$ne": True}},
                    {"is_deleted": {"$exists": False}},
                ],
            }

            global_existing_club = await club_collection.find_one(
                global_uniqueness_query
            )

            if global_existing_club:
                # Name already exists globally - reject
                logger.warning(
                    f"Club name '{club_data.name}' already exists globally with captain ID: {global_existing_club.get('captain_id')}"
                )
                return create_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    status="error",
                    message="A club with this name already exists. Please choose a different name.",
                    data=None,
                )
            else:
                # Name is globally unique - create new club
                logger.info(
                    f"Club name '{club_data.name}' is globally unique, proceeding with creation"
                )

                # Create club step 1
                try:
                    logger.info(f"Creating club step 1 for name: '{club_data.name}'")
                    created_club = await create_club_step1(club_data, captain_id)

                    if not created_club:
                        logger.error(
                            f"Failed to create club step 1 for name: '{club_data.name}'"
                        )
                        return create_response(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            status="error",
                            message="Failed to create club. Please try again.",
                            data=None,
                        )

                    logger.info(
                        f"Successfully created club step 1 with ID: {created_club.get('id', 'unknown')}"
                    )

                    # Note: Club count will only be incremented when club_complete_step = 5 (after confirmation)
                    # This ensures club_count = 0 until the entire 5-step process is completed

                except Exception as create_error:
                    logger.error(f"Error creating club step 1: {create_error}")

                    # Check if it's a duplicate key error (unique constraint violation)
                    if "duplicate key error" in str(
                        create_error
                    ).lower() or "e11000" in str(create_error):
                        logger.warning(
                            f"Duplicate key error caught for club name: '{club_data.name}'"
                        )
                        return create_response(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            status="error",
                            message="A club with this name already exists. Please choose a different name.",
                            data=None,
                        )
                    else:
                        # Re-raise other errors
                        logger.error(
                            f"Unexpected error during club creation: {create_error}"
                        )
                        raise create_error

                # Convert to response model and then to dict for JSON serialization
                try:
                    club_response = ClubStep1Response(**created_club)
                    club_response_dict = club_response.dict()

                    logger.debug(
                        f"Club response converted to dict: {club_response_dict}"
                    )

                    return create_response(
                        status_code=status.HTTP_201_CREATED,
                        status="success",
                        message="Step1 Club created successfully.",
                        data=club_response_dict,
                    )
                except Exception as conversion_error:
                    logger.error(f"Error converting club response: {conversion_error}")
                    # Fallback: return the raw created_club data
                    return create_response(
                        status_code=status.HTTP_201_CREATED,
                        status="success",
                        message="Step1 Club created successfully.",
                        data=created_club,
                    )

    except Exception as e:
        logger.error(f"Error creating/updating club info: {str(e)}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Internal server error. Please try again.",
            data=None,
        )


async def get_captain_info(captain_id: str) -> ClubCaptain:
    """Get captain information from user database"""
    user_collection = get_user_collection()

    try:
        captain_object_id = ObjectId(captain_id)
        captain = await user_collection.find_one({"_id": captain_object_id})

        if not captain:
            # Generate name-based ID for unknown captain
            captain_name_based_id = generate_unique_name_based_id(
                "Unknown Captain", captain_id
            )
            return ClubCaptain(
                id=captain_id,
                full_name="Unknown Captain",
                avatar_url=None,
                bio=None,
                name_based_id=captain_name_based_id,
            )

        # Use stored name-based ID or generate if not present
        captain_name = captain.get("full_name", "Unknown Captain")
        captain_name_based_id = captain.get(
            "name_based_id"
        ) or generate_unique_name_based_id(captain_name, captain_id)

        return ClubCaptain(
            id=captain_id,
            full_name=captain.get("full_name", "Unknown Captain"),
            avatar_url=captain.get("avatar_url"),
            bio=captain.get("bio"),
            name_based_id=captain_name_based_id,
        )
    except Exception:
        # Generate name-based ID for unknown captain
        captain_name_based_id = generate_unique_name_based_id(
            "Unknown Captain", captain_id
        )
        return ClubCaptain(
            id=captain_id,
            full_name="Unknown Captain",
            avatar_url=None,
            bio=None,
            name_based_id=captain_name_based_id,
        )


async def get_detailed_captain_info(captain_id: str) -> CaptainDetails:
    """Get detailed captain information"""
    user_collection = get_user_collection()

    try:
        captain_object_id = ObjectId(captain_id)
        captain = await user_collection.find_one({"_id": captain_object_id})

        if not captain:
            return CaptainDetails(
                id=captain_id,
                full_name="Unknown Captain",
                total_picks=0,
                win_pct=0.0,
                member_count=0,
                clubs_count=0,
            )

        # Get captain stats
        stats = await get_captain_stats(captain_id)
        total_members = await get_captain_total_members(captain_id)

        return CaptainDetails(
            id=captain_id,
            full_name=captain.get("full_name", "Unknown Captain"),
            email=captain.get("email") if captain.get("role") == "Captain" else None,
            avatar_url=captain.get("avatar_url"),
            bio=captain.get("bio"),
            total_picks=stats.get("total_picks", 0),
            win_pct=stats.get("average_win_pct", 0.0),
            member_count=total_members,
            clubs_count=stats.get("total_clubs", 0),
            joined_date=captain.get("created_at"),
        )
    except Exception:
        return CaptainDetails(
            id=captain_id,
            full_name="Unknown Captain",
            total_picks=0,
            win_pct=0.0,
            member_count=0,
            clubs_count=0,
        )


async def build_club_stats(club_doc: dict) -> ClubStats:
    """Build club statistics from database document"""
    return ClubStats(
        total_picks=club_doc.get("total_bets", 0),
        winning_picks=club_doc.get("winning_bets", 0),
        win_pct=club_doc.get("win_pct", 0.0),
        member_count=club_doc.get("member_count", 0),
        total_revenue=club_doc.get("total_revenue", 0.0),
        created_at=club_doc["created_at"],
        last_pick_date=club_doc.get("last_pick_date"),
    )


def build_filter_query(filters: ClubFilters) -> dict:
    """Build MongoDB query from filters"""
    query = {"status": "approved"}  # Only show approved clubs

    # Text search
    if filters.search:
        # Create regex pattern for case-insensitive search
        search_pattern = re.compile(filters.search, re.IGNORECASE)
        query["$or"] = [
            {"name": {"$regex": search_pattern}},
            {"description": {"$regex": search_pattern}},
            {"sub_description": {"$regex": search_pattern}},
        ]

    # # Category filter
    # if filters.category:
    #     query["category"] = filters.category.value

    # # Win percentage filter
    # if filters.min_win_pct is not None or filters.max_win_pct is not None:
    #     win_pct_query = {}
    #     if filters.min_win_pct is not None:
    #         win_pct_query["$gte"] = filters.min_win_pct
    #     if filters.max_win_pct is not None:
    #         win_pct_query["$lte"] = filters.max_win_pct
    #     query["win_pct"] = win_pct_query

    # # Price range filter (check any pricing plan within range)
    # if filters.min_price is not None or filters.max_price is not None:
    #     price_conditions = []

    #     if filters.min_price is not None:
    #         price_conditions.append({"pricing_plans.price": {"$gte": filters.min_price}})
    #     if filters.max_price is not None:
    #         price_conditions.append({"pricing_plans.price": {"$lte": filters.max_price}})

    #     if price_conditions:
    #         query["$and"] = query.get("$and", []) + price_conditions

    # # Pricing plan filter
    # if filters.pricing_plan:
    #     query["pricing_plans.plan"] = filters.pricing_plan.value

    return query


def get_sort_criteria(sort_by: SortOption) -> List[tuple]:
    """Get MongoDB sort criteria based on sort option"""
    if sort_by == SortOption.TOP_PERFORMING:
        return [("win_pct", -1), ("created_at", -1)]  # Secondary sort by creation date
    elif sort_by == SortOption.NEWEST:
        return [("created_at", -1)]
    elif sort_by == SortOption.MOST_MEMBERS:
        return [
            ("member_count", -1),
            ("created_at", -1),
        ]  # Secondary sort by creation date
    elif sort_by == SortOption.POPULAR:
        return [
            ("member_count", -1),
            ("created_at", -1),
        ]  # Same as most_members but will be limited to 1
    else:
        return [("win_pct", -1), ("created_at", -1)]  # Default to top performing


def convert_pricing_plans(pricing_plans: list) -> list:
    """Convert database pricing plans format to ClubPricing model format"""
    converted_plans = []
    for plan in pricing_plans:
        if isinstance(plan, dict):
            # Convert frequency to plan if needed
            converted_plan = {
                "plan": plan.get("frequency", plan.get("plan", "monthly")),
                "price": plan.get("price", 0.0),
                "currency": plan.get("currency", "USD"),
            }
            converted_plans.append(converted_plan)
    return converted_plans


async def get_captain_info(captain_id: str) -> dict:
    """Get captain information from user collection"""
    if not captain_id:
        return {"id": "", "name": "Unknown Captain", "email": ""}

    try:
        user_collection = get_user_collection()
        captain = await user_collection.find_one({"_id": ObjectId(captain_id)})
        if captain:
            return {
                "id": str(captain["_id"]),
                "name": captain.get("full_name", "Unknown Captain"),
                "email": captain.get("email", ""),
                "avatar_url": captain.get("avatar_url"),
                "bio": captain.get("bio"),
            }
    except Exception as e:
        print(f"Error getting captain info: {e}")

    return {"id": captain_id or "", "name": "Unknown Captain", "email": ""}


async def club_document_to_response(club_doc: dict) -> ClubResponse:
    """Convert MongoDB club document to ClubResponse"""
    captain_info = await get_captain_info(club_doc.get("captain_id"))

    # Use stored name-based ID or generate if not present
    club_name_based_id = club_doc.get("name_based_id") or generate_unique_name_based_id(
        club_doc["name"], str(club_doc["_id"])
    )

    return ClubResponse(
        id=str(club_doc["_id"]),
        name=club_doc.get("name", "Unknown Club"),
        description=club_doc.get("description", "No description available"),
        sub_description=club_doc.get("sub_description"),
        logo_url=club_doc.get("logo_url"),
        category=club_doc.get("category"),
        win_pct=club_doc.get("win_pct", 0.0),
        member_count=club_doc.get("total_members", 0),
        total_bets=club_doc.get("total_bets", 0),
        pricing_plans=convert_pricing_plans(club_doc.get("pricing_plans", [])),
        captain=captain_info,
        whats_included=club_doc.get("whats_included"),
        top_3_sports=club_doc.get("top_3_sports"),
        is_active=club_doc.get("is_active", True),
        is_popular=club_doc.get("is_popular", False),
        name_based_id=club_name_based_id,
        created_at=club_doc.get("created_at", datetime.utcnow()),
        updated_at=club_doc.get("updated_at", datetime.utcnow()),
    )


async def club_document_to_response_with_user_data(
    club_doc: dict, current_user: Optional[dict]
) -> ClubResponse:
    """Convert MongoDB club document to ClubResponse with user trial data"""
    captain_info = await get_captain_info(club_doc.get("captain_id"))

    # Use stored name-based ID or generate if not present
    club_name_based_id = club_doc.get("name_based_id") or generate_unique_name_based_id(
        club_doc["name"], str(club_doc["_id"])
    )

    # Get user trial club statistics
    clubs_joined_count = 0
    clubs_remaining = 0
    max_clubs = 4

    if current_user and current_user.get("user_id"):
        try:
            from .db import get_user_collection

            user_collection = get_user_collection()
            user = await user_collection.find_one(
                {"_id": ObjectId(current_user["user_id"])}
            )

            if user:
                clubs_joined_count = user.get("clubs_joined_count", 0)
                clubs_remaining = user.get("clubs_remaining", 4)
                max_clubs = user.get("max_clubs", 4)
        except Exception as e:
            # If there's any error fetching user data, use defaults
            pass

    return ClubResponse(
        id=str(club_doc["_id"]),
        name=club_doc.get("name", "Unknown Club"),
        description=club_doc.get("description", "No description available"),
        sub_description=club_doc.get("sub_description"),
        logo_url=club_doc.get("logo_url"),
        category=club_doc.get("category"),
        win_pct=club_doc.get("win_pct", 0.0),
        member_count=club_doc.get("total_members", 0),
        total_bets=club_doc.get("total_bets", 0),
        pricing_plans=convert_pricing_plans(club_doc.get("pricing_plans", [])),
        captain=captain_info,
        whats_included=club_doc.get("whats_included"),
        top_3_sports=club_doc.get("top_3_sports"),
        is_active=club_doc.get("is_active", True),
        is_popular=club_doc.get("is_popular", False),
        name_based_id=club_name_based_id,
        created_at=club_doc.get("created_at", datetime.utcnow()),
        updated_at=club_doc.get("updated_at", datetime.utcnow()),
        clubs_joined_count=clubs_joined_count,
        clubs_remaining=clubs_remaining,
        max_clubs=max_clubs,
    )


async def club_document_to_public_response(club_doc: dict) -> ClubResponse:
    """
    Convert club document to public response format (no authentication required).
    This function provides limited captain information for public access.
    """
    captain_info = await get_captain_info(club_doc.get("captain_id"))

    # Use stored name-based ID or generate if not present
    club_name_based_id = club_doc.get("name_based_id") or generate_unique_name_based_id(
        club_doc["name"], str(club_doc["_id"])
    )

    return ClubResponse(
        id=str(club_doc["_id"]),
        name=club_doc.get("name", "Unknown Club"),
        description=club_doc.get("description", "No description available"),
        sub_description=club_doc.get("sub_description"),
        logo_url=club_doc.get("logo_url"),
        # category=club_doc["category"],
        win_pct=club_doc.get("win_pct", 0.0),
        member_count=club_doc.get("total_members", 0),
        total_bets=club_doc.get("total_bets", 0),
        pricing_plans=convert_pricing_plans(club_doc.get("pricing_plans", [])),
        captain=captain_info,
        whats_included=club_doc.get("whats_included"),
        top_3_sports=club_doc.get("top_3_sports"),
        is_active=club_doc.get("is_active", True),
        is_popular=club_doc.get("is_popular", False),
        name_based_id=club_name_based_id,
        created_at=club_doc.get("created_at", datetime.utcnow()),
        updated_at=club_doc.get("updated_at", datetime.utcnow()),
    )


# @router.post("/clubs", response_model=ClubCreateResponse, status_code=status.HTTP_201_CREATED)
# async def create_club(
#     club_data: ClubCreateRequest,
#     current_captain: dict = Depends(get_current_captain)
# ):
#     """Create a new club (only captains with paid membership)"""
#     club_collection = get_club_collection()

#     # Check if captain already has a club with the same name
#     existing_club = await club_collection.find_one({
#         "captain_id": current_captain["user_id"],
#         "name": club_data.name,
#         "is_active": True
#     })

#     if existing_club:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="You already have an active club with this name"
#         )

#     # Create club document
#     now = datetime.utcnow()
#     club_doc = {
#         "name": club_data.name,
#         "description": club_data.description,
#         "sub_description": club_data.sub_description,
#         "logo_url": club_data.logo_url,
#         "category": club_data.category.value,
#         "pricing_plans": [plan.dict() for plan in club_data.pricing_plans],
#         "captain_id": current_captain["user_id"],
#         "win_pct": 0.0,
#         "member_count": 0,
#         "total_bets": 0,
#         "winning_bets": 0,
#         "is_active": True,
#         "created_at": now,
#         "updated_at": now
#     }

#     result = await club_collection.insert_one(club_doc)

#     # Get the created club
#     created_club = await club_collection.find_one({"_id": result.inserted_id})
#     club_response = await club_document_to_response(created_club)

#     return ClubCreateResponse(
#         message="Club created successfully",
#         club_id=str(result.inserted_id),
#         club=club_response
#     )


# checking api
@router.get("/clubs", response_model=ClubListResponse)
async def get_clubs(
    # Search and filters
    search: Optional[str] = Query(
        None, description="Search by club name or captain name"
    ),
    # category: Optional[str] = Query(None, description="Filter by category"),
    # min_win_pct: Optional[float] = Query(None, ge=0, le=100, description="Minimum win percentage"),
    # max_win_pct: Optional[float] = Query(None, ge=0, le=100, description="Maximum win percentage"),
    # min_price: Optional[float] = Query(None, ge=0, description="Minimum price"),
    # max_price: Optional[float] = Query(None, ge=0, description="Maximum price"),
    # pricing_plan: Optional[str] = Query(None, description="Filter by pricing plan"),
    # Sorting and pagination
    sort_by: SortOption = Query(SortOption.TOP_PERFORMING, description="Sort criteria"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    # Optional authentication for personalized results
    current_user: Optional[dict] = Depends(get_current_user),
):
    """Get paginated list of approved clubs with search, filter, and sort capabilities (requires authentication)"""
    club_collection = get_club_collection()

    # Build filters
    filters = ClubFilters(
        search=search,
        # category=category,
        # min_win_pct=min_win_pct,
        # max_win_pct=max_win_pct,
        # min_price=min_price,
        # max_price=max_price,
        # pricing_plan=pricing_plan
    )

    # Build query - this will include status="approved" filter
    query = build_filter_query(filters)

    # Handle captain name search separately (requires lookup)
    if search:
        # We need to also search by captain name
        user_collection = get_user_collection()
        search_pattern = re.compile(search, re.IGNORECASE)

        # Find captains matching the search
        matching_captains = await user_collection.find(
            {"full_name": {"$regex": search_pattern}, "role": "Captain"}
        ).to_list(None)

        captain_ids = [str(captain["_id"]) for captain in matching_captains]

        if captain_ids:
            # Update query to include captain name search
            if "$or" in query:
                query["$or"].append({"captain_id": {"$in": captain_ids}})
            else:
                query["$or"] = [
                    {"name": {"$regex": search_pattern}},
                    {"description": {"$regex": search_pattern}},
                    {"sub_description": {"$regex": search_pattern}},
                    {"captain_id": {"$in": captain_ids}},
                ]

    # Filter out clubs that the member has already joined (if user is a member)
    # Also filter out clubs where the user is a moderator (for any user role)
    excluded_club_ids = []
    
    if current_user:
        user_id = current_user["user_id"]
        user_collection = get_user_collection()
        user = await user_collection.find_one({"_id": ObjectId(user_id)})

        if user:
            # Get clubs the member has already joined (if user is a member)
            if current_user.get("role") == "Member":
                clubs_joined = user.get("clubs_joined", [])
                joined_club_ids = [
                    club_data.get("club_id")
                    for club_data in clubs_joined
                    if club_data.get("is_active", False)
                ]
                excluded_club_ids.extend(joined_club_ids)
            
            # Get clubs where the user is a moderator (for any user role)
            # Find clubs where user_id appears in detailed_moderators array OR email in moderator_emails
            user_email = user.get("email")
            
            # Build moderator query
            moderator_query = {"status": "approved"}  # Only exclude approved clubs
            moderator_conditions = []
            
            # Check detailed_moderators array by user_id
            moderator_conditions.append({"detailed_moderators.user_id": user_id})
            
            # Check moderator_emails array by email (if email exists)
            if user_email:
                moderator_conditions.append({"moderator_emails": user_email})
            
            if moderator_conditions:
                moderator_query["$or"] = moderator_conditions
                
                moderator_clubs_cursor = club_collection.find(
                    moderator_query,
                    {"_id": 1}
                )
                moderator_clubs = await moderator_clubs_cursor.to_list(None)
                moderator_club_ids = [str(club["_id"]) for club in moderator_clubs]
                excluded_club_ids.extend(moderator_club_ids)

            # Add exclusion filter to query
            if excluded_club_ids:
                # Remove duplicates
                excluded_club_ids = list(set(excluded_club_ids))
                # Convert string IDs to ObjectIds for proper MongoDB query
                try:
                    excluded_object_ids = [
                        ObjectId(club_id) for club_id in excluded_club_ids if club_id
                    ]
                    if excluded_object_ids:
                        # If query already has _id filter, combine with $nin
                        if "_id" in query:
                            if isinstance(query["_id"], dict) and "$nin" in query["_id"]:
                                # Merge with existing $nin
                                existing_nin = query["_id"]["$nin"]
                                if isinstance(existing_nin, list):
                                    query["_id"]["$nin"] = list(set(existing_nin + excluded_object_ids))
                                else:
                                    query["_id"]["$nin"] = excluded_object_ids
                            else:
                                # Replace with $nin
                                query["_id"] = {"$nin": excluded_object_ids}
                        else:
                            query["_id"] = {"$nin": excluded_object_ids}
                except Exception as e:
                    # If there's an issue with ObjectId conversion, log it but continue
                    logger.warning(f"Could not convert club IDs to ObjectIds: {e}")
                    pass

    # Get sort criteria
    sort_criteria = get_sort_criteria(sort_by)

    # Handle popular sort option - return only 1 club with max member_count
    if sort_by == SortOption.POPULAR:
        cursor = club_collection.find(query).sort(sort_criteria).limit(1)
        clubs = await cursor.to_list(length=1)
        # Override pagination for popular option
        total_count = len(clubs)
        total_pages = 1
        page = 1
        page_size = 1
    else:
        # Get total count
        total_count = await club_collection.count_documents(query)

        # Calculate pagination
        total_pages = math.ceil(total_count / page_size)
        skip = (page - 1) * page_size

        # Execute query with pagination and sorting
        cursor = (
            club_collection.find(query).sort(sort_criteria).skip(skip).limit(page_size)
        )
        clubs = await cursor.to_list(length=page_size)

    # Convert to response format
    club_responses = []
    for club in clubs:
        club_response = await club_document_to_response(club)
        club_responses.append(club_response)

    return ClubListResponse(
        clubs=club_responses,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )


@router.get("/all/clubs", response_model=ClubListResponse)
async def get_public_clubs(
    # Search and filters
    search: Optional[str] = Query(
        None, description="Search by club name or description"
    ),
    # category: Optional[str] = Query(None, description="Filter by category"),
    # min_win_pct: Optional[float] = Query(None, ge=0, le=100, description="Minimum win percentage"),
    # max_win_pct: Optional[float] = Query(None, ge=0, le=100, description="Maximum win percentage"),
    # min_price: Optional[float] = Query(None, ge=0, description="Minimum price"),
    # max_price: Optional[float] = Query(None, ge=0, description="Maximum price"),
    # pricing_plan: Optional[str] = Query(None, description="Filter by pricing plan"),
    # Sorting and pagination
    sort_by: SortOption = Query(SortOption.TOP_PERFORMING, description="Sort criteria"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """
    Get paginated list of approved public clubs with search, filter, and sort capabilities.
    This endpoint is publicly accessible without authentication.

    Features:
    - No authentication required (public access)
    - Only shows approved clubs (status = "approved")
    - Shows all approved clubs to everyone
    - Full search and filtering capabilities
    - Performance optimized for public access
    """
    club_collection = get_club_collection()

    # Build filters (same as authenticated endpoint)
    filters = ClubFilters(
        search=search,
        # category=category,
        # min_win_pct=min_win_pct,
        # max_win_pct=max_win_pct,
        # min_price=min_price,
        # max_price=max_price,
        # pricing_plan=pricing_plan
    )

    # Build query - this will include status="approved" filter
    query = build_filter_query(filters)

    # Handle search (only club fields, no captain name lookup for performance)
    if search:
        search_pattern = re.compile(search, re.IGNORECASE)
        query["$or"] = [
            {"name": {"$regex": search_pattern}},
            {"description": {"$regex": search_pattern}},
            {"sub_description": {"$regex": search_pattern}},
        ]

    # No authentication required - show all approved clubs

    # Get sort criteria
    sort_criteria = get_sort_criteria(sort_by)

    # Handle popular sort option - return only 1 club with max member_count
    if sort_by == SortOption.POPULAR:
        cursor = club_collection.find(query).sort(sort_criteria).limit(1)
        clubs = await cursor.to_list(length=1)
        # Override pagination for popular option
        total_count = len(clubs)
        total_pages = 1
        page = 1
        page_size = 1
    else:
        # Get total count
        total_count = await club_collection.count_documents(query)

        # Calculate pagination
        total_pages = math.ceil(total_count / page_size)
        skip = (page - 1) * page_size

        # Execute query with pagination and sorting
        cursor = (
            club_collection.find(query).sort(sort_criteria).skip(skip).limit(page_size)
        )
        clubs = await cursor.to_list(length=page_size)

    # Convert to response format (public version with limited captain info)
    club_responses = []
    for club in clubs:
        # Create a simplified response for public access
        club_response = await club_document_to_public_response(club)
        club_responses.append(club_response)

    return ClubListResponse(
        clubs=club_responses,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )


@router.get("/simple/clubs", response_model=SimpleClubListResponse)
async def get_simple_clubs(
    # Search parameter
    search: Optional[str] = Query(
        None, description="Search by club name"
    ),
    # Pagination parameters
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    # Authentication required
    current_user: dict = Depends(get_current_user),
):
    """
    Get a simple list of all approved clubs with only essential fields (id, name, name_based_id).
    This endpoint provides search and pagination support.
    
    Features:
    - Authentication required
    - Only shows approved clubs (status = "approved")
    - Returns only essential club information
    - Search by club name
    - Pagination support
    """
    club_collection = get_club_collection()
    
    # Build base query for approved clubs only
    query = {"status": "approved"}
    
    # Add search filter if provided
    if search:
        search_pattern = re.compile(search, re.IGNORECASE)
        query["name"] = {"$regex": search_pattern}
    
    # Calculate pagination
    skip = (page - 1) * page_size
    
    # Get total count for pagination
    total_count = await club_collection.count_documents(query)
    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
    
    # Get clubs with pagination
    clubs_cursor = club_collection.find(
        query,
        {
            "_id": 1,
            "name": 1,
            "name_based_id": 1
        }
    ).skip(skip).limit(page_size)
    
    clubs = await clubs_cursor.to_list(length=page_size)
    
    # Convert to response format
    club_responses = []
    for club in clubs:
        club_responses.append(SimpleClubResponse(
            id=str(club["_id"]),
            name=club["name"],
            name_based_id=club["name_based_id"]
        ))
    
    return SimpleClubListResponse(
        clubs=club_responses,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )


@router.get("/clubs/{club_id}", response_model=ClubResponse)
async def get_club(
    club_id: str, current_user: Optional[dict] = Depends(get_current_user)
):
    """Get a specific approved club by ID (basic view - use /details for full view) - requires authentication"""
    club_collection = get_club_collection()

    # Check if club_id is a name-based ID or ObjectId
    if is_valid_name_based_id(club_id):
        # Search by name-based ID with approved status filter
        club = await club_collection.find_one(
            {"name_based_id": club_id, "status": "approved"}  # Only approved clubs
        )

        if not club:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Approved club not found"
            )

        return await club_document_to_response_with_user_data(club, current_user)
    else:
        # Try as ObjectId
        try:
            club_object_id = ObjectId(club_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid club ID format"
            )

        club = await club_collection.find_one(
            {"_id": club_object_id, "status": "approved"}  # Only approved clubs
        )

        if not club:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Approved club not found"
            )

        return await club_document_to_response_with_user_data(club, current_user)


@router.get("/all/clubs/{club_id}", response_model=ClubResponse)
async def get_public_club(club_id: str):
    """
    Get a specific approved club by ID for public access (no authentication required).
    Perfect for public club browsing and discovery.
    """
    club_collection = get_club_collection()

    # Check if club_id is a name-based ID or ObjectId
    if is_valid_name_based_id(club_id):
        # Search by name-based ID with approved status filter
        club = await club_collection.find_one(
            {"name_based_id": club_id, "status": "approved"}  # Only approved clubs
        )

        if not club:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Approved club not found"
            )

        return await club_document_to_public_response(club)
    else:
        # Try as ObjectId
        try:
            club_object_id = ObjectId(club_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid club ID format"
            )

        club = await club_collection.find_one(
            {"_id": club_object_id, "status": "approved"}  # Only approved clubs
        )

        if not club:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Approved club not found"
            )

        return await club_document_to_public_response(club)


# @router.get("/clubs/{club_id}/details", response_model=ClubDetailsResponse)
# async def get_club_details(
#     club_id: str,
#     current_user: Optional[dict] = Depends(get_current_user)
# ):
#     """Get detailed club information with membership-based access"""
#     club_collection = get_club_collection()

#     try:
#         club_object_id = ObjectId(club_id)
#     except Exception:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Invalid club ID format"
#         )

#     # Get club from database
#     club = await club_collection.find_one({"_id": club_object_id, "is_active": True})

#     if not club:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Club not found"
#         )

#     # Check user membership if user is logged in
#     user_membership = None
#     is_member = False
#     can_join = True
#     join_requirements = []

#     if current_user:
#         user_membership = await check_user_membership(current_user["user_id"], club_id)
#         is_member = user_membership.is_member if user_membership else False

#         if not is_member:
#             can_join, join_requirements = await can_user_join_club(current_user["user_id"], club_id)

#     # Get captain info
#     captain_info = await get_detailed_captain_info(club["captain_id"])

#     # Build response based on membership status
#     if is_member and user_membership and user_membership.can_access_premium:
#         # Full details for members
#         stats = await build_club_stats(club)

#         # Mock member-only content (you can expand this based on your needs)
#         recent_picks = [
#             {"id": "pick1", "game": "Team A vs Team B", "prediction": "Team A", "odds": 1.85, "status": "pending"},
#             {"id": "pick2", "game": "Team C vs Team D", "prediction": "Over 2.5", "odds": 1.92, "status": "won"}
#         ]

#         member_benefits = [
#             "Access to all premium picks",
#             "Detailed analysis and reasoning",
#             "Real-time notifications",
#             "Historical performance data",
#             "Direct captain communication"
#         ]

#         club_response = ClubFullDetails(
#             id=str(club["_id"]),
#             name=club["name"],
#             description=club["description"],
#             sub_description=club.get("sub_description"),
#             logo_url=club.get("logo_url"),
#             category=club["category"],
#             bio=club.get("bio", club["description"]),  # Extended description
#             pricing_plans=club["pricing_plans"],
#             captain=captain_info,
#             stats=stats,
#             membership_info=user_membership,
#             is_preview=False,
#             is_active=club.get("is_active", True),
#             created_at=club["created_at"],
#             updated_at=club["updated_at"],
#             recent_picks=recent_picks,
#             member_benefits=member_benefits,
#             exclusive_content={"access_level": "premium", "content_count": 50}
#         )
#     else:
#         # Preview for non-members or logged-out users
#         basic_captain = ClubCaptain(
#             id=club["captain_id"],
#             full_name=captain_info.full_name,
#             avatar_url=captain_info.avatar_url
#         )

#         club_response = ClubPreview(
#             id=str(club["_id"]),
#             name=club["name"],
#             description=club["description"],
#             sub_description=club.get("sub_description"),
#             logo_url=club.get("logo_url"),
#             category=club["category"],
#             win_pct=club.get("win_pct", 0.0),
#             member_count=club.get("member_count", 0),
#             pricing_plans=club["pricing_plans"],
#             captain=basic_captain,
#             is_preview=True,
#             recent_picks_count=club.get("total_bets", 0)
#         )

#     return ClubDetailsResponse(
#         club=club_response,
#         user_membership=user_membership,
#         can_join=can_join,
#         join_requirements=join_requirements if join_requirements else None
#     )

# @router.get("/clubs/{club_id}/captain", response_model=CaptainInfoResponse)
# async def get_club_captain_info(
#     club_id: str,
#     current_user: Optional[dict] = Depends(get_current_user)
# ):
#     """Get detailed captain information for a club"""
#     club_collection = get_club_collection()

#     try:
#         club_object_id = ObjectId(club_id)
#     except Exception:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Invalid club ID format"
#         )

#     # Get club to verify it exists and get captain ID
#     club = await club_collection.find_one({"_id": club_object_id, "is_active": True})

#     if not club:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Club not found"
#         )

#     captain_id = club["captain_id"]

#     # Get detailed captain info
#     captain_info = await get_detailed_captain_info(captain_id)

#     # Get other clubs by this captain (excluding current club)
#     other_clubs_cursor = club_collection.find({
#         "captain_id": captain_id,
#         "is_active": True,
#         "_id": {"$ne": club_object_id}
#     }).limit(5)  # Limit to prevent large responses

#     other_clubs_docs = await other_clubs_cursor.to_list(length=5)
#     other_clubs = []

#     for club_doc in other_clubs_docs:
#         club_response = await club_document_to_response(club_doc)
#         other_clubs.append(club_response)

#     # Get aggregated stats
#     total_stats = await get_captain_stats(captain_id)

#     return CaptainInfoResponse(
#         captain=captain_info,
#         clubs=other_clubs,
#         total_stats=total_stats
#     )

# @router.post("/clubs/join", response_model=ClubJoinResponse)
# async def join_club(
#     join_request: ClubJoinRequest,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Join a club (trial or paid membership)"""
#     user_id = current_user["user_id"]
#     club_id = join_request.club_id
#     pricing_plan = join_request.pricing_plan.value

#     # Check if user is trial member
#     is_trial = await is_user_trial_member(user_id)
#     print(f"is_trial: {is_trial}")

#     if is_trial:
#         # Handle trial membership
#         can_join, restrictions = await can_join_club_trial(user_id, club_id)

#         if not can_join:
#             # Check if restriction is about club limit
#             restriction_msg = "; ".join(restrictions)
#             if "Trial limit reached" in restriction_msg:
#                 # Get club info for pricing
#                 club_collection = get_club_collection()
#                 try:
#                     club_object_id = ObjectId(club_id)
#                     club = await club_collection.find_one({"_id": club_object_id})

#                     if club:
#                         # Find the selected pricing plan
#                         club_price = None
#                         for plan in club.get("pricing_plans", []):
#                             if plan["plan"] == pricing_plan:
#                                 club_price = plan["price"]
#                                 break

#                         if club_price:
#                             restriction_msg += f" To join this club, pay ${club_price} for the {pricing_plan} plan."
#                 except Exception:
#                     pass

#             return ClubJoinResponse(
#                 success=False,
#                 message=restriction_msg,
#                 payment_required=True if "pay $" in restriction_msg else False
#             )

#         # Join as trial member
#         success, message = await join_club_trial(user_id, club_id, pricing_plan)

#         if success:
#             # Get updated trial status
#             trial_status = await get_trial_membership_status(user_id)
#             membership_info = await check_user_membership(user_id, club_id)

#             return ClubJoinResponse(
#                 success=True,
#                 message=message,
#                 membership_info=membership_info,
#                 payment_required=False,
#                 trial_status=trial_status
#             )
#         else:
#             return ClubJoinResponse(
#                 success=False,
#                 message=message
#             )

#     else:
#         # Handle paid membership
#         if not join_request.payment_method_id:
#             return ClubJoinResponse(
#                 success=False,
#                 message="Payment method required for paid membership",
#                 payment_required=True
#             )

#         # TODO: Implement Stripe payment processing
#         # For now, return payment required response
#         club_collection = get_club_collection()
#         try:
#             club_object_id = ObjectId(club_id)
#             club = await club_collection.find_one({"_id": club_object_id})

#             if not club:
#                 return ClubJoinResponse(
#                     success=False,
#                     message="Club not found"
#                 )

#             # Find pricing
#             club_price = None
#             for plan in club.get("pricing_plans", []):
#                 if plan["plan"] == pricing_plan:
#                     club_price = plan["price"]
#                     break

#             if not club_price:
#                 return ClubJoinResponse(
#                     success=False,
#                     message="Invalid pricing plan selected"
#                 )

#             # TODO: After successful payment processing, add member to club
#             # from .membership_service import add_member_to_club
#             # await add_member_to_club(user_id, club_id, pricing_plan, is_trial=False)

#             return ClubJoinResponse(
#                 success=False,
#                 message=f"Payment processing not implemented. Would charge ${club_price} for {pricing_plan} plan.",
#                 payment_required=True,
#                 payment_intent_id="stripe_payment_intent_id_placeholder"
#             )

#         except Exception:
#             return ClubJoinResponse(
#                 success=False,
#                 message="Error processing request"
#             )

# @router.get("/trial/status", response_model=TrialStatusResponse)
# async def get_trial_status(
#     current_user: dict = Depends(get_current_user)
# ):
#     """Get comprehensive trial membership status"""
#     user_id = current_user["user_id"]

#     # Get trial status
#     trial_status = await get_trial_membership_status(user_id)

#     # Get joined clubs
#     joined_clubs = []
#     if trial_status.is_trial_user:
#         joined_clubs = await get_trial_joined_clubs(user_id)

#     # Get available actions
#     available_actions = await get_available_trial_actions(user_id)

#     return TrialStatusResponse(
#         trial_status=trial_status,
#         joined_clubs=joined_clubs,
#         available_actions=available_actions,
#         limits=TRIAL_LIMITS
#     )

# @router.post("/trial/refund", response_model=RefundResponse)
# async def request_trial_refund(
#     refund_request: RefundRequest,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Request refund for trial memberships"""
#     user_id = current_user["user_id"]

#     success, message, refund_amount = await request_refund(
#         user_id,
#         refund_request.reason,
#         refund_request.club_ids
#     )

#     if success:
#         refunded_clubs = refund_request.club_ids if refund_request.club_ids else []
#         if not refunded_clubs:
#             # Get all trial memberships that were refunded
#             trial_clubs = await get_trial_joined_clubs(user_id)
#             refunded_clubs = [club.id for club in trial_clubs]

#         return RefundResponse(
#             success=True,
#             message=message,
#             refund_amount=refund_amount,
#             refunded_memberships=refunded_clubs,
#             refund_id=f"refund_{user_id}_{int(datetime.utcnow().timestamp())}"
#         )
#     else:
#         return RefundResponse(
#             success=False,
#             message=message
#         )

# @router.get("/trial/group-access", response_model=GroupAccessInfo)
# async def get_group_access_info(
#     current_user: dict = Depends(get_current_user)
# ):
#     """Get user's group access status for current week"""
#     user_id = current_user["user_id"]

#     if not await is_user_trial_member(user_id):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Group access limits only apply to trial members"
#         )

#     return await get_group_access_status(user_id)

# @router.post("/trial/access-group")
# async def access_group_endpoint(
#     current_user: dict = Depends(get_current_user)
# ):
#     """Record group access for trial user"""
#     user_id = current_user["user_id"]

#     success, message = await access_group(user_id)

#     if success:
#         # Get updated access info
#         access_info = await get_group_access_status(user_id)
#         return {
#             "success": True,
#             "message": message,
#             "group_access_info": access_info
#         }
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail=message
#         )

# @router.get("/trial/limits", response_model=TrialLimits)
# async def get_trial_limits():
#     """Get trial membership limits and configuration"""
#     return TRIAL_LIMITS

# # Enhanced membership status endpoint with trial info
# @router.get("/clubs/{club_id}/membership-status", response_model=MembershipStatusResponse)
# async def get_membership_status(
#     club_id: str,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Check current user's membership status for a specific club"""
#     club_collection = get_club_collection()

#     try:
#         club_object_id = ObjectId(club_id)
#     except Exception:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Invalid club ID format"
#         )

#     # Get club to verify it exists
#     club = await club_collection.find_one({"_id": club_object_id, "is_active": True})

#     if not club:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Club not found"
#         )

#     user_id = current_user["user_id"]

#     # Check membership status
#     membership_info = await check_user_membership(user_id, club_id)
#     is_member = membership_info.is_member if membership_info else False

#     # Check if user can join (trial or paid)
#     is_trial = await is_user_trial_member(user_id)
#     join_restrictions = []

#     if is_trial:
#         can_join, restrictions = await can_join_club_trial(user_id, club_id)
#         join_restrictions = restrictions
#     else:
#         can_join, restrictions = await can_user_join_club(user_id, club_id)
#         join_restrictions = restrictions

#     # Add trial-specific information to restrictions
#     if is_trial and not can_join:
#         trial_status = await get_trial_membership_status(user_id)
#         if trial_status.clubs_remaining == 0:
#             join_restrictions.append(
#                 f"Trial limit: {trial_status.clubs_joined_count}/{TRIAL_LIMITS.max_clubs} clubs joined. "
#                 f"Upgrade to paid membership to join more clubs."
#             )

#     return MembershipStatusResponse(
#         is_member=is_member,
#         membership_info=membership_info,
#         club_id=club_id,
#         club_name=club["name"],
#         available_plans=club["pricing_plans"],
#         can_join=can_join,
#         join_restrictions=join_restrictions if join_restrictions else None
#     )

# @router.put("/clubs/{club_id}", response_model=ClubUpdateResponse)
# async def update_club(
#     club_id: str,
#     club_data: ClubUpdateRequest,
#     current_captain: dict = Depends(get_club_owner)
# ):
#     """Update a club (only by the club owner)"""
#     club_collection = get_club_collection()

#     try:
#         club_object_id = ObjectId(club_id)
#     except Exception:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Invalid club ID format"
#         )

#     # Check if club exists and user owns it
#     club = await club_collection.find_one({"_id": club_object_id})

#     if not club:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Club not found"
#         )

#     if not verify_club_ownership(club["captain_id"], current_captain):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="You can only update your own clubs"
#         )

#     # Build update document
#     update_doc = {"updated_at": datetime.utcnow()}

#     if club_data.name is not None:
#         # Check for duplicate name for this captain
#         existing_club = await club_collection.find_one({
#             "captain_id": current_captain["user_id"],
#             "name": club_data.name,
#             "is_active": True,
#             "_id": {"$ne": club_object_id}
#         })

#         if existing_club:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="You already have another active club with this name"
#             )

#         update_doc["name"] = club_data.name

#     if club_data.description is not None:
#         update_doc["description"] = club_data.description

#     if club_data.sub_description is not None:
#         update_doc["sub_description"] = club_data.sub_description

#     if club_data.logo_url is not None:
#         update_doc["logo_url"] = club_data.logo_url

#     if club_data.category is not None:
#         update_doc["category"] = club_data.category.value

#     if club_data.pricing_plans is not None:
#         update_doc["pricing_plans"] = [plan.dict() for plan in club_data.pricing_plans]

#     if club_data.is_active is not None:
#         update_doc["is_active"] = club_data.is_active

#     # Update club
#     await club_collection.update_one(
#         {"_id": club_object_id},
#         {"$set": update_doc}
#     )

#     # Get updated club
#     updated_club = await club_collection.find_one({"_id": club_object_id})
#     club_response = await club_document_to_response(updated_club)

#     return ClubUpdateResponse(
#         message="Club updated successfully",
#         club=club_response
#     )

# @router.delete("/clubs/{club_id}", response_model=ClubDeleteResponse)
# async def delete_club(
#     club_id: str,
#     current_captain: dict = Depends(get_club_owner)
# ):
#     """Delete a club (soft delete - mark as inactive)"""
#     club_collection = get_club_collection()

#     try:
#         club_object_id = ObjectId(club_id)
#     except Exception:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Invalid club ID format"
#         )

#     # Check if club exists and user owns it
#     club = await club_collection.find_one({"_id": club_object_id})

#     if not club:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Club not found"
#         )

#     if not verify_club_ownership(club["captain_id"], current_captain):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="You can only delete your own clubs"
#         )

#     # Soft delete - mark as inactive
#     await club_collection.update_one(
#         {"_id": club_object_id},
#         {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
#     )

#     return ClubDeleteResponse(
#         message="Club deleted successfully",
#         club_id=club_id
#     )

# @router.get("/my-memberships", response_model=OngoingMembershipsResponse)
# async def get_my_memberships(
#     current_user: dict = Depends(get_current_user)
# ):
#     """Get all ongoing (active) memberships for the logged-in user"""
#     user_id = current_user["user_id"]

#     memberships = await get_ongoing_memberships(user_id)

#     return memberships

# @router.get("/my-memberships/summary", response_model=MembershipSummary)
# async def get_my_membership_summary(
#     current_user: dict = Depends(get_current_user)
# ):
#     """Get summary of user's membership status"""
#     user_id = current_user["user_id"]

#     summary = await get_membership_summary(user_id)

#     return summary

# @router.post("/my-memberships/{club_id}/cancel")
# async def cancel_my_membership(
#     club_id: str,
#     reason: Optional[str] = None,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Cancel a specific membership"""
#     user_id = current_user["user_id"]

#     success, message = await cancel_membership_by_id(user_id, club_id, reason)

#     if success:
#         return {
#             "success": True,
#             "message": message,
#             "club_id": club_id
#         }
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=message
#         )

# @router.post("/my-memberships/{club_id}/pause")
# async def pause_my_membership(
#     club_id: str,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Pause a specific paid membership"""
#     user_id = current_user["user_id"]

#     success, message = await pause_membership_by_id(user_id, club_id)

#     if success:
#         return {
#             "success": True,
#             "message": message,
#             "club_id": club_id
#         }
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=message
#         )

# @router.post("/my-memberships/{club_id}/resume")
# async def resume_my_membership(
#     club_id: str,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Resume a paused membership"""
#     user_id = current_user["user_id"]

#     success, message = await resume_membership_by_id(user_id, club_id)

#     if success:
#         return {
#             "success": True,
#             "message": message,
#             "club_id": club_id
#         }
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=message
#         )

# @router.get("/my-memberships/{club_id}/details", response_model=OngoingMembershipDetails)
# async def get_my_membership_details(
#     club_id: str,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Get detailed information about a specific membership"""
#     user_id = current_user["user_id"]

#     # Get all memberships and find the specific one
#     memberships = await get_ongoing_memberships(user_id)

#     for membership in memberships.memberships:
#         if membership.club_id == club_id:
#             return membership

#     raise HTTPException(
#         status_code=status.HTTP_404_NOT_FOUND,
#         detail="Membership not found"
#     )

# # Enhanced my-clubs endpoint to show only owned clubs (for captains)
# @router.get("/my-clubs", response_model=ClubListResponse)
# async def get_my_clubs(
#     page: int = Query(1, ge=1),
#     page_size: int = Query(20, ge=1, le=100),
#     current_captain: dict = Depends(get_club_owner)
# ):
#     """Get all clubs owned by the current captain"""
#     club_collection = get_club_collection()

#     query = {"captain_id": current_captain["user_id"], "is_active": True}

#     # Get total count
#     total_count = await club_collection.count_documents(query)

#     # Calculate pagination
#     total_pages = math.ceil(total_count / page_size)
#     skip = (page - 1) * page_size

#     # Get clubs
#     cursor = club_collection.find(query).sort([("created_at", -1)]).skip(skip).limit(page_size)
#     clubs = await cursor.to_list(length=page_size)

#     # Convert to response format
#     club_responses = []
#     for club in clubs:
#         club_response = await club_document_to_response(club)
#         club_responses.append(club_response)

#     return ClubListResponse(
#         clubs=club_responses,
#         total_count=total_count,
#         page=page,
#         page_size=page_size,
#         total_pages=total_pages,
#         has_next=page < total_pages,
#         has_previous=page > 1
#     )

# @router.post("/clubs/search", response_model=ClubListResponse)
# async def search_clubs(
#     search_request: ClubSearchRequest,
#     current_user: Optional[dict] = Depends(get_current_user)
# ):
#     """Advanced club search with filters, sorting, and pagination"""
#     club_collection = get_club_collection()

#     # Build query from filters
#     query = {"is_active": True}

#     if search_request.filters:
#         query = build_filter_query(search_request.filters)

#         # Handle captain name search
#         if search_request.filters.search:
#             user_collection = get_user_collection()
#             search_pattern = re.compile(search_request.filters.search, re.IGNORECASE)

#             matching_captains = await user_collection.find(
#                 {"full_name": {"$regex": search_pattern}, "role": "Captain"}
#             ).to_list(None)

#             captain_ids = [str(captain["_id"]) for captain in matching_captains]

#             if captain_ids:
#                 if "$or" in query:
#                     query["$or"].append({"captain_id": {"$in": captain_ids}})
#                 else:
#                     query["$or"] = [
#                         {"name": {"$regex": search_pattern}},
#                         {"description": {"$regex": search_pattern}},
#                         {"captain_id": {"$in": captain_ids}}
#                     ]

#     # Get total count
#     total_count = await club_collection.count_documents(query)

#     # Calculate pagination
#     page = search_request.pagination.page
#     page_size = search_request.pagination.page_size
#     total_pages = math.ceil(total_count / page_size)
#     skip = (page - 1) * page_size

#     # Get sort criteria
#     sort_criteria = get_sort_criteria(search_request.sort_by)

#     # Execute query
#     cursor = club_collection.find(query).sort(sort_criteria).skip(skip).limit(page_size)
#     clubs = await cursor.to_list(length=page_size)

#     # Convert to response format
#     club_responses = []
#     for club in clubs:
#         club_response = await club_document_to_response(club)
#         club_responses.append(club_response)

#     return ClubListResponse(
#         clubs=club_responses,
#         total_count=total_count,
#         page=page,
#         page_size=page_size,
#         total_pages=total_pages,
#         has_next=page < total_pages,
#         has_previous=page > 1
#     )

# @router.get("/my-memberships/past", response_model=PastMembershipsResponse)
# async def get_my_past_memberships(
#     current_user: dict = Depends(get_current_user)
# ):
#     """Get all past (ended/cancelled) memberships for the logged-in user"""
#     user_id = current_user["user_id"]

#     past_memberships = await get_past_memberships(user_id)

#     return past_memberships

# @router.get("/my-memberships/history", response_model=MembershipHistorySummary)
# async def get_my_membership_history(
#     current_user: dict = Depends(get_current_user)
# ):
#     """Get comprehensive membership history summary"""
#     user_id = current_user["user_id"]

#     history = await get_membership_history_summary(user_id)

#     return history

# @router.get("/my-memberships/past/{club_id}/can-rejoin")
# async def check_can_rejoin_club(
#     club_id: str,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Check if user can rejoin a club they previously left"""
#     user_id = current_user["user_id"]

#     can_rejoin, message = await can_rejoin_club(user_id, club_id)

#     return {
#         "can_rejoin": can_rejoin,
#         "message": message,
#         "club_id": club_id
#     }

# @router.get("/my-memberships/rejoinable")
# async def get_my_rejoinable_clubs(
#     current_user: dict = Depends(get_current_user)
# ):
#     """Get list of clubs user can rejoin"""
#     user_id = current_user["user_id"]

#     rejoinable_club_ids = await get_rejoinable_clubs(user_id)

#     return {
#         "rejoinable_clubs": rejoinable_club_ids,
#         "count": len(rejoinable_club_ids)
#     }

# @router.post("/my-memberships/past/{club_id}/rejoin", response_model=ClubJoinResponse)
# async def rejoin_past_club(
#     club_id: str,
#     join_request: ClubJoinRequest,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Rejoin a club that user was previously a member of"""
#     user_id = current_user["user_id"]

#     # Check if user can rejoin
#     can_rejoin, message = await can_rejoin_club(user_id, club_id)

#     if not can_rejoin:
#         return ClubJoinResponse(
#             success=False,
#             message=message
#         )

#     # Override the club_id in join_request to ensure consistency
#     join_request.club_id = club_id

#     # Use the existing join_club logic
#     from .trial_service import is_user_trial_member, can_join_club_trial, join_club_trial

#     pricing_plan = join_request.pricing_plan.value

#     # Check if user is trial member
#     is_trial = await is_user_trial_member(user_id)

#     if is_trial:
#         # Handle trial membership
#         can_join, restrictions = await can_join_club_trial(user_id, club_id)

#         if not can_join:
#             return ClubJoinResponse(
#                 success=False,
#                 message="; ".join(restrictions)
#             )

#         # Join as trial member
#         success, message = await join_club_trial(user_id, club_id, pricing_plan)

#         if success:
#             # Get updated trial status
#             from .trial_service import get_trial_membership_status
#             trial_status = await get_trial_membership_status(user_id)
#             membership_info = await check_user_membership(user_id, club_id)

#             return ClubJoinResponse(
#                 success=True,
#                 message=f"Successfully rejoined {join_request.club_id}! {message}",
#                 membership_info=membership_info,
#                 payment_required=False,
#                 trial_status=trial_status
#             )
#         else:
#             return ClubJoinResponse(
#                 success=False,
#                 message=message
#             )

#     else:
#         # Handle paid membership
#         if not join_request.payment_method_id:
#             return ClubJoinResponse(
#                 success=False,
#                 message="Payment method required for paid membership",
#                 payment_required=True
#             )

#         # TODO: Implement Stripe payment processing for rejoin
#         return ClubJoinResponse(
#             success=False,
#             message="Payment processing for rejoin not implemented yet",
#             payment_required=True
#         )

# # ============================================================================
# # IMAGE UPLOAD ENDPOINTS
# # ============================================================================

# @router.post("/upload/image", response_model=ImageUploadResponse)
# async def upload_image(
#     file: UploadFile,
#     purpose: str = Form(..., description="Upload purpose: club_logo, club_banner, user_avatar, club_gallery, general"),
#     resize: bool = Form(True, description="Whether to resize the image"),
#     max_width: int = Form(800, description="Maximum width for resizing"),
#     max_height: int = Form(800, description="Maximum height for resizing"),
#     quality: int = Form(85, description="JPEG quality (1-100)"),
#     club_id: Optional[str] = Form(None, description="Club ID if uploading for a club"),
#     current_user: dict = Depends(get_current_user)
# ):
#     """
#     Upload an image file

#     Supported purposes:
#     - club_logo: Club logo images
#     - club_banner: Club banner images
#     - user_avatar: User profile pictures
#     - club_gallery: Club gallery images
#     - general: General purpose images

#     File requirements:
#     - Max size: 10MB
#     - Formats: JPG, JPEG, PNG, GIF, WebP
#     - Min dimensions: 100x100 pixels
#     - Max dimensions: 4000x4000 pixels
#     """
#     try:
#         # Validate purpose
#         valid_purposes = ["club_logo", "club_banner", "user_avatar", "club_gallery", "general"]
#         if purpose not in valid_purposes:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail=f"Invalid purpose. Must be one of: {', '.join(valid_purposes)}"
#             )

#         # Validate quality parameter
#         if not 1 <= quality <= 100:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Quality must be between 1 and 100"
#             )

#         # Validate dimensions
#         if max_width < 100 or max_height < 100:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Maximum dimensions must be at least 100x100 pixels"
#             )

#         # Process and upload image
#         result = await image_service.process_image(
#             file=file,
#             purpose=purpose,
#             resize=resize,
#             max_width=max_width,
#             max_height=max_height,
#             quality=quality
#         )

#         # Add user information to metadata
#         user_id = current_user["user_id"]
#         result["metadata"]["uploaded_by"] = user_id
#         if club_id:
#             result["metadata"]["club_id"] = club_id

#         return ImageUploadResponse(
#             success=True,
#             message="Image uploaded successfully",
#             image_url=result["image_url"],
#             image_id=result["image_id"],
#             filename=result["filename"],
#             file_size=result["file_size"],
#             content_type=result["content_type"],
#             upload_timestamp=result["upload_timestamp"],
#             metadata=result["metadata"]
#         )

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error uploading image: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to upload image: {str(e)}"
#         )

# @router.post("/upload/club-logo", response_model=ImageUploadResponse)
# async def upload_club_logo(
#     file: UploadFile,
#     club_id: str = Form(..., description="Club ID"),
#     resize: bool = Form(True, description="Whether to resize the image"),
#     max_width: int = Form(400, description="Maximum width for logo (recommended: 400px)"),
#     max_height: int = Form(400, description="Maximum height for logo (recommended: 400px)"),
#     quality: int = Form(90, description="JPEG quality (1-100)"),
#     current_user: dict = Depends(get_current_user)
# ):
#     """
#     Upload a club logo image

#     This endpoint is specifically designed for club logos with optimized settings:
#     - Recommended dimensions: 400x400 pixels
#     - High quality (90) for crisp logos
#     - Automatic resizing to maintain aspect ratio
#     """
#     try:
#         # Verify user is the club captain
#         await verify_club_ownership(current_user["user_id"], club_id)

#         # Process and upload image
#         result = await image_service.process_image(
#             file=file,
#             purpose="club_logo",
#             resize=resize,
#             max_width=max_width,
#             max_height=max_height,
#             quality=quality
#         )

#         # Add metadata
#         user_id = current_user["user_id"]
#         result["metadata"]["uploaded_by"] = user_id
#         result["metadata"]["club_id"] = club_id

#         return ImageUploadResponse(
#             success=True,
#             message="Club logo uploaded successfully",
#             image_url=result["image_url"],
#             image_id=result["image_id"],
#             filename=result["filename"],
#             file_size=result["file_size"],
#             content_type=result["content_type"],
#             upload_timestamp=result["upload_timestamp"],
#             metadata=result["metadata"]
#         )

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error uploading club logo: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to upload club logo: {str(e)}"
#         )

# @router.post("/upload/user-avatar", response_model=ImageUploadResponse)
# async def upload_user_avatar(
#     file: UploadFile,
#     resize: bool = Form(True, description="Whether to resize the image"),
#     max_width: int = Form(300, description="Maximum width for avatar (recommended: 300px)"),
#     max_height: int = Form(300, description="Maximum height for avatar (recommended: 300px)"),
#     quality: int = Form(85, description="JPEG quality (1-100)"),
#     current_user: dict = Depends(get_current_user)
# ):
#     """
#     Upload a user avatar image

#     This endpoint is specifically designed for user avatars with optimized settings:
#     - Recommended dimensions: 300x300 pixels
#     - Balanced quality (85) for good appearance and file size
#     - Automatic resizing to maintain aspect ratio
#     """
#     try:
#         # Process and upload image
#         result = await image_service.process_image(
#             file=file,
#             purpose="user_avatar",
#             resize=resize,
#             max_width=max_width,
#             max_height=max_height,
#             quality=quality
#         )

#         # Add metadata
#         user_id = current_user["user_id"]
#         result["metadata"]["uploaded_by"] = user_id
#         result["metadata"]["user_id"] = user_id

#         return ImageUploadResponse(
#             success=True,
#             message="User avatar uploaded successfully",
#             image_url=result["image_url"],
#             image_id=result["image_id"],
#             filename=result["filename"],
#             file_size=result["file_size"],
#             content_type=result["content_type"],
#             upload_timestamp=result["upload_timestamp"],
#             metadata=result["metadata"]
#         )

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error uploading user avatar: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to upload user avatar: {str(e)}"
#         )

# @router.delete("/upload/image/{image_path:path}")
# async def delete_image(
#     image_path: str,
#     current_user: dict = Depends(get_current_user)
# ):
#     """
#     Delete an uploaded image

#     Note: Users can only delete images they uploaded
#     """
#     try:
#         # Get image info to verify ownership
#         image_info = image_service.get_image_info(image_path)
#         if not image_info:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Image not found"
#             )

#         # TODO: Add ownership verification logic here
#         # For now, allow deletion if user is authenticated

#         # Delete the image
#         success = await image_service.delete_image(image_path)

#         if success:
#             return {
#                 "success": True,
#                 "message": "Image deleted successfully",
#                 "deleted_path": image_path
#             }
#         else:
#             raise HTTPException(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 detail="Failed to delete image"
#             )

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error deleting image: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to delete image: {str(e)}"
#         )

# @router.get("/upload/image/{image_path:path}")
# async def get_image_info(
#     image_path: str,
#     current_user: dict = Depends(get_current_user)
# ):
#     """
#     Get information about an uploaded image
#     """
#     try:
#         image_info = image_service.get_image_info(image_path)

#         if not image_info:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Image not found"
#             )

#         return {
#             "success": True,
#             "image_info": image_info
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting image info: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to get image info: {str(e)}"
#         )

# ============================================================================
# GENERAL IMAGE UPLOAD ENDPOINT (NO AUTHENTICATION REQUIRED)
# ============================================================================


@router.post("/upload-images", response_model=ImageUploadResponse)
async def upload_general_image(
    file: UploadFile,
    resize: bool = Form(True, description="Whether to resize the image"),
    max_width: int = Form(800, description="Maximum width for resizing"),
    max_height: int = Form(800, description="Maximum height for resizing"),
    quality: int = Form(85, description="JPEG quality (1-100)"),
):
    """
    Upload a general image file without authentication

    This endpoint allows frontend applications to upload images without requiring user authentication.
    Perfect for general purpose image uploads where user context is not needed.

    File requirements:
    - Max size: 10MB
    - Formats: JPG, JPEG, PNG, GIF, WebP
    - Min dimensions: 100x100 pixels
    - Max dimensions: 4000x4000 pixels

    Returns:
    - Image URL for immediate use
    - File metadata and processing information
    """
    try:
        # Validate quality parameter
        if not 1 <= quality <= 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quality must be between 1 and 100",
            )

        # Validate dimensions
        if max_width < 100 or max_height < 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum dimensions must be at least 100x100 pixels",
            )

        # Process and upload image with general purpose
        result = await image_service.process_image(
            file=file,
            purpose="general",
            resize=resize,
            max_width=max_width,
            max_height=max_height,
            quality=quality,
        )

        # Add general upload metadata
        result["metadata"]["upload_type"] = "general"
        result["metadata"]["requires_auth"] = False

        return ImageUploadResponse(
            success=True,
            message="General image uploaded successfully",
            image_url=result["image_url"],
            image_id=result["image_id"],
            filename=result["filename"],
            file_size=result["file_size"],
            content_type=result["content_type"],
            upload_timestamp=result["upload_timestamp"],
            metadata=result["metadata"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading general image: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload general image: {str(e)}",
        )


# ============================================================================
# IMAGE MANAGEMENT ENDPOINTS
# ============================================================================


@router.put("/update-club-step2")
async def update_club_step2(
    step2_data: ClubStep2UpdateSimpleRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Update club with step 2 data (what's included + top 3 sports)

    **Features:**
    - **Step 2 Update**: Update club with selected inclusions and top 3 sports
    - **Data Source**: Selections come from admin database (inclusions and sports tables)
    - **Validation**: Ensures captain owns the club and can proceed from step 1 to step 2
    - **Captain Only**: Restricted to captains with active paid/trial membership
    - **Reusable**: Can be used to update step 2 data even after initial completion

    **Request Body:**
    - `club_id`: ID of the club to update (can be ObjectId or name_based_id)
    - `whats_included`: List of selected inclusion titles (only title required)
    - `top_3_sports`: List of selected sport names (only name required) - max 3

    **Response includes:**
    - Updated club details with step 2 data
    - club_complete_step remains at 2 or higher (preserves existing progress)
    - Selected inclusions and sports (with complete data fetched from admin database)

    **Use Cases:**
    - Complete club setup step 2 (initial completion)
    - Update existing step 2 data (add/remove/modify inclusions or sports)
    - Select club benefits and features
    - Choose primary sports for the club
    - Progress club creation workflow

    **Example Usage:**
    ```
    # Initial step 2 completion
    PUT /api/v1/update-club-step2
    {
        "club_id": "football-group",
        "whats_included": [
            {"title": "Daily Expert Picks"},
            {"title": "Premium Analysis"}
        ],
        "top_3_sports": [
            {"name": "Football"},
            {"name": "Basketball"},
            {"name": "Cricket"}
        ]
    }

    # Subsequent update (add/remove inclusions or sports)
    PUT /api/v1/update-club-step2
    {
        "club_id": "football-group",
        "whats_included": [
            {"title": "Live Chat"},
            {"title": "Main Chat"}
        ],
        "top_3_sports": [
            {"name": "Cricket"}
        ]
    }
    ```

    **Note:** The `club_id` field can accept either:
    - ObjectId (e.g., "64f7b1234567890abcdef123")
    - name_based_id (e.g., "football-group")

    The API will automatically fetch complete data (sub_desc, logo_url for inclusions and icon for sports) from the admin database.

    Captain-only access required. Club must be at step 1 or higher to update step 2 data.
    """
    try:
        logger.info(
            f"Starting update_club_step2 for club_id: {step2_data.club_id}, captain_id: {current_captain.get('user_id')}"
        )

        # Validate step 2 data
        is_valid, validation_message = (
            await club_step2_service.validate_step2_simple_data(step2_data)
        )
        if not is_valid:
            logger.warning(f"Step 2 data validation failed: {validation_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=validation_message,
                data=None,
            )

        logger.info(f"Step 2 data validation passed, proceeding with update")

        # Update club step 2 using simplified service
        updated_club = await club_step2_service.update_club_step2_simple(
            step2_data.club_id, step2_data, current_captain["user_id"]
        )
        print("updated_club", updated_club)

        if updated_club:
            logger.info(f"Club step 2 updated successfully, converting response")
            # Convert to response model and then to dict for JSON serialization
            try:
                club_response = ClubStep2Response(**updated_club)
                club_response_dict = club_response.model_dump()

                logger.debug(
                    f"Club step 2 response converted to dict: {club_response_dict}"
                )

                return create_response(
                    status_code=status.HTTP_200_OK,
                    status="success",
                    message="Club step 2 data updated successfully.",
                    data=club_response_dict,
                )
            except Exception as conversion_error:
                logger.error(
                    f"Error converting club step 2 response: {conversion_error}"
                )
                # Fallback: return the raw updated_club data
                return create_response(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    status="error",
                    message=f"Failed to serialize club step 2 response: {conversion_error}",
                    data=updated_club,
                )
        else:
            logger.error(
                f"Failed to update club step 2 for club_id: {step2_data.club_id}"
            )
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message="Failed to update club step 2. Please check club ID and ownership.",
                data=None,
            )

    except Exception as e:
        logger.error(f"Error in update_club_step2: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# CLUB STEP 3 ENDPOINT (Pricing Setup)
# ============================================================================


@router.put("/setup-pricing")
async def setup_club_pricing(
    step3_data: ClubStep3UpdateRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Setup club pricing (Step 3) - Only for captains with clubs at step 2

    This endpoint allows captains to set up pricing plans for their club:
    - Must have completed step 2 (inclusions and sports)
    - Can choose from monthly, quarterly, yearly frequencies
    - Sets club_complete_step = 3

    **Features:**
    - **Step 3 Update**: Setup pricing plans with frequency and price
    - **Validation**: Ensures club is at step 2 before proceeding to step 3
    - **Flexible Pricing**: Choose monthly, quarterly, yearly or any combination
    - **Captain Only**: Restricted to captains with active paid/trial membership

    **Request Body:**
    - `club_id`: ID of the club to update (can be ObjectId or name_based_id)
    - `pricing_plans`: List of pricing plans with frequency and price

    **Note:** The `club_id` field can accept either:
    - ObjectId (e.g., "64f7b1234567890abcdef123")
    - name_based_id (e.g., "football-group")

    **Pricing Plan Fields:**
    - `frequency`: "monthly", "quarterly", or "yearly"
    - `price`: Price amount (must be > 0)
    - `currency`: Currency code (defaults to "USD")

    **Response includes:**
    - Updated club details with pricing plans
    - New club_complete_step = 3
    - Complete club information from all steps

    **Use Cases:**
    - Complete club setup step 3
    - Set flexible pricing options
    - Choose pricing frequency (monthly/quarterly/yearly)
    - Finalize club creation workflow

    **Example Usage:**
    ```
    # Setup club pricing
    PUT /api/v1/setup-pricing
    {
        "club_id": "football-group",
        "pricing_plans": [
            {
                "frequency": "monthly",
                "price": 19.99,
                "currency": "USD"
            },
            {
                "frequency": "quarterly",
                "price": 49.99,
                "currency": "USD"
            },
            {
                "frequency": "yearly",
                "price": 179.99,
                "currency": "USD"
            }
        ]
    }
    ```

    **Note:** The `club_id` field can accept either:
    - ObjectId (e.g., "64f7b1234567890abcdef123")
    - name_based_id (e.g., "football-group")

    Captain-only access required. Club must be at step 2 to proceed to step 3.
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"Processing setup-pricing request for captain: {captain_id}")

        # Update club step 3
        logger.info(f"Calling club_step3_service.update_club_step3...")
        # Get admin_id for tj@mailinator.com
        admin_id = await club_step3_service.get_admin_id_for_tj()
        logger.info(f"Retrieved admin_id for tj@mailinator.com: {admin_id}")
        
        updated_club = await club_step3_service.update_club_step3(
            step3_data, captain_id, admin_id
        )

        if updated_club:
            logger.info("Club step 3 update successful, processing response...")

            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club pricing setup completed successfully. Club is now ready for members.",
                data=updated_club,
            )
        else:
            logger.warning("Club step 3 update returned None")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message="Failed to setup club pricing. Please check club ID, ownership, and step completion.",
                data=None,
            )

    except ValueError as e:
        # Handle validation errors
        return create_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
            message=str(e),
            data=None,
        )
    except Exception as e:
        logger.error(f"Unexpected error in setup_club_pricing: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# CLUB STEP 4 ENDPOINT (Moderator Setup)
# ============================================================================


@router.put("/setup-moderators")
async def setup_club_moderators(
    step4_data: ClubStep4UpdateRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Setup club moderators (Step 4) - Only for captains with clubs at step 3

    This endpoint allows captains to invite moderators to their club:
    - Must have completed step 3 (pricing setup)
    - First moderator is free, additional moderators cost $9.95/month
    - Creates Stripe products/prices for paid moderator subscriptions
    - Sends invitation emails to potential moderators
    - Sets club_complete_step = 4

    **Features:**
    - **Step 4 Update**: Setup moderator invitations with email addresses
    - **Validation**: Ensures club is at step 3 before proceeding to step 4
    - **Pricing Model**: First moderator free, $9.95/month for additional ones
    - **Email Invitations**: Sends professional invitation emails
    - **Captain Only**: Restricted to captains with active paid/trial membership

    **Request Body:**
    - `club_id`: ID of the club to update (can be ObjectId or name_based_id)
    - `moderator_emails`: List of moderator email addresses (optional - if not provided, will set up empty moderator structure)

    **Note:** The `club_id` field can accept either:
    - ObjectId (e.g., "64f7b1234567890abcdef123")
    - name_based_id (e.g., "football-group")

    **Moderator Pricing:**
    - **Free**: First moderator (no cost)
    - **Paid**: Additional moderators at $9.95/month each
    - **Always Returned**: Pricing information is always included in response, even with no moderators

    **Response includes:**
    - Updated club details with moderator information
    - New club_complete_step = 4
    - Moderator pricing information
    - Moderator invitation details and status

    **Use Cases:**
    - Complete club setup step 4
    - Invite moderators to help manage the club
    - Set up moderator pricing structure
    - Finalize club creation workflow

    **Example Usage:**
    ```
    # Setup club moderators with specific emails
    PUT /api/v1/setup-moderators
    {
        "club_id": "football-group",
        "moderator_emails": [
            "moderator1@example.com",
            "moderator2@example.com",
            "moderator3@example.com"
        ]
    }

    # Setup club moderators without emails (empty structure)
    PUT /api/v1/setup-moderators
    {
        "club_id": "football-group",
        "moderator_emails": []
    }

    # Setup club moderators without emails (field omitted)
    PUT /api/v1/setup-moderators
    {
        "club_id": "football-group"
    }
    ```

    **Note:** The `club_id` field can accept either:
    - ObjectId (e.g., "64f7b1234567890abcdef123")
    - name_based_id (e.g., "football-group")

    Captain-only access required. Club must be at step 3 to proceed to step 4.
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"Processing setup-moderators request for captain: {captain_id}")

        # Update club step 4
        logger.info(f"Calling club_step4_service.update_club_step4...")
        updated_club = await club_step4_service.update_club_step4(
            step4_data, captain_id
        )

        if updated_club:
            logger.info("Club step 4 update successful, processing response...")

            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club moderator setup completed successfully. Invitations have been sent.",
                data=updated_club,
            )
        else:
            logger.warning("Club step 4 update returned None")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message="Failed to setup club moderators. Please check club ID, ownership, and step completion.",
                data=None,
            )

    except ValueError as e:
        # Handle validation errors
        return create_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
            message=str(e),
            data=None,
        )
    except Exception as e:
        logger.error(f"Unexpected error in setup_club_moderators: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/validate-moderator-token")
async def validate_moderator_token(token: str):
    """
    Validate moderator signup token

    This endpoint validates a moderator signup token and checks if it's valid.
    It decodes the token, verifies the signature, and checks the isvalid field.

    **Features:**
    - **Token Validation**: Validates token signature and format
    - **Payload Extraction**: Decodes token to get email, role, and validity status
    - **Security Check**: Verifies isvalid field is true
    - **Public Access**: No authentication required (token contains all needed info)

    **Query Parameters:**
    - `token`: The signup token to validate

    **Response:**
    - **200 OK**: Token is valid, returns decoded payload
    - **400 Bad Request**: Invalid token format or isvalid=false
    - **401 Unauthorized**: Token signature validation failed

    **Example Usage:**
    ```
    GET /api/v1/validate-moderator-token?token=eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJyb2xlIjoibW9kZXJhdG9yIiwiaXN2YWxpZCI6dHJ1ZX1fYWJjZGVmZ2hpams=
    ```
    """
    try:
        logger.info(f"Validating moderator token: {token[:20]}...")

        # Validate token using club_step4_service
        validation_result = await club_step4_service.validate_moderator_signup_token(
            token
        )

        if validation_result["valid"]:
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Token is valid",
                data=validation_result["payload"],
            )
        else:
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=validation_result["error"],
                data=None,
            )

    except ValueError as e:
        # Handle validation errors
        return create_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
            message=str(e),
            data=None,
        )
    except Exception as e:
        logger.error(f"Unexpected error validating moderator token: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/club/{club_id}/moderator-status")
async def get_club_moderator_status(
    club_id: str, current_captain: dict = Depends(get_current_captain)
):
    """
    Get club moderator setup status (Step 4)

    This endpoint allows captains to check the current status of their club's
    moderator setup and whether they can proceed to step 4.

    **Features:**
    - **Status Check**: Get current step completion status
    - **Moderator Info**: View existing moderator invitations if step 4 is completed
    - **Validation**: Ensures captain owns the club

    **Path Parameters:**
    - `club_id`: ID of the club to check (can be ObjectId or name_based_id)

    **Response includes:**
    - Current club_complete_step
    - Whether step 4 can be accessed
    - Existing moderator information (if step 4 completed)
    - Step completion status

    **Use Cases:**
    - Check if club is ready for moderator setup
    - View current moderator configuration
    - Monitor club creation progress

    **Example Usage:**
    ```
    # Check club moderator status using ObjectId
    GET /api/v1/club/64f7b1234567890abcdef123/moderator-status

    # Check club moderator status using name_based_id
    GET /api/v1/club/tennis-grand-slam-elite/moderator-status
    ```

    Captain-only access required.
    """
    try:
        captain_id = current_captain["user_id"]

        # Get club step 4 status
        status_info = await club_step4_service.get_club_step4_status(
            club_id, captain_id
        )

        if status_info:
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club moderator status retrieved successfully",
                data=status_info,
            )
        else:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Club not found or you don't have permission to access it",
                data=None,
            )

    except Exception as e:
        logger.error(f"Error in get_club_moderator_status: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.post("/moderator-invitation/respond")
async def respond_to_moderator_invitation(
    club_id: str = Query(..., description="Club ID"),
    moderator_email: str = Query(..., description="Moderator email"),
    response: str = Query(..., description="Response: 'accept' or 'decline'"),
    invitation_token: str = Query(..., description="Invitation token for validation"),
):
    """
    Handle moderator response to invitation (accept/decline)

    This endpoint allows invited moderators to respond to club invitations:
    - Accept or decline moderator role
    - Updates moderator status in database
    - Sends notification to club captain

    **Features:**
    - **Invitation Response**: Accept or decline moderator role
    - **Status Update**: Updates moderator status in club database
    - **Captain Notification**: Informs captain of moderator decision
    - **Token Validation**: Uses invitation token for security

    **Query Parameters:**
    - `club_id`: ID of the club (can be ObjectId or name_based_id)
    - `moderator_email`: Email address of the moderator
    - `response`: Response type ('accept' or 'decline')
    - `invitation_token`: Security token for invitation validation

    **Response includes:**
    - Success/failure status
    - Moderator response details
    - Club information

    **Use Cases:**
    - Moderator accepts invitation to join club
    - Moderator declines invitation
    - Track moderator invitation responses
    - Update club moderator roster

    **Example Usage:**
    ```
    # Accept moderator invitation
    POST /api/v1/moderator-invitation/respond?club_id=football-group&moderator_email=mod@example.com&response=accept&invitation_token=abc123

    # Decline moderator invitation
    POST /api/v1/moderator-invitation/respond?club_id=football-group&moderator_email=mod@example.com&response=decline&invitation_token=abc123
    ```

    Public endpoint - no authentication required (uses invitation token).
    """
    try:
        logger.info(
            f"Processing moderator invitation response: {response} from {moderator_email}"
        )

        # Process moderator response
        result = await club_step4_service.respond_to_moderator_invitation(
            club_id, moderator_email, response, invitation_token
        )

        if result and result.get("success"):
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message=result["message"],
                data=result,
            )
        else:
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("message", "Failed to process moderator response"),
                data=None,
            )

    except Exception as e:
        logger.error(f"Error in respond_to_moderator_invitation: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/club/{club_id}/pricing-status")
async def get_club_pricing_status(
    club_id: str, current_captain: dict = Depends(get_current_captain)
):
    """
    Get club pricing setup status (Step 3)

    This endpoint allows captains to check the current status of their club's
    pricing setup and whether they can proceed to step 3.

    **Features:**
    - **Status Check**: Get current step completion status
    - **Pricing Info**: View existing pricing plans if step 3 is completed
    - **Validation**: Ensures captain owns the club

    **Path Parameters:**
    - `club_id`: ID of the club to check (can be ObjectId or name_based_id)

    **Response includes:**
    - Current club_complete_step
    - Whether step 3 can be accessed
    - Existing pricing plans (if step 3 completed)
    - Step completion status

    **Use Cases:**
    - Check if club is ready for pricing setup
    - View current pricing configuration
    - Monitor club creation progress

    **Example Usage:**
    ```
    # Check club pricing status using ObjectId
    GET /api/v1/club/64f7b1234567890abcdef123/pricing-status

    # Check club pricing status using name_based_id
    GET /api/v1/club/tennis-grand-slam-elite/pricing-status
    ```

    Captain-only access required.
    """
    try:
        captain_id = current_captain["user_id"]

        # Get club step 3 status
        status_info = await club_step3_service.get_club_step3_status(
            club_id, captain_id
        )

        if status_info:
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club pricing status retrieved successfully",
                data=status_info,
            )
        else:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Club not found or you don't have permission to access it",
                data=None,
            )

    except Exception as e:
        logger.error(f"Error in get_club_pricing_status: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/club/by-name/{name_based_id}")
async def get_club_by_name_based_id(name_based_id: str):
    """
    Get club information by name_based_id

    This endpoint allows anyone to retrieve basic club information using
    the club's name_based_id (URL-friendly identifier).

    **Features:**
    - **Public Access**: No authentication required
    - **Name-based Lookup**: Find clubs by their URL-friendly ID
    - **Basic Info**: Returns non-sensitive club information

    **Path Parameters:**
    - `name_based_id`: URL-friendly identifier (e.g., "tennis-grand-slam-elite")

    **Response includes:**
    - Club basic information
    - Current completion step
    - Pricing plans (if available)

    **Use Cases:**
    - Public club discovery
    - Frontend routing with friendly URLs
    - Club information sharing

    **Example Usage:**
    ```
    # Get club by name_based_id
    GET /api/v1/club/by-name/tennis-grand-slam-elite
    ```

    Public access (no authentication required).
    """
    try:
        # Get club by name_based_id
        club_info = await club_step3_service.get_club_by_name_based_id(name_based_id)

        if club_info:
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club information retrieved successfully",
                data=club_info,
            )
        else:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Club not found",
                data=None,
            )

    except ValueError as e:
        return create_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
            message=str(e),
            data=None,
        )
    except Exception as e:
        logger.error(f"Error in get_club_by_name_based_id: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/pricing-frequencies")
async def get_pricing_frequencies():
    """
    Get available pricing frequencies for club setup

    This endpoint provides the list of available pricing frequencies that
    captains can choose from when setting up their club's pricing plans.

    **Response includes:**
    - List of available pricing frequencies
    - Used for club step 3 setup

    **Access:** Public endpoint (no authentication required)
    """
    try:
        from .models import PricingPlan

        frequencies = [
            {
                "value": PricingPlan.DAILY,
                "label": "Daily",
                "description": "Billed every day",
            },
            {
                "value": PricingPlan.WEEKLY,
                "label": "Weekly",
                "description": "Billed every week",
            },
            {
                "value": PricingPlan.MONTHLY,
                "label": "Monthly",
                "description": "Billed every month",
            },
            {
                "value": PricingPlan.QUARTERLY,
                "label": "Quarterly",
                "description": "Billed every 3 months",
            },
            {
                "value": PricingPlan.YEARLY,
                "label": "Yearly",
                "description": "Billed annually",
            },
            {
                "value": PricingPlan.LIFETIME,
                "label": "Lifetime",
                "description": "One-time payment for lifetime access",
            },
        ]

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Found {len(frequencies)} pricing frequencies",
            data=frequencies,
        )

    except Exception as e:
        logger.error(f"Error fetching pricing frequencies: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to fetch pricing frequencies: {str(e)}",
            data=None,
        )


# ============================================================================
# ADMIN DATA ENDPOINTS (Inclusions & Sports)
# ============================================================================


@router.get("/admin/inclusions", status_code=status.HTTP_200_OK)
async def get_admin_inclusions():
    """
    Get all available inclusions from admin database

    This endpoint fetches the complete list of inclusions that captains can select from
    when setting up their club's "What's Included" section.

    **Response includes:**
    - List of all available inclusions with title, sub_desc, and logo_url
    - Used for club step 2 setup

    **Access:** Public endpoint (no authentication required)
    """
    try:
        logger.info("=== Starting admin inclusions fetch ===")

        # Get inclusions collection
        inclusions_collection = get_inclusions_collection()
        logger.info("✅ Successfully got inclusions collection")

        # Check if collection exists and has documents
        collection_stats = await inclusions_collection.estimated_document_count()
        logger.info(f"Collection estimated document count: {collection_stats}")

        # Fetch all inclusions from admin database
        inclusions = await inclusions_collection.find({}, {"_id": 0}).to_list(
            length=None
        )

        logger.info(
            f"Found {len(inclusions) if inclusions else 0} inclusions in database"
        )

        if not inclusions:
            logger.warning(
                "No inclusions found in database - this might indicate a data issue"
            )
            # Return 200 OK with empty data instead of 404
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="No inclusions found in admin database",
                data=[],
            )

        logger.info(f"Successfully returning {len(inclusions)} inclusions")
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Found {len(inclusions)} inclusions",
            data=inclusions,
        )

    except Exception as e:
        logger.error(f"=== Error in admin inclusions endpoint ===")
        logger.error(f"Error fetching admin inclusions: {e}")
        logger.error(f"Exception type: {type(e)}")
        logger.error(f"Exception details: {str(e)}")

        # Return 500 for actual errors, not 404 for empty data
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to fetch inclusions: {str(e)}",
            data=None,
        )


@router.get("/admin/sports", status_code=status.HTTP_200_OK)
async def get_admin_sports():
    """
    Get all available sports from admin database

    This endpoint fetches the complete list of sports that captains can select from
    when setting up their club's "Top 3 Sports" section.

    **Response includes:**
    - List of all available sports with name and icon
    - Used for club step 2 setup

    **Access:** Public endpoint (no authentication required)
    """
    try:
        sports_collection = get_sports_collection()

        # Fetch all sports from admin database
        sports = await sports_collection.find({}, {"_id": 0}).to_list(length=None)

        if not sports:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="No sports found in admin database",
                data=[],
            )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Found {len(sports)} sports",
            data=sports,
        )

    except Exception as e:
        logger.error(f"Error fetching admin sports: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to fetch sports: {str(e)}",
            data=None,
        )


@router.get("/club/{club_id}/step-status", status_code=status.HTTP_200_OK)
async def get_club_step_status(
    club_id: str, current_captain: dict = Depends(get_current_captain)
):
    """
    Get the current step status of a club

    This endpoint allows captains to check the current completion step of their club
    and determine what needs to be done next.

    **Response includes:**
    - Current club_complete_step (0, 1, 2, or 3)
    - Club basic information including name_based_id
    - Next steps required

    **Access:** Captain authentication required
    """
    try:
        club_collection = get_club_collection()
        captain_id = current_captain["user_id"]

        # Check if club_id is a name_based_id or ObjectId

        if is_valid_name_based_id(club_id):
            # Search by name_based_id
            club = await club_collection.find_one(
                {"name_based_id": club_id, "captain_id": captain_id}
            )
        else:
            # Try to validate as ObjectId
            try:
                club = await club_collection.find_one(
                    {"_id": ObjectId(club_id), "captain_id": captain_id}
                )
            except Exception:
                return create_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    status="error",
                    message="Invalid club ID format",
                    data=None,
                )

        if not club:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Club not found or you don't have permission to access it",
                data=None,
            )

        current_step = club.get("club_complete_step", 0)

        # Determine next steps based on current step
        next_steps = []
        if current_step == 0:
            next_steps = ["Create basic club information"]
        elif current_step == 1:
            next_steps = ["Select inclusions and top 3 sports"]
        elif current_step == 2:
            next_steps = ["Set up pricing plans"]
        elif current_step == 3:
            next_steps = ["Club setup complete! Awaiting admin approval."]

        response_data = {
            "club_id": str(club["_id"]),
            "name": club.get("name"),
            "name_based_id": club.get("name_based_id", ""),
            "current_step": current_step,
            "next_steps": next_steps,
            "status": club.get("status"),
            "is_complete": current_step >= 3,
        }

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Club is at step {current_step}",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"Error getting club step status: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to get club step status: {str(e)}",
            data=None,
        )


# ============================================================================
# CLUB LISTING ENDPOINTS
# ============================================================================

# ============================================================================
# DEBUG ENDPOINTS (for troubleshooting)
# ============================================================================


@router.get("/debug/test-connection")
async def test_database_connection():
    """Test database connections for debugging"""
    try:
        from .db import (
            get_club_collection,
            get_inclusions_collection,
            get_sports_collection,
        )

        # Test club database
        club_collection = get_club_collection()
        club_count = await club_collection.count_documents({})

        # Test admin database connections
        inclusions_collection = get_inclusions_collection()
        sports_collection = get_sports_collection()

        try:
            inclusion_count = await inclusions_collection.count_documents({})
            sample_inclusions = (
                await inclusions_collection.find({}).limit(5).to_list(length=5)
            )
        except Exception as e:
            inclusion_count = f"Error: {str(e)}"
            sample_inclusions = []

        try:
            sports_count = await sports_collection.count_documents({})
            sample_sports = await sports_collection.find({}).limit(5).to_list(length=5)
        except Exception as e:
            sports_count = f"Error: {str(e)}"
            sample_sports = []

        return {
            "status": "success",
            "message": "Database connection test completed",
            "data": {
                "club_database": {
                    "name": os.getenv("DATABASE_NAME", "betting_main"),
                    "clubs_count": club_count,
                },
                "admin_database": {
                    "name": os.getenv("ADMIN_DATABASE_NAME", "betting_main"),
                    "inclusions_count": inclusion_count,
                    "sports_count": sports_count,
                    "sample_inclusions": [
                        inc.get("title") for inc in sample_inclusions
                    ],
                    "sample_sports": [sport.get("name") for sport in sample_sports],
                },
            },
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Database connection test failed: {str(e)}",
            "data": None,
        }


@router.get("/debug/clubs")
async def debug_list_clubs(current_user: dict = Depends(get_current_user_or_captain)):
    """Debug endpoint to list all clubs"""
    try:
        from .db import get_club_collection

        user_id = current_user["user_id"]
        user_role = current_user["role"]

        club_collection = get_club_collection()

        # Get all clubs
        all_clubs = await club_collection.find({}).to_list(None)

        # Get clubs owned by this captain
        captain_clubs = await club_collection.find({"captain_id": user_id}).to_list(
            None
        )

        return {
            "status": "success",
            "message": "Club list debug info",
            "data": {
                "user_id": user_id,
                "user_role": user_role,
                "total_clubs": len(all_clubs),
                "captain_clubs": [
                    {
                        "name": club.get("name"),
                        "name_based_id": club.get("name_based_id"),
                        "captain_id": club.get("captain_id"),
                        "is_active": club.get("is_active", True),
                    }
                    for club in captain_clubs
                ],
                "all_clubs": [
                    {
                        "name": club.get("name"),
                        "name_based_id": club.get("name_based_id"),
                        "captain_id": club.get("captain_id"),
                        "is_active": club.get("is_active", True),
                    }
                    for club in all_clubs[:10]  # Limit to first 10 for readability
                ],
            },
        }

    except Exception as e:
        return {"status": "error", "message": f"Debug error: {str(e)}", "data": None}


@router.get("/debug/hub-access/{club_name_based_id}")
async def debug_hub_access(
    club_name_based_id: str, current_user: dict = Depends(get_current_user_or_captain)
):
    """Debug endpoint to check hub access for a specific club"""
    try:
        from .db import get_club_collection, get_membership_collection
        from bson import ObjectId

        user_id = current_user["user_id"]
        user_role = current_user["role"]

        club_collection = get_club_collection()

        # Check if club exists
        club = await club_collection.find_one({"name_based_id": club_name_based_id})

        if not club:
            return {
                "status": "error",
                "message": f"Club '{club_name_based_id}' not found",
                "data": {
                    "user_id": user_id,
                    "user_role": user_role,
                    "club_name_based_id": club_name_based_id,
                },
            }

        # Check ownership/membership
        is_captain = user_role == "Captain"
        is_owner = club.get("captain_id") == user_id
        is_active = club.get("is_active", True)

        # For members, check membership
        is_member = False
        if not is_captain:
            membership_collection = get_membership_collection()
            membership = await membership_collection.find_one(
                {
                    "user_id": user_id,
                    "club_id": str(club["_id"]),
                    "subscription_status": {"$in": ["active", "pending"]},
                }
            )
            is_member = membership is not None

        return {
            "status": "success",
            "message": "Hub access debug info",
            "data": {
                "user_id": user_id,
                "user_role": user_role,
                "club_name_based_id": club_name_based_id,
                "club_info": {
                    "club_id": str(club["_id"]),
                    "name": club.get("name"),
                    "captain_id": club.get("captain_id"),
                    "is_active": is_active,
                },
                "access_check": {
                    "is_captain": is_captain,
                    "is_owner": is_owner,
                    "is_member": is_member,
                    "has_access": (is_captain and is_owner)
                    or (not is_captain and is_member),
                },
            },
        }

    except Exception as e:
        return {"status": "error", "message": f"Debug error: {str(e)}", "data": None}


@router.get("/debug/club/{club_id}")
async def debug_club_info(
    club_id: str, current_captain: dict = Depends(get_current_captain)
):
    """Debug endpoint to check club information"""
    try:
        from .db import get_club_collection
        from .id_utils import is_valid_name_based_id
        from bson import ObjectId

        club_collection = get_club_collection()

        # Try to find the club
        club = None
        search_method = ""

        if is_valid_name_based_id(club_id):
            search_method = "name_based_id"
            club = await club_collection.find_one({"name_based_id": club_id})
        else:
            try:
                search_method = "ObjectId"
                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({"_id": club_object_id})
            except:
                search_method = "invalid_format"

        if not club:
            # Check if there are similar clubs
            similar_clubs = (
                await club_collection.find(
                    {"name_based_id": {"$regex": club_id, "$options": "i"}}
                )
                .limit(5)
                .to_list(length=5)
            )

            return {
                "status": "error",
                "message": f"Club not found with {search_method}: {club_id}",
                "data": {
                    "search_method": search_method,
                    "similar_clubs": (
                        [c.get("name_based_id") for c in similar_clubs]
                        if similar_clubs
                        else []
                    ),
                    "total_clubs": await club_collection.count_documents({}),
                },
            }

        # Check ownership
        captain_id = current_captain.get("user_id")
        is_owner = club.get("captain_id") == captain_id

        return {
            "status": "success",
            "message": "Club information retrieved",
            "data": {
                "club_id": str(club["_id"]),
                "name_based_id": club.get("name_based_id"),
                "name": club.get("name"),
                "captain_id": club.get("captain_id"),
                "current_captain_id": captain_id,
                "is_owner": is_owner,
                "club_complete_step": club.get("club_complete_step", 0),
                "created_at": club.get("created_at"),
                "updated_at": club.get("updated_at"),
            },
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error retrieving club info: {str(e)}",
            "data": None,
        }


# ============================================================================
# CLUB STEP 2 ENDPOINT (What's Included + Top 3 Sports)
# ============================================================================


@router.get("/debug/admin-db")
async def debug_admin_database():
    """
    Debug endpoint to check admin database connectivity

    This endpoint helps troubleshoot admin database connection issues by testing
    the connection to inclusions and sports collections.

    **Access:** Public (for debugging purposes)
    """
    try:
        from .db import get_inclusions_collection, get_sports_collection

        logger.info("Testing admin database connectivity...")

        # Test inclusions collection
        try:
            inclusions_collection = get_inclusions_collection()
            inclusions_count = await inclusions_collection.count_documents({})
            logger.info(
                f"Successfully connected to inclusions collection. Count: {inclusions_count}"
            )

            # Get a sample inclusion
            sample_inclusion = await inclusions_collection.find_one({})
            sample_inclusion_data = (
                {
                    "title": (
                        sample_inclusion.get("title") if sample_inclusion else None
                    ),
                    "sub_desc": (
                        sample_inclusion.get("sub_desc") if sample_inclusion else None
                    ),
                    "logo_url": (
                        sample_inclusion.get("logo_url") if sample_inclusion else None
                    ),
                }
                if sample_inclusion
                else None
            )

        except Exception as e:
            logger.error(f"Failed to connect to inclusions collection: {e}")
            inclusions_count = None
            sample_inclusion_data = None

        # Test sports collection
        try:
            sports_collection = get_sports_collection()
            sports_count = await sports_collection.count_documents({})
            logger.info(
                f"Successfully connected to sports collection. Count: {sports_count}"
            )

            # Get a sample sport
            sample_sport = await sports_collection.find_one({})
            sample_sport_data = (
                {
                    "name": sample_sport.get("name") if sample_sport else None,
                    "icon": sample_sport.get("icon") if sample_sport else None,
                }
                if sample_sport
                else None
            )

        except Exception as e:
            logger.error(f"Failed to connect to sports collection: {e}")
            sports_count = None
            sample_sport_data = None

        debug_info = {
            "admin_database_status": (
                "connected"
                if (inclusions_count is not None or sports_count is not None)
                else "failed"
            ),
            "inclusions_collection": {
                "status": "connected" if inclusions_count is not None else "failed",
                "count": inclusions_count,
                "sample_data": sample_inclusion_data,
            },
            "sports_collection": {
                "status": "connected" if sports_count is not None else "failed",
                "count": sports_count,
                "sample_data": sample_sport_data,
            },
        }

        if debug_info["admin_database_status"] == "connected":
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Admin database connectivity test completed",
                data=debug_info,
            )
        else:
            return create_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Admin database connectivity test failed",
                data=debug_info,
            )

    except Exception as e:
        logger.error(f"Error in debug_admin_database: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Debug error: {str(e)}",
            data=None,
        )


@router.post("/debug/create-test-club")
async def create_test_club(current_captain: dict = Depends(get_current_captain)):
    """
    Debug endpoint to create a test club for testing purposes

    This endpoint creates a simple test club that can be used to test
    the step 2 update functionality.

    **Access:** Captain only (for testing)
    """
    try:
        from .db import get_club_collection
        from .id_utils import generate_unique_name_based_id
        from datetime import datetime, timezone

        club_collection = get_club_collection()
        captain_id = current_captain.get("user_id")

        logger.info(f"Creating test club for captain: {captain_id}")

        # Create a test club
        test_club = {
            "name": "Test Club for Debugging",
            "name_based_id": "test-club-debug",
            "description": "This is a test club created for debugging the step 2 update functionality",
            "sub_description": "Test club for debugging",
            "captain_id": captain_id,
            "club_complete_step": 1,  # Start at step 1
            "status": "active",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        # Insert the test club
        result = await club_collection.insert_one(test_club)

        if result.inserted_id:
            logger.info(f"Test club created successfully with ID: {result.inserted_id}")
            return create_response(
                status_code=status.HTTP_201_CREATED,
                status="success",
                message="Test club created successfully",
                data={
                    "club_id": str(result.inserted_id),
                    "name_based_id": "test-club-debug",
                    "club_complete_step": 1,
                    "message": "You can now test the step 2 update with this club",
                },
            )
        else:
            logger.error("Failed to create test club")
            return create_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Failed to create test club",
                data=None,
            )

    except Exception as e:
        logger.error(f"Error creating test club: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error creating test club: {str(e)}",
            data=None,
        )


# ============================================================================
# CLUB STEP 2 ENDPOINT (What's Included + Top 3 Sports)
# ============================================================================


@router.get("/debug/available-data")
async def get_available_admin_data():
    """
    Debug endpoint to get available inclusions and sports from admin database

    This endpoint helps troubleshoot by showing what data is available
    for club step 2 setup.

    **Access:** Public (for debugging purposes)
    """
    try:
        from .db import get_inclusions_collection, get_sports_collection

        logger.info("Fetching available admin data for debugging...")

        # Get inclusions
        try:
            inclusions_collection = get_inclusions_collection()
            inclusions = await inclusions_collection.find(
                {}, {"_id": 0, "title": 1, "sub_desc": 1}
            ).to_list(length=None)
            inclusions_titles = [inc["title"] for inc in inclusions]
            logger.info(
                f"Found {len(inclusions_titles)} inclusions: {inclusions_titles}"
            )
        except Exception as e:
            logger.error(f"Failed to fetch inclusions: {e}")
            inclusions_titles = []
            inclusions = []

        # Get sports
        try:
            sports_collection = get_sports_collection()
            sports = await sports_collection.find(
                {}, {"_id": 0, "name": 1, "icon": 1}
            ).to_list(length=None)
            sports_names = [sport["name"] for sport in sports]
            logger.info(f"Found {len(sports_names)} sports: {sports_names}")
        except Exception as e:
            logger.error(f"Failed to fetch sports: {e}")
            sports_names = []
            sports = []

        debug_data = {
            "inclusions": {
                "count": len(inclusions_titles),
                "titles": inclusions_titles,
                "sample_data": (
                    inclusions[:3] if inclusions else []
                ),  # First 3 for reference
            },
            "sports": {
                "count": len(sports_names),
                "names": sports_names,
                "sample_data": sports[:3] if sports else [],  # First 3 for reference
            },
            "status": "success" if (inclusions_titles or sports_names) else "no_data",
        }

        if debug_data["status"] == "success":
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message=f"Found {len(inclusions_titles)} inclusions and {len(sports_names)} sports",
                data=debug_data,
            )
        else:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="No admin data found. Please check admin database connection.",
                data=debug_data,
            )

    except Exception as e:
        logger.error(f"Error in get_available_admin_data: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Debug error: {str(e)}",
            data=None,
        )


# ============================================================================
# CLUB STEP 2 ENDPOINT (What's Included + Top 3 Sports)
# ============================================================================

# ============================================================================
# CLUB CONFIRMATION ENDPOINTS
# ============================================================================


@router.post("/confirm-club-free", response_model=ClubConfirmationFreeResponse)
async def confirm_club_free(
    request: ClubConfirmationFreeRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Confirm club creation for free (no additional moderators payment required)

    This endpoint allows captains to confirm their club creation when no additional
    moderators are required, making it a free confirmation process.

    **Features:**
    - **Free Confirmation**: No payment required
    - **Status Update**: Club status changes to 'pending'
    - **Step 4 Validation**: Ensures club has completed moderator setup
    - **Zero Paid Moderators**: Validates that there are no paid moderators

    **Request Body:**
    - `club_id`: ID of the club to confirm (can be ObjectId or name_based_id)

    **Requirements:**
    - Club must be at step 4 (moderator setup completed)
    - Club must have zero paid moderators (total_additional_moderator_pricing = 0)
    - Captain must own the club
    - Club must not already be confirmed

    **Response includes:**
    - Club details with confirmation status
    - Moderator count information
    - Confirmation timestamp
    - Total additional moderator pricing (should be 0.0)

    **Use Cases:**
    - Complete club creation with no additional moderators
    - Finalize club setup for free tier
    - Activate club for public use

    **Example Usage:**
    ```
    POST /api/v1/confirm-club-free
    {
        "club_id": "techtic-group-solutions-ltd"
    }
    ```

    Captain-only access required. Club status set to pending after successful confirmation.
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(
            f"Processing free club confirmation request for captain: {captain_id}"
        )

        success, response_data, error_message = (
            await club_confirmation_service.confirm_club_free(request, captain_id)
        )

        if success and response_data:
            logger.info(
                f"Club free confirmation successful for club: {request.club_id}"
            )
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club confirmed successfully",
                data=response_data,
            )
        else:
            logger.warning(f"Club free confirmation failed: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to confirm club",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in confirm_club_free: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.post("/confirm-club-paid", response_model=ClubConfirmationPaidResponse)
async def confirm_club_paid(
    request: ClubConfirmationPaidRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Confirm club creation with payment for additional moderators

    This endpoint allows captains to confirm their club creation when additional
    moderators are required, processing payment through Stripe.

    **Features:**
    - **Paid Confirmation**: Processes payment for additional moderators
    - **Stripe Integration**: Creates payment intent and processes payment
    - **Price Validation**: Verifies price matches expected amount
    - **Webhook Support**: Status updated via Stripe webhooks
    - **Payment Tracking**: Stores payment intent ID and status

    **Request Body:**
    - `club_id`: ID of the club to confirm (can be ObjectId or name_based_id)
    - `email`: Captain's email for payment receipt
    - `payment_method_id`: Stripe payment method ID
    - `price`: Expected price to pay (must match total_additional_moderator_pricing)

    **Requirements:**
    - Club must be at step 4 (moderator setup completed)
    - Club must have paid moderators (total_additional_moderator_pricing > 0)
    - Price must match club's total_additional_moderator_pricing

    - Captain must own the club
    - Club must not already be confirmed

    **Payment Process:**
    1. Validates club and pricing information
    2. Creates Stripe payment intent
    3. Processes payment immediately
    4. Updates club status based on payment result
    5. Webhook handles final confirmation if payment succeeds later

    **Response includes:**
    - Club details with payment status
    - Payment intent ID for tracking
    - Payment status (succeeded, requires_action, failed)
    - Confirmation timestamp (if payment succeeded immediately)

    **Use Cases:**
    - Complete club creation with additional moderators
    - Process payment for moderator subscriptions
    - Finalize paid club setup

    **Example Usage:**
    ```
    POST /api/v1/confirm-club-paid
    {
        "club_id": "techtic-group-solutions-ltd",
        "email": "captain@example.com",
        "payment_method_id": "pm_1234567890",
        "price": 19.90,

    }
    ```

    Captain-only access required. Club status set to pending after successful payment.
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(
            f"Processing paid club confirmation request for captain: {captain_id}"
        )

        success, response_data, error_message = (
            await club_confirmation_service.confirm_club_paid(request, captain_id)
        )

        if success and response_data:
            logger.info(f"Club paid confirmation processed for club: {request.club_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club payment processed successfully",
                data=response_data,
            )
        else:
            logger.warning(f"Club paid confirmation failed: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to process club payment",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in confirm_club_paid: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.post("/webhook/club-payment-confirmation")
async def handle_club_payment_webhook(request: Request):
    """
    Handle Stripe webhook for club payment confirmation

    This endpoint receives and processes Stripe webhook events related to
    club payment confirmations for additional moderators.

    **Webhook Events Handled:**
    - `payment_intent.succeeded`: Payment completed successfully
    - `payment_intent.payment_failed`: Payment failed
    - `payment_intent.canceled`: Payment was canceled

    **Process:**
    1. Verifies webhook signature (if configured)
    2. Extracts payment intent information
    3. Updates club status based on payment result
    4. Logs payment event for tracking

    **Security:**
    - Webhook endpoint should be secured with Stripe signature verification
    - Only processes events with club-related metadata

    **Example Webhook Payload:**
    ```json
    {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_1234567890",
                "status": "succeeded",
                "metadata": {
                    "club_id": "64f7b1234567890abcdef123",
                    "confirmation_type": "paid_moderators"
                }
            }
        }
    }
    ```

    **Note:** This webhook endpoint should be configured in your Stripe dashboard
    to receive payment_intent events.
    """
    try:
        logger.info("Received club payment webhook")

        # Get webhook payload
        payload = await request.body()
        event_data = json.loads(payload)

        # Extract event information
        event_type = event_data.get("type")
        data_object = event_data.get("data", {}).get("object", {})
        payment_intent_id = data_object.get("id")
        payment_status = data_object.get("status")
        metadata = data_object.get("metadata", {})

        logger.info(
            f"Webhook event: {event_type}, payment_intent: {payment_intent_id}, status: {payment_status}"
        )

        # Only process payment_intent events with club metadata
        if not event_type.startswith("payment_intent.") or not metadata.get("club_id"):
            logger.info("Ignoring webhook - not a club payment event")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Webhook received but not processed (not a club payment event)",
                data=None,
            )

        # Handle the webhook based on event type
        if event_type in [
            "payment_intent.succeeded",
            "payment_intent.payment_failed",
            "payment_intent.canceled",
        ]:
            success, error_message = (
                await club_confirmation_service.handle_payment_webhook(
                    payment_intent_id, payment_status
                )
            )

            if success:
                logger.info(
                    f"Webhook processed successfully for payment_intent: {payment_intent_id}"
                )
                return create_response(
                    status_code=status.HTTP_200_OK,
                    status="success",
                    message="Webhook processed successfully",
                    data={
                        "payment_intent_id": payment_intent_id,
                        "status": payment_status,
                    },
                )
            else:
                logger.error(f"Webhook processing failed: {error_message}")
                return create_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    status="error",
                    message=error_message,
                    data=None,
                )
        else:
            logger.info(f"Unhandled webhook event type: {event_type}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message=f"Webhook received but not handled: {event_type}",
                data=None,
            )

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook payload: {e}")
        return create_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
            message="Invalid JSON payload",
            data=None,
        )
    except Exception as e:
        logger.error(f"Error processing club payment webhook: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Webhook processing error: {str(e)}",
            data=None,
        )


# ============================================================================
# CLUB COUNT ENDPOINT
# ============================================================================


@router.get("/get-club-count", response_model=dict)
async def get_club_count(current_user: dict = Depends(get_current_user)):
    """
    Get the current club count for the authenticated user (captain or member)

    This endpoint returns the club count for both captains and members:
    - **For Captains**: Number of clubs they have successfully created and confirmed
    - **For Members**: Whether they have joined any clubs (0 or 1)

    **Features:**
    - **Authentication Required**: Accessible to all authenticated users regardless of membership status
    - **Real-time Data**: Returns the current club count from the database
    - **Role-based Logic**: Different logic for captains vs members
    - **No Membership Check**: Works for users with any membership status (active, inactive, trial, etc.)

    **Response includes:**
    - `club_count`: The current club count for the user
    - `user_id`: The user's ID
    - `user_name`: The user's full name
    - `role`: The user's role (Captain or Member)

    **Use Cases:**
    - Display user's club count in UI
    - Verify club count for validation
    - Check user's progress
    - Show club count regardless of membership status

    **Example Response for Captain:**
    ```json
    {
        "status": "success",
        "message": "Club count retrieved successfully",
        "data": {
            "club_count": 3,
            "user_id": "64f7b1234567890abcdef123",
            "user_name": "John Doe",
            "role": "Captain"
        }
    }
    ```

    **Example Response for Member:**
    ```json
    {
        "status": "success",
        "message": "Club count retrieved successfully",
        "data": {
            "club_count": 1,
            "user_id": "64f7b1234567890abcdef456",
            "user_name": "Jane Smith",
            "role": "Member"
        }
    }
    ```

    Accessible to all authenticated users regardless of membership status.
    """
    try:
        user_id = current_user["user_id"]
        user_name = current_user.get("full_name", "Unknown")
        user_role = current_user.get("role", "Member")

        logger.info(f"Getting club count for {user_role}: {user_id}")

        # Get the user's club count from the database
        from .db import get_user_collection

        users_collection = get_user_collection()

        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            logger.warning(f"User {user_id} not found in auth database")
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="User not found",
                data=None,
            )

        club_count = user.get("club_count", 0)

        # For members, ensure club_count is 1 if they have joined any clubs
        if user_role == "Member":
            # Check if member has joined any clubs
            clubs_joined = user.get("clubs_joined", [])
            total_clubs_joined = user.get("total_clubs_joined", 0)

            # If member has joined clubs but club_count is 0, update it to 1
            if (len(clubs_joined) > 0 or total_clubs_joined > 0) and club_count == 0:
                logger.info(
                    f"Member {user_id} has joined clubs but club_count is 0, updating to 1"
                )
                club_count = 1

                # Update the club_count in the database
                try:
                    from datetime import datetime

                    await users_collection.update_one(
                        {"_id": ObjectId(user_id)},
                        {"$set": {"club_count": 1, "updated_at": datetime.utcnow()}},
                    )
                    logger.info(f"Updated member {user_id} club_count to 1")
                except Exception as update_error:
                    logger.error(f"Failed to update member club_count: {update_error}")

        logger.info(f"{user_role} {user_name} has club_count: {club_count}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Club count retrieved successfully",
            data={
                "club_count": club_count,
                "user_id": user_id,
                "user_name": user_name,
                "role": user_role,
            },
        )

    except Exception as e:
        logger.error(f"Unexpected error in get_club_count: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# HUB ENDPOINTS
# ============================================================================


# Dependency to get hub service
async def get_hub_service():
    """Get hub service instance"""
    from .db import get_database

    database = await get_database()
    hub_db = HubDatabase(database)
    from .hub_service import HubService

    return HubService(hub_db)


async def get_join_trial_free_service():
    """Get join trial free service instance"""
    return JoinTrialFreeService()


@router.post("/hub/create-hub", response_model=CreateHubResponse)
async def create_hub(
    request: CreateHubRequest,
    current_captain: dict = Depends(get_current_captain),
    hub_service=Depends(get_hub_service),
):
    """
    Create a new hub entry

    This endpoint allows captains to create hub entries for their clubs.
    Only captains can create hub entries for clubs they own.

    **Required Fields:**
    - title: Title of the hub entry (1-200 characters)
    - description: Description of the hub entry (1-1000 characters)
    - resource_url: URL to the resource (video/link)
    - platform: Platform where the resource is hosted
    - club_id: name_based_id of the club
    - section: Category for the hub entry (strategy video, training video, partner links)

    **Optional Fields:**
    - duration: Duration of the video/content
    - thumbnail: URL to the thumbnail image (optional)

    **Authorization:**
    - User must be authenticated
    - User must be a captain
    - User must be the captain of the specified club

    **Returns:**
    - Success response with created hub entry details
    - Error response if validation fails or user is not authorized
    """
    try:
        captain_id = current_captain["user_id"]
        captain_name = current_captain.get("full_name", "Unknown Captain")

        logger.info(f"Create hub request received from captain {captain_id}")

        # Create hub entry
        success, hub_id, error_message = await hub_service.create_hub(
            request, captain_id, captain_name
        )

        if not success:
            logger.error(f"Failed to create hub: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message,
                data=None,
            )

        # Get the created hub entry
        hub_response = await hub_service.get_hub_by_id(hub_id)
        if not hub_response:
            logger.error(f"Hub created but failed to retrieve: {hub_id}")
            return create_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Hub created but failed to retrieve details",
                data=None,
            )

        logger.info(f"Hub entry created successfully: {hub_id}")
        return create_response(
            status_code=status.HTTP_201_CREATED,
            status="success",
            message="Hub entry created successfully",
            data=hub_response,
        )

    except Exception as e:
        error_msg = f"Unexpected error creating hub entry: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Internal server error",
            data=None,
        )


# ============================================================================
# HUB FILTERING ENDPOINT
# ============================================================================


@router.get("/hub/filter", response_model=HubFiltersResponse)
async def get_filtered_hubs(
    search: Optional[str] = Query(
        None, description="Search by hub title (case-insensitive)"
    ),
    sort_by: Literal["newest", "oldest", "A-Z"] = Query(
        default="newest", description="Sorting option (newest, oldest, A-Z)"
    ),
    club_name_based_id: Optional[str] = Query(
        None,
        description="Filter by club name_based_id (user can only access clubs they are member of or captain of)",
    ),
    section: Optional[
        Literal["strategy video", "training video", "partner links"]
    ] = Query(
        None,
        description="Filter by section (strategy video, training video, partner links)",
    ),
    page: int = Query(default=1, ge=1, description="Page number for pagination"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Number of items per page"
    ),
    current_user: dict = Depends(get_current_user_or_captain),
    hub_service=Depends(get_hub_service),
):
    """
    Get all hubs based on filters with search, sorting, and pagination
    Supports both captains and members with proper access control

    **Query Parameters:**
    - `search`: Optional search term for hub title (case-insensitive)
    - `sort_by`: Sorting option (newest, oldest, A-Z) - defaults to newest
    - `club_name_based_id`: Optional club filter (user can only access clubs they are member of or captain of)
    - `section`: Optional section filter (strategy video, training video, partner links)
    - `page`: Page number for pagination (default: 1)
    - `page_size`: Items per page (default: 20, max: 100)

    **Returns:**
    - List of filtered hubs with pagination information
    - Summary of filters applied
    - Error message if user is not authorized or validation fails

    **Authorization:**
    - Only authenticated users with active membership can access this endpoint
    - **Captains**: Can view all hub content from clubs they have created
    - **Members**: Can view hub content only from clubs they have joined
    - If club_name_based_id is provided, user must have access to that club

    **Example Usage:**
    ```
    GET /api/v1/hub/filter?search=strategy&sort_by=newest&section=strategy%20video&page=1&page_size=20
    GET /api/v1/hub/filter?club_name_based_id=amey-captain-mvp
    ```
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user["role"]
        user_name = current_user.get("full_name", "Unknown")

        logger.info(
            f"Filter hubs request by user: {user_id} (role: {user_role}) with filters: "
            f"search={search}, sort_by={sort_by}, club={club_name_based_id}, "
            f"section={section}, page={page}, page_size={page_size}"
        )
        logger.info(f"User details: {current_user}")

        # Get filtered hubs using the service
        logger.info(
            f"About to call hub_service.get_filtered_hubs with user_id={user_id}, role={user_role}"
        )

        success, hubs, error_message, pagination_info = (
            await hub_service.get_filtered_hubs(
                search=search,
                sort_by=sort_by,
                club_name_based_id=club_name_based_id,
                section=section,
                user_id=user_id,
                user_role=user_role,
                page=page,
                page_size=page_size,
            )
        )

        logger.info(
            f"Service returned: success={success}, hubs_count={len(hubs) if hubs else 0}, error={error_message}"
        )

        if not success:
            logger.warning(f"Failed to get filtered hubs: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve hubs",
                data=None,
            )

        # Build filters applied summary
        filters_applied = {
            "search": search,
            "sort_by": sort_by,
            "club_name_based_id": club_name_based_id,
            "section": section,
            "page": page,
            "page_size": page_size,
        }

        # Remove None values for cleaner output
        filters_applied = {k: v for k, v in filters_applied.items() if v is not None}

        logger.info(
            f"Successfully retrieved {len(hubs)} hubs with filters for user: {user_id} (role: {user_role})"
        )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Hubs retrieved successfully",
            data={
                "data": hubs,
                "pagination": pagination_info,
                "filters_applied": filters_applied,
            },
        )

    except Exception as e:
        error_msg = f"Error getting filtered hubs: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Internal server error",
            data=None,
        )


@router.get("/hub/stats", response_model=HubStatsResponse)
async def get_hub_stats(
    club_id: Optional[str] = Query(
        None, description="Club name-based ID to filter stats (optional)"
    ),
    current_captain: dict = Depends(get_current_captain),
    hub_service=Depends(get_hub_service),
):
    """
    Get hub statistics for content counts

    This endpoint provides statistics about hub content including:
    - Total strategy videos
    - Total training videos
    - Total partner links
    - Total content (sum of all above)

    **Query Parameters:**
    - `club_id`: Optional club name-based ID to filter stats for a specific club

    **Features:**
    - **Captain Only**: Only captains can access this endpoint
    - **Club Filtering**: If club_id is provided, stats are filtered to that specific club
    - **Club Validation**: If club_id is provided, validates that the captain owns that club
    - **Captain's Clubs**: If no club_id is provided, returns stats for ALL clubs created by the captain

    **Response includes:**
    - `total_strategy_videos`: Count of strategy video content
    - `total_training_videos`: Count of training video content
    - `total_partner_links`: Count of partner link content
    - `total_content`: Total count of all content types
    - `club_id`: Club ID filter applied (if any)
    - `club_name_based_id`: Club name-based ID filter applied (if any)

    **Use Cases:**
    - View content statistics across all captain's clubs
    - Get content counts for a specific club
    - Monitor content distribution across different types

    **Example Usage:**
    ```
    GET /api/v1/hub/stats                    # Stats for all captain's clubs
    GET /api/v1/hub/stats?club_id=new-cap-mvp # Stats for specific club
    ```

    Captain-only access required. Returns content statistics with optional club filtering.
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"Getting hub stats for captain: {captain_id}, club_id: {club_id}")

        # Get statistics from hub service
        success, stats_data, error_message = await hub_service.get_hub_statistics(
            club_name_based_id=club_id, captain_id=captain_id
        )

        if success and stats_data:
            # Create response model
            response_data = HubStatsResponse(
                total_strategy_videos=stats_data["total_strategy_videos"],
                total_training_videos=stats_data["total_training_videos"],
                total_partner_links=stats_data["total_partner_links"],
                total_content=stats_data["total_content"],
                club_id=club_id,
                club_name_based_id=stats_data.get("club_name_based_id"),
            )

            logger.info(f"Hub stats retrieved successfully: {response_data}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Hub statistics retrieved successfully",
                data=response_data,
            )
        else:
            logger.warning(f"Failed to get hub stats: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve hub statistics",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in get_hub_stats: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/hub/{hub_id}", response_model=HubResponse)
async def get_hub(hub_id: str, hub_service=Depends(get_hub_service)):
    """
    Get a specific hub entry by hub_id (accepts hub_name_based_id as value)

    **Parameters:**
    - hub_id: The hub_id parameter (use hub_name_based_id as value)

    **Returns:**
    - Hub entry details if found
    - 404 error if hub entry not found
    """
    try:
        logger.info(f"Get hub request for hub_id: {hub_id}")

        logger.info(f"Looking up hub with name_based_id: {hub_id}")
        hub_response = await hub_service.get_hub_by_name_based_id(hub_id)
        if not hub_response:
            logger.warning(f"Hub not found with name_based_id: {hub_id}")
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Hub entry not found",
                data=None,
            )

        logger.info(f"Hub retrieved successfully: {hub_id}")
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Hub entry retrieved successfully",
            data=hub_response,
        )

    except Exception as e:
        error_msg = f"Error retrieving hub: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Internal server error",
            data=None,
        )


@router.get("/hub/club/{club_name_based_id}", response_model=List[HubResponse])
async def get_hubs_by_club(
    club_name_based_id: str,
    limit: Optional[int] = 50,
    hub_service=Depends(get_hub_service),
):
    """
    Get all hub entries for a specific club

    **Parameters:**
    - club_name_based_id: The name_based_id of the club
    - limit: Maximum number of hub entries to return (default: 50, max: 100)

    **Returns:**
    - List of hub entries for the specified club
    - Empty list if no hub entries found
    """
    try:
        if limit and (limit < 1 or limit > 100):
            limit = 50

        logger.info(f"Get hubs by club request: {club_name_based_id}, limit: {limit}")

        hubs = await hub_service.get_hubs_by_club(club_name_based_id, limit)
        logger.info(f"Retrieved {len(hubs)} hub entries for club: {club_name_based_id}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Retrieved {len(hubs)} hub entries",
            data=hubs,
        )

    except Exception as e:
        error_msg = f"Error retrieving hubs by club: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Internal server error",
            data=None,
        )


@router.get("/hub/captain/{captain_id}", response_model=List[HubResponse])
async def get_hubs_by_captain(
    captain_id: str, limit: Optional[int] = 50, hub_service=Depends(get_hub_service)
):
    """
    Get all hub entries created by a specific captain

    **Parameters:**
    - captain_id: The ID of the captain
    - limit: Maximum number of hub entries to return (default: 50, max: 100)

    **Returns:**
    - List of hub entries created by the specified captain
    - Empty list if no hub entries found
    """
    try:
        if limit and (limit < 1 or limit > 100):
            limit = 50

        logger.info(f"Get hubs by captain request: {captain_id}, limit: {limit}")

        hubs = await hub_service.get_hubs_by_captain(captain_id, limit)
        logger.info(f"Retrieved {len(hubs)} hub entries for captain: {captain_id}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Retrieved {len(hubs)} hub entries",
            data=hubs,
        )

    except Exception as e:
        error_msg = f"Error retrieving hubs by captain: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Internal server error",
            data=None,
        )


@router.put("/hub/{hub_id}", response_model=EditHubResponse)
async def edit_hub(
    hub_id: str,
    request: EditHubRequest,
    current_captain: dict = Depends(get_current_captain),
    hub_service=Depends(get_hub_service),
):
    """
    Edit an existing hub entry
    Only the captain who created the hub can edit it

    **Parameters:**
    - hub_id: The hub_id parameter (use hub_name_based_id as value)
    - request: The updated hub data (section field is required, others are optional)

    **Returns:**
    - Updated hub entry data
    - Error message if captain is not authorized or hub not found
    """
    try:
        captain_id = current_captain["user_id"]
        captain_name = current_captain.get("full_name", "Unknown")

        logger.info(f"Edit hub request: {hub_id} by captain: {captain_id}")

        # First get the hub by name_based_id to get the actual hub_id
        logger.info(f"Looking up hub with name_based_id: {hub_id}")
        hub_response = await hub_service.get_hub_by_name_based_id(hub_id)
        if not hub_response:
            logger.warning(f"Hub not found with name_based_id: {hub_id}")
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Hub entry not found",
                data=None,
            )

        actual_hub_id = hub_response.hub_id

        success, hub_id_result, error_message = await hub_service.edit_hub(
            actual_hub_id, request, captain_id
        )

        if not success:
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message,
                data=None,
            )

        # Get the updated hub
        logger.info(f"Retrieving updated hub with name_based_id: {hub_id}")
        updated_hub = await hub_service.get_hub_by_name_based_id(hub_id)
        if not updated_hub:
            logger.error(f"Failed to retrieve updated hub with name_based_id: {hub_id}")
            return create_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Failed to retrieve updated hub entry",
                data=None,
            )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Hub entry updated successfully",
            data=updated_hub,
        )

    except Exception as e:
        error_msg = f"Error editing hub: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Internal server error",
            data=None,
        )


@router.delete("/hub/{hub_id}", response_model=DeleteHubResponse)
async def delete_hub(
    hub_id: str,
    current_captain: dict = Depends(get_current_captain),
    hub_service=Depends(get_hub_service),
):
    """
    Delete a hub entry (soft delete)
    Only the captain who created the hub can delete it

    **Parameters:**
    - hub_id: The hub_id parameter (use hub_name_based_id as value)

    **Returns:**
    - Success message with deleted hub ID
    - Error message if captain is not authorized or hub not found
    """
    try:
        captain_id = current_captain["user_id"]
        captain_name = current_captain.get("full_name", "Unknown")

        logger.info(f"Delete hub request: {hub_id} by captain: {captain_id}")

        # First get the hub by name_based_id to get the actual hub_id
        logger.info(f"Looking up hub with name_based_id: {hub_id}")
        hub_response = await hub_service.get_hub_by_name_based_id(hub_id)
        if not hub_response:
            logger.warning(f"Hub not found with name_based_id: {hub_id}")
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Hub entry not found",
                data=None,
            )

        actual_hub_id = hub_response.hub_id

        success, hub_id_result, error_message = await hub_service.delete_hub(
            actual_hub_id, captain_id
        )

        if not success:
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message,
                data=None,
            )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Hub entry deleted successfully",
            data={"hub_id": actual_hub_id},
        )

    except Exception as e:
        error_msg = f"Error deleting hub: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Internal server error",
            data=None,
        )


# ============================================================================
# USER CLUBS ENDPOINT
# ============================================================================


@router.get("/user/clubs", response_model=UserClubsResponse)
async def get_user_clubs(
    current_user: dict = Depends(get_current_user_or_captain),
    hub_service=Depends(get_hub_service),
):
    """
    Get clubs that the current user has access to based on their role

    **For Captains:**
    - Returns all clubs they have created

    **For Members:**
    - Returns all clubs they have joined (with active or pending membership)

    **Response includes:**
    - `club_id`: Club ObjectId
    - `name`: Club name
    - `name_based_id`: Club name-based ID (for API calls)
    - `description`: Club description
    - `logo_url`: Club logo URL
    - `member_count`: Number of members in the club
    - `is_active`: Whether the club is active
    - `created_at`: Club creation date
    - `user_role`: User's role in this club (captain/member)

    **Example Usage:**
    ```
    GET /api/v1/user/clubs
    ```

    Returns clubs based on user's role and access permissions.
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user["role"]
        user_name = current_user.get("full_name", "Unknown")

        logger.info(f"Getting clubs for user: {user_id} (role: {user_role})")

        # Get user's clubs using the service
        success, clubs_data, error_message = await hub_service.get_user_clubs(
            user_id, user_role
        )

        if not success:
            logger.warning(f"Failed to get user clubs: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve user clubs",
                data=None,
            )

        # Convert to UserClubInfo objects and calculate totals
        clubs = []
        total_members = 0
        total_moderators = 0
        
        for club_data in clubs_data:
            member_count = club_data.get("member_count", 0)
            moderator_count = club_data.get("moderator_count", 0)
            
            print(f"Club data for {club_data.get('name')}: member_count={member_count}, moderator_count={moderator_count}")
            
            club_info = UserClubInfo(
                club_id=club_data["club_id"],
                name=club_data["name"],
                name_based_id=club_data["name_based_id"],
                description=club_data.get("description"),
                logo_url=club_data.get("logo_url"),
                member_count=member_count,
                moderator_count=moderator_count,
                is_active=club_data.get("is_active", True),
                created_at=club_data["created_at"],
                user_role=club_data["user_role"],
            )
            clubs.append(club_info)
            
            # Add to totals
            total_members += member_count
            total_moderators += moderator_count

        # Create response
        response_data = UserClubsResponse(
            clubs=clubs,
            total_count=len(clubs),
            total_members=total_members,
            total_moderators=total_moderators,
            user_role=user_role,
            message=f"Successfully retrieved {len(clubs)} clubs for {user_role.lower()}",
        )

        logger.info(
            f"Successfully retrieved {len(clubs)} clubs for user: {user_id} (role: {user_role})"
        )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"User clubs retrieved successfully",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"Unexpected error in get_user_clubs: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# REFUND POLICY ROUTES
# ============================================================================

# # Include refund routes
# from .refund_routes import router as refund_router
# router.include_router(refund_router, prefix="/api/v1")

# ============================================================================
# TEST ENDPOINTS (FOR DEVELOPMENT/TESTING ONLY)
# ============================================================================


@router.post("/test/create-payment-method")
async def create_test_payment_method(
    email: str = Query(..., description="Customer email for the payment method"),
    current_captain: dict = Depends(get_current_captain),
):
    """
    Create a test payment method for testing purposes

    This endpoint creates a test payment method using Stripe's test card.
    Use this for testing the club confirmation payment flow.

    **Query Parameters:**
    - `email`: Customer email to associate with the payment method

    **Returns:**
    - Test payment method details including the payment_method_id

    **Note:** This is for testing only. Remove in production.
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(
            f"Creating test payment method for captain: {captain_id}, email: {email}"
        )

        from .stripe_service import StripeService

        payment_method = await StripeService.create_test_payment_method(email)

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Test payment method created successfully",
            data={
                "payment_method_id": payment_method.id,
                "customer_id": payment_method.customer,
                "type": payment_method.type,
                "card": (
                    {
                        "last4": payment_method.card.last4,
                        "brand": payment_method.card.brand,
                        "exp_month": payment_method.card.exp_month,
                        "exp_year": payment_method.card.exp_year,
                    }
                    if payment_method.card
                    else None
                ),
            },
        )

    except Exception as e:
        logger.error(f"Error creating test payment method: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to create test payment method: {str(e)}",
            data=None,
        )


@router.post("/confirm-club-paid-with-card")
async def confirm_club_paid_with_card(
    request: ClubConfirmationPaidRequest,
    card_number: str = Query(
        default="4242424242424242",
        description="Card number (default: Stripe test card)",
    ),
    exp_month: int = Query(default=12, description="Card expiration month"),
    exp_year: int = Query(default=2025, description="Card expiration year"),
    cvc: str = Query(default="123", description="Card CVC"),
    current_captain: dict = Depends(get_current_captain),
):
    """
    Confirm club creation with payment using card details directly

    This endpoint allows captains to confirm their club creation when additional
    moderators are required, processing payment through Stripe using card details.

    **Features:**
    - **Direct Card Payment**: Accepts card details directly (no PaymentMethod ID needed)
    - **Stripe Integration**: Creates payment intent and processes payment
    - **Price Validation**: Verifies price matches expected amount
    - **Webhook Support**: Status updated via Stripe webhooks
    - **Payment Tracking**: Stores payment intent ID and status

    **Request Body:**
    - `club_id`: ID of the club to confirm (can be ObjectId or name_based_id)
    - `email`: Captain's email for payment receipt
    - `price`: Expected price to pay (must match total_additional_moderator_pricing)
    - `price_id`: Stripe price ID (must match club's stripe_price_id)

    **Query Parameters:**
    - `card_number`: Card number (defaults to Stripe test card 4242424242424242)
    - `exp_month`: Card expiration month (default: 12)
    - `exp_year`: Card expiration year (default: 2025)
    - `cvc`: Card CVC (default: 123)

    **Requirements:**
    - Club must be at step 4 (moderator setup completed)
    - Club must have paid moderators (total_additional_moderator_pricing > 0)
    - Price must match club's total_additional_moderator_pricing

    - Captain must own the club
    - Club must not already be confirmed

    **Payment Process:**
    1. Validates club and pricing information
    2. Creates Stripe payment intent with card details
    3. Processes payment immediately
    4. Updates club status based on payment result
    5. Webhook handles final confirmation if payment succeeds later

    **Response includes:**
    - Club details with payment status
    - Payment intent ID for tracking
    - Payment status (succeeded, requires_action, failed)
    - Confirmation timestamp (if payment succeeded immediately)

    **Use Cases:**
    - Complete club creation with additional moderators
    - Process payment for moderator subscriptions
    - Finalize paid club setup
    - Testing payment flow without PaymentMethod IDs

    **Example Usage:**
    ```
    POST /api/v1/confirm-club-paid-with-card?card_number=4242424242424242&exp_month=12&exp_year=2025&cvc=123
    {
        "club_id": "new-club-for-cricket",
        "email": "captain@example.com",
        "price": 19.90,

    }
    ```

    Captain-only access required. Club status set to pending after successful payment.
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"Processing club confirmation with card for captain: {captain_id}")

        # Import the service here to avoid circular imports
        from .club_confirmation_service import club_confirmation_service

        success, response_data, error_message = (
            await club_confirmation_service.confirm_club_paid_with_card(
                request, captain_id, card_number, exp_month, exp_year, cvc
            )
        )

        if success and response_data:
            logger.info(
                f"Club confirmation with card processed for club: {request.club_id}"
            )
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club payment processed successfully",
                data=response_data,
            )
        else:
            logger.warning(f"Club confirmation with card failed: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to process club payment",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in confirm_club_paid_with_card: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# CLUB STATISTICS ENDPOINTS
# ============================================================================


@router.get("/club/stats", response_model=ClubStatsResponse)
async def get_club_statistics(
    current_captain: dict = Depends(get_current_captain),
    hub_service=Depends(get_hub_service),
):
    """
    Get comprehensive statistics for the current captain's clubs

    Returns:
        ClubStatsResponse: Statistics including total clubs, members, revenue, and win percentage
    """
    try:
        captain_id = current_captain["user_id"]
        captain_name = current_captain.get("full_name", "Unknown Captain")

        logger.info(f"Getting club statistics for captain: {captain_id}")

        success, stats_data, error_message = (
            await hub_service.get_captain_club_statistics(captain_id, captain_name)
        )
        print(f"Stats data: {stats_data}")
        if not success:
            logger.warning(f"Failed to get club statistics: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve club statistics",
                data=None,
            )

        # Create response data
        response_data = ClubStatsResponse(
            total_clubs=stats_data["total_clubs"],
            total_members=stats_data["total_members"],
            total_revenue=stats_data["total_revenue"],
            average_win_percentage=stats_data["average_win_percentage"],
            captain_id=stats_data["captain_id"],
            captain_name=stats_data["captain_name"],
            message=stats_data["message"],
        )

        logger.info(f"Successfully retrieved club statistics for captain: {captain_id}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Club statistics retrieved successfully",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"Unexpected error in get_club_statistics: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# JOIN TRIAL FREE ENDPOINTS
# ============================================================================


async def _notify_captain_member_join(
    club_name_based_id: Optional[str],
    new_member_id: Optional[str],
    new_member_name: Optional[str],
    membership_type: str,
) -> None:
    """Send a club_member_join notification to the club captain."""
    if not club_name_based_id or not new_member_id:
        return

    try:
        club_collection = get_club_collection()
        club = await club_collection.find_one({"name_based_id": club_name_based_id})
        if not club:
            return

        captain_id = club.get("captain_id")
        if not captain_id:
            return

        captain_id = str(captain_id)
        if captain_id == str(new_member_id):
            return

        from services.notifications.notification_service import (
            send_notification_to_users,
            filter_users_by_notification_preference,
            get_collections,
        )

        enabled_user_ids = await filter_users_by_notification_preference(
            [captain_id],
            "club_join_alerts",
        )
        enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]
        if not enabled_user_ids:
            return

        collections = get_collections()
        user_tokens_collection = collections.get_user_tokens_collection()
        token_docs = await user_tokens_collection.find(
            {"user_id": {"$in": enabled_user_ids}, "is_active": True},
            {"user_id": 1},
        ).to_list(length=None)
        push_user_ids = list(
            {
                doc.get("user_id")
                for doc in token_docs
                if doc.get("user_id") in enabled_user_ids
            }
        )

        membership_type_text = (membership_type or "member").capitalize()
        club_name = club.get("name", "Club")
        display_name = new_member_name or "New member"

        notification_data = {
            "club_id": club_name_based_id,
            "club_name": club_name,
            "new_member_name": display_name,
            "membership_type": (membership_type or "member").lower(),
            "new_member_id": str(new_member_id),
        }

        await send_notification_to_users(
            user_ids=push_user_ids,
            title="New Member Joined!",
            body=f"{display_name} has joined the club ({membership_type_text} member)",
            notification_type="club_member_join",
            data=notification_data,
            click_action=f"club/{club_name_based_id}/members",
            priority="normal",
            all_user_ids=enabled_user_ids,
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to notify captain about new member: {e}")


@router.post("/join-trial-free", response_model=JoinTrialFreeResponse)
async def join_club_trial_free(
    request: JoinTrialFreeRequest,
    current_user: dict = Depends(get_current_user),
    join_trial_service=Depends(get_join_trial_free_service),
):
    """
    Join a club with trial membership (free for 7 days per club)

    This endpoint allows Members with active trial membership to join clubs for free.
    Each club joined provides 7 days of access, and users can join up to 4 clubs total
    during their 30-day trial period.

    **Requirements:**
    - User must have `role = "Member"`
    - User must have `membership_status = "active"`
    - User must have `membership_type = "trial"`
    - User must not have reached the 4-club limit

    **Features:**
    - **7-Day Access**: Each club provides 7 days of access from join date
    - **4-Club Limit**: Maximum 4 clubs can be joined during trial period
    - **30-Day Trial**: Trial period lasts 30 days from membership start
    - **Automatic Expiry**: Club access expires after 7 days, regardless of trial period
    - **Club Tracking**: All joined clubs are tracked with join dates and expiry dates

    **Response includes:**
    - Success status and message
    - Details of the joined club
    - Current trial membership status
    - List of all clubs joined during trial
    - Whether user can join more clubs
    - Days remaining in trial period

    **Example Usage:**
    ```
    POST /api/v1/join-trial-free
    {
        "club_id": "new-cap-mvp"
    }
    ```

    **Access Control:**
    - Only Members with active trial membership can use this endpoint
    - Club must exist and be active
    - User cannot already be a member of the club
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role", "Member")

        # Validate user role
        if user_role != "Member":
            return create_response(
                status_code=status.HTTP_403_FORBIDDEN,
                status="error",
                message="Only Members can use trial-free club joining",
                data=None,
            )

        logger.info(
            f"Processing trial-free join request for user {user_id}, club {request.club_id}"
        )

        # Process the join request
        success, response_data, error_message = (
            await join_trial_service.join_club_trial_free(user_id, request)
        )

        if success and response_data:
            logger.info(f"Successfully processed trial-free join for user {user_id}")
            member_name = (
                current_user.get("full_name")
                or current_user.get("first_name")
                or current_user.get("email")
                or "New member"
            )
            await _notify_captain_member_join(
                club_name_based_id=request.club_id,
                new_member_id=user_id,
                new_member_name=member_name,
                membership_type="trial",
            )
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club joined successfully with trial access",
                data=response_data,
            )
        else:
            logger.warning(f"Failed to process trial-free join: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to join club with trial access",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in join_club_trial_free: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/trial-status", response_model=JoinTrialFreeResponse)
async def get_trial_status(
    current_user: dict = Depends(get_current_user),
    join_trial_service=Depends(get_join_trial_free_service),
):
    """
    Get user's trial membership status and joined clubs

    This endpoint provides comprehensive information about the user's trial membership
    including all clubs they have joined and their access status.

    **Response includes:**
    - Current trial membership status
    - List of all clubs joined during trial
    - Access expiry dates for each club
    - Whether user can join more clubs
    - Days remaining in trial period

    **Example Usage:**
    ```
    GET /api/v1/trial-status
    ```

    **Access Control:**
    - Only Members with trial membership can access this endpoint
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role", "Member")

        # Validate user role
        if user_role != "Member":
            return create_response(
                status_code=status.HTTP_403_FORBIDDEN,
                status="error",
                message="Only Members can access trial status",
                data=None,
            )

        logger.info(f"Getting trial status for user {user_id}")

        # Get trial status
        success, response_data, error_message = (
            await join_trial_service.get_user_trial_status(user_id)
        )

        if success and response_data:
            logger.info(f"Successfully retrieved trial status for user {user_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Trial status retrieved successfully",
                data=response_data,
            )
        else:
            logger.warning(f"Failed to get trial status: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve trial status",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in get_trial_status: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# JOIN PAID ENDPOINTS
# ============================================================================


# Dependency to get join paid service
def get_join_paid_service():
    from .join_paid_service import JoinPaidService

    return JoinPaidService()


@router.post("/join-paid", response_model=JoinPaidResponse)
async def join_club_paid(request: JoinPaidRequest):
    """
    Join a club with paid subscription or change existing subscription plan

    This endpoint allows members to join clubs with paid subscriptions OR change their existing subscription plan.
    It processes Stripe payments, validates pricing plans, and manages paid memberships.

    **Features:**
    - **New Membership**: Processes payments for new club memberships
    - **Plan Changes**: Allows existing members to change their subscription plans
    - **Payment Processing**: Processes payments through Stripe (regular payments)
    - **Price Validation**: Validates price_id against Stripe dashboard
    - **Trial Member Support**: Allows trial members to join paid clubs
    - **Membership Management**: Creates paid memberships with proper duration
    - **Database Updates**: Updates both clubs and users collections

    **Request Body:**
    - `email`: Member's email address
    - `payment_method_id`: Stripe payment method ID
    - `price`: Price to be paid
    - `price_id`: Stripe price ID for validation
    - `club_name_based_id`: Name-based ID of the club to join
    - `pricing_plan`: Pricing plan (monthly, quarterly, yearly)

    **Response includes:**
    - Club details (ID, name, captain name)
    - Member details (join date, end date, pricing plan)
    - Payment information (amount paid, payment ID)
    - Club statistics (member count, paid member count)
    - User statistics (total clubs joined, paid clubs joined)

    **Plan Change Logic (for existing members):**
    - Current subscription continues until its end date
    - New plan starts the day after current subscription ends
    - Payment is processed immediately for the new plan
    - Plan change is scheduled in the database
    - User continues with current plan until scheduled change date

    **Trial Member Logic:**
    - Trial members can join paid clubs even during trial period
    - Trial members can join 5th+ club only via paid (not free)
    - After trial ends, can only access paid clubs
    - Club count remains 1 regardless of how many clubs joined

    **Example Usage (New Membership):**
    ```
    POST /api/v1/join-paid
    {
        "email": "member@example.com",
        "payment_method_id": "pm_1234567890",
        "price": 29.99,
        "price_id": "price_monthly_1234567890",
        "club_name_based_id": "premium-sports-club",
        "pricing_plan": "monthly"
    }
    ```

    **Example Usage (Plan Change):**
    ```
    POST /api/v1/join-paid
    {
        "email": "existing_member@example.com",
        "payment_method_id": "pm_1234567890",
        "price": 299.99,
        "price_id": "price_yearly_1234567890",
        "club_name_based_id": "premium-sports-club",
        "pricing_plan": "yearly"
    }
    ```

    **Access Control:**
    - No authentication required (email-based lookup)
    - Validates user exists with provided email
    - For new memberships: Checks if user is already a member
    - For plan changes: Validates user is an active member
    """
    try:
        logger.info(f"Processing paid club join request for email: {request.email}")

        # Get join paid service
        join_paid_service = get_join_paid_service()

        # Process the join request
        success, response_data, error_message = await join_paid_service.join_club_paid(
            request
        )

        if success and response_data:
            logger.info(
                f"Successfully processed paid club join for email: {request.email}"
            )
            member_details = response_data.member_details
            member_id = getattr(member_details, "user_id", None) if member_details else None
            if not member_id:
                try:
                    user_doc = await get_user_collection().find_one({"email": request.email})
                    if user_doc:
                        member_id = str(user_doc.get("_id"))
                except Exception as lookup_error:
                    logger.warning(f"⚠️ Unable to resolve member ID for notification: {lookup_error}")
            member_name = (
                getattr(member_details, "full_name", None)
                if member_details
                else None
            ) or request.email
            await _notify_captain_member_join(
                club_name_based_id=response_data.club_name_based_id or request.club_name_based_id,
                new_member_id=member_id,
                new_member_name=member_name,
                membership_type="paid",
            )
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club joined successfully with paid membership",
                data=response_data,
            )
        else:
            logger.warning(f"Failed to process paid club join: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to join club with paid membership",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in join_club_paid: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# PLAN CHANGE EXECUTION ENDPOINTS (Admin/System)
# ============================================================================


@router.post("/execute-plan-changes")
async def execute_scheduled_plan_changes():
    """
    Execute all scheduled plan changes that are due (Admin/System endpoint)

    This endpoint manually triggers the execution of scheduled plan changes.
    In production, this would typically be run as a scheduled job/cron task.

    **Features:**
    - **Manual Execution**: Triggers execution of all due plan changes
    - **Batch Processing**: Processes all scheduled changes at once
    - **Error Handling**: Continues processing even if some changes fail
    - **Summary Report**: Returns count of successful and failed executions

    **Response includes:**
    - Total scheduled changes found
    - Number of successful executions
    - Number of failed executions
    - Execution summary and timing

    **Use Cases:**
    - Manual testing of plan change execution
    - Admin intervention for stuck plan changes
    - System maintenance and monitoring
    - Debugging plan change issues
    """
    try:
        logger.info("🔄 Manual execution of scheduled plan changes requested")

        # Get plan change executor service
        from .plan_change_executor_service import PlanChangeExecutorService

        executor_service = PlanChangeExecutorService()

        # Execute scheduled plan changes
        successful, failed = await executor_service.execute_scheduled_plan_changes()

        # Get summary of remaining scheduled changes
        summary = await executor_service.get_scheduled_plan_changes_summary()

        response_data = {
            "execution_summary": {
                "successful_executions": successful,
                "failed_executions": failed,
                "total_processed": successful + failed,
                "execution_time": datetime.now().isoformat(),
            },
            "remaining_scheduled_changes": summary,
        }

        logger.info(
            f"✅ Plan change execution completed: {successful} successful, {failed} failed"
        )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Plan change execution completed. {successful} successful, {failed} failed.",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"❌ Error in execute_scheduled_plan_changes: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/plan-changes/summary")
async def get_plan_changes_summary():
    """
    Get summary of all scheduled plan changes (Admin endpoint)

    This endpoint provides a summary of all scheduled plan changes in the system.
    Useful for monitoring and administrative purposes.

    **Response includes:**
    - Total scheduled changes
    - Changes due today
    - Overdue changes
    - Last checked timestamp

    **Use Cases:**
    - System monitoring
    - Administrative oversight
    - Planning maintenance windows
    - Debugging plan change issues
    """
    try:
        logger.info("📊 Getting plan changes summary")

        # Get plan change executor service
        from .plan_change_executor_service import PlanChangeExecutorService

        executor_service = PlanChangeExecutorService()

        # Get summary
        summary = await executor_service.get_scheduled_plan_changes_summary()

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Plan changes summary retrieved successfully",
            data=summary,
        )

    except Exception as e:
        logger.error(f"❌ Error getting plan changes summary: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# MODERATOR MANAGEMENT ENDPOINTS
# ============================================================================


@router.delete("/moderator/delete")
async def delete_moderator(
    club_id: str = Query(..., description="Club ID where moderator is to be deleted"),
    moderator_user_id: str = Query(..., description="User ID of moderator to delete"),
    current_captain: dict = Depends(get_current_captain),
):
    """
    Soft delete a moderator from a club (Captain only)

    This endpoint allows captains to soft delete moderators from their clubs
    by setting the moderator's status to "inactive" in the detailed_moderators array.

    **Features:**
    - **Captain Only**: Only the club captain can delete moderators
    - **Soft Delete**: Sets status to "inactive" instead of removing the record
    - **Club Validation**: Ensures captain owns the club
    - **Moderator Validation**: Ensures moderator exists in the club

    **Query Parameters:**
    - `club_id`: ID of the club (name_based_id or ObjectId)
    - `moderator_user_id`: User ID of the moderator to delete

    **Response includes:**
    - Success confirmation
    - Updated moderator count
    - Updated free/paid moderator counts

    **Example Usage:**
    ```
    DELETE /api/v1/moderator/delete?club_id=first-club&moderator_user_id=68a5c9e3fbc52005261df136
    ```
    """
    try:
        logger.info(
            f"🗑️ Processing moderator delete request for club: {club_id}, moderator: {moderator_user_id}"
        )

        captain_id = current_captain["user_id"]
        club_collection = get_club_collection()

        # Find the club and verify captain ownership
        if is_valid_name_based_id(club_id):
            club = await club_collection.find_one(
                {"name_based_id": club_id, "captain_id": captain_id}
            )
        else:
            try:
                club = await club_collection.find_one(
                    {"_id": ObjectId(club_id), "captain_id": captain_id}
                )
            except Exception:
                return create_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    status="error",
                    message="Invalid club ID format",
                    data=None,
                )

        if not club:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Club not found or you don't have permission to delete moderators from this club",
                data=None,
            )

        # Find the moderator in detailed_moderators array
        detailed_moderators = club.get("detailed_moderators", [])
        moderator_found = False
        updated_moderators = []

        for moderator in detailed_moderators:
            if str(moderator.get("user_id")) == moderator_user_id:
                if moderator.get("status") == "inactive":
                    return create_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        status="error",
                        message="Moderator is already deleted",
                        data=None,
                    )

                # Soft delete the moderator
                moderator["status"] = "inactive"
                moderator["deleted_at"] = datetime.utcnow()
                moderator_found = True
                logger.info(
                    f"✅ Moderator {moderator.get('full_name')} marked as inactive"
                )

            updated_moderators.append(moderator)

        if not moderator_found:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Moderator not found in this club",
                data=None,
            )

        # Calculate updated counts
        active_moderators = [
            m for m in updated_moderators if m.get("status") == "active"
        ]
        active_free_moderators = [
            m for m in active_moderators if m.get("type_of_moderator") == "free"
        ]
        active_paid_moderators = [
            m for m in active_moderators if m.get("type_of_moderator") == "paid"
        ]

        # Update the club document
        update_result = await club_collection.update_one(
            {"_id": club["_id"]},
            {
                "$set": {
                    "detailed_moderators": updated_moderators,
                    "moderator_count": len(active_moderators),
                    "free_moderators": len(active_free_moderators),
                    "paid_moderators": len(active_paid_moderators),
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        if update_result.modified_count > 0:
            logger.info(f"✅ Successfully soft deleted moderator from club {club_id}")
            
            # Send moderator deletion notification to all club members
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    get_club_members,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                club_name_based_id = club.get("name_based_id")
                if club_name_based_id:
                    # Get all club members
                    all_club_members = await get_club_members(club_name_based_id)
                    
                    if all_club_members:
                        # Normalize member IDs
                        db_user_ids: List[str] = []
                        for member in all_club_members:
                            if isinstance(member, dict):
                                uid = member.get("user_id")
                            else:
                                uid = member
                            if uid:
                                db_user_ids.append(uid)
                        
                        # Filter by club status alerts
                        enabled_user_ids = await filter_users_by_notification_preference(
                            db_user_ids,
                            "club_status_alerts"
                        )
                        enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]

                        # Determine users with active device tokens
                        collections = get_collections()
                        user_tokens_collection = collections.get_user_tokens_collection()

                        users_with_tokens: List[str] = []
                        if enabled_user_ids:
                            token_cursor = user_tokens_collection.find(
                                {
                                    "user_id": {"$in": enabled_user_ids},
                                    "is_active": True,
                                },
                                {"user_id": 1},
                            )
                            token_docs = await token_cursor.to_list(length=None)
                            users_with_tokens = list({
                                doc.get("user_id") for doc in token_docs if doc.get("user_id")
                            })

                        push_user_ids = [
                            uid for uid in users_with_tokens if uid in enabled_user_ids
                        ]

                        if db_user_ids:
                            # Get moderator name for notification
                            deleted_moderator = None
                            for mod in updated_moderators:
                                if str(mod.get("user_id")) == moderator_user_id:
                                    deleted_moderator = mod
                                    break
                            
                            moderator_name = deleted_moderator.get("full_name", "A moderator") if deleted_moderator else "A moderator"
                            
                            # Prepare notification content
                            title = f"Moderator Removed!"
                            body = f"{moderator_name} has been removed as moderator by Captain"
                            
                            notification_data = {
                                "club_id": club_name_based_id,
                                "club_name": club.get("name", "Club"),
                                "moderator_name": moderator_name,
                                "moderator_id": moderator_user_id,
                                "action_type": "moderator_deletion",
                                "changed_by": "Captain"
                            }
                            
                            notification_result = await send_notification_to_users(
                                user_ids=push_user_ids,
                                title=title,
                                body=body,
                                notification_type="club_status_change",
                                data=notification_data,
                                click_action=f"club/{club_name_based_id}/moderators",
                                priority="normal",
                                all_user_ids=db_user_ids,
                            )
                            logger.info(
                                f"✅ Moderator deletion notification stored for club {club_name_based_id}: {notification_result}"
                            )
                        else:
                            logger.info(f"ℹ️ No eligible club members found for club {club_name_based_id}")
                    else:
                        logger.info(f"ℹ️ No club members found for club {club_name_based_id}")
                        
            except Exception as e:
                logger.error(f"⚠️ Failed to send moderator deletion notification: {e}")
            
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Moderator deleted successfully",
                data={
                    "club_id": str(club["_id"]),
                    "club_name": club.get("name"),
                    "club_name_based_id": club.get("name_based_id"),
                    "moderator_user_id": moderator_user_id,
                    "moderator_count": len(active_moderators),
                    "free_moderators": len(active_free_moderators),
                    "paid_moderators": len(active_paid_moderators),
                    "deleted_at": datetime.utcnow().isoformat(),
                },
            )
        else:
            return create_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Failed to update club document",
                data=None,
            )

    except Exception as e:
        logger.error(f"Error deleting moderator: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.delete("/club/delete-member", response_model=SoftDeleteMemberResponse)
async def soft_delete_member(
    request: SoftDeleteMemberRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Soft delete a member from a club (Captain only)

    This endpoint allows captains to soft delete members from their clubs.
    The member's status and membership_status will be set to "inactive" in both
    the paid_members and members arrays in the clubs table.

    **Features:**
    - **Captain Only**: Only the club captain can delete members
    - **Soft Delete**: Sets status and membership_status to "inactive" instead of removing the record
    - **Club Validation**: Ensures captain owns the club
    - **Member Validation**: Ensures member exists in the club (trial or paid)
    - **Dual Array Update**: Updates both paid_members and members arrays

    **Request Body:**
    - `club_id`: ID of the club (name_based_id or ObjectId)
    - `member_user_id`: User ID of the member to soft delete

    **Response includes:**
    - Success confirmation
    - Club and member details
    - Membership type (trial/paid)
    - Updated arrays information

    **Example Usage:**
    ```json
    DELETE /api/v1/club/delete-member
    {
        "club_id": "elite-sports-betting",
        "member_user_id": "68a5c9e3fbc52005261df136"
    }
    ```
    """
    try:
        logger.info(
            f"🗑️ Processing soft delete member request for club: {request.club_id}, member: {request.member_user_id}"
        )

        captain_id = current_captain["user_id"]
        soft_delete_service = get_soft_delete_member_service()

        result = await soft_delete_service.soft_delete_member(request, captain_id)

        if result.success:
            logger.info(
                f"✅ Member soft deleted successfully from club: {result.club_name}"
            )
        else:
            logger.warning(f"⚠️ Member soft delete failed: {result.message}")

        return result

    except Exception as e:
        logger.error(f"❌ Error in soft delete member endpoint: {e}")
        import traceback

        traceback.print_exc()
        return SoftDeleteMemberResponse(
            success=False,
            message=f"Internal server error: {str(e)}",
            club_id=request.club_id,
            club_name="",
            member_user_id=request.member_user_id,
            member_name="",
            membership_type="",
            updated_arrays=[],
        )


@router.get("/debug/captain-clubs")
async def debug_captain_clubs(current_captain: dict = Depends(get_current_captain)):
    """Debug endpoint to see what clubs the current captain owns"""
    try:
        captain_id = current_captain["user_id"]
        club_collection = get_club_collection()

        # Get all clubs owned by this captain
        captain_clubs = await club_collection.find({"captain_id": captain_id}).to_list(
            length=10
        )

        # Also check for any clubs with "mvp" in the name
        mvp_clubs = await club_collection.find(
            {"name": {"$regex": "mvp", "$options": "i"}}
        ).to_list(length=5)

        # Check specifically for the club we're trying to edit
        target_club = await club_collection.find_one(
            {"name_based_id": "mvp-football-club"}
        )

        # Check for "second-club" specifically
        second_club = await club_collection.find_one({"name_based_id": "second-club"})

        debug_info = {
            "captain_id": captain_id,
            "captain_name": current_captain.get("full_name"),
            "total_clubs_owned": len(captain_clubs),
            "target_club_found": target_club is not None,
            "target_club": (
                {
                    "name": target_club.get("name") if target_club else None,
                    "name_based_id": (
                        target_club.get("name_based_id") if target_club else None
                    ),
                    "captain_id": (
                        str(target_club.get("captain_id")) if target_club else None
                    ),
                    "is_active": (
                        target_club.get("is_active", True) if target_club else None
                    ),
                }
                if target_club
                else None
            ),
            "second_club_found": second_club is not None,
            "second_club": (
                {
                    "name": second_club.get("name") if second_club else None,
                    "name_based_id": (
                        second_club.get("name_based_id") if second_club else None
                    ),
                    "captain_id": (
                        str(second_club.get("captain_id")) if second_club else None
                    ),
                    "captain_id_type": (
                        type(second_club.get("captain_id")).__name__
                        if second_club
                        else None
                    ),
                    "is_active": (
                        second_club.get("is_active", True) if second_club else None
                    ),
                    "total_members": (
                        second_club.get("total_members", 0) if second_club else None
                    ),
                    "paid_member_count": (
                        second_club.get("paid_member_count", 0) if second_club else None
                    ),
                }
                if second_club
                else None
            ),
            "captain_clubs": [
                {
                    "name": club.get("name"),
                    "name_based_id": club.get("name_based_id"),
                    "captain_id": str(club.get("captain_id")),
                    "captain_id_type": type(club.get("captain_id")).__name__,
                    "is_active": club.get("is_active", True),
                    "club_complete_step": club.get("club_complete_step", 0),
                }
                for club in captain_clubs
            ],
            "mvp_clubs_found": [
                {
                    "name": club.get("name"),
                    "name_based_id": club.get("name_based_id"),
                    "captain_id": str(club.get("captain_id")),
                    "is_active": club.get("is_active", True),
                }
                for club in mvp_clubs
            ],
        }

        return create_response(
            status_code=200,
            status="success",
            message="Captain clubs debug info",
            data=debug_info,
        )

    except Exception as e:
        logger.error(f"Error in debug_captain_clubs: {e}")
        return create_response(
            status_code=500, status="error", message=f"Debug error: {str(e)}", data=None
        )


@router.put("/club/edit", response_model=ClubEditResponse)
async def edit_club(
    request: ClubEditRequest, current_captain: dict = Depends(get_current_captain)
):
    """
    Edit club details including pricing plans with Stripe integration (Captain only)

    This endpoint allows captains to edit their club details including:
    - Basic information (name, description, sub_description, logo_url)
    - Content (whats_included, top_3_sports)
    - Pricing plans (update existing and add new ones)

    **Features:**
    - **Captain Only**: Only the club captain can edit their own clubs
    - **Stripe Integration**: Automatically updates/creates Stripe prices
    - **Member Notifications**: Sends email notifications when pricing changes
    - **Comprehensive Updates**: Supports updating multiple fields at once

    **Request Body:**
    - `club_id`: ID of the club to edit (name_based_id or ObjectId)
    - `name`: Updated club name (optional)
    - `description`: Updated club description (optional)
    - `sub_description`: Updated sub description (optional)
    - `logo_url`: Updated logo URL (optional)
    - `whats_included`: Updated what's included list (optional)
    - `top_3_sports`: Updated top 3 sports list (optional)
    - `pricing_plans_edit`: Existing pricing plans to update (optional)
    - `pricing_plans_add`: New pricing plans to add (optional)

    **Response includes:**
    - Success confirmation
    - List of updated fields
    - Count of pricing plans updated/added
    - Number of members notified

    **Example Usage:**
    ```json
    {
        "club_id": "first-club",
        "name": "Updated Club Name",
        "description": "Updated description",
        "pricing_plans_edit": [
            {
                "frequency": "monthly",
                "price": 15.99,
                "currency": "USD",
                "stripe_price_id": "price_1234567890"
            }
        ],
        "pricing_plans_add": [
            {
                "frequency": "yearly",
                "price": 149.99,
                "currency": "USD"
            }
        ]
    }
    ```
    """
    try:
        logger.info(f"🔧 Processing club edit request for club: {request.club_id}")

        captain_id = current_captain["user_id"]
        club_edit_service = get_club_edit_service()

        # Process the club edit
        result = await club_edit_service.edit_club(request, captain_id)

        if result.success:
            logger.info(f"✅ Club edited successfully: {result.club_name}")
        else:
            logger.warning(f"⚠️ Club edit failed: {result.message}")

        return result

    except Exception as e:
        logger.error(f"❌ Error in club edit endpoint: {e}")
        import traceback

        traceback.print_exc()
        return ClubEditResponse(
            success=False,
            message=f"Internal server error: {str(e)}",
            club_id=request.club_id,
            club_name="",
            updated_fields=[],
            pricing_plans_updated=0,
            pricing_plans_added=0,
            members_notified=0,
        )


# ============================================================================
# MEMBER AND CLUB DETAILS ENDPOINTS
# ============================================================================


@router.get("/club/{club_id}/members")
async def get_club_members_details(
    club_id: str, current_captain: dict = Depends(get_current_captain)
):
    """
    Get detailed information about all members of a club

    This endpoint allows captains to view detailed information about all members
    who have joined their club, including membership details, join dates, and status.

    **Response includes:**
    - Member's full name, email, phone
    - Membership type (trial/paid) and status
    - Pricing plan and payment details
    - Join date and end date
    - Last seen and activity status

    **Access Control:**
    - Only the club captain can access this endpoint
    - Validates club ownership before returning member details
    """
    try:
        captain_id = current_captain["user_id"]

        # Validate club ownership
        club_collection = get_club_collection()
        club = await club_collection.find_one(
            {"_id": ObjectId(club_id), "captain_id": captain_id}
        )

        if not club:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Club not found or you don't have permission to view its members",
                data=None,
            )

        # Get detailed member information
        from .membership_service import get_club_members_details

        members_details = await get_club_members_details(club_id)

        logger.info(f"Retrieved {len(members_details)} members for club {club_id}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Retrieved {len(members_details)} members successfully",
            data={
                "club_id": club_id,
                "club_name": club.get("name", ""),
                "total_members": len(members_details),
                "members": members_details,
            },
        )

    except Exception as e:
        logger.error(f"Error getting club members details: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error retrieving member details: {str(e)}",
            data=None,
        )


@router.get("/user/clubs-details")
async def get_user_clubs_details(current_user: dict = Depends(get_current_user)):
    """
    Get detailed information about all clubs a user has joined

    This endpoint provides comprehensive information about all clubs the user
    has joined, including membership details, join dates, and status.

    **Response includes:**
    - Club name, ID, and captain details
    - Membership type (trial/paid) and status
    - Pricing plan and payment details
    - Join date and end date
    - Payment information and amounts

    **Access Control:**
    - Only authenticated users can access this endpoint
    - Returns clubs for the authenticated user only
    """
    try:
        user_id = current_user["user_id"]

        # Get detailed club information for user
        from .membership_service import get_user_clubs_details

        clubs_details = await get_user_clubs_details(user_id)

        logger.info(f"Retrieved {len(clubs_details)} clubs for user {user_id}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Retrieved {len(clubs_details)} clubs successfully",
            data={
                "user_id": user_id,
                "user_name": current_user.get("full_name", "Unknown"),
                "total_clubs_joined": len(clubs_details),
                "clubs": clubs_details,
            },
        )

    except Exception as e:
        logger.error(f"Error getting user clubs details: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error retrieving club details: {str(e)}",
            data=None,
        )


@router.get("/user/stats")
async def get_user_membership_stats(current_user: dict = Depends(get_current_user)):
    """
    Get user's membership statistics and summary

    This endpoint provides a summary of the user's membership activity,
    including total clubs joined, active memberships, and trial usage.

    **Response includes:**
    - Total clubs joined
    - Active memberships count
    - Trial memberships count
    - Paid memberships count
    - Total amount paid
    - Membership status breakdown

    **Access Control:**
    - Only authenticated users can access this endpoint
    - Returns statistics for the authenticated user only
    """
    try:
        user_id = current_user["user_id"]

        # Get detailed club information for user
        from .membership_service import get_user_clubs_details

        clubs_details = await get_user_clubs_details(user_id)

        # Calculate statistics
        total_clubs = len(clubs_details)
        active_memberships = len(
            [c for c in clubs_details if c.get("is_active", False)]
        )
        trial_memberships = len([c for c in clubs_details if c.get("is_trial", False)])
        paid_memberships = len(
            [c for c in clubs_details if not c.get("is_trial", False)]
        )
        total_amount_paid = sum([c.get("amount_paid", 0.0) for c in clubs_details])

        # Status breakdown
        status_breakdown = {}
        for club in clubs_details:
            status = club.get("membership_status", "unknown")
            status_breakdown[status] = status_breakdown.get(status, 0) + 1

        stats = {
            "user_id": user_id,
            "user_name": current_user.get("full_name", "Unknown"),
            "total_clubs_joined": total_clubs,
            "active_memberships": active_memberships,
            "trial_memberships": trial_memberships,
            "paid_memberships": paid_memberships,
            "total_amount_paid": round(total_amount_paid, 2),
            "status_breakdown": status_breakdown,
            "membership_summary": {
                "total_clubs": total_clubs,
                "active_clubs": active_memberships,
                "trial_clubs": trial_memberships,
                "paid_clubs": paid_memberships,
                "total_spent": round(total_amount_paid, 2),
            },
        }

        logger.info(f"Retrieved membership stats for user {user_id}: {stats}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Membership statistics retrieved successfully",
            data=stats,
        )

    except Exception as e:
        logger.error(f"Error getting user membership stats: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error retrieving membership statistics: {str(e)}",
            data=None,
        )


# ============================================================================
# MY CLUB DETAIL ENDPOINT
# # ============================================================================
# @router.get("yes/{club_name_based_id}")
# async def get_live_bets_by_club(
#     club_name_based_id: str,
#     chat_user=Depends(get_current_user),
# ):
#     """
#     Get all live bets submitted by the Captain for a specific club (club_name_based_id)
#     where bet_source = "live-support".
#     """

#     try:
#         from .db import get_database
#         logger.info(f"Fetching live bets for club: {club_name_based_id}")

#         db = await get_database()
#         club_picks_collection = db["club_picks"]
#         users_collection = get_user_collection()

#         # Query club_picks for live bets
#         club_picks_cursor = club_picks_collection.find(
#             {
#                 "club_id": club_name_based_id,
#                 "bet_source": "live-support",
#             }
#         )

#         club_picks = await club_picks_cursor.to_list(length=None)

#         if not club_picks:
#             return create_response(
#                 status_code=status.HTTP_200_OK,
#                 status="success",
#                 message="No live bets found for this club.",
#                 data=[],
#             )

#         response_data = []
#         for pick in club_picks:
#             submitted_by_id = pick.get("submitted_by")

#             # Get user (captain/moderator) info from users table
#             user_info = await users_collection.find_one(
#                 {"_id": ObjectId(submitted_by_id)},
#                 {"full_name": 1, "avatar_url": 1},
#             )

#             response_data.append({
#                 "submitted_by": str(submitted_by_id),
#                 "submitted_by_role": pick.get("submitted_by_role"),
#                 "captain_name": user_info.get("full_name") if user_info else None,
#                 "captain_avatar_url": user_info.get("avatar_url") if user_info else None,
#                 "pick_entity_type": pick.get("pick_entity_type"),
#                 "team1": pick.get("team1"),
#                 "team2": pick.get("team2"),
#                 "player_name": pick.get("player_name"),
#                 "platform": pick.get("platform"),
#                 "bet_for": pick.get("bet_for"),
#                 "match_datetime": pick.get("match_datetime"),
#                 "status": pick.get("status"),
#                 "result": pick.get("result"),
#             })

#         return create_response(
#             status_code=status.HTTP_200_OK,
#             status="success",
#             message="Live bets fetched successfully.",
#             data=response_data,
#         )

#     except Exception as e:
#         logger.exception(f"Error fetching live bets: {str(e)}")
#         return create_response(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             status="error",
#             message="Failed to fetch live bets.",
#         )

@router.get("/my-club-detail/{club_name_based_id}", response_model=MyClubDetailResponse)
async def get_my_club_detail(
    club_name_based_id: str,
    current_user: dict = Depends(get_current_user),
    hub_service=Depends(get_hub_service),
):
    """
    Get detailed information about a specific club for a member

    This endpoint allows members to view comprehensive details about a club they have joined,
    including club information, membership details, moderator information, and hub content.

    **Access Control:**
    - Only members who have joined the club can access this endpoint
    - Validates membership before returning club details

    **Response includes:**
    - Club basic information (ID, name, description, status)
    - Member's join and end dates for this club
    - Moderator details (emails and names)
    - Captain information (ID, name, name-based ID)
    - Club statistics (member count, total bets, win percentage)
    - Hub content summary (strategy videos, training videos, partner links)
    - Top 3 sports for the club
    - Trial club statistics (clubs_joined_count, clubs_remaining, max_clubs)
    - Club rejection information (rejection_type, rejection_reason, rejected_by, is_resubmit, is_club_reject_temporary, is_club_reject_permanently)
    - User role (Member, Moderator, or Captain based on user's relationship to the club)

    **Example Usage:**
    ```
    GET /api/v1/my-club-detail/badminton-group
    ```

    Returns detailed club information for the authenticated member.
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role", "Member")
        user_name = current_user.get("full_name", "Unknown")

        # Validate that user is a member
        if user_role != "Member":
            return create_response(
                status_code=status.HTTP_403_FORBIDDEN,
                status="error",
                message="Only members can access club details",
                data=None,
            )

        logger.info(
            f"Getting club detail for member {user_id} ({user_name}), club {club_name_based_id}"
        )

        # Get club detail using the service
        success, club_detail_data, error_message = (
            await hub_service.get_member_club_detail(user_id, club_name_based_id)
        )

        if not success:
            logger.warning(f"Failed to get club detail: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve club details",
                data=None,
            )

        # Convert to response model
        response_data = MyClubDetailResponse(**club_detail_data)

        logger.info(
            f"Successfully retrieved club detail for member {user_id}, club {club_name_based_id}"
        )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Club details retrieved successfully",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"Unexpected error in get_my_club_detail: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# CAPTAIN CLUB DETAIL ENDPOINT
# ============================================================================


@router.get(
    "/my-club-captain-detail/{club_name_based_id}",
    response_model=CaptainClubDetailResponse,
)
async def get_my_club_captain_detail(
    club_name_based_id: str,
    current_captain: dict = Depends(get_current_captain),
    hub_service=Depends(get_hub_service),
):
    """
    Get detailed information about a specific club for a captain/moderator/member

    This endpoint allows users to view comprehensive details about clubs they have access to,
    including club information, betting statistics, revenue, and member details.

    **Access Control:**
    - Requires captain authentication (get_current_captain)
    - User can view details if they are:
      - Captain (owner) of the club
      - Moderator of the club
      - Member of the club (trial or paid)

    **Response includes:**
    - Club basic information (ID, name, description, status, logo URL, pricing plan, pricing plans array)
    - Betting statistics (total bets, wins, losses, win percentage)
    - Bet type breakdowns (spread, over/under, moneyline, parlay)
    - Revenue information (total revenue generated)
    - Member counts (total members, active members, inactive members)
    - Moderator counts
    - Captain information (ID, name, name-based ID)
    - User role (dynamic: "Captain", "Moderator", or "Member" based on user's relationship to the club)
    - Club features (what's included, top 3 sports)
    - Club rejection information (rejection_type, rejection_reason, rejected_by, is_resubmit, is_club_reject_temporary, is_club_reject_permanently)

    **Example Usage:**
    ```
    GET /api/v1/my-club-captain-detail/badminton-group
    ```

    Returns detailed club information based on user's role in the club.
    """
    try:
        captain_id = current_captain["user_id"]
        captain_name = current_captain.get("full_name", "Unknown Captain")

        logger.info(
            f"Getting captain club detail for captain {captain_id} ({captain_name}), club {club_name_based_id}"
        )

        # Get club detail using the service
        success, club_detail_data, error_message = (
            await hub_service.get_captain_club_detail(captain_id, club_name_based_id)
        )

        if not success:
            logger.warning(f"Failed to get captain club detail: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve club details",
                data=None,
            )

        # Convert to response model
        response_data = CaptainClubDetailResponse(**club_detail_data)

        logger.info(
            f"Successfully retrieved captain club detail for captain {captain_id}, club {club_name_based_id}"
        )

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Captain club details retrieved successfully",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"Unexpected error in get_my_club_captain_detail: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# MODERATOR VIEW ENDPOINTS
# ============================================================================


# Dependency to get moderator view service
def get_moderator_view_service():
    from .moderator_view_service import ModeratorViewService

    return ModeratorViewService()


@router.post("/view-moderators", response_model=ModeratorViewResponse)
async def view_club_moderators(
    request: ModeratorViewRequest, current_captain: dict = Depends(get_current_captain)
):
    """
    View detailed moderator information for a club with pagination

    This endpoint allows captains to view detailed information about moderators
    in their own clubs only. It provides pagination and comprehensive moderator statistics.

    **Features:**
    - **Captain Only**: Only accessible to authenticated captains
    - **Ownership Validation**: Captains can only view moderators of clubs they created
    - **Pagination**: Supports pagination with configurable page size
    - **Detailed Information**: Returns comprehensive moderator details
    - **Statistics**: Provides moderator counts and pricing information

    **Request Body:**
    - `club_id`: Club ID or name_based_id to view moderators for
    - `page`: Page number for pagination (default: 1)
    - `page_size`: Number of moderators per page (default: 10, max: 100)

    **Response includes:**
    - Club information (ID, name, name_based_id)
    - List of detailed moderator information
    - Pagination information (current page, total pages, has_next, has_previous)
    - Moderator statistics (total, free, paid, pricing)

    **Moderator Details include:**
    - Email address
    - Full name
    - User ID
    - Status (active, inactive, pending)
    - Type (free, paid)
    - Price (0 for free, 9.95 for paid)
    - Invitation timestamps
    - Response status

    **Example Usage:**
    ```
    POST /api/v1/view-moderators
    {
        "club_id": "new-club1",
        "page": 1,
        "page_size": 10
    }
    ```

    **Example Response:**
    ```json
    {
        "status": "success",
        "message": "Moderators retrieved successfully",
        "data": {
            "success": true,
            "message": "Moderators retrieved successfully",
            "club_id": "64f7b1234567890abcdef123",
            "club_name": "New Club 1",
            "club_name_based_id": "new-club1",
            "moderators": [
                {
                    "email": "amey@gmail.com",
                    "full_name": "Amey Test",
                    "user_id": "68a5d8b06203022cf799cbd3",
                    "status": "active",
                    "type_of_moderator": "free",
                    "price": 0,
                    "invited_at": "2025-09-04T02:12:33.514Z",
                    "responded_at": null,
                    "response": null
                }
            ],
            "pagination": {
                "current_page": 1,
                "page_size": 10,
                "total_items": 3,
                "total_pages": 1,
                "has_next": false,
                "has_previous": false,
                "items_on_current_page": 3
            },
            "moderator_stats": {
                "total_moderators": 3,
                "free_moderators": 1,
                "paid_moderators": 2,
                "total_price": 19.9,
                "average_price": 9.95
            }
        }
    }
    ```

    **Access Control:**
    - Only captains can access this endpoint
    - Captains can only view moderators of clubs they created
    - Club ownership is validated before returning data

    **Error Scenarios:**
    - Club not found or captain doesn't own the club
    - Invalid page number (beyond total pages)
    - Invalid club ID format
    """
    try:
        captain_id = current_captain["user_id"]
        captain_name = current_captain.get("full_name", "Unknown")

        logger.info(
            f"Processing view-moderators request for captain: {captain_id} ({captain_name})"
        )

        # Get moderator view service
        moderator_service = get_moderator_view_service()

        # Get moderators with pagination
        success, response_data, error_message = (
            await moderator_service.get_club_moderators(request, captain_id)
        )

        if success and response_data:
            logger.info(f"Successfully retrieved moderators for captain {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Moderators retrieved successfully",
                data=response_data,
            )
        else:
            logger.warning(f"Failed to retrieve moderators: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve moderators",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in view_club_moderators: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# MEMBER VIEW ENDPOINTS
# ============================================================================


# Dependency to get member view service
def get_member_view_service():
    from .member_view_service import MemberViewService

    return MemberViewService()


@router.post("/view-members", response_model=MemberViewResponse)
async def view_club_members(
    request: MemberViewRequest, current_captain: dict = Depends(get_current_captain)
):
    """
    View detailed member information for a club with pagination

    This endpoint allows captains to view detailed information about all members
    (both trial and paid) in their own clubs only. It provides pagination and comprehensive member statistics.

    **Features:**
    - **Captain Only**: Only accessible to authenticated captains
    - **Ownership Validation**: Captains can only view members of clubs they created
    - **All Member Types**: Returns both trial and paid members
    - **Pagination**: Supports pagination with configurable page size
    - **Detailed Information**: Returns comprehensive member details
    - **Statistics**: Provides member counts and revenue information

    **Request Body:**
    - `club_id`: Club ID or name_based_id to view members for
    - `page`: Page number for pagination (default: 1)
    - `page_size`: Number of members per page (default: 10, max: 100)

    **Response includes:**
    - Club information (ID, name, name_based_id)
    - List of detailed member information (both trial and paid)
    - Pagination information (current page, total pages, has_next, has_previous)
    - Member statistics (total, trial, paid, active, revenue)

    **Member Details include:**
    - User ID and full name
    - Email and phone number
    - Avatar URL
    - Membership type (trial, paid)
    - Membership status (active, inactive, expired)
    - Pricing plan (trial, monthly, quarterly, yearly)
    - Join date and end date
    - Trial status and active status
    - Last seen timestamp
    - Payment information (for paid members)
    - Amount paid
    - Creation and update timestamps

    **Example Usage:**
    ```
    POST /api/v1/view-members
    {
        "club_id": "new-club1",
        "page": 1,
        "page_size": 10
    }
    ```

    **Example Response:**
    ```json
    {
        "status": "success",
        "message": "Members retrieved successfully",
        "data": {
            "success": true,
            "message": "Members retrieved successfully",
            "club_id": "64f7b1234567890abcdef123",
            "club_name": "New Club 1",
            "club_name_based_id": "new-club1",
            "members": [
                {
                    "user_id": "68b7ee702c555ffbff37fa4c",
                    "full_name": "Member Priya",
                    "email": "memberpriya@yopmail.com",
                    "phone": "111224455778",
                    "avatar_url": null,
                    "membership_type": "trial",
                    "membership_status": "active",
                    "pricing_plan": "trial",
                    "join_date": "2025-09-03T08:37:29.306Z",
                    "end_date": "2025-09-10T08:37:29.116Z",
                    "is_trial": true,
                    "is_active": true,
                    "last_seen": "2025-09-03T08:37:29.306Z",
                    "payment_id": null,
                    "amount_paid": 0,
                    "created_at": "2025-09-03T08:37:29.306Z",
                    "updated_at": "2025-09-03T08:37:29.306Z"
                }
            ],
            "pagination": {
                "current_page": 1,
                "page_size": 10,
                "total_items": 3,
                "total_pages": 1,
                "has_next": false,
                "has_previous": false,
                "items_on_current_page": 3
            },
            "member_stats": {
                "total_members": 3,
                "trial_members": 2,
                "paid_members": 1,
                "active_members": 3,
                "inactive_members": 0,
                "total_revenue": 29.99,
                "average_revenue_per_paid_member": 29.99
            }
        }
    }
    ```

    **Access Control:**
    - Only captains can access this endpoint
    - Captains can only view members of clubs they created
    - Club ownership is validated before returning data

    **Error Scenarios:**
    - Club not found or captain doesn't own the club
    - Invalid page number (beyond total pages)
    - Invalid club ID format
    """
    try:
        captain_id = current_captain["user_id"]
        captain_name = current_captain.get("full_name", "Unknown")

        logger.info(
            f"Processing view-members request for captain: {captain_id} ({captain_name})"
        )

        # Get member view service
        member_service = get_member_view_service()

        # Get members with pagination
        success, response_data, error_message = await member_service.get_club_members(
            request, captain_id
        )

        if success and response_data:
            logger.info(f"Successfully retrieved members for captain {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Members retrieved successfully",
                data=response_data,
            )
        else:
            logger.warning(f"Failed to retrieve members: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve members",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in view_club_members: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


@router.get("/export-captain-members-csv")
async def export_captain_members_csv(
    search: str = Query(
        None, description="Search by email, club name, or member/moderator name"
    ),
    status_filter: str = Query(
        "all", description="Filter by status: 'all', 'active', or 'inactive'"
    ),
    plan_type: str = Query(
        "all", description="Filter by plan type: 'all', 'trial', or 'paid'"
    ),
    club_filter: str = Query(
        "all", description="Filter by specific club (club_id or 'all')"
    ),
    role_filter: str = Query(
        "Member", description="Filter by role: 'Member' or 'Moderator'"
    ),
    moderator_type_filter: str = Query(
        "all",
        description="Filter by moderator type: 'all', 'free', or 'paid' (only when role_filter=Moderator)",
    ),
    sort_by: str = Query(
        "newest",
        description="Sort by: 'newest', 'oldest', 'name_az', 'name_za', 'club_name'",
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Export all members across Captain's created clubs to CSV format

    This endpoint allows captains to export detailed information about all members
    across all their created clubs to CSV format. It uses the same filtering and
    validation logic as the captain-members endpoint.

    **Features:**
    - **Captain Only**: Only accessible to authenticated captains
    - **All Clubs**: Exports members from all clubs created by the captain
    - **Advanced Filtering**: Supports all filters from captain-members endpoint
    - **CSV Format**: Returns data in CSV format for easy import/analysis
    - **Comprehensive Data**: Includes detailed member and club information

    **Query Parameters:**
    - **search**: Search term for email, club name, or member name
    - **status_filter**: Filter by membership status ('all', 'active', 'inactive')
    - **plan_type**: Filter by plan type ('all', 'trial', 'paid')
    - **club_filter**: Filter by specific club ID ('all' for all clubs)
    - **role_filter**: Filter by role ('Member' or 'Moderator')
    - **moderator_type_filter**: Filter by moderator type ('all', 'free', 'paid')
    - **sort_by**: Sort order ('newest', 'oldest', 'name_az', 'name_za', 'club_name')

    **CSV Fields:**
    - User Name: Member's full name
    - Email: Member's email address
    - Club Name: Name of the club the member joined
    - Membership Type: trial or paid
    - Membership Status: active or inactive
    - Amount Paid: Amount paid for paid memberships (empty for trial memberships)

    **Example Usage:**
    ```
    GET /api/v1/export-captain-members-csv?status_filter=active&plan_type=paid&sort_by=newest
    ```

    **Response:**
    - Returns CSV file as blob/stream
    - Content-Type: text/csv
    - Filename: captain_members_[timestamp].csv

    **Access Control:**
    - Only captains can access this endpoint
    - Captains can only export members from clubs they created
    - All filters work exactly like the captain-members endpoint

    **Error Scenarios:**
    - User is not a captain
    - Invalid filter parameters
    - No members found matching the criteria
    """
    try:
        # Validate user role
        user_role = current_user.get("role")
        if user_role != "Captain":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Captains can access this endpoint",
            )

        captain_id = current_user.get("user_id")
        captain_name = current_user.get("full_name", "Unknown")

        if not captain_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Captain ID not found in token",
            )

        logger.info(
            f"Processing CSV export request for captain: {captain_id} ({captain_name})"
        )

        # Validate filter parameters (same as captain-members endpoint)
        valid_status_filters = ["all", "active", "inactive"]
        if status_filter not in valid_status_filters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status_filter. Must be one of: {valid_status_filters}",
            )

        valid_plan_types = ["all", "trial", "paid"]
        if plan_type not in valid_plan_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid plan_type. Must be one of: {valid_plan_types}",
            )

        valid_role_filters = ["Member", "Moderator"]
        if role_filter not in valid_role_filters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role_filter. Must be one of: {valid_role_filters}",
            )

        valid_moderator_type_filters = ["all", "free", "paid"]
        if moderator_type_filter not in valid_moderator_type_filters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid moderator_type_filter. Must be one of: {valid_moderator_type_filters}",
            )

        valid_sort_options = ["newest", "oldest", "name_az", "name_za", "club_name"]
        if sort_by not in valid_sort_options:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort_by. Must be one of: {valid_sort_options}",
            )

        # Get captain members service
        captain_members_service = get_captain_members_service()

        # Get ALL members data by fetching multiple pages if needed
        all_members = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            # Retrieve captain members for current page
            success, members_data, error_message = (
                await captain_members_service.get_captain_members(
                    captain_id=captain_id,
                    page=page,
                    page_size=100,  # Maximum page size to get all data efficiently
                    search=search,
                    status_filter=status_filter,
                    plan_type=plan_type,
                    club_filter=club_filter,
                    role_filter=role_filter,
                    moderator_type_filter=moderator_type_filter,
                    sort_by=sort_by,
                )
            )

            if not success or not members_data:
                logger.warning(
                    f"Failed to retrieve members for CSV export on page {page}: {error_message}"
                )
                if page == 1:  # If first page fails, return error
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=error_message or "Failed to retrieve members for export",
                    )
                else:
                    break  # If later page fails, use what we have

            # Extract members data from current page
            page_members = members_data.get("members", [])
            all_members.extend(page_members)

            # Get pagination info
            pagination = members_data.get("pagination", {})
            total_pages = pagination.get("total_pages", 1)

            page += 1

        # Use all collected members
        members = all_members

        if not members:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No members found matching the criteria",
            )

        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)

        # Write CSV headers - simplified as requested
        headers = [
            "User Name",
            "Email",
            "Club Name",
            "Membership Type",
            "Membership Status",
            "Amount Paid",
        ]
        writer.writerow(headers)

        # Write member data - simplified to only required fields
        for member in members:
            # Debug: Log the member object structure
            logger.info(
                f"Processing member for CSV: {type(member)} - Keys: {list(member.keys()) if isinstance(member, dict) else 'Pydantic object'}"
            )

            # Handle both dict and Pydantic model objects
            if hasattr(member, "full_name"):
                # Pydantic model object
                user_name = member.full_name or ""
                email = member.email or ""
                club_name = getattr(member, "club_name", "") or ""
                membership_type = member.membership_type or ""
                membership_status = member.membership_status or ""
                amount_paid = getattr(member, "amount_paid", "") or ""
            else:
                # Dictionary object - use the correct field names from captain members service
                user_name = (
                    member.get("member_name")  # This is the correct field name
                    or member.get("full_name")
                    or member.get("user_name")
                    or member.get("name")
                    or ""
                )
                email = (
                    member.get("member_email")  # This is the correct field name
                    or member.get("email")
                    or ""
                )
                club_name = member.get("club_name") or member.get("club") or ""
                membership_type = member.get("membership_type") or ""
                membership_status = member.get("membership_status") or ""
                amount_paid = member.get("amount_paid") or ""

            # Handle trial memberships - set amount_paid to 0 for trial members
            if membership_type.lower() == "trial":
                amount_paid = "0"
            elif amount_paid == "" or amount_paid is None:
                amount_paid = "0"

            # Debug: Log extracted values
            logger.info(
                f"Extracted values - User: '{user_name}', Email: '{email}', Club: '{club_name}', Type: '{membership_type}', Status: '{membership_status}', Amount: '{amount_paid}'"
            )

            # Create row with only the required fields
            row = [
                user_name,
                email,
                club_name,
                membership_type,
                membership_status,
                amount_paid,
            ]
            writer.writerow(row)

        # Get CSV content
        csv_content = output.getvalue()
        output.close()

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"captain_members_{timestamp}.csv"

        logger.info(
            f"Successfully exported {len(members)} members to CSV for captain {captain_id}"
        )

        return StreamingResponse(
            io.BytesIO(csv_content.encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in export_captain_members_csv: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred",
        )


@router.post("/export-members-csv")
async def export_club_members_csv(
    request: MemberViewRequest, current_captain: dict = Depends(get_current_captain)
):
    """
    Export detailed member information for a club to CSV format

    This endpoint allows captains to export detailed information about all members
    (both trial and paid) in their own clubs to CSV format. It uses the same filtering
    and validation logic as the view-members endpoint.

    **Features:**
    - **Captain Only**: Only accessible to authenticated captains
    - **Ownership Validation**: Captains can only export members of clubs they created
    - **All Member Types**: Exports both trial and paid members
    - **CSV Format**: Returns data in CSV format for easy import/analysis
    - **Same Logic**: Uses identical filtering logic as view-members endpoint

    **Request Body:**
    - `club_id`: Club ID or name_based_id to export members for
    - `page`: Page number for pagination (default: 1) - Note: CSV export gets ALL members
    - `page_size`: Number of members per page (default: 10, max: 100) - Note: CSV export gets ALL members

    **CSV Fields:**
    - Full Name: Member's full name
    - Email: Member's email address
    - Membership Type: trial or paid
    - Joined Date: When the member joined the club
    - Url: Member's avatar URL (if available)

    **Example Usage:**
    ```
    POST /api/v1/export-members-csv
    {
        "club_id": "new-club1",
        "page": 1,
        "page_size": 10
    }
    ```

    **Response:**
    - Returns CSV file as blob/stream
    - Content-Type: text/csv
    - Filename: club_members_[club_name]_[timestamp].csv

    **Access Control:**
    - Only captains can access this endpoint
    - Captains can only export members of clubs they created
    - Club ownership is validated before returning data

    **Error Scenarios:**
    - Club not found or captain doesn't own the club
    - Invalid club ID format
    - No members found in the club
    """
    try:
        captain_id = current_captain["user_id"]
        captain_name = current_captain.get("full_name", "Unknown")

        logger.info(
            f"Processing export-members-csv request for captain: {captain_id} ({captain_name})"
        )

        # Get member view service
        member_service = get_member_view_service()

        # Create a modified request to get ALL members (no pagination for CSV export)
        # We'll use the maximum allowed page_size and handle multiple pages if needed
        export_request = MemberViewRequest(
            club_id=request.club_id,
            page=1,
            page_size=100,  # Maximum allowed by validation
        )

        # Get ALL members data by fetching multiple pages if needed
        all_members = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            # Create request for current page
            current_request = MemberViewRequest(
                club_id=request.club_id,
                page=page,
                page_size=100,  # Maximum allowed by validation
            )

            # Get members data for current page
            success, response_data, error_message = (
                await member_service.get_club_members(current_request, captain_id)
            )

            if not success or not response_data:
                logger.warning(
                    f"Failed to retrieve members for CSV export on page {page}: {error_message}"
                )
                if page == 1:  # If first page fails, return error
                    return create_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        status="error",
                        message=error_message
                        or "Failed to retrieve members for export",
                        data=None,
                    )
                else:
                    break  # If later page fails, use what we have

            # Extract members data from current page
            page_members = response_data.members
            all_members.extend(page_members)

            # Get pagination info
            pagination = response_data.pagination
            total_pages = pagination.get("total_pages", 1)

            # Get club info from first page
            if page == 1:
                club_name = response_data.club_name
                club_name_based_id = response_data.club_name_based_id

            page += 1

        # Use all collected members
        members = all_members

        if not members:
            logger.warning(f"No members found for club {club_name_based_id}")
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="No members found in this club",
                data=None,
            )

        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)

        # Write CSV headers
        headers = ["Full Name", "Email", "Membership Type", "Joined Date", "Url"]
        writer.writerow(headers)

        # Write member data
        for member in members:
            # Handle both dict and Pydantic model objects
            if hasattr(member, "full_name"):
                # Pydantic model object
                full_name = member.full_name
                email = member.email
                membership_type = member.membership_type
                join_date = (
                    member.join_date.strftime("%Y-%m-%d %H:%M:%S")
                    if member.join_date
                    else ""
                )
                avatar_url = member.avatar_url or ""
            else:
                # Dictionary object
                full_name = member.get("full_name", "")
                email = member.get("email", "")
                membership_type = member.get("membership_type", "")
                join_date = (
                    member.get("join_date", "").strftime("%Y-%m-%d %H:%M:%S")
                    if member.get("join_date")
                    else ""
                )
                avatar_url = member.get("avatar_url", "") or ""

            row = [full_name, email, membership_type, join_date, avatar_url]
            writer.writerow(row)

        # Get CSV content
        csv_content = output.getvalue()
        output.close()

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"club_members_{club_name_based_id}_{timestamp}.csv"

        # Create streaming response
        csv_bytes = io.BytesIO(csv_content.encode("utf-8"))

        logger.info(
            f"Successfully exported {len(members)} members to CSV for captain {captain_id}"
        )

        return StreamingResponse(
            io.BytesIO(csv_content.encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        logger.error(f"Unexpected error in export_club_members_csv: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# MEMBER PRICING ENDPOINTS
# ============================================================================


# Dependency to get member pricing service
def get_member_pricing_service():
    from .member_pricing_service import MemberPricingService

    return MemberPricingService()


@router.post("/member-pricing", response_model=MemberPricingResponse)
async def get_member_pricing_details(request: MemberPricingRequest):
    """
    Get pricing details for any club (public access)

    This endpoint allows anyone to view pricing information for any club.
    It provides detailed pricing plans including Stripe product and price IDs.

    **Features:**
    - **Public Access**: No authentication required - anyone can access
    - **Club Discovery**: View pricing for any club by club_id
    - **Frequency Support**: Supports monthly, quarterly, and yearly pricing
    - **Stripe Integration**: Returns Stripe product and price IDs
    - **Complete Information**: Returns all available pricing plans

    **Request Body:**
    - `club_id`: Club ID or name_based_id to get pricing for
    - `frequency`: Pricing frequency (monthly, quarterly, yearly)

    **Response includes:**
    - Club information (ID, name, name_based_id, logo_url)
    - Member type (trial, paid) and current frequency
    - Specific pricing plan for requested frequency
    - All available pricing plans
    - Member join and end dates

    **Pricing Plan Details include:**
    - Frequency (monthly, quarterly, yearly)
    - Price and currency
    - Stripe product ID and price ID
    - Creation and update timestamps

    **Example Usage:**
    ```
    POST /api/v1/member-pricing
    {
        "club_id": "new-club1",
        "frequency": "monthly"
    }
    ```

    **Example Response:**
    ```json
    {
        "status": "success",
        "message": "Pricing details retrieved successfully",
        "data": {
            "success": true,
            "message": "Pricing details retrieved successfully",
            "club_id": "64f7b1234567890abcdef123",
            "logo_url": "https://example.com/club-logo.jpg",
            "club_name": "New Club 1",
            "club_name_based_id": "new-club1",
            "member_type": "paid",
            "current_frequency": "monthly",
            "pricing_plan": {
                "frequency": "monthly",
                "price": 29.99,
                "currency": "USD",
                "stripe_product_id": "prod_SzANiAQcMbOlcb",
                "stripe_price_id": "price_1S3C2lFhr4pAMUPt6D00rK5x",
                "created_at": "2025-09-03T08:25:30.334Z",
                "updated_at": "2025-09-03T08:25:30.334Z"
            },
            "all_pricing_plans": [
                {
                    "frequency": "monthly",
                    "price": 29.99,
                    "currency": "USD",
                    "stripe_product_id": "prod_SzANiAQcMbOlcb",
                    "stripe_price_id": "price_1S3C2lFhr4pAMUPt6D00rK5x",
                    "created_at": "2025-09-03T08:25:30.334Z",
                    "updated_at": "2025-09-03T08:25:30.334Z"
                },
                {
                    "frequency": "yearly",
                    "price": 100.0,
                    "currency": "USD",
                    "stripe_product_id": "prod_SzANiAQcMbOlcb",
                    "stripe_price_id": "price_1S3C2lFhr4pAMUPt6D00rK5x",
                    "created_at": "2025-09-03T08:25:30.334Z",
                    "updated_at": "2025-09-03T08:25:30.334Z"
                }
            ],
            "member_join_date": "2025-09-03T08:37:29.306Z",
            "member_end_date": "2025-10-03T08:37:29.116Z"
        }
    }
    ```

    **Access Control:**
    - Public access - no authentication required
    - Anyone can view pricing for any club
    - No membership validation required

    **Error Scenarios:**
    - Club not found
    - Invalid frequency (must be monthly, quarterly, or yearly)
    - No pricing plans available for the club
    """
    try:
        logger.info(
            f"Processing public pricing request for club: {request.club_id}, frequency: {request.frequency}"
        )

        # Get member pricing service
        pricing_service = get_member_pricing_service()

        # Get pricing details (no member validation required)
        success, response_data, error_message = (
            await pricing_service.get_public_pricing(request)
        )

        if success and response_data:
            logger.info(
                f"Successfully retrieved pricing details for club {request.club_id}"
            )
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Pricing details retrieved successfully",
                data=response_data,
            )
        else:
            logger.warning(f"Failed to retrieve pricing details: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve pricing details",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in get_member_pricing_details: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# USER MODERATOR STATUS ENDPOINT
# ============================================================================

@router.get("/user/moderator-status")
async def check_user_moderator_status(
    current_user: dict = Depends(get_current_user)
):
    """
    Check if the logged-in user is eligible to submit picks
    
    This endpoint returns a boolean flag indicating whether the user is eligible
    to submit picks, which means they are either:
    1. A captain (regardless of moderator status)
    2. A moderator in any club (regardless of current role)
    
    **Authorization:**
    - Any authenticated user can access this endpoint
    
    **Returns:**
    - Boolean flag indicating eligibility status
    - User information and role details
    
    **Example Response:**
    ```json
    {
        "status": "success",
        "message": "User eligibility status retrieved successfully",
        "data": {
            "user_id": "68e76ec672a292abce5186f1",
            "full_name": "John Doe",
            "user_role": "Captain",
            "is_eligible": true,
            "is_captain": true,
            "is_moderator": true,
            "captain_clubs_count": 3,
            "moderator_clubs_count": 2
        }
    }
    ```
    """
    try:
        from .db import get_club_collection
        
        user_id = current_user["user_id"]
        user_role = current_user["role"]  # Get user's current role
        club_collection = get_club_collection()
        
        # Check if user is a captain (owns any clubs)
        captain_clubs = await club_collection.find({
            "captain_id": user_id
        }).to_list(length=None)
        
        # Check if user is a moderator in any club
        moderator_clubs = await club_collection.find({
            "detailed_moderators.user_id": user_id
        }).to_list(length=None)
        
        is_captain = len(captain_clubs) > 0
        is_moderator = len(moderator_clubs) > 0
        
        # User is eligible if they are either a captain OR a moderator
        is_eligible = is_captain or is_moderator
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="User eligibility status retrieved successfully",
            data={
                "user_id": user_id,
                "full_name": current_user["full_name"],
                "email": current_user["email"],
                "user_role": user_role,
                "is_eligible": is_eligible,
                "is_captain": is_captain,
                "is_moderator": is_moderator,
                "captain_clubs_count": len(captain_clubs),
                "moderator_clubs_count": len(moderator_clubs)
            }
        )
        
    except Exception as e:
        logger.error(f"Error checking user eligibility status: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to check eligibility status: {str(e)}",
            data=None
        )


# ============================================================================
# DEBUG ENDPOINTS (FOR DEVELOPMENT/TESTING ONLY)
# ============================================================================


@router.get("/debug/user-clubs-data/{user_id}")
async def debug_user_clubs_data(
    user_id: str, current_user: dict = Depends(get_current_user)
):
    """
    Debug endpoint to check user's clubs_joined data
    """
    try:
        from .db import get_user_collection
        from bson import ObjectId

        user_collection = get_user_collection()
        user = await user_collection.find_one({"_id": ObjectId(user_id)})

        if not user:
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="User not found",
                data=None,
            )

        clubs_joined = user.get("clubs_joined", [])
        total_clubs_joined = user.get("total_clubs_joined", 0)

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="User clubs data retrieved",
            data={
                "user_id": user_id,
                "user_name": user.get("full_name", "Unknown"),
                "total_clubs_joined": total_clubs_joined,
                "clubs_joined_count": len(clubs_joined),
                "clubs_joined": clubs_joined,
            },
        )

    except Exception as e:
        logger.error(f"Error in debug_user_clubs_data: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error: {str(e)}",
            data=None,
        )


# ============================================================================
# ADD MODERATORS TO EXISTING CLUB ENDPOINTS
# ============================================================================


@router.post("/add-moderators", response_model=AddModeratorsResponse)
async def add_moderators_to_club(
    request: AddModeratorsRequest, current_captain: dict = Depends(get_current_captain)
):
    """
    Add moderators to an existing club with payment processing

    This endpoint allows captains to add additional moderators to their existing clubs
    after the club has been created. Each moderator costs $9.95.

    **Features:**
    - **Payment Processing**: Handles Stripe payment for moderator additions
    - **Duplicate Prevention**: Prevents adding moderators who already exist
    - **User Validation**: Checks if users exist or creates external users
    - **Email Invitations**: Sends invitation emails to new moderators
    - **Captain Verification**: Verifies captain email matches club owner

    **Request Body:**
    - `club_name_based_id`: Name-based ID of the club
    - `captain_email`: Captain's email for verification
    - `moderator_emails`: List of moderator emails to add
    - `payment_method_id`: Stripe payment method ID (optional for free additions)

    **Requirements:**
    - Captain must own the club
    - Captain email must match club owner's email
    - All moderator emails must be unique (not already in club)
    - Payment must be completed if payment_method_id provided
    - Backend calculates amount automatically based on club state

    **Payment Process:**
    1. Backend calculates expected amount based on club moderator count
    2. Creates Stripe customer if needed
    3. Attaches payment method to customer
    4. Creates and processes payment intent
    5. Confirms payment status is "succeeded"
    6. Processes moderator additions

    **Response includes:**
    - Number of moderators added vs skipped
    - Total moderators in club after addition
    - Payment details and status (backend calculated amount)
    - Details of added moderators (free/paid status)
    - Backend calculated total amount paid

    **Use Cases:**
    - Add moderators to existing clubs
    - Scale club management team
    - Process payments for moderator additions

    **Example Usage:**
    ```
    POST /api/v1/add-moderators
    {
        "club_name_based_id": "my-awesome-club",
        "captain_email": "captain@example.com",
        "moderator_emails": ["mod1@example.com", "mod2@example.com"],
        "payment_method_id": "pm_1234567890"
    }
    ```

    **Pricing Logic:**
    - If club has 0 moderators: First moderator is FREE, rest are PAID ($9.95 each)
    - If club has 1+ moderators: All new moderators are PAID ($9.95 each)
    - Backend automatically calculates the correct amount

    Captain-only access required. Each moderator costs $9.95.
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"Processing add moderators request for captain: {captain_id}")

        # Import the service
        from .moderators_service import moderators_service

        success, response_data, error_message = (
            await moderators_service.add_moderators_to_club(request, captain_id)
        )

        if success and response_data:
            logger.info(
                f"Moderators added successfully to club: {request.club_name_based_id}"
            )
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Moderators added successfully",
                data=response_data.model_dump(),
            )
        else:
            logger.warning(f"Add moderators failed: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to add moderators",
                data=None,
            )

    except Exception as e:
        logger.error(f"Unexpected error in add_moderators_to_club: {e}")
        import traceback

        traceback.print_exc()
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# ============================================================================
# MODERATOR MANAGEMENT API ENDPOINTS
# ============================================================================

@router.post("/moderator/delete", response_model=ModeratorDeleteResponse)
async def delete_moderator_by_captain(
    request: ModeratorDeleteRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Delete (deactivate) a moderator from a club by captain
    
    This endpoint allows captains to delete moderators from their clubs
    using the club's name_based_id. The moderator becomes inactive in that specific club.
    
    **Features:**
    - **Captain Only**: Only the club captain can delete moderators
    - **Soft Delete**: Sets moderator status to "inactive" instead of removing the record
    - **Club Validation**: Ensures captain owns the club using name_based_id
    - **Moderator Validation**: Ensures moderator exists in the club
    
    **Request Body:**
    - `club_name_based_id`: Club's name_based_id (e.g., "new-test")
    - `moderator_user_id`: User ID of the moderator to delete
    - `reason`: Optional reason for deletion
    - `notify_moderator`: Whether to notify the moderator (default: true)
    
    **Response includes:**
    - Success confirmation
    - Updated moderator counts
    - Moderator information
    - Club details
    
    **Example Usage:**
    ```json
    POST /api/v1/moderator/delete
    {
        "club_name_based_id": "new-test",
        "moderator_user_id": "68a5c9e3fbc52005261df136",
        "reason": "Performance issues",
        "notify_moderator": true
    }
    ```
    """
    try:
        logger.info(f"🗑️ Processing moderator deletion request: club={request.club_name_based_id}, moderator={request.moderator_user_id}")
        
        captain_id = current_captain["user_id"]
        
        # Import the service
        from .moderator_management_service import moderator_management_service
        
        # Call the service
        success, response_data, error_message = await moderator_management_service.delete_moderator(
            club_name_based_id=request.club_name_based_id,
            moderator_user_id=request.moderator_user_id,
            captain_id=captain_id
        )
        
        if success:
            logger.info(f"✅ Successfully deleted moderator from club {request.club_name_based_id}")
            return ModeratorDeleteResponse(**response_data)
        else:
            logger.warning(f"❌ Failed to delete moderator: {error_message}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in delete_moderator_by_captain: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/moderator/reactivate", response_model=ModeratorReactivateResponse)
async def reactivate_moderator_by_captain(
    request: ModeratorReactivateRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Reactivate a deleted moderator in a club by captain
    
    This endpoint allows captains to reactivate previously deleted moderators
    in their clubs using the club's name_based_id. The moderator becomes active again.
    
    **Features:**
    - **Captain Only**: Only the club captain can reactivate moderators
    - **Status Update**: Sets moderator status to "active"
    - **Club Validation**: Ensures captain owns the club using name_based_id
    - **Moderator Validation**: Ensures moderator exists in the club
    
    **Request Body:**
    - `club_name_based_id`: Club's name_based_id (e.g., "new-test")
    - `moderator_user_id`: User ID of the moderator to reactivate
    - `notify_moderator`: Whether to notify the moderator (default: true)
    
    **Response includes:**
    - Success confirmation
    - Updated moderator counts
    - Moderator information
    - Club details
    
    **Example Usage:**
    ```json
    POST /api/v1/moderator/reactivate
    {
        "club_name_based_id": "new-test",
        "moderator_user_id": "68a5c9e3fbc52005261df136",
        "notify_moderator": true
    }
    ```
    """
    try:
        logger.info(f"🔄 Processing moderator reactivation request: club={request.club_name_based_id}, moderator={request.moderator_user_id}")
        
        captain_id = current_captain["user_id"]
        
        # Import the service
        from .moderator_management_service import moderator_management_service
        
        # Call the service
        success, response_data, error_message = await moderator_management_service.reactivate_moderator(
            club_name_based_id=request.club_name_based_id,
            moderator_user_id=request.moderator_user_id,
            captain_id=captain_id
        )
        
        if success:
            logger.info(f"✅ Successfully reactivated moderator in club {request.club_name_based_id}")
            return ModeratorReactivateResponse(**response_data)
        else:
            logger.warning(f"❌ Failed to reactivate moderator: {error_message}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in reactivate_moderator_by_captain: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/moderator/details", response_model=ModeratorDetailsResponse)
async def get_moderator_details(
    request: ModeratorDetailsRequest,
    current_captain: dict = Depends(get_current_captain),
):
    """
    Get detailed moderator information for a specific club by captain
    
    This endpoint allows captains to view detailed information about moderators
    in their clubs, including moderator details and all club assignments.
    
    **Features:**
    - **Captain Only**: Only the club captain can view moderator details
    - **Club Validation**: Ensures captain owns the club using name_based_id
    - **Moderator Validation**: Ensures moderator exists in the specified club
    - **Comprehensive Data**: Shows moderator details and all club assignments
    - **Club Assignments**: Lists all clubs where moderator is assigned (created by captain)
    
    **Request Body:**
    - `club_name_based_id`: Club's name_based_id (e.g., "new-club")
    - `moderator_user_id`: User ID of the moderator to view
    
    **Response includes:**
    - Moderator's basic information (name, email, avatar, bio, etc.)
    - Current club assignment details (status, type, joined date)
    - All club assignments where moderator is assigned
    - Club information (name, logo, banner) for each assignment
    - Captain's total clubs count
    
    **Example Usage:**
    ```json
    POST /api/v1/moderator/details
    {
        "club_name_based_id": "new-club",
        "moderator_user_id": "68a5c9e3fbc52005261df136"
    }
    ```
    
    **Response Example:**
    ```json
    {
        "success": true,
        "message": "Moderator details retrieved successfully for New Club",
        "moderator_details": {
            "user_id": "68a5c9e3fbc52005261df136",
            "full_name": "John Moderator",
            "email": "john@example.com",
            "avatar_url": "https://example.com/avatar.jpg",
            "bio": "Experienced moderator",
            "phone_number": "+1234567890",
            "created_at": "2024-01-01T00:00:00Z",
            "last_login": "2024-01-15T10:30:00Z"
        },
        "current_club_info": {
            "club_id": "68a5c9e3fbc52005261df136",
            "club_name": "New Club",
            "club_name_based_id": "new-club",
            "logo_url": "https://example.com/logo.jpg",
            "banner_url": "https://example.com/banner.jpg",
            "moderator_status": "active",
            "moderator_type": "paid",
            "joined_date": "2024-01-10T00:00:00Z",
            "invited_at": "2024-01-10T00:00:00Z"
        },
        "all_club_assignments": [
            {
                "club_id": "68a5c9e3fbc52005261df136",
                "club_name": "New Club",
                "club_name_based_id": "new-club",
                "logo_url": "https://example.com/logo.jpg",
                "banner_url": "https://example.com/banner.jpg",
                "moderator_status": "active",
                "moderator_type": "paid",
                "joined_date": "2024-01-10T00:00:00Z",
                "invited_at": "2024-01-10T00:00:00Z"
            }
        ],
        "total_club_assignments": 1,
        "captain_clubs_count": 5
    }
    ```
    """
    try:
        logger.info(f"🔍 Processing moderator details request: club={request.club_name_based_id}, moderator={request.moderator_user_id}")
        
        captain_id = current_captain["user_id"]
        
        # Import the service
        from .moderator_details_service import moderator_details_service
        
        # Call the service
        success, response_data, error_message = await moderator_details_service.get_moderator_details(
            club_name_based_id=request.club_name_based_id,
            moderator_user_id=request.moderator_user_id,
            captain_id=captain_id
        )
        
        if success:
            logger.info(f"✅ Successfully retrieved moderator details for {request.moderator_user_id} in club {request.club_name_based_id}")
            return ModeratorDetailsResponse(**response_data)
        else:
            logger.warning(f"❌ Failed to get moderator details: {error_message}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_moderator_details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ============================================================================
# CAPTAIN CLUB MANAGEMENT ROUTER
# ============================================================================

# Include captain club management router
from . import captain_club_management
router.include_router(captain_club_management.router)

# Include Stripe Connect routes
from .stripe_connect_routes import router as stripe_connect_router
router.include_router(stripe_connect_router)

# Include Analytics routes
from .analytics_routes import router as analytics_router
router.include_router(analytics_router)


# ============================================================================
# GLOBAL RANKINGS ROUTES
# ============================================================================

from .global_rankings_service import (
    global_rankings_service,
    RankingType,
    TimePeriod,
    PickType,
    GlobalRankingsResponse
)


@router.get("/rankings/debug")
async def debug_rankings(
    current_user: Optional[dict] = Depends(get_current_user)
):
    """
    Debug endpoint to check clubs collection and rankings setup
    """
    try:
        from .db import get_club_collection
        
        club_collection = get_club_collection()
        
        # Get basic stats
        total_clubs = await club_collection.count_documents({})
        approved_clubs = await club_collection.count_documents({"status": "approved"})
        active_clubs = await club_collection.count_documents({"is_active": True})
        
        # Get a sample club
        sample_club = await club_collection.find_one({})
        sample_data = {}
        if sample_club:
            sample_data = {
                "id": str(sample_club["_id"]),
                "name": sample_club.get("name"),
                "status": sample_club.get("status"),
                "is_active": sample_club.get("is_active"),
                "captain_id": sample_club.get("captain_id"),
                "moderators_count": len(sample_club.get("detailed_moderators", []))
            }
        
        return {
            "success": True,
            "message": "Debug info retrieved successfully",
            "data": {
                "total_clubs": total_clubs,
                "approved_clubs": approved_clubs,
                "active_clubs": active_clubs,
                "sample_club": sample_data
            }
        }
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "data": {}
        }


@router.get("/rankings/global", response_model=GlobalRankingsResponse)
async def get_global_rankings(
    ranking_type: RankingType = Query(RankingType.GLOBAL, description="Type of ranking (global or club-specific)"),
    time_period: TimePeriod = Query(TimePeriod.ALL_TIME, description="Time period for filtering picks"),
    pick_type: PickType = Query(PickType.ALL_TYPES, description="Type of picks to include"),
    top_limit: int = Query(100, ge=1, le=1000, description="Maximum number of users to rank"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    current_user: Optional[dict] = Depends(get_current_user)
):
    """
    Get global rankings for club captains and moderators across all clubs
    
    This endpoint provides a leaderboard showing the top performers globally,
    including their win rates, total picks, total wins, and other statistics.
    
    **Features:**
    - Global rankings across all clubs
    - Filter by time period (All Time, Last 7 Days, Last 30 Days, Last 3 Months)
    - Filter by pick type (All Types, Single, Parlay)
    - Pagination support
    - Rank icons (Crown for #1, Diamond for #2, Shield for #3, etc.)
    
    **Response includes:**
    - User rankings with rank, name, avatar, role
    - Club name for each user
    - Total picks, win rate, total wins/losses
    - Profit/loss information
    - Top 3 performers highlighted
    
    **Example Response:**
    ```json
    {
        "success": true,
        "message": "Global rankings retrieved successfully",
        "data": {
            "rankings": [
                {
                    "rank": 1,
                    "rank_icon": "crown",
                    "user_id": "64a1b2c3d4e5f6789abcdef0",
                    "user_name": "John Downey",
                    "user_avatar": "https://example.com/avatar1.jpg",
                    "user_role": "Captain",
                    "club_name": "The King of Kurtz",
                    "total_picks": 217,
                    "win_rate": 90.0,
                    "total_wins": 136,
                    "total_losses": 81,
                    "total_pending": 0,
                    "profit_loss": 1250.50
                }
            ],
            "total_count": 150,
            "top_performers": [...]
        },
        "filters": {
            "ranking_type": "global",
            "time_period": "all_time",
            "pick_type": "all_types",
            "top_limit": 100
        },
        "pagination": {
            "page": 1,
            "page_size": 20,
            "total_pages": 8,
            "total_count": 150,
            "has_next": true,
            "has_prev": false
        }
    }
    ```
    """
    try:
        logger.info(f"Getting global rankings with filters: {ranking_type}, {time_period}, {pick_type}")
        
        response = await global_rankings_service.get_global_rankings(
            ranking_type=ranking_type,
            time_period=time_period,
            pick_type=pick_type,
            top_limit=top_limit,
            page=page,
            page_size=page_size
        )
        
        logger.info(f"Global rankings retrieved successfully: {response.data.get('total_count', 0)} total users")
        return response
        
    except Exception as e:
        logger.error(f"Error in get_global_rankings endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving global rankings: {str(e)}"
        )


@router.get("/rankings/club/{club_id}", response_model=GlobalRankingsResponse)
async def get_club_rankings(
    club_id: str,
    time_period: TimePeriod = Query(TimePeriod.ALL_TIME, description="Time period for filtering picks"),
    pick_type: PickType = Query(PickType.ALL_TYPES, description="Type of picks to include"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    current_user: Optional[dict] = Depends(get_current_user)
):
    """
    Get rankings for a specific club
    
    This endpoint provides a leaderboard showing the top performers within a specific club,
    including captains and moderators who have submitted picks for that club.
    
    **Features:**
    - Club-specific rankings
    - Filter by time period and pick type
    - Pagination support
    - Rank icons and statistics
    
    **Response includes:**
    - User rankings within the club
    - Club information
    - Performance statistics
    - Top performers
    
    **Example Response:**
    ```json
    {
        "success": true,
        "message": "Club rankings for The King of Kurtz retrieved successfully",
        "data": {
            "rankings": [...],
            "total_count": 25,
            "top_performers": [...],
            "club_info": {
                "club_id": "64a1b2c3d4e5f6789abcdef0",
                "club_name": "The King of Kurtz"
            }
        },
        "filters": {
            "ranking_type": "club",
            "club_id": "64a1b2c3d4e5f6789abcdef0",
            "time_period": "all_time",
            "pick_type": "all_types"
        },
        "pagination": {...}
    }
    ```
    """
    try:
        logger.info(f"Getting club rankings for club {club_id} with filters: {time_period}, {pick_type}")
        
        response = await global_rankings_service.get_club_rankings(
            club_id=club_id,
            time_period=time_period,
            pick_type=pick_type,
            page=page,
            page_size=page_size
        )
        
        if not response.success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=response.message
            )
        
        logger.info(f"Club rankings retrieved successfully for club {club_id}: {response.data.get('total_count', 0)} total users")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_club_rankings endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving club rankings: {str(e)}"
        )


# ============================================================================
# TEST ENDPOINTS (FOR DEVELOPMENT/TESTING ONLY)
# ============================================================================
