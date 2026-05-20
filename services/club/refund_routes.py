"""
Refund Policy Routes

This module defines the API routes for the refund policy system.
Handles refund requests, eligibility checks, and admin management.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional, List
from datetime import datetime

from .refund_service import RefundService
from .refund_models import (
    RefundRequest, RefundResponse, RefundEligibilityResponse, RefundDetails,
    RefundType, RefundStatus, RefundHistoryResponse, RefundStatistics,
    RefundAdminResponse, RefundProcessingUpdate, RefundBulkAction, RefundBulkResponse
)
from .auth import get_current_user
# Import create_response from routes.py
def create_response(status_code: int, status: str, message: str, data=None):
    """Create a common response body with status code"""
    return {
        "status_code": status_code,
        "status": status,
        "message": message,
        "data": data
    }

# Create router
router = APIRouter(prefix="/refunds", tags=["Refunds"])

# Initialize service
refund_service = RefundService()

@router.get("/check-eligibility", response_model=RefundEligibilityResponse)
async def check_refund_eligibility(
    club_id: str = Query(..., description="Club ID to check eligibility for"),
    refund_type: RefundType = Query(..., description="Type of refund to check"),
    current_user: dict = Depends(get_current_user)
):
    """
    Check if user is eligible for a refund
    
    Args:
        club_id: Club ID to check eligibility for
        refund_type: Type of refund (trial_refund, paid_club_refund, platform_refund)
        current_user: Current authenticated user
        
    Returns:
        RefundEligibilityResponse with eligibility details
    """
    try:
        user_id = current_user['user_id']
        
        eligibility = await refund_service.check_refund_eligibility(
            user_id=user_id,
            club_id=club_id,
            refund_type=refund_type
        )
        
        return eligibility
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking refund eligibility: {str(e)}"
        )

@router.post("/request", response_model=RefundResponse)
async def submit_refund_request(
    request: RefundRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Submit a refund request
    
    Args:
        request: Refund request details
        current_user: Current authenticated user
        
    Returns:
        RefundResponse with request details
    """
    try:
        user_id = current_user['user_id']
        
        success, response, error = await refund_service.submit_refund_request(
            user_id=user_id,
            request=request
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error submitting refund request: {str(e)}"
        )

@router.get("/history", response_model=RefundHistoryResponse)
async def get_refund_history(
    limit: int = Query(50, ge=1, le=100, description="Number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get user's refund history
    
    Args:
        limit: Number of records to return
        offset: Number of records to skip
        current_user: Current authenticated user
        
    Returns:
        RefundHistoryResponse with refund history
    """
    try:
        user_id = current_user['user_id']
        
        history = await refund_service.get_refund_history(
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        
        return history
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting refund history: {str(e)}"
        )

@router.get("/{refund_id}", response_model=RefundDetails)
async def get_refund_details(
    refund_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get details of a specific refund
    
    Args:
        refund_id: Refund ID to get details for
        current_user: Current authenticated user
        
    Returns:
        RefundDetails with refund information
    """
    try:
        user_id = current_user['user_id']
        
        # Get refund details
        refund = await refund_service.refund_collection.find_one({
            "refund_id": refund_id,
            "user_id": user_id
        })
        
        if not refund:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Refund not found"
            )
        
        # Convert to RefundDetails
        refund_details = RefundDetails(
            refund_id=refund["refund_id"],
            user_id=refund["user_id"],
            club_id=refund["club_id"],
            club_name=refund["club_name"],
            refund_type=RefundType(refund["refund_type"]),
            refund_status=RefundStatus(refund["refund_status"]),
            original_amount=refund["original_amount"],
            refund_amount=refund["refund_amount"],
            stripe_fee=refund["stripe_fee"],
            net_refund=refund["net_refund"],
            reason=refund.get("reason"),
            requested_at=refund["requested_at"],
            processed_at=refund.get("processed_at"),
            stripe_refund_id=refund.get("stripe_refund_id"),
            membership_type=refund["membership_type"],
            membership_status=refund["membership_status"],
            join_date=refund["join_date"],
            refund_deadline=refund["refund_deadline"],
            is_one_time_refund=refund.get("is_one_time_refund", True)
        )
        
        return refund_details
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting refund details: {str(e)}"
        )

# Admin routes
@router.post("/admin/approve/{refund_id}", response_model=RefundAdminResponse)
async def approve_refund(
    refund_id: str,
    admin_notes: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Approve a refund request (Admin only)
    
    Args:
        refund_id: Refund ID to approve
        admin_notes: Optional admin notes
        current_user: Current authenticated user (must be admin)
        
    Returns:
        RefundAdminResponse with approval details
    """
    try:
        # Check if user is admin (you can implement your own admin check)
        if current_user.get('role') not in ['Admin', 'Captain']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        admin_id = current_user['user_id']
        
        success, response, error = await refund_service.approve_refund(
            refund_id=refund_id,
            admin_id=admin_id,
            admin_notes=admin_notes
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error approving refund: {str(e)}"
        )

@router.post("/admin/reject/{refund_id}", response_model=RefundAdminResponse)
async def reject_refund(
    refund_id: str,
    rejection_reason: str,
    admin_notes: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Reject a refund request (Admin only)
    
    Args:
        refund_id: Refund ID to reject
        rejection_reason: Reason for rejection
        admin_notes: Optional admin notes
        current_user: Current authenticated user (must be admin)
        
    Returns:
        RefundAdminResponse with rejection details
    """
    try:
        # Check if user is admin
        if current_user.get('role') not in ['Admin', 'Captain']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        admin_id = current_user['user_id']
        
        success, response, error = await refund_service.reject_refund(
            refund_id=refund_id,
            admin_id=admin_id,
            rejection_reason=rejection_reason,
            admin_notes=admin_notes
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error rejecting refund: {str(e)}"
        )

@router.post("/admin/process/{refund_id}", response_model=RefundResponse)
async def process_refund(
    refund_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Process an approved refund (Admin only)
    
    Args:
        refund_id: Refund ID to process
        current_user: Current authenticated user (must be admin)
        
    Returns:
        RefundResponse with processing details
    """
    try:
        # Check if user is admin
        if current_user.get('role') not in ['Admin', 'Captain']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        admin_id = current_user['user_id']
        
        success, response, error = await refund_service.process_refund(
            refund_id=refund_id,
            admin_id=admin_id
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing refund: {str(e)}"
        )

@router.get("/admin/statistics", response_model=RefundStatistics)
async def get_refund_statistics(
    current_user: dict = Depends(get_current_user)
):
    """
    Get refund statistics (Admin only)
    
    Args:
        current_user: Current authenticated user (must be admin)
        
    Returns:
        RefundStatistics with refund metrics
    """
    try:
        # Check if user is admin
        if current_user.get('role') not in ['Admin', 'Captain']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        statistics = await refund_service.get_refund_statistics()
        return statistics
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting refund statistics: {str(e)}"
        )

@router.get("/admin/pending", response_model=List[RefundDetails])
async def get_pending_refunds(
    limit: int = Query(50, ge=1, le=100, description="Number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get pending refunds (Admin only)
    
    Args:
        limit: Number of records to return
        offset: Number of records to skip
        current_user: Current authenticated user (must be admin)
        
    Returns:
        List of RefundDetails for pending refunds
    """
    try:
        # Check if user is admin
        if current_user.get('role') not in ['Admin', 'Captain']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        # Get pending refunds
        refunds_cursor = refund_service.refund_collection.find(
            {"refund_status": RefundStatus.PENDING.value}
        ).sort("requested_at", -1).skip(offset).limit(limit)
        
        refunds = await refunds_cursor.to_list(length=limit)
        
        # Convert to RefundDetails objects
        refund_details = []
        for refund in refunds:
            refund_detail = RefundDetails(
                refund_id=refund["refund_id"],
                user_id=refund["user_id"],
                club_id=refund["club_id"],
                club_name=refund["club_name"],
                refund_type=RefundType(refund["refund_type"]),
                refund_status=RefundStatus(refund["refund_status"]),
                original_amount=refund["original_amount"],
                refund_amount=refund["refund_amount"],
                stripe_fee=refund["stripe_fee"],
                net_refund=refund["net_refund"],
                reason=refund.get("reason"),
                requested_at=refund["requested_at"],
                processed_at=refund.get("processed_at"),
                stripe_refund_id=refund.get("stripe_refund_id"),
                membership_type=refund["membership_type"],
                membership_status=refund["membership_status"],
                join_date=refund["join_date"],
                refund_deadline=refund["refund_deadline"],
                is_one_time_refund=refund.get("is_one_time_refund", True)
            )
            refund_details.append(refund_detail)
        
        return refund_details
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting pending refunds: {str(e)}"
        )

@router.post("/admin/bulk-action", response_model=RefundBulkResponse)
async def bulk_refund_action(
    action: RefundBulkAction,
    current_user: dict = Depends(get_current_user)
):
    """
    Perform bulk action on refunds (Admin only)
    
    Args:
        action: Bulk action details
        current_user: Current authenticated user (must be admin)
        
    Returns:
        RefundBulkResponse with bulk action results
    """
    try:
        # Check if user is admin
        if current_user.get('role') not in ['Admin', 'Captain']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        admin_id = current_user['user_id']
        results = []
        errors = []
        processed_count = 0
        failed_count = 0
        
        for refund_id in action.refund_ids:
            try:
                if action.action == "approve":
                    success, response, error = await refund_service.approve_refund(
                        refund_id=refund_id,
                        admin_id=admin_id,
                        admin_notes=action.admin_notes
                    )
                elif action.action == "reject":
                    success, response, error = await refund_service.reject_refund(
                        refund_id=refund_id,
                        admin_id=admin_id,
                        rejection_reason=action.reason or "Bulk rejection",
                        admin_notes=action.admin_notes
                    )
                elif action.action == "process":
                    success, response, error = await refund_service.process_refund(
                        refund_id=refund_id,
                        admin_id=admin_id
                    )
                else:
                    success, response, error = False, None, "Invalid action"
                
                if success:
                    processed_count += 1
                    results.append({
                        "refund_id": refund_id,
                        "action": action.action,
                        "status": "success",
                        "message": response.message if response else "Action completed"
                    })
                else:
                    failed_count += 1
                    errors.append(f"Refund {refund_id}: {error}")
                    results.append({
                        "refund_id": refund_id,
                        "action": action.action,
                        "status": "failed",
                        "message": error
                    })
                    
            except Exception as e:
                failed_count += 1
                error_msg = f"Refund {refund_id}: {str(e)}"
                errors.append(error_msg)
                results.append({
                    "refund_id": refund_id,
                    "action": action.action,
                    "status": "failed",
                    "message": str(e)
                })
        
        return RefundBulkResponse(
            success=processed_count > 0,
            processed_count=processed_count,
            failed_count=failed_count,
            results=results,
            errors=errors,
            message=f"Bulk action completed: {processed_count} successful, {failed_count} failed"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error performing bulk action: {str(e)}"
        )

@router.get("/policy/info")
async def get_refund_policy_info():
    """
    Get refund policy information for users
    
    Returns:
        Refund policy information
    """
    try:
        policy_info = {
            "trial_refund_policy": "Trial members can request a full refund of platform fees within 7 days of joining. Stripe processing fees will be deducted.",
            "paid_refund_policy": "Club joining fees are non-refundable. Only platform membership fees can be refunded within 7 days of joining.",
            "platform_refund_policy": "Platform membership fees can be refunded within 7 days of joining. Stripe processing fees will be deducted.",
            "refund_deadline_days": 7,
            "stripe_fee_info": "Stripe processing fee: 2.9% + $0.30 per transaction",
            "processing_time_info": "Refunds are typically processed within 5 business days after approval",
            "contact_info": "For refund questions, contact support at support@example.com",
            "terms_url": "https://example.com/refund-terms",
            "faq_url": "https://example.com/refund-faq"
        }
        
        return create_response(
            status_code=200,
            status="success",
            message="Refund policy information retrieved successfully",
            data=policy_info
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting refund policy info: {str(e)}"
        )
