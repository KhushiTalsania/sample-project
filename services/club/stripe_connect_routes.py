"""
Stripe Connect API Routes

This module contains all API endpoints for Stripe Connect functionality including:
- Captain onboarding
- Payment processing
- Bank account management
- Payout management
- Dashboard and analytics
"""

from fastapi import APIRouter, HTTPException, status, Depends
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from .stripe_connect_service import get_stripe_connect_service
from core.utils.response_utils import create_response
from .auth import get_current_user, get_current_captain
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/stripe-connect", tags=["Stripe Connect"])

# ==================== REQUEST/RESPONSE MODELS ====================

class CaptainOnboardingRequest(BaseModel):
    """Request model for captain Stripe Connect onboarding"""
    captain_id: str = Field(..., description="Captain's user ID")
    captain_email: str = Field(..., description="Captain's email address")
    captain_name: str = Field(..., description="Captain's full name")
    country: str = Field(default="US", description="Country code")

class BankAccountRequest(BaseModel):
    """Request model for adding bank account"""
    account_holder_name: str = Field(..., description="Account holder name")
    account_number: str = Field(..., description="Bank account number")
    routing_number: str = Field(..., description="Bank routing number")
    bank_name: str = Field(..., description="Bank name")
    account_holder_type: str = Field(default="individual", description="Account holder type")
    country: str = Field(default="US", description="Country code")
    currency: str = Field(default="usd", description="Currency code")

class PayoutSettingsRequest(BaseModel):
    """Request model for updating payout settings"""
    interval: str = Field(..., description="Payout interval (daily, weekly, monthly)")
    weekly_anchor: Optional[str] = Field(None, description="Day of week for weekly payouts")

class PaymentWithSplitRequest(BaseModel):
    """Request model for payment with revenue split"""
    payment_method_id: str = Field(..., description="Stripe payment method ID")
    amount: float = Field(..., gt=0, description="Payment amount")
    customer_id: str = Field(..., description="Stripe customer ID")
    club_id: str = Field(..., description="Club ID")
    captain_id: str = Field(..., description="Captain's user ID")
    club_name: str = Field(..., description="Club name")
    customer_name: str = Field(..., description="Customer name")

# ==================== CAPTAIN ONBOARDING ROUTES ====================

@router.post("/captain/onboard")
async def onboard_captain(request: CaptainOnboardingRequest):
    """
    Create Stripe Connect account for captain
    
    This endpoint creates a Stripe Connect Express account for the captain
    and returns an onboarding URL for them to complete the setup process.
    
    **Features:**
    - Creates Express account with required capabilities
    - Generates secure onboarding link
    - Stores account details in database
    - Handles duplicate account creation
    
    **Request Body:**
    - `captain_id`: Captain's user ID
    - `captain_email`: Captain's email address
    - `captain_name`: Captain's full name
    - `country`: Country code (default: US)
    
    **Response includes:**
    - Account ID
    - Onboarding URL
    - Account status
    - Success message
    """
    try:
        logger.info(f"🚀 Processing captain onboarding request for: {request.captain_email}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Create captain Connect account
        result = await stripe_service.create_captain_connect_account(
            captain_id=request.captain_id,
            captain_email=request.captain_email,
            captain_name=request.captain_name,
            country=request.country
        )
        
        if result["success"]:
            logger.info(f"✅ Captain onboarding initiated successfully for: {request.captain_email}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Captain Stripe Connect account created successfully",
                data=result
            )
        else:
            logger.warning(f"❌ Captain onboarding failed: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to create captain Connect account"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error in captain onboarding: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.get("/captain/{captain_id}/status")
async def get_captain_account_status(captain_id: str):
    """
    Get captain's Stripe Connect account status
    
    This endpoint retrieves the current status of the captain's Stripe Connect account
    including onboarding progress, capabilities, and requirements.
    
    **Features:**
    - Real-time account status from Stripe
    - Onboarding progress tracking
    - Capability status (charges, payouts)
    - Requirements checklist
    
    **Response includes:**
    - Account ID and status
    - Details submission status
    - Charges and payouts enabled status
    - Requirements checklist
    - Account creation date
    """
    try:
        logger.info(f"📋 Getting account status for captain: {captain_id}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Get account status
        result = await stripe_service.get_captain_account_status(captain_id)
        
        if result["success"]:
            logger.info(f"✅ Account status retrieved for captain: {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Account status retrieved successfully",
                data=result
            )
        else:
            logger.warning(f"❌ Failed to get account status: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get account status"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting account status: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.get("/account/{account_id}/status")
async def get_account_status_by_id(account_id: str):
    """
    Get Stripe Connect account status by account ID
    
    This endpoint retrieves the current status of a Stripe Connect account
    using the Stripe account ID directly.
    
    **Features:**
    - Real-time account status from Stripe
    - Onboarding progress tracking
    - Capability status (charges, payouts)
    - Requirements checklist
    
    **Response includes:**
    - Account ID and status
    - Details submission status
    - Charges and payouts enabled status
    - Requirements checklist
    - Business profile and capabilities
    """
    try:
        logger.info(f"📋 Getting account status by account ID: {account_id}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Import stripe to retrieve account directly
        import stripe
        
        # Retrieve account from Stripe
        account = stripe.Account.retrieve(account_id)
        
        # Determine status
        onboarding_status = "completed" if account.details_submitted else "pending"
        
        result = {
            "success": True,
            "account_id": account.id,
            "status": onboarding_status,
            "details_submitted": account.details_submitted,
            "charges_enabled": account.charges_enabled,
            "payouts_enabled": account.payouts_enabled,
            "business_type": account.business_type,
            "country": account.country,
            "email": account.email,
            "requirements": {
                "currently_due": account.requirements.currently_due if account.requirements else [],
                "eventually_due": account.requirements.eventually_due if account.requirements else [],
                "past_due": account.requirements.past_due if account.requirements else [],
                "pending_verification": account.requirements.pending_verification if account.requirements else [],
                "disabled_reason": account.requirements.disabled_reason if account.requirements else None,
            },
            "capabilities": {
                "card_payments": account.capabilities.card_payments if hasattr(account, 'capabilities') else None,
                "transfers": account.capabilities.transfers if hasattr(account, 'capabilities') else None,
            },
            "created": account.created,
        }
        
        logger.info(f"✅ Account status retrieved for account: {account_id}")
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Account status retrieved successfully",
            data=result
        )
            
    except stripe.error.InvalidRequestError as e:
        logger.error(f"❌ Invalid account ID: {e}")
        return create_response(
            status_code=status.HTTP_404_NOT_FOUND,
            status="error",
            message=f"Account not found: {str(e)}",
            data=None
        )
    except Exception as e:
        logger.error(f"💥 Unexpected error getting account status: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.get("/my-account/status")
async def get_my_account_status(current_user: dict = Depends(get_current_user)):
    """
    Get current user's Stripe Connect account status
    
    This endpoint retrieves the Stripe Connect account status for the currently
    authenticated user (must be a Captain with a Stripe Connect account).
    
    **Authentication Required:** Yes (Bearer token)
    
    **Features:**
    - Real-time account status from Stripe
    - Onboarding progress tracking
    - Capability status (charges, payouts)
    - Requirements checklist
    
    **Response includes:**
    - Account ID and status
    - Details submission status
    - Onboarding URL (if not completed)
    - Charges and payouts enabled status
    - Requirements checklist
    """
    try:
        user_id = current_user.get("user_id")
        user_role = current_user.get("role")
        
        logger.info(f"📋 Getting account status for current user: {user_id} (role: {user_role})")
        
        # Check if user is a Captain
        if user_role != "Captain":
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message="Only Captains can have Stripe Connect accounts",
                data=None
            )
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Get account status
        result = await stripe_service.get_captain_account_status(user_id)
        
        if result["success"]:
            # If onboarding not complete, add onboarding link
            if result.get("status") == "pending_onboarding":
                login_link_result = await stripe_service.create_captain_login_link(user_id)
                if login_link_result.get("success"):
                    result["onboarding_url"] = login_link_result.get("login_url")
                    result["onboarding_type"] = login_link_result.get("type")
            
            logger.info(f"✅ Account status retrieved for current user: {user_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Account status retrieved successfully",
                data=result
            )
        else:
            logger.warning(f"❌ No Stripe Connect account found for user: {user_id}")
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message=result.get("error", "No Stripe Connect account found"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting account status: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.post("/captain/{captain_id}/login-link")
async def create_captain_login_link(captain_id: str):
    """
    Create login link for captain's Stripe dashboard
    
    This endpoint generates a secure login link that allows the captain
    to access their Stripe Connect dashboard.
    
    **Features:**
    - Secure, time-limited login link
    - Direct access to Stripe dashboard
    - Automatic redirect to captain portal
    
    **Response includes:**
    - Login URL
    - Expiration timestamp
    - Success status
    """
    try:
        logger.info(f"🔗 Creating login link for captain: {captain_id}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Create login link
        result = await stripe_service.create_captain_login_link(captain_id)
        
        if result["success"]:
            logger.info(f"✅ Login link created for captain: {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Login link created successfully",
                data=result
            )
        else:
            logger.warning(f"❌ Failed to create login link: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to create login link"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error creating login link: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.post("/captain/dashboard-link")
async def get_my_dashboard_link(current_user: dict = Depends(get_current_user)):
    """
    Generate a one-time login link for the authenticated captain's Stripe dashboard.
    This endpoint uses the logged-in captain's JWT token to automatically fetch their
    Stripe Connect account and generate a fresh dashboard link.
    
    **Authentication Required:** Captain must be logged in
    
    **Features:**
    - Automatic account lookup using JWT token
    - Fresh dashboard link generation (expires in 5 minutes)
    - Handles both onboarding and completed accounts
    - Secure - captain can only access their own dashboard
    
    **Use Cases:**
    - Captain accessing their Stripe dashboard
    - View balance and transactions
    - Manage bank accounts and payouts
    - Complete onboarding if not finished
    
    **No Parameters Required:** Uses authenticated captain's token
    
    **Response includes:**
    - Dashboard link URL
    - Link type (onboarding or dashboard)
    - Account status details
    - Expiration time
    
    **Important Notes:**
    - Links expire after 5 minutes - generate fresh link each time
    - If onboarding incomplete, returns onboarding link
    - Must have Captain role
    """
    try:
        # Get captain ID from authenticated user
        captain_id = current_user.get("user_id")
        captain_role = current_user.get("role")
        
        logger.info(f"🔗 Captain requesting dashboard link: {captain_id}")
        
        # Verify user is a Captain
        if captain_role != "Captain":
            logger.warning(f"❌ Non-captain user attempted to access dashboard: {captain_id}")
            return create_response(
                status_code=status.HTTP_403_FORBIDDEN,
                status="error",
                message="Access denied. Only captains can access Stripe dashboard.",
                data=None
            )
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Get captain's user record to fetch stripe_connect_account_id
        from .db import get_user_collection
        from bson import ObjectId
        
        users_collection = get_user_collection()
        captain = await users_collection.find_one({"_id": ObjectId(captain_id)})
        
        if not captain:
            logger.error(f"❌ Captain not found in database: {captain_id}")
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Captain account not found",
                data=None
            )
        
        # Get Stripe Connect account ID
        connected_account_id = captain.get("stripe_connect_account_id")
        
        if not connected_account_id:
            logger.warning(f"❌ Captain has no Stripe Connect account: {captain_id}")
            return create_response(
                status_code=status.HTTP_404_NOT_FOUND,
                status="error",
                message="Stripe Connect account not set up. Please contact support.",
                data=None
            )
        
        logger.info(f"   Stripe Account ID: {connected_account_id}")
        
        # Generate dashboard link using the account ID
        result = await stripe_service.get_dashboard_link_by_account_id(connected_account_id)
        
        if result["success"]:
            logger.info(f"✅ Dashboard link generated for captain: {captain_id}")
            logger.info(f"   Type: {result.get('type')}")
            logger.info(f"   Onboarding complete: {result.get('details_submitted')}")
            
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message=result.get("message", "Dashboard link generated successfully"),
                data={
                    "dashboard_link": result["dashboard_link"],
                    "type": result.get("type"),
                    "expires_at": result.get("expires_at"),
                    "details_submitted": result.get("details_submitted"),
                    "charges_enabled": result.get("charges_enabled"),
                    "payouts_enabled": result.get("payouts_enabled"),
                    "account_status": {
                        "ready_to_accept_payments": result.get("charges_enabled") and result.get("payouts_enabled"),
                        "onboarding_complete": result.get("details_submitted")
                    }
                }
            )
        else:
            logger.warning(f"❌ Failed to generate dashboard link for captain {captain_id}: {result.get('error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to generate dashboard link"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error generating dashboard link: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== PAYMENT PROCESSING ROUTES ====================

@router.post("/payment/process-with-split")
async def process_payment_with_revenue_split(request: PaymentWithSplitRequest):
    """
    Process payment with automatic revenue split
    
    This endpoint processes a payment and automatically splits the revenue
    between the platform (5%) and captain (95%) using Stripe Connect.
    
    **Features:**
    - Automatic revenue splitting
    - Real-time payment processing
    - Revenue tracking and analytics
    - Error handling and validation
    
    **Request Body:**
    - `payment_method_id`: Stripe payment method ID
    - `amount`: Payment amount
    - `customer_id`: Stripe customer ID
    - `club_id`: Club ID
    - `captain_id`: Captain's user ID
    - `club_name`: Club name
    - `customer_name`: Customer name
    
    **Response includes:**
    - Payment intent ID
    - Subscription ID
    - Success status
    - Error details (if failed)
    """
    try:
        logger.info(f"💳 Processing payment with revenue split: ${request.amount}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Process payment with revenue split
        success, payment_intent_id, subscription_id, error_message = await stripe_service.process_payment_with_revenue_split(
            payment_method_id=request.payment_method_id,
            amount=request.amount,
            customer_id=request.customer_id,
            club_id=request.club_id,
            captain_id=request.captain_id,
            club_name=request.club_name,
            customer_name=request.customer_name
        )
        
        if success:
            logger.info(f"✅ Payment processed successfully: {payment_intent_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Payment processed successfully with revenue split",
                data={
                    "payment_intent_id": payment_intent_id,
                    "subscription_id": subscription_id,
                    "amount": request.amount,
                    "platform_fee": request.amount * 0.05,
                    "captain_amount": request.amount * 0.95
                }
            )
        else:
            logger.warning(f"❌ Payment processing failed: {error_message}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=error_message,
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error processing payment: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== BANK ACCOUNT MANAGEMENT ROUTES ====================

@router.post("/captain/{captain_id}/bank-accounts")
async def add_bank_account(captain_id: str, request: BankAccountRequest):
    """
    Add bank account to captain's Stripe Connect account
    
    This endpoint adds a bank account to the captain's Stripe Connect account
    for receiving payouts.
    
    **Features:**
    - Secure bank account tokenization
    - Automatic account verification
    - Support for multiple bank accounts
    - Error handling and validation
    
    **Request Body:**
    - `account_holder_name`: Account holder name
    - `account_number`: Bank account number
    - `routing_number`: Bank routing number
    - `bank_name`: Bank name
    - `account_holder_type`: Account holder type (individual/company)
    - `country`: Country code
    - `currency`: Currency code
    
    **Response includes:**
    - Bank account ID
    - Success status
    - Error details (if failed)
    """
    try:
        logger.info(f"🏦 Adding bank account for captain: {captain_id}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Add bank account
        result = await stripe_service.add_bank_account(
            captain_id=captain_id,
            bank_details=request.dict()
        )
        
        if result["success"]:
            logger.info(f"✅ Bank account added for captain: {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Bank account added successfully",
                data=result
            )
        else:
            logger.warning(f"❌ Failed to add bank account: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to add bank account"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error adding bank account: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.get("/captain/{captain_id}/bank-accounts")
async def get_bank_accounts(captain_id: str):
    """
    Get captain's bank accounts
    
    This endpoint retrieves all bank accounts associated with the captain's
    Stripe Connect account.
    
    **Features:**
    - List all bank accounts
    - Account details and status
    - Default account identification
    - Secure data handling
    
    **Response includes:**
    - List of bank accounts
    - Account details (last 4 digits, bank name, etc.)
    - Default account status
    - Account holder information
    """
    try:
        logger.info(f"📋 Getting bank accounts for captain: {captain_id}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Get bank accounts
        result = await stripe_service.get_bank_accounts(captain_id)
        
        if result["success"]:
            logger.info(f"✅ Bank accounts retrieved for captain: {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Bank accounts retrieved successfully",
                data=result
            )
        else:
            logger.warning(f"❌ Failed to get bank accounts: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get bank accounts"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting bank accounts: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== PAYOUT MANAGEMENT ROUTES ====================

@router.post("/captain/{captain_id}/payout-settings")
async def update_payout_settings(captain_id: str, request: PayoutSettingsRequest):
    """
    Update captain's payout settings
    
    This endpoint updates the captain's payout schedule and preferences
    for receiving payments.
    
    **Features:**
    - Configurable payout intervals
    - Weekly anchor day selection
    - Real-time settings update
    - Validation and error handling
    
    **Request Body:**
    - `interval`: Payout interval (daily, weekly, monthly)
    - `weekly_anchor`: Day of week for weekly payouts (optional)
    
    **Response includes:**
    - Success status
    - Updated settings confirmation
    - Error details (if failed)
    """
    try:
        logger.info(f"⚙️ Updating payout settings for captain: {captain_id}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Update payout settings
        result = await stripe_service.update_payout_settings(
            captain_id=captain_id,
            payout_schedule=request.dict()
        )
        
        if result["success"]:
            logger.info(f"✅ Payout settings updated for captain: {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Payout settings updated successfully",
                data=result
            )
        else:
            logger.warning(f"❌ Failed to update payout settings: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to update payout settings"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error updating payout settings: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.get("/captain/{captain_id}/payouts")
async def get_payout_history(captain_id: str, limit: int = 20):
    """
    Get captain's payout history
    
    This endpoint retrieves the captain's payout history including
    completed, pending, and failed payouts.
    
    **Features:**
    - Paginated payout history
    - Detailed payout information
    - Status tracking
    - Date and amount details
    
    **Query Parameters:**
    - `limit`: Number of payouts to retrieve (default: 20)
    
    **Response includes:**
    - List of payouts
    - Payout details (amount, status, date)
    - Pagination information
    - Success status
    """
    try:
        logger.info(f"📊 Getting payout history for captain: {captain_id}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Get payout history
        result = await stripe_service.get_payout_history(captain_id, limit)
        
        if result["success"]:
            logger.info(f"✅ Payout history retrieved for captain: {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Payout history retrieved successfully",
                data=result
            )
        else:
            logger.warning(f"❌ Failed to get payout history: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get payout history"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting payout history: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== DASHBOARD ROUTES ====================

@router.get("/captain/{captain_id}/dashboard")
async def get_captain_dashboard(captain_id: str):
    """
    Get captain's comprehensive dashboard data
    
    This endpoint provides a complete overview of the captain's Stripe Connect
    account including balance, transactions, payouts, and revenue analytics.
    
    **Features:**
    - Real-time balance information
    - Transaction history
    - Payout status and history
    - Revenue analytics and trends
    - Account status and capabilities
    
    **Response includes:**
    - Account information
    - Current balance (available/pending)
    - Recent transactions
    - Payout history
    - Revenue summary and trends
    - Account capabilities and status
    """
    try:
        logger.info(f"📊 Getting dashboard data for captain: {captain_id}")
        
        # Get Stripe Connect service
        stripe_service = get_stripe_connect_service()
        
        # Get dashboard data
        result = await stripe_service.get_captain_dashboard_data(captain_id)
        
        if result["success"]:
            logger.info(f"✅ Dashboard data retrieved for captain: {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Dashboard data retrieved successfully",
                data=result
            )
        else:
            logger.warning(f"❌ Failed to get dashboard data: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get dashboard data"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting dashboard data: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== WEBHOOK ROUTES ====================

@router.post("/webhooks/stripe")
async def handle_stripe_webhook(request: dict):
    """
    Handle Stripe webhooks for Connect events
    
    This endpoint processes Stripe webhooks related to Connect accounts,
    payments, and payouts.
    
    **Features:**
    - Webhook signature verification
    - Event processing and handling
    - Database updates
    - Error logging and handling
    
    **Supported Events:**
    - account.updated
    - payment_intent.succeeded
    - payout.paid
    - payout.failed
    """
    try:
        logger.info("🔔 Processing Stripe webhook")
        
        # TODO: Implement webhook signature verification
        # TODO: Process different event types
        # TODO: Update database based on events
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Webhook processed successfully",
            data=None
        )
        
    except Exception as e:
        logger.error(f"💥 Error processing webhook: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Webhook processing error: {str(e)}",
            data=None
        )


import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

app = FastAPI(title="Stripe Club Platform")
class CaptainBankDetails(BaseModel):
    captain_id: str
    account_holder_name: str
    account_number: str
    routing_number: str
    account_holder_type: str = "individual"
    country: str = "US"
    currency: str = "usd"

class ClubProduct(BaseModel):
    name: str
    price_cents: int
    currency: str = "usd"

class PaymentRequest(BaseModel):
    amount: int
    currency: str = "usd"
    captain_id: str  # to know which bank to transfer 95%

import time
@router.post("/admin/create-connected-account")
async def create_connected_account(country: str = "US", email: str = "tj@mailinator.com"):
    """
    Admin creates a connected account for club payments.
    """
    try:
        connected_account = stripe.Account.create(
    type="custom",
    country="US",
    email="tj@mailinator.com",
    business_type="individual",
    individual={
        "first_name": "Admin",
        "last_name": "Owner",
        "dob": {"day": 1, "month": 1, "year": 1990},
        "ssn_last_4": "1234",
        "address": {"line1": "123 Street", "city": "City", "state": "CA", "postal_code": "90001", "country": "US"}
    },
    capabilities={"transfers": {"requested": True}},
    tos_acceptance={"date": int(time.time()), "ip": "127.0.0.1"}
)

       # 2️⃣ Generate onboarding link
        account_link = stripe.AccountLink.create(
            account=connected_account.id,
            refresh_url="https://yourdomain.com/admin/reauth",
            return_url="https://yourdomain.com/admin/success",
            type="account_onboarding"
        )

        return {
            "connected_account_id": connected_account.id,
            "onboarding_url": account_link.url,
            "message": "Connected account created. Use link to complete onboarding."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Simulated DB
CAPTAIN_BANKS = {}  # {captain_id: bank_account_id}

@router.post("/captain/add-bank")
async def add_bank(details: CaptainBankDetails, connected_account_id: str):
    """
    Captain adds bank details to receive 95% payouts.
    """
    try:
        bank_account = stripe.Account.create_external_account(
            connected_account_id,
            external_account={
                "object": "bank_account",
                "country": details.country,
                "currency": details.currency,
                "account_holder_name": details.account_holder_name,
                "account_holder_type": details.account_holder_type,
                "account_number": details.account_number,
                "routing_number": details.routing_number,
            }
        )

        # Save in simulated DB
        CAPTAIN_BANKS[details.captain_id] = bank_account.id

        return {
            "message": "Bank added successfully",
            "bank_account_id": bank_account.id
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
