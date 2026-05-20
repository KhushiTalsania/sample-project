"""
Member Deletion API Routes

This module provides API endpoints for captains to delete members from clubs.
It supports both temporary and permanent deletion with Stripe integration.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional

from services.auth.member_deletion_service import get_member_deletion_service
from services.auth.models import (
    MemberDeletionRequest, MemberDeletionResponse,
    MemberReactivationRequest, MemberReactivationResponse
)
from core.auth.auth_middleware import get_current_user
from core.utils.response_utils import create_response

logger = logging.getLogger(__name__)

# Create router for member deletion endpoints
member_deletion_router = APIRouter(prefix="/member-deletion", tags=["Member Deletion"])

router = APIRouter()

@router.post("/delete-member", response_model=MemberDeletionResponse)
async def delete_member_from_club(
    request: MemberDeletionRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a member from a club with temporary or permanent deletion
    
    **Features:**
    - **Authentication Required**: Only authenticated users can access
    - **Role Validation**: Only users with role "Captain" can delete members
    - **Authorization**: Captains can only delete members from their own clubs
    - **Two Deletion Types**: Temporary (inactive) or Permanent (deleted)
    - **Stripe Integration**: Manages subscriptions and billing automatically
    - **Email Notifications**: Sends notifications to affected members
    
    **Request Body:**
    - **club_id**: The club ID to delete member from
    - **member_id**: The member ID to delete
    - **deletion_type**: "temporary" or "permanent"
    - **reason**: Optional reason for deletion
    
    **Temporary Deletion:**
    - Sets membership_status to "inactive"
    - Calculates usage statistics (total_days, used_days, remaining_days)
    - Pauses Stripe subscription billing
    - Member can be reactivated later
    - Unused days are preserved for reactivation
    
    **Permanent Deletion:**
    - Sets membership_status to "deleted"
    - Cancels Stripe subscription
    - Processes refund for unused period
    - Member cannot be reactivated
    - Complete removal from club
    
    **Stripe Management:**
    - For paid memberships, handles subscription lifecycle
    - Pauses billing for temporary deletion
    - Cancels subscription for permanent deletion
    - Processes refunds when applicable
    
    **Example Usage:**
    ```
    POST /auth/delete-member
    {
        "club_id": "68cd2bf3ab5f4194a06c8b12",
        "member_id": "68c7daaf1a1911ad2e7505b2",
        "deletion_type": "temporary",
        "reason": "Violation of club rules"
    }
    ```
    """
    try:
        captain_id = current_user.get("user_id")
        captain_role = current_user.get("role")
        
        logger.info(f"Member deletion request from captain {captain_id} for member {request.member_id}")
        
        # Validate captain role
        if captain_role != "Captain":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Captains can delete members from clubs. Members and Moderators cannot access this feature."
            )
        
        # Get member deletion service
        member_deletion_service = get_member_deletion_service()
        success, deletion_data, error_message = await member_deletion_service.delete_member_from_club(
            captain_id=captain_id,
            club_id=request.club_id,
            member_id=request.member_id,
            deletion_type=request.deletion_type,
            reason=request.reason
        )
        
        if not success:
            if "not found" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=error_message
                )
            elif "not authorized" in error_message.lower() or "owner" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=error_message
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_message or "Failed to delete member from club"
                )
        
        logger.info(f"Successfully deleted member {request.member_id} from club {request.club_id}")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=deletion_data.get("message", "Member deleted successfully"),
            data=deletion_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in delete_member_from_club: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )

@router.post("/reactivate-member", response_model=MemberReactivationResponse)
async def reactivate_member(
    request: MemberReactivationRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Reactivate a temporarily deleted member
    
    **Features:**
    - **Authentication Required**: Only authenticated users can access
    - **Role Validation**: Only users with role "Captain" can reactivate members
    - **Authorization**: Captains can only reactivate members from their own clubs
    - **Unused Days**: Applies any unused days from the previous subscription
    - **Stripe Integration**: Resumes billing with adjusted dates
    
    **Request Body:**
    - **club_id**: The club ID to reactivate member in
    - **member_id**: The member ID to reactivate
    
    **Business Logic:**
    - Only works for temporarily deleted members (membership_status: "inactive")
    - Calculates unused days from previous subscription
    - Sets new end date based on unused days
    - Resumes Stripe subscription billing
    - Sends reactivation confirmation email
    
    **Example Usage:**
    ```
    POST /auth/reactivate-member
    {
        "club_id": "68cd2bf3ab5f4194a06c8b12",
        "member_id": "68c7daaf1a1911ad2e7505b2"
    }
    ```
    """
    try:
        captain_id = current_user.get("user_id")
        captain_role = current_user.get("role")
        
        logger.info(f"Member reactivation request from captain {captain_id} for member {request.member_id}")
        
        # Validate captain role
        if captain_role != "Captain":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Captains can reactivate members. Members and Moderators cannot access this feature."
            )
        
        # Get member deletion service
        member_deletion_service = get_member_deletion_service()
        success, reactivation_data, error_message = await member_deletion_service.reactivate_member(
            captain_id=captain_id,
            club_id=request.club_id,
            member_id=request.member_id
        )
        
        if not success:
            if "not found" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=error_message
                )
            elif "not authorized" in error_message.lower() or "owner" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=error_message
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_message or "Failed to reactivate member"
                )
        
        logger.info(f"Successfully reactivated member {request.member_id} in club {request.club_id}")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=reactivation_data.get("message", "Member reactivated successfully"),
            data=reactivation_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in reactivate_member: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )

@member_deletion_router.post("/admin-unpause-subscription", response_model=MemberReactivationResponse)
async def admin_unpause_subscription(
    request: MemberReactivationRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Admin endpoint to unpause a permanently paused subscription with free extension
    
    This endpoint allows admins to manually unpause subscriptions that were permanently paused
    during temporary member deletion. It applies unused days as a free extension.
    
    **Example Request:**
    ```json
    {
        "member_id": "68cbd1588ba431ee8500a3bb",
        "club_id": "68bfe903eee2fa74d277795e"
    }
    ```
    
    **Example Response:**
    ```json
    {
        "status": "success",
        "message": "Subscription unpaused successfully with 165 days free extension",
        "data": {
            "success": true,
            "message": "Subscription unpaused with free extension",
            "member_id": "68cbd1588ba431ee8500a3bb",
            "club_id": "68bfe903eee2fa74d277795e",
            "subscription_id": "sub_1234567890",
            "free_extension_days": 165,
            "free_extension_until": "2031-03-07T00:00:00Z",
            "next_billing_date": "2031-03-07T00:00:00Z",
            "unpause_date": "2030-09-24T10:30:00Z"
        }
    }
    ```
    """
    try:
        logger.info(f"Admin unpause request for member {request.member_id} in club {request.club_id}")
        
        # Get member deletion service
        service = get_member_deletion_service()
        
        # Admin unpause with free extension
        unpause_success, unpause_data, error_message = await service.admin_unpause_subscription(
            member_id=request.member_id,
            club_id=request.club_id,
            admin_user=current_user
        )
        
        if not unpause_success:
            if error_message and "not found" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=error_message
                )
            elif error_message and "unauthorized" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=error_message
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_message or "Failed to unpause subscription"
                )
        
        logger.info(f"Successfully unpaused subscription for member {request.member_id} in club {request.club_id}")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=unpause_data.get("message", "Subscription unpaused successfully"),
            data=unpause_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in admin_unpause_subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )
