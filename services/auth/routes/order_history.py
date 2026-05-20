"""
Order History API Routes

This module handles order history endpoints for members,
including platform fees and club memberships.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from core.auth.auth_middleware import get_current_user, get_current_admin
from core.utils.response_utils import create_response
from ..order_history_service import get_order_history_service
from bson import ObjectId

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/order-history")
async def get_order_history(
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page (max 100)"),
    order_type: str = Query(None, description="Filter by order type: 'platform_fee', 'club_membership', or 'club_payment'"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get order history for the authenticated member with pagination
    
    **Features:**
    - **Authentication Required**: Only authenticated users can access
    - **Role Validation**: Only users with role "Member", "Captain", or "Admin" can view order history
    - **Platform Fees**: Retrieves subscription payments from payments table
    - **Club Memberships**: Retrieves paid club memberships from club_memberships table (Members only)
    - **Club Payments**: Retrieves club payments from club_payments table (Captains only)
    - **Status Information**: Includes status and membership_status from users table
    - **Sorted Results**: Orders are sorted by payment date (newest first)
    - **Pagination Support**: Supports page and page_size parameters
    - **Summary Statistics**: Provides totals and counts for different order types
    
    **Data Sources:**
    1. **Payments Table**: Platform fees (subscription payments)
       - Status and membership_status from users table
    2. **Club Memberships Table**: Paid club memberships
       - Status and membership_status from clubs_joined array in users table
    
    **Parameters:**
    - **page**: Page number (default: 1, minimum: 1)
    - **page_size**: Number of items per page (default: 10, minimum: 1, maximum: 100)
    
    **Response includes:**
    - Order details (payment date, membership type, amount, status)
    - Pagination information (current page, total pages, has next/previous)
    - Summary statistics (total amounts, counts)
    - Club information for club membership orders
    - Payment and subscription IDs for tracking
    
    **Business Logic:**
    - Members, Captains, and Admins can access order history
    - Moderators cannot view order history
    - Platform fees are identified by payment_type="subscription"
    - Club memberships include club details and pricing plans
    - All amounts are converted to dollars (assuming cents in database)
    """
    try:
        user_id = current_user.get("user_id")
        user_role = current_user.get("role")
        
        logger.info(f"Order history request from user {user_id} with role {user_role}")
        
        # Validate user role
        if user_role not in ["Member", "Captain", "Admin"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Members, Captains, and Admins can view order history. Moderators cannot access this feature."
            )
        
        # Get order history
        order_history_service = get_order_history_service()
        success, order_data, error_message = await order_history_service.get_order_history(user_id, page, page_size, order_type)
        print(order_data,"order_data")
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message or "Failed to retrieve order history"
            )
        
        pagination_info = order_data.get('pagination', {})
        logger.info(f"Successfully retrieved order history for user {user_id}: {pagination_info.get('total_orders', 0)} total orders, page {page}/{pagination_info.get('total_pages', 1)}")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Order history retrieved successfully. Page {page} of {pagination_info.get('total_pages', 1)} with {pagination_info.get('total_orders', 0)} total orders.",
            data=order_data
        )
        
    except HTTPException as e:
        logger.warning(f"HTTP error retrieving order history: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error retrieving order history: {str(e)}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.get("/admin/order-history/{user_id}")
async def get_user_order_history_admin(
    user_id: str,
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page (max 100)"),
    order_type: str = Query(None, description="Filter by order type: 'platform_fee', 'club_membership', or 'club_payment'"),
    current_admin: dict = Depends(get_current_admin)
):
    """
    Admin-only: Get order history for a specific user by user_id.

    - Requires valid Admin token
    - Validates user_id format
    - Reuses the same service logic as member endpoint
    """
    try:
        # Validate ObjectId format
        try:
            ObjectId(user_id)
        except Exception:
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message="Invalid user ID format",
                data=None
            )

        logger.info(f"Admin {current_admin.get('email','')} requested order history for user {user_id}")

        order_history_service = get_order_history_service()
        success, order_data, error_message = await order_history_service.get_order_history(user_id, page, page_size, order_type)

        if not success:
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message or "Failed to retrieve order history",
                data=None
            )

        pagination_info = order_data.get('pagination', {})
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Order history retrieved successfully. Page {page} of {pagination_info.get('total_pages', 1)} with {pagination_info.get('total_orders', 0)} total orders.",
            data=order_data
        )

    except HTTPException as e:
        logger.warning(f"HTTP error retrieving order history for user (admin): {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error retrieving order history for user (admin): {str(e)}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )
