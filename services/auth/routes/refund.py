"""
Refund API Routes

This module handles refund requests for trial memberships with complex business logic:
1. Only Members (role="Member") are eligible for refunds
2. Refunds are only available for portal/platform fees ($19.95)
3. Refund eligibility depends on when user first joined a club as trial
4. Processing fees are deducted from refund amount
5. Refunds affect membership status and club memberships differently based on join type
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime
import logging

from ..models import RefundRequest, RefundResponse, RefundStatusResponse
from core.utils.email_service import send_email
from ..utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize refund service when needed to avoid circular imports
def get_refund_service():
    from ..refund_service import RefundService
    return RefundService()

@router.post("/refund/request", response_model=RefundResponse)
async def request_refund(
    request: RefundRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Request a refund for trial membership
    
    **Business Rules:**
    - Only Members (role="Member") are eligible for refunds
    - Captains and Moderators cannot request refunds
    - Refunds are only available for portal/platform fees ($19.95)
    - Refund must be requested within 7 days of joining first trial club
    - Processing fees (Stripe fees) are deducted from refund amount
    - Only trial clubs become inactive after refund, paid clubs remain active
    
    **Scenarios:**
    1. **Pure Trial User**: Joined only trial clubs → Full portal fee refund, all clubs inactive
    2. **Mixed User**: Joined some trial + some paid clubs → Portal fee refund only, trial clubs inactive, paid clubs remain active
    3. **Paid User**: Never joined trial clubs → Not eligible for portal fee refund
    
    **Processing:**
    - Stripe refund processed for original payment
    - User membership status becomes "inactive"
    - Trial club memberships become inactive
    - Paid club memberships remain active
    - User marked as refunded to prevent duplicate requests
    
    **Response includes:**
    - Refund amount before processing fees
    - Processing fee deducted
    - Net refund amount paid to customer
    - Stripe refund ID for tracking
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role")
        
        logger.info(f"Refund request from user {user_id} with role {user_role}")
        
        # Validate user role
        if user_role != "Member":
            raise HTTPException(
                status_code=403,
                detail="Only Members are eligible for refunds. Captains and Moderators cannot request refunds."
            )
        
        # Process refund request
        refund_service = get_refund_service()
        success, refund_data, error_message = await refund_service.process_refund_request(
            user_id=user_id,
            reason=request.reason
        )
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail=error_message or "Refund request failed"
            )
        
        # Send confirmation email to the user (best-effort)
        try:
            user_email = current_user.get("email", "")
            if user_email:
                subject = "Your refund has been processed"
                processed_ts = refund_data.get('processed_at')
                processed_str = processed_ts.isoformat() if processed_ts else datetime.utcnow().isoformat()
                refund_amount = refund_data.get('refund_amount', 0)
                processing_fee = refund_data.get('processing_fee', 0)
                net_refund = refund_data.get('net_refund', 0)
                refund_id = refund_data.get('stripe_refund_id') or "N/A"

                body = (
                    f"Hello,\n\n"
                    f"We have processed your refund successfully.\n\n"
                    f"Refund summary:\n"
                    f"- Refund ID: {refund_id}\n"
                    f"- Gross refund amount: ${refund_amount:.2f}\n"
                    f"- Processing fee deducted: ${processing_fee:.2f}\n"
                    f"- Net amount credited: ${net_refund:.2f}\n"
                    f"- Processed at: {processed_str}\n\n"
                    f"Please note: The net refund amount has been credited back to your original payment method. "
                    f"Depending on your bank, it may take 5-10 business days to appear on your statement.\n\n"
                    f"If you have any questions, just reply to this email.\n\n"
                    f"Thank you."
                )
                await send_email(user_email, subject, body, is_html=False)
                logger.info(f"Refund confirmation email sent to {user_email}")
            else:
                logger.warning("User email not found; skipping refund confirmation email")
        except Exception as email_err:
            logger.warning(f"Failed to send refund confirmation email: {email_err}")

        # Format response
        response = RefundResponse(
            success=True,
            message=f"Refund processed successfully. ${refund_data.get('net_refund', 0):.2f} has been refunded to your account.",
            refund_amount=refund_data.get('refund_amount'),
            processing_fee=refund_data.get('processing_fee'),
            net_refund=refund_data.get('net_refund'),
            stripe_refund_id=refund_data.get('stripe_refund_id'),
            refund_processed_at=refund_data.get('processed_at').isoformat() if refund_data.get('processed_at') else None,
            refund_details=refund_data.get('refund_details'),
            reactivation_message="To reactivate your membership, you will need to pay $19.95 portal fees again.",
            is_reactive=refund_data.get('is_reactive', True),  # True after successful refund
            refund_count=refund_data.get('refund_count', 1)  # Number of times user has been refunded
        )
        
        logger.info(f"Refund successfully processed for user {user_id}: ${refund_data.get('net_refund', 0):.2f}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing refund request: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.get("/refund/status", response_model=RefundStatusResponse)
async def get_refund_status(
    current_user: dict = Depends(get_current_user)
):
    """
    Get refund status for current user
    
    **Returns:**
    - Current refund status (refunded/not refunded)
    - Membership status and type
    - Refund eligibility and deadline
    - Whether user can request refund
    - Refund details if already processed
    
    **Use Cases:**
    - Check if user is eligible for refund
    - Display refund deadline to user
    - Show refund history if already processed
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role")
        
        logger.info(f"Refund status check for user {user_id} with role {user_role}")
        
        # Get refund status
        refund_service = get_refund_service()
        success, status_data, error_message = await refund_service.get_refund_status(user_id)
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail=error_message or "Failed to get refund status"
            )
        
        # Format response
        response = RefundStatusResponse(
            success=True,
            message="Refund status retrieved successfully",
            user_id=user_id,
            is_refunded=status_data.get('is_refunded', False),
            membership_status=status_data.get('membership_status', 'unknown'),
            membership_type=status_data.get('membership_type', 'unknown'),
            refund_eligible=status_data.get('refund_eligible', False),
            refund_deadline=status_data.get('refund_deadline').isoformat() if status_data.get('refund_deadline') else None,
            can_request_refund=status_data.get('can_request_refund', False),
            first_trial_join_date=status_data.get('first_trial_join_date').isoformat() if status_data.get('first_trial_join_date') else None,
            refund_type=status_data.get('refund_type'),
            refund_amount=status_data.get('refund_amount'),
            refund_processed_at=status_data.get('refund_processed_at').isoformat() if status_data.get('refund_processed_at') else None,
            refund_reason=status_data.get('refund_reason'),
            stripe_refund_id=status_data.get('stripe_refund_id'),
            refund_details=status_data.get('refund_details'),
            is_reactive=status_data.get('is_reactive', True)  # Default to true
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting refund status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.get("/refund/eligibility")
async def check_refund_eligibility(
    current_user: dict = Depends(get_current_user)
):
    """
    Check if user is eligible for refund without processing
    
    **Returns:**
    - Eligibility status
    - Reason if not eligible
    - Refund deadline if eligible
    - Detailed eligibility breakdown
    
    **Use Cases:**
    - Show/hide refund button in UI
    - Display eligibility information
    - Pre-validate before showing refund form
    """
    try:
        user_id = current_user["user_id"]
        user_role = current_user.get("role")
        
        logger.info(f"Refund eligibility check for user {user_id} with role {user_role}")
        
        # Get refund status for eligibility check
        refund_service = get_refund_service()
        success, status_data, error_message = await refund_service.get_refund_status(user_id)
        
        if not success:
            return {
                "success": False,
                "eligible": False,
                "reason": error_message or "Unable to check eligibility",
                "details": {}
            }
        
        # Build eligibility response
        eligibility_details = {
            "user_role": user_role,
            "membership_status": status_data.get('membership_status'),
            "membership_type": status_data.get('membership_type'),
            "is_temporary_deactivate": status_data.get('is_temporary_deactivate'),
            "is_permanent_deactivate": status_data.get('is_permanent_deactivate'),
            "is_refunded": status_data.get('is_refunded', False),
            "refund_eligible": status_data.get('refund_eligible', False),
            "refund_count": status_data.get('refund_count', 0),
            "is_reactive": status_data.get('is_reactive', True),
            "can_request_refund": status_data.get('can_request_refund', False),
            "refund_deadline": status_data.get('refund_deadline').isoformat() if status_data.get('refund_deadline') else None,
            "first_trial_join_date": status_data.get('first_trial_join_date').isoformat() if status_data.get('first_trial_join_date') else None
        }
        
        # Determine eligibility reason
        if user_role != "Member":
            reason = "Only Members are eligible for refunds"
        elif status_data.get('is_refunded', False):
            reason = "User has already been refunded"
        elif status_data.get('membership_status') != "active":
            reason = "User does not have active membership"
        elif status_data.get('membership_type') != "trial":
            reason = "Only trial memberships are eligible for refund"
        elif not status_data.get('can_request_refund', False):
            reason = "Refund period has expired (7 days from first trial club join)"
        else:
            reason = "User is eligible for refund"
        
        return {
            "success": True,
            "eligible": status_data.get('can_request_refund', False),
            "reason": reason,
            "details": eligibility_details
        }
        
    except Exception as e:
        logger.error(f"Error checking refund eligibility: {str(e)}")
        return {
            "success": False,
            "eligible": False,
            "reason": f"Error checking eligibility: {str(e)}",
            "details": {}
        }
