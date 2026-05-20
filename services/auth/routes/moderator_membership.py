from fastapi import APIRouter, HTTPException
from datetime import datetime
import stripe
import os
from core.utils.price_config import PriceConfig, CurrencyConfig
from pydantic import BaseModel, Field, field_validator
from typing import Optional

router = APIRouter()


# Request and Response Models
class ModeratorUpgradeRequest(BaseModel):
    """Request model for moderator role upgrade"""

    email: str = Field(
        ..., description="Moderator's email address", example="moderator@example.com"
    )
    payment_method_id: str = Field(
        ...,
        description="Stripe payment method ID from frontend",
        example="pm_1234567890",
    )
    target_role: str = Field(
        ...,
        description="Target role to upgrade to - 'Member' or 'Captain'",
        example="Member",
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if not v or "@" not in v:
            raise ValueError("Invalid email format")
        return v.lower().strip()

    @field_validator("target_role")
    @classmethod
    def validate_target_role(cls, v):
        if v not in ["Member", "Captain"]:
            raise ValueError("Target role must be 'Member' or 'Captain'")
        return v


class ModeratorUpgradeResponse(BaseModel):
    """Response model for moderator role upgrade"""

    success: bool = Field(
        description="Whether the upgrade was successful", example=True
    )
    message: str = Field(
        description="Success or error message",
        example="Successfully upgraded from Moderator to Member",
    )
    data: Optional[dict] = Field(
        description="Upgrade details and user information",
        example={
            "user_id": "64f7b1234567890abcdef123",
            "email": "moderator@example.com",
            "previous_role": "Moderator",
            "new_role": "Member",
            "membership_type": "trial",
            "club_count": 1,
            "amount_paid": 9.95,
            "currency": "usd",
            "payment_intent_id": "pi_1234567890",
            "stripe_customer_id": "cus_1234567890",
            "upgrade_date": "2024-01-15T10:30:00Z",
        },
    )
    
    # Stripe Connect fields for Captain upgrades
    stripe_connect_account_id: Optional[str] = Field(
        None, description="Stripe Connect account ID (only for Captain upgrades)"
    )
    stripe_onboarding_url: Optional[str] = Field(
        None, description="Stripe onboarding URL (only for Captain upgrades)"
    )
    stripe_connect_status: Optional[str] = Field(
        None, description="Stripe Connect account status (only for Captain upgrades)"
    )


# Initialize Stripe
stripe.api_key = os.getenv(
    "STRIPE_SECRET_KEY",
    "",
)


@router.post(
    "/api/membership/moderator-upgrade",
    response_model=ModeratorUpgradeResponse,
    tags=["Moderator Membership"],
    summary="Upgrade Moderator Role",
    description="Allows moderators to upgrade their role to Member or Captain with payment processing",
)
async def moderator_role_upgrade(request: ModeratorUpgradeRequest):
    """
    Moderator Role Upgrade API

    This endpoint allows moderators to upgrade their role to either "Member" or "Captain" by paying the respective amount.
    The API validates the user's moderator status, processes payment through Stripe, and updates the user's role and membership details.

    **Features:**
    - **Role Validation**: Ensures user is currently a moderator
    - **Payment Processing**: Handles Stripe payment using payment method ID
    - **Role Upgrade**: Updates user role to Member or Captain
    - **Membership Management**: Sets appropriate membership type and club count
    - **Payment Tracking**: Stores payment records for audit purposes

    **Request Body:**
    - `email`: Moderator's email address (required)
    - `payment_method_id`: Stripe payment method ID from frontend (required)
    - `target_role`: Target role to upgrade to - "Member" or "Captain" (required)

    **Pricing:**
    - **Member Role**: $9.95 (membership_type: "trial", club_count: 1)
    - **Captain Role**: $99.00 (membership_type: "paid", club_count: 1)

    **Payment Process:**
    1. Validates user exists and is a moderator
    2. Creates or retrieves Stripe customer
    3. Attaches payment method to customer
    4. Creates and processes PaymentIntent
    5. Updates user role and membership details
    6. Stores payment record

    **Response includes:**
    - Success status and message
    - User details (ID, email, previous/new role)
    - Membership information (type, club count)
    - Payment details (amount, currency, payment intent ID)
    - Upgrade timestamp

    **Use Cases:**
    - Moderators upgrading to Member role for basic platform access
    - Moderators upgrading to Captain role for club creation privileges
    - Payment processing for role upgrades

    **Example Usage:**
    ```
    POST /api/membership/moderator-upgrade
    {
        "email": "moderator@example.com",
        "payment_method_id": "pm_1234567890",
        "target_role": "Member"
    }
    ```

    **Error Responses:**
    - 400: Missing required fields or invalid target role
    - 404: User not found
    - 400: User is not a moderator
    - 500: Payment processing failed or internal server error

    **Note:** This API requires the user to be currently assigned as a moderator role.
    """
    try:
        # Extract request data
        email = request.email
        payment_method_id = request.payment_method_id
        target_role = request.target_role

        # Validate target role
        if target_role not in ["Member", "Captain"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid target role. Must be 'Member' or 'Captain'",
            )

        # Get user collection
        from ..db import get_user_collection

        users_collection = get_user_collection()

        # Find user by email and validate they are a moderator
        user = await users_collection.find_one({"email": email.lower()})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Check if user is a moderator (case-insensitive)
        if user.get("role", "").lower() != "moderator":
            raise HTTPException(
                status_code=400,
                detail="User must be a moderator to use this upgrade service",
            )

        # Get price based on target role
        if target_role == "Member":
            amount = PriceConfig.MEMBER_ROLE_AMOUNT
        elif target_role == "Captain":
            amount = PriceConfig.CAPTAIN_ROLE_AMOUNT

        print(f"✅ Moderator upgrade request: {email} -> {target_role} (${amount})")

        # Get or create Stripe customer first
        stripe_customer_id = user.get("stripe_customer_id")
        if not stripe_customer_id:
            try:
                customer = stripe.Customer.create(
                    email=email,
                    name=user.get("full_name", ""),
                    metadata={"user_id": str(user["_id"]), "type": "moderator_upgrade"},
                )
                stripe_customer_id = customer.id
                print(f"✅ Created new Stripe customer: {stripe_customer_id}")
            except Exception as e:
                print(f"❌ Failed to create Stripe customer: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create Stripe customer: {str(e)}",
                )
        else:
            print(f"✅ Using existing Stripe customer: {stripe_customer_id}")

        # Attach payment method to customer
        try:
            stripe.PaymentMethod.attach(
                payment_method_id,
                customer=stripe_customer_id,
            )
            print(f"✅ Payment method attached: {payment_method_id}")
        except Exception as e:
            print(f"❌ Failed to attach payment method: {str(e)}")
            raise HTTPException(
                status_code=400, detail=f"Invalid payment method: {str(e)}"
            )

        # Process payment using PaymentIntent
        try:
            # Create payment intent for the upgrade
            payment_intent = stripe.PaymentIntent.create(
                amount=int(amount * 100),  # Convert to cents
                currency=CurrencyConfig.DEFAULT_CURRENCY,
                customer=stripe_customer_id,
                payment_method=payment_method_id,
                confirm=True,
                automatic_payment_methods={
                    "enabled": True,
                    "allow_redirects": "never",
                },
                metadata={
                    "user_id": str(user["_id"]),
                    "type": "moderator_upgrade",
                    "target_role": target_role,
                    "amount": str(amount),
                },
            )

            print(f"✅ Payment intent created: {payment_intent.id}")
            print(f"✅ Payment intent amount: ${payment_intent.amount/100}")
            print(f"✅ Payment intent status: {payment_intent.status}")

            # Check if payment requires additional action
            if payment_intent.status == "requires_action":
                raise HTTPException(
                    status_code=400,
                    detail="Payment requires additional authentication. Please complete the payment process.",
                )

            # Verify payment is succeeded
            if payment_intent.status != "succeeded":
                raise HTTPException(
                    status_code=400,
                    detail=f"Payment failed. Status: {payment_intent.status}",
                )

        except stripe.error.CardError as e:
            print(f"❌ Card error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Payment failed: {e.user_message}",
            )
        except stripe.error.InvalidRequestError as e:
            print(f"❌ Invalid request error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid payment request: {str(e)}",
            )
        except Exception as e:
            print(f"❌ Payment processing error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error processing payment: {str(e)}",
            )

        # Update user role and payment information
        try:
            # Determine membership_type based on target role
            membership_type = "trial" if target_role == "Member" else "paid"

            # Set club_count based on target role
            club_count = 1

            update_data = {
                "role": target_role,
                "membership_status": "active",
                "membership_type": membership_type,
                "subscription_id": payment_intent.id,  # Store payment intent as subscription reference
                "stripe_customer_id": stripe_customer_id,
                "upgraded_from_moderator": True,
                "upgrade_date": datetime.utcnow(),
                "upgrade_payment_amount": amount,
                "club_count": club_count,  # Set club count based on role
                "updated_at": datetime.utcnow(),
            }

            result = await users_collection.update_one(
                {"_id": user["_id"]}, {"$set": update_data}
            )

            if result.modified_count == 0:
                raise HTTPException(
                    status_code=500, detail="Failed to update user role"
                )

            print(f"✅ User role updated: {email} -> {target_role}")
            print(f"✅ Membership type set to: {membership_type}")
            print(f"✅ Club count set to: {club_count}")

        except Exception as e:
            print(f"❌ Failed to update user role: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Failed to update user role: {str(e)}"
            )

        # Store payment record
        try:
            from ..routes.trial_membership import store_payment_record

            await store_payment_record(
                user_id=str(user["_id"]),
                subscription_id=payment_intent.id,
                price_id="",  # No price_id for one-time payments
                amount=amount,
                currency=CurrencyConfig.DEFAULT_CURRENCY,
                status="succeeded",
                payment_method_id=payment_method_id,
                stripe_customer_id=stripe_customer_id,
                payment_intent_id=payment_intent.id,
                start_date=datetime.utcnow(),
                end_date=None,  # One-time payment, no end date
                payment_type="moderator_upgrade",
                membership_type=membership_type,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            print(f"✅ Payment record stored for moderator upgrade")

        except Exception as e:
            print(f"⚠️ Failed to store payment record: {str(e)}")
            # Don't fail the entire operation for payment record storage

        # Initialize Stripe Connect variables
        stripe_connect_account_id = None
        stripe_onboarding_url = None
        stripe_connect_status = None
        
        # For Captain role upgrade, create Stripe Connect account
        if target_role == "Captain":
            try:
                # Import Stripe Connect service
                from services.club.stripe_connect_service import StripeConnectService
                
                stripe_connect_service = StripeConnectService()
                
                # Create Stripe Connect account for the Captain
                print(f"🚀 Creating Stripe Connect account for Captain (Moderator Upgrade): {email}")
                
                connect_result = await stripe_connect_service.create_captain_connect_account(
                    captain_id=str(user["_id"]),
                    captain_email=email,
                    captain_name=user.get("full_name", ""),
                    country='US'  # Default country, can be made configurable
                )
                
                if connect_result.get("success"):
                    stripe_connect_account_id = connect_result.get("account_id")
                    stripe_onboarding_url = connect_result.get("onboarding_url")
                    stripe_connect_status = connect_result.get("status", "pending_onboarding")
                    
                    print(f"✅ Stripe Connect account created for Captain {str(user['_id'])}")
                    print(f"   Account ID: {stripe_connect_account_id}")
                    print(f"   Onboarding URL: {stripe_onboarding_url}")
                else:
                    print(f"⚠️ Failed to create Stripe Connect account: {connect_result.get('error')}")
                    # Don't fail the upgrade if Stripe Connect setup fails
                    
            except Exception as stripe_error:
                print(f"⚠️ Error creating Stripe Connect account for Captain: {str(stripe_error)}")
                # Don't fail the upgrade if Stripe Connect setup fails

        # Prepare response data
        response_data = {
            "user_id": str(user["_id"]),
            "email": email,
            "previous_role": "Moderator",
            "new_role": target_role,
            "membership_type": membership_type,
            "club_count": club_count,
            "amount_paid": amount,
            "currency": CurrencyConfig.DEFAULT_CURRENCY,
            "payment_intent_id": payment_intent.id,
            "stripe_customer_id": stripe_customer_id,
            "upgrade_date": datetime.utcnow().isoformat(),
        }
        
        # Add Stripe Connect info to response data if Captain
        if stripe_connect_account_id:
            response_data["stripe_connect_account_id"] = stripe_connect_account_id
            response_data["stripe_connect_status"] = stripe_connect_status

        # Return success response
        return ModeratorUpgradeResponse(
            success=True,
            message=f"Successfully upgraded from Moderator to {target_role}" if target_role != "Captain" else f"Successfully upgraded from Moderator to {target_role}. Please complete Stripe onboarding to start receiving payments.",
            data=response_data,
            # Stripe Connect fields (will be None for Member upgrades)
            stripe_connect_account_id=stripe_connect_account_id,
            stripe_onboarding_url=stripe_onboarding_url,
            stripe_connect_status=stripe_connect_status,
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Unexpected error in moderator upgrade: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
