"""
My Profile API Routes

This module handles the my-profile API endpoint for authenticated users.
Returns comprehensive user profile information.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from ..models import (
    MyProfileResponse,
    UpdateProfileRequest,
    SubscriptionDetailsResponse,
    PaymentCardDetailsResponse,
    AddPaymentCardRequest,
    ViewProfileResponse,
    CaptainViewProfileResponse,
    ModeratorViewProfileResponse,
    MemberViewProfileResponse,
)
from ..utils import get_current_user
from ..db import get_user_collection
from core.database.collections import Collections
from core.utils.response_utils import create_response
from bson import ObjectId
from datetime import datetime
import logging
import stripe
import os

# Setup logging
logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
if not stripe.api_key:
    logger.warning("⚠️ STRIPE_SECRET_KEY not found in environment variables")

router = APIRouter()


@router.get("/my-profile", response_model=MyProfileResponse)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    """
    Get the current user's profile information

    Args:
        current_user: Current authenticated user from JWT token

    Returns:
        MyProfileResponse with user profile data
        
    For Captains:
        - total_moderator_count: Total moderators across all clubs created by captain
        - total_picks_submitted: Total picks submitted by captain across all clubs
        
    For Moderators:
        - total_picks_submitted: Total picks submitted by moderator across all clubs
        - clubs_moderated_count: Total number of clubs where user is a moderator
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user token"
            )

        # Get user collection
        user_collection = get_user_collection()
        
        # Initialize collections
        collections = Collections()
        clubs_collection = collections.get_clubs_collection()
        club_picks_collection = collections.get_club_picks_collection()

        # Fetch user details from database
        user = await user_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Get club count, moderator count, and picks count for captains
        clubs_created_count = 0
        total_moderator_count = 0
        total_picks_submitted = 0
        
        if user.get("role") == "Captain":
            try:
                # Get all clubs created by this captain
                all_clubs = await clubs_collection.find(
                    {"captain_id": user_id, "is_permanently_deleted": {"$ne": True}}
                ).to_list(None)

                # Count clubs with complete_step >= 4 (since we see the club has step 4)
                clubs_created_count = await clubs_collection.count_documents(
                    {
                        "captain_id": user_id,  # captain_id is stored as string, not ObjectId
                        "club_complete_step": {
                            "$gte": 4
                        },  # Count clubs with step 4 or higher
                        "is_permanently_deleted": {
                            "$ne": True
                        },  # Exclude permanently deleted clubs
                    }
                )
                
                # Additional check: if clubs_created_count == 1 but club_complete_step < 5, set to 0
                if clubs_created_count == 1:
                    # Check if the single club has completed step 5
                    club_with_step = await clubs_collection.find_one(
                        {
                            "captain_id": user_id,
                            "club_complete_step": {"$gte": 4},
                            "is_permanently_deleted": {"$ne": True}
                        },
                        {"club_complete_step": 1}
                    )
                    if club_with_step and club_with_step.get("club_complete_step", 0) < 5:
                        clubs_created_count = 0
                
                # Calculate total moderator count across all clubs created by this captain
                club_ids = [club.get("name_based_id") for club in all_clubs if club.get("club_complete_step", 0) >= 4 and club.get("name_based_id")]
                if club_ids:
                    # Sum up detailed_moderators count from all clubs
                    for club in all_clubs:
                        if club.get("club_complete_step", 0) >= 4:
                            try:
                                detailed_moderators = club.get("detailed_moderators", {})
                                # Handle case where detailed_moderators might be a list or dict
                                if isinstance(detailed_moderators, dict):
                                    detailed_moderators_count = detailed_moderators.get("count", 0)
                                elif isinstance(detailed_moderators, list):
                                    detailed_moderators_count = len(detailed_moderators)
                                else:
                                    detailed_moderators_count = 0
                                
                                total_moderator_count += detailed_moderators_count
                            except Exception as e:
                                logger.error(f"Error getting moderator count for club {club.get('name')}: {e}")
                
                # Calculate total picks submitted by this captain
                try:
                    total_picks_submitted = await club_picks_collection.count_documents({
                        "submitted_by": user_id
                    })
                except Exception as e:
                    logger.error(f"Error getting picks count for captain {user_id}: {e}")
                    total_picks_submitted = 0
            except Exception as e:
                logger.error(f"Error getting captain statistics for {user_id}: {e}")
                clubs_created_count = 0
                total_moderator_count = 0
                total_picks_submitted = 0
        
        # Calculate moderator statistics
        moderator_picks_submitted = 0
        clubs_moderated_count = 0
        if user.get("role") == "Moderator" or user.get("role") == "moderator":
            try:
                # Get total picks submitted by this user across all clubs
                moderator_picks_submitted = await club_picks_collection.count_documents({
                    "submitted_by": user_id
                })
                
                # Count how many clubs this user is a moderator in
                clubs_moderated_count = await clubs_collection.count_documents({
                    "detailed_moderators": {"$elemMatch": {"user_id": user_id}},
                    "is_permanently_deleted": {"$ne": True}
                })
                
            except Exception as e:
                logger.error(f"Error getting moderator statistics for {user_id}: {e}")
                moderator_picks_submitted = 0
                clubs_moderated_count = 0

        # Prepare user profile data - return ALL available fields from database
        # Start with all fields from the user document, excluding sensitive data
        profile_data = {}

        # Copy all fields from user document except sensitive ones
        sensitive_fields = {"password_hash", "_id"}
        for key, value in user.items():
            if key not in sensitive_fields:
                profile_data[key] = value

        # Convert ObjectId to string for user_id
        profile_data["user_id"] = str(user["_id"])

        # Ensure bio field is always present (null if not set)
        if "bio" not in profile_data:
            profile_data["bio"] = None
        
        # Add notification center status (default to False if not set)
        is_open = user.get("is_open", False)
        profile_data["is_open"] = is_open
        
        # Calculate unread notification count
        notifications_collection = collections.get_notifications_collection()
        if is_open:
            # If notification center is open, unread count is 0
            unread_count = 0
        else:
            # If closed, count unread notifications
            unread_count = await notifications_collection.count_documents({
                "user_id": user_id,
                "is_read": False
            })
        profile_data["unread_count"] = unread_count

        # Add computed fields
        profile_data["clubs_created_count"] = clubs_created_count
        
        # Add captain-specific fields
        if user.get("role") == "Captain":
            profile_data["total_moderator_count"] = total_moderator_count
            profile_data["total_picks_submitted"] = total_picks_submitted
        
        # Add moderator-specific fields (only for users with primary role "Moderator")
        if user.get("role") == "Moderator" or user.get("role") == "moderator":
            profile_data["total_picks_submitted"] = moderator_picks_submitted
            profile_data["clubs_moderated_count"] = clubs_moderated_count

        # Add computed statistics
        profile_data["statistics"] = {
            "total_logins": user.get("total_logins", 0),
            "last_activity": user.get("last_activity"),
            "account_age_days": _calculate_account_age_days(user.get("created_at")),
            "profile_completion_percentage": _calculate_profile_completion(user),
        }

        # Add preferences if not already present
        if "preferences" not in profile_data:
            profile_data["preferences"] = {
                "language": user.get("language", "en"),
                "timezone": user.get("timezone", "UTC"),
                "currency": user.get("currency", "USD"),
                "theme": user.get("theme", "light"),
            }

        # Add club information if user has joined clubs
        if user.get("clubs_joined"):
            profile_data["club_summary"] = {
                "total_clubs": len(user["clubs_joined"]),
                "active_clubs": len(
                    [
                        club
                        for club in user["clubs_joined"]
                        if club.get("is_active", True)
                    ]
                ),
                "trial_clubs": len(
                    [
                        club
                        for club in user["clubs_joined"]
                        if club.get("membership_type") == "trial"
                    ]
                ),
                "paid_clubs": len(
                    [
                        club
                        for club in user["clubs_joined"]
                        if club.get("membership_type") == "paid"
                    ]
                ),
            }

        # # Add membership information
        # if user.get("membership_type"):
        #     profile_data["membership_info"] = {
        #         "type": user.get("membership_type"),
        #         "status": user.get("membership_status"),
        #         "start_date": user.get("plan_start_date"),
        #         "end_date": user.get("plan_end_date"),
        #         "is_trial": user.get("is_trial", False),
        #         "subscription_id": user.get("subscription_id")
        #    u}

        logger.info(f"Successfully retrieved profile for user {user_id}")

        return MyProfileResponse(
            success=True, message="Profile retrieved successfully", data=profile_data
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving profile: {str(e)}",
        )


def _calculate_account_age_days(created_at):
    """Calculate account age in days"""
    if not created_at:
        return 0

    try:
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        now = datetime.utcnow()
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.utcnow().tzinfo)

        age_days = (now - created_at).days
        return max(0, age_days)
    except Exception:
        return 0


def _calculate_profile_completion(user):
    """Calculate profile completion percentage"""
    try:
        total_fields = 0
        completed_fields = 0

        # Required fields for profile completion
        profile_fields = [
            "full_name",
            "email",
            "phone",
            "country_code",
            "avatar_url",
            "first_name",
            "last_name",
        ]

        for field in profile_fields:
            total_fields += 1
            if user.get(field) and str(user.get(field)).strip():
                completed_fields += 1

        # Check if profile is marked as completed
        if user.get("profile_completed"):
            return 100.0

        # Calculate percentage
        if total_fields == 0:
            return 0.0

        percentage = (completed_fields / total_fields) * 100
        return round(percentage, 1)

    except Exception:
        return 0.0


@router.put("/my-profile", response_model=MyProfileResponse)
async def update_my_profile(
    profile_data: UpdateProfileRequest, current_user: dict = Depends(get_current_user)
):
    """
    Update the current user's profile information

    Args:
        profile_data: Profile data to update
        current_user: Current authenticated user from JWT token

    Returns:
        MyProfileResponse with updated profile data
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user token"
            )

        # Get user collection
        user_collection = get_user_collection()

        # Fields that can be updated
        allowed_fields = [
            "first_name",
            "last_name",
            "phone",
            "country_code",
            "avatar_url",
            "bio",
        ]

        # Filter profile_data to only include allowed fields
        update_data = {}
        for field in allowed_fields:
            value = getattr(profile_data, field, None)
            if value is not None:
                update_data[field] = value

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update. Allowed fields: first_name, last_name, phone, country_code, avatar_url, bio",
            )

        # Validate phone number length if provided
        if "phone" in update_data:
            phone = update_data["phone"]
            if phone and (len(phone) < 7 or len(phone) > 15):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone number must be between 7 and 15 characters long",
                )
        
        # Validate bio length if provided
        if "bio" in update_data:
            bio = update_data["bio"]
            if bio and len(bio) > 500:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Bio must be 500 characters or less",
                )

        # Validate and format data if provided
        if (
            "phone" in update_data
            or "country_code" in update_data
            or "first_name" in update_data
            or "last_name" in update_data
            or "avatar_url" in update_data
            or "bio" in update_data
        ):
            update_data = await _validate_and_format_phone_data(update_data, user_id)

        # Update full_name if first_name or last_name is being updated
        if "first_name" in update_data or "last_name" in update_data:
            # Get current user data to build full_name
            current_user = await user_collection.find_one({"_id": ObjectId(user_id)})
            if current_user:
                first_name = update_data.get(
                    "first_name", current_user.get("first_name", "")
                )
                last_name = update_data.get(
                    "last_name", current_user.get("last_name", "")
                )

                # Create full_name from first_name and last_name
                full_name_parts = [
                    part.strip() for part in [first_name, last_name] if part.strip()
                ]
                update_data["full_name"] = (
                    " ".join(full_name_parts) if full_name_parts else ""
                )

        # Add updated_at timestamp
        update_data["updated_at"] = datetime.utcnow()

        # Update user profile
        result = await user_collection.update_one(
            {"_id": ObjectId(user_id)}, {"$set": update_data}
        )

        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found or no changes made",
            )

        # Get updated user data
        updated_user = await user_collection.find_one({"_id": ObjectId(user_id)})

        # Prepare updated profile data
        profile_data = {
            "user_id": str(updated_user["_id"]),
            "full_name": updated_user.get("full_name", ""),
            "first_name": updated_user.get("first_name", ""),
            "last_name": updated_user.get("last_name", ""),
            "email": updated_user.get("email", ""),
            "phone": updated_user.get("phone", ""),
            "country_code": updated_user.get("country_code", ""),
            "role": updated_user.get("role", ""),
            "status": updated_user.get("status", ""),
            "avatar_url": updated_user.get("avatar_url", ""),
            "bio": updated_user.get("bio", ""),
            "profile_completed": updated_user.get("profile_completed", False),
            "updated_at": updated_user.get("updated_at"),
            "notification_preferences": updated_user.get(
                "notification_preferences", {}
            ),
            "privacy_settings": updated_user.get("privacy_settings", {}),
            "preferences": {
                "language": updated_user.get("language", "en"),
                "timezone": updated_user.get("timezone", "UTC"),
                "currency": updated_user.get("currency", "USD"),
                "theme": updated_user.get("theme", "light"),
            },
        }

        logger.info(f"Successfully updated profile for user {user_id}")

        return MyProfileResponse(
            success=True, message="Profile updated successfully", data=profile_data
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating profile: {str(e)}",
        )


@router.get("/subscription-details", response_model=SubscriptionDetailsResponse)
async def get_subscription_details(current_user: dict = Depends(get_current_user)):
    """
    Get subscription details for the logged-in member

    Returns subscription information including:
    - User's full name
    - Membership type (trial, paid, etc.)
    - Status (active, inactive, etc.)
    - Membership status (active, inactive, etc.)
    - Total clubs joined
    - Clubs created count (for captains)
    - Plan start date
    - Plan end date

    Args:
        current_user: Current authenticated user from JWT token

    Returns:
        SubscriptionDetailsResponse with subscription details
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user token"
            )

        # Get user collection
        user_collection = get_user_collection()

        # Get user data from database
        user = await user_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Calculate clubs_created_count for captains using the same logic as /my-profile
        clubs_created_count = 0
        if user.get("role") == "Captain":
            try:
                # Get clubs collection
                from services.club.db import get_club_collection
                clubs_collection = get_club_collection()
                
                # Count clubs with complete_step >= 4 (same logic as /my-profile)
                clubs_created_count = await clubs_collection.count_documents(
                    {
                        "captain_id": user_id,  # captain_id is stored as string, not ObjectId
                        "club_complete_step": {
                            "$gte": 4
                        },  # Count clubs with step 4 or higher
                        "is_permanently_deleted": {
                            "$ne": True
                        },  # Exclude permanently deleted clubs
                    }
                )
                
                # Additional check: if clubs_created_count == 1 but club_complete_step < 5, set to 0
                if clubs_created_count == 1:
                    # Check if the single club has completed step 5
                    club_with_step = await clubs_collection.find_one(
                        {
                            "captain_id": user_id,
                            "club_complete_step": {"$gte": 4},
                            "is_permanently_deleted": {"$ne": True}
                        },
                        {"club_complete_step": 1}
                    )
                    if club_with_step and club_with_step.get("club_complete_step", 0) < 5:
                        clubs_created_count = 0
                
                logger.info(f"Captain {user_id} has created {clubs_created_count} clubs")
                
            except Exception as e:
                logger.error(f"Error getting captain club count for {user_id}: {e}")
                clubs_created_count = 0

        # Extract subscription details
        subscription_data = {
            "name": user.get("full_name", "Unknown"),
            "membership_type": user.get("membership_type", "none"),
            "status": user.get("status", "unknown"),
            "membership_status": user.get("membership_status", "none"),
            "total_clubs_joined": user.get("total_clubs_joined", 0),
            "clubs_created_count": clubs_created_count,  # For captains - calculated from actual clubs
            "plan_start_date": user.get("plan_start_date"),
            "plan_end_date": user.get("plan_end_date"),
            "whats_included": [
                "Access to all premium clubs",
                "Live betting picks and strategies",
                "Expert analysis and insights",
                "Community discussions and support",
            ],
        }

        # Format dates if they exist
        if subscription_data["plan_start_date"]:
            if isinstance(subscription_data["plan_start_date"], datetime):
                subscription_data["plan_start_date"] = subscription_data[
                    "plan_start_date"
                ].isoformat()

        if subscription_data["plan_end_date"]:
            if isinstance(subscription_data["plan_end_date"], datetime):
                subscription_data["plan_end_date"] = subscription_data[
                    "plan_end_date"
                ].isoformat()

        logger.info(f"Retrieved subscription details for user {user_id}")

        return SubscriptionDetailsResponse(
            success=True,
            message="Subscription details retrieved successfully",
            data=subscription_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving subscription details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving subscription details: {str(e)}",
        )


@router.get("/payment-card-details", response_model=PaymentCardDetailsResponse)
async def get_payment_card_details(current_user: dict = Depends(get_current_user)):
    """
    Get payment card details from Stripe for the logged-in user

    Retrieves card information directly from Stripe using the user's Stripe customer ID.
    This data is not stored in our database - it's fetched live from Stripe.

    Returns:
    - Card details (last 4 digits, brand, expiry month/year)
    - Payment methods associated with the customer
    - Recent payment history

    Args:
        current_user: Current authenticated user from JWT token

    Returns:
        PaymentCardDetailsResponse with card details from Stripe
    """
    try:
        user_id = current_user.get("user_id")
        stripe_customer_id = current_user.get("stripe_customer_id")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user token"
            )

        # If not in JWT token, try to get from database
        if not stripe_customer_id:
            from ..db import get_user_collection

            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user:
                stripe_customer_id = user.get("stripe_customer_id")

        if not stripe_customer_id:
            return PaymentCardDetailsResponse(
                success=True,
                message="No Stripe customer ID found for this user",
                data={
                    "has_stripe_customer": False,
                    "user_name": current_user.get("full_name", ""),
                    "user_email": current_user.get("email", ""),
                    "customer_name": None,
                    "customer_email": None,
                    "payment_method": "Card",
                    "payment_methods": [],
                    "default_payment_method": None,
                    "recent_charges": [],
                },
            )

        # Check if Stripe is configured
        if not stripe.api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Payment system not configured",
            )

        logger.info(
            f"Retrieving payment details for Stripe customer: {stripe_customer_id}"
        )

        # Get customer details from Stripe
        try:
            customer = stripe.Customer.retrieve(stripe_customer_id)
            print(customer, "customercustomercustomercustomer")
        except stripe.error.InvalidRequestError:
            return PaymentCardDetailsResponse(
                success=True,
                message="Stripe customer not found",
                data={
                    "has_stripe_customer": False,
                    "user_name": current_user.get("full_name", ""),
                    "user_email": current_user.get("email", ""),
                    "customer_name": None,
                    "customer_email": None,
                    "payment_method": "Card",
                    "payment_methods": [],
                    "default_payment_method": None,
                    "recent_charges": [],
                },
            )

        # Get payment methods for this customer
        payment_methods = stripe.PaymentMethod.list(
            customer=stripe_customer_id, type="card"
        )

        # Get recent charges for this customer
        recent_charges = stripe.Charge.list(customer=stripe_customer_id, limit=10)

        # Get payment cards from database for additional information
        collections = Collections()
        payment_cards_collection = collections.get_payment_cards_collection()
        db_cards = await payment_cards_collection.find({"user_id": user_id}).to_list(
            None
        )
        db_cards_dict = {card["stripe_payment_method_id"]: card for card in db_cards}

        # Process payment methods
        processed_payment_methods = []
        default_payment_method = None

        for pm in payment_methods.data:
            if pm.type == "card":
                # Get additional info from database
                db_card_info = db_cards_dict.get(pm.id, {})

                # Get cardholder name with fallback to user name
                cardholder_name = pm.billing_details.name or db_card_info.get(
                    "cardholder_name", ""
                )
                if not cardholder_name.strip():
                    cardholder_name = current_user.get("full_name", "")

                card_details = {
                    "id": pm.id,
                    "brand": pm.card.brand,
                    "last4": pm.card.last4,
                    "exp_month": pm.card.exp_month,
                    "exp_year": pm.card.exp_year,
                    "funding": pm.card.funding,
                    "country": pm.card.country,
                    "cardholder_name": cardholder_name,
                    "is_default": pm.id
                    == customer.invoice_settings.default_payment_method,
                    "created_at": db_card_info.get("created_at"),
                    "updated_at": db_card_info.get("updated_at"),
                }
                processed_payment_methods.append(card_details)

                if pm.id == customer.invoice_settings.default_payment_method:
                    default_payment_method = card_details

        # Process recent charges
        processed_charges = []
        for charge in recent_charges.data:
            if charge.status == "succeeded":
                charge_details = {
                    "id": charge.id,
                    "amount": charge.amount / 100,  # Convert from cents
                    "currency": charge.currency,
                    "description": charge.description,
                    "created": datetime.fromtimestamp(charge.created).isoformat(),
                    "status": charge.status,
                    "payment_method_details": (
                        {
                            "type": charge.payment_method_details.type,
                            "brand": (
                                charge.payment_method_details.card.brand
                                if charge.payment_method_details.card
                                else None
                            ),
                            "last4": (
                                charge.payment_method_details.card.last4
                                if charge.payment_method_details.card
                                else None
                            ),
                        }
                        if charge.payment_method_details
                        else None
                    ),
                }
                processed_charges.append(charge_details)

        payment_data = {
            "has_stripe_customer": True,
            "stripe_customer_id": stripe_customer_id,
            "user_name": current_user.get("full_name", ""),
            "user_email": current_user.get("email", ""),
            "customer_name": customer.name,
            "customer_email": customer.email,
            "payment_method": "Card",
            "payment_methods": processed_payment_methods,
            "default_payment_method": default_payment_method,
            "recent_charges": processed_charges,
            "total_payment_methods": len(processed_payment_methods),
            "total_recent_charges": len(processed_charges),
        }

        logger.info(
            f"Retrieved payment details for user {user_id}: {len(processed_payment_methods)} payment methods, {len(processed_charges)} recent charges"
        )

        return PaymentCardDetailsResponse(
            success=True,
            message="Payment card details retrieved successfully",
            data=payment_data,
        )

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error retrieving payment details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment system error: {str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving payment card details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving payment card details: {str(e)}",
        )


# @router.post("/add-payment-card", response_model=PaymentCardDetailsResponse)
# async def add_payment_card(
#     request: AddPaymentCardRequest,
#     current_user: dict = Depends(get_current_user)
# ):
#     """
#     Add a new payment card to the user's Stripe customer account

#     Creates a new payment method in Stripe and optionally sets it as the default.

#     Args:
#         request: AddPaymentCardRequest containing card details
#         current_user: Current authenticated user from JWT token

#     Returns:
#         PaymentCardDetailsResponse with updated payment methods
#     """
#     try:
#         user_id = current_user.get('user_id')
#         stripe_customer_id = current_user.get('stripe_customer_id')

#         if not user_id:
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Invalid user token"
#             )

#         # If not in JWT token, try to get from database
#         if not stripe_customer_id:
#             from ..db import get_user_collection
#             users_collection = get_user_collection()
#             user = await users_collection.find_one({"_id": ObjectId(user_id)})
#             if user:
#                 stripe_customer_id = user.get('stripe_customer_id')

#         if not stripe_customer_id:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="No Stripe customer ID found for this user"
#             )

#         # Check if Stripe is configured
#         if not stripe.api_key:
#             raise HTTPException(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 detail="Payment system not configured"
#             )

#         logger.info(f"Adding payment card for Stripe customer: {stripe_customer_id}")

#         # Create payment method in Stripe
#         try:
#             payment_method = stripe.PaymentMethod.create(
#                 type='card',
#                 card={
#                     'number': request.card_number,
#                     'exp_month': request.exp_month,
#                     'exp_year': request.exp_year,
#                     'cvc': request.cvc,
#                 },
#                 billing_details={
#                     'name': request.cardholder_name,
#                     'email': current_user.get('email'),
#                 }
#             )

#             # Attach payment method to customer
#             stripe.PaymentMethod.attach(
#                 payment_method.id,
#                 customer=stripe_customer_id,
#             )

#             # Set as default if requested
#             if request.set_as_default:
#                 stripe.Customer.modify(
#                     stripe_customer_id,
#                     invoice_settings={
#                         'default_payment_method': payment_method.id,
#                     },
#                 )

#             logger.info(f"Successfully added payment card {payment_method.id} for user {user_id}")

#             # Save payment card details to database
#             collections = Collections()
#             payment_cards_collection = collections.get_payment_cards_collection()

#             card_document = {
#                 "user_id": user_id,
#                 "stripe_customer_id": stripe_customer_id,
#                 "stripe_payment_method_id": payment_method.id,
#                 "card_brand": payment_method.card.brand,
#                 "card_last4": payment_method.card.last4,
#                 "card_exp_month": payment_method.card.exp_month,
#                 "card_exp_year": payment_method.card.exp_year,
#                 "card_funding": payment_method.card.funding,
#                 "card_country": payment_method.card.country,
#                 "cardholder_name": request.cardholder_name,
#                 "is_default": request.set_as_default,
#                 "created_at": datetime.utcnow(),
#                 "updated_at": datetime.utcnow()
#             }

#             await payment_cards_collection.insert_one(card_document)
#             logger.info(f"Saved payment card {payment_method.id} to database for user {user_id}")

#             # Get updated payment card details
#             updated_details = await get_payment_card_details(current_user)

#             return create_response(
#                 status_code=status.HTTP_200_OK,
#                 status="success",
#                 message="Payment card added successfully",
#                 data=updated_details.data
#             )

#         except stripe.error.CardError as e:
#             logger.error(f"Card error adding payment method: {e}")
#             return create_response(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 status="error",
#                 message=f"Card error: {e.user_message}",
#                 data=None
#             )
#         except stripe.error.InvalidRequestError as e:
#             logger.error(f"Invalid request error: {e}")
#             error_message = str(e)
#             if "raw card data" in error_message.lower():
#                 return create_response(
#                     status_code=status.HTTP_400_BAD_REQUEST,
#                     status="error",
#                     message="Raw card data APIs are not enabled in test mode. Please enable them in your Stripe dashboard or use test tokens instead.",
#                     data={
#                         "error_type": "raw_card_data_disabled",
#                         "solution": "Enable raw card data APIs in Stripe dashboard under Settings > API keys > Test mode toggle"
#                     }
#                 )
#             return create_response(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 status="error",
#                 message=f"Invalid request: {str(e)}",
#                 data=None
#             )

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error adding payment card: {e}")
#         return create_response(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             status="error",
#             message=f"Error adding payment card: {str(e)}",
#             data=None
#         )


@router.delete(
    "/delete-payment-card/{payment_method_id}",
    response_model=PaymentCardDetailsResponse,
)
async def delete_payment_card(
    payment_method_id: str, current_user: dict = Depends(get_current_user)
):
    """
    Delete a payment card from the user's Stripe customer account

    Detaches and deletes the specified payment method from Stripe.
    Provides detailed information about card usage before preventing deletion.

    Args:
        payment_method_id: Stripe payment method ID to delete
        current_user: Current authenticated user from JWT token

    Returns:
        PaymentCardDetailsResponse with updated payment methods or detailed usage information

    Raises:
        HTTPException: If card is used for active subscription or is default payment method
    """
    try:
        user_id = current_user.get("user_id")
        stripe_customer_id = current_user.get("stripe_customer_id")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user token"
            )

        # If not in JWT token, try to get from database
        if not stripe_customer_id:
            from ..db import get_user_collection

            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user:
                stripe_customer_id = user.get("stripe_customer_id")

        if not stripe_customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Stripe customer ID found for this user",
            )

        # Check if Stripe is configured
        if not stripe.api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Payment system not configured",
            )

        logger.info(
            f"Deleting payment method {payment_method_id} for Stripe customer: {stripe_customer_id}"
        )

        try:
            # Get the payment method to verify it belongs to this customer
            payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

            if payment_method.customer != stripe_customer_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Payment method does not belong to this user",
                )

            # Check if this payment method is being used for any active subscriptions
            subscriptions = stripe.Subscription.list(
                customer=stripe_customer_id, status="active", limit=100
            )

            # Find all subscriptions using this payment method
            using_subscriptions = []
            for subscription in subscriptions.data:
                if subscription.default_payment_method == payment_method_id:
                    using_subscriptions.append(
                        {
                            "subscription_id": subscription.id,
                            "status": subscription.status,
                            "current_period_start": (
                                datetime.fromtimestamp(
                                    subscription.current_period_start
                                ).isoformat()
                                if subscription.current_period_start
                                else None
                            ),
                            "current_period_end": (
                                datetime.fromtimestamp(
                                    subscription.current_period_end
                                ).isoformat()
                                if subscription.current_period_end
                                else None
                            ),
                            "plan_id": (
                                subscription.items.data[0].price.id
                                if subscription.items.data
                                else None
                            ),
                            "plan_name": (
                                subscription.items.data[0].price.nickname
                                if subscription.items.data
                                and subscription.items.data[0].price.nickname
                                else "Unknown Plan"
                            ),
                        }
                    )

            # If card is being used by subscriptions, return detailed information
            if using_subscriptions:
                return create_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    status="error",
                    message=f"Cannot delete payment card. This card is currently being used by {len(using_subscriptions)} active subscription(s).",
                    data={
                        "card_usage": {
                            "total_active_subscriptions": len(using_subscriptions),
                            "subscriptions_using_card": using_subscriptions,
                            "card_id": payment_method_id,
                            "card_last4": (
                                payment_method.card.last4
                                if hasattr(payment_method, "card")
                                else "Unknown"
                            ),
                            "card_brand": (
                                payment_method.card.brand
                                if hasattr(payment_method, "card")
                                else "Unknown"
                            ),
                        },
                        "solution": "Please cancel or change the payment method for these subscriptions before deleting this card.",
                    },
                )

            # Also check if this is the default payment method for the customer
            customer = stripe.Customer.retrieve(stripe_customer_id)
            if customer.invoice_settings.default_payment_method == payment_method_id:
                # Get total number of payment methods for context
                all_payment_methods = stripe.PaymentMethod.list(
                    customer=stripe_customer_id, type="card"
                )

                return create_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    status="error",
                    message="Cannot delete payment card. This card is set as the default payment method for your account.",
                    data={
                        "card_usage": {
                            "is_default_payment_method": True,
                            "card_id": payment_method_id,
                            "card_last4": (
                                payment_method.card.last4
                                if hasattr(payment_method, "card")
                                else "Unknown"
                            ),
                            "card_brand": (
                                payment_method.card.brand
                                if hasattr(payment_method, "card")
                                else "Unknown"
                            ),
                            "total_payment_methods": len(all_payment_methods.data),
                            "customer_id": stripe_customer_id,
                        },
                        "solution": f"Please set another card as default before deleting this one. You have {len(all_payment_methods.data)} total payment method(s).",
                    },
                )

            # Detach the payment method from the customer
            stripe.PaymentMethod.detach(payment_method_id)

            logger.info(
                f"Successfully deleted payment method {payment_method_id} for user {user_id}"
            )

            # Remove payment card from database
            collections = Collections()
            payment_cards_collection = collections.get_payment_cards_collection()

            delete_result = await payment_cards_collection.delete_one(
                {"user_id": user_id, "stripe_payment_method_id": payment_method_id}
            )

            if delete_result.deleted_count > 0:
                logger.info(
                    f"Removed payment card {payment_method_id} from database for user {user_id}"
                )
            else:
                logger.warning(
                    f"Payment card {payment_method_id} not found in database for user {user_id}"
                )

            # Get updated payment card details
            updated_details = await get_payment_card_details(current_user)

            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Payment card deleted successfully",
                data=updated_details.data,
            )

        except stripe.error.InvalidRequestError as e:
            logger.error(f"Invalid request error: {e}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=f"Payment method not found: {str(e)}",
                data=None,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting payment card: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Error deleting payment card: {str(e)}",
            data=None,
        )


async def _validate_and_format_phone_data(update_data: dict, user_id: str) -> dict:
    """
    Validate and format profile data according to the validation rules

    Args:
        update_data: Dictionary containing the fields to update
        user_id: User ID for logging purposes

    Returns:
        dict: Updated data with validated and formatted fields

    Raises:
        HTTPException: If validation fails
    """
    import re

    try:
        # Get user collection to check for existing phone numbers
        user_collection = get_user_collection()

        # Validate first_name if provided
        if "first_name" in update_data:
            first_name = update_data["first_name"]
            if not isinstance(first_name, str) or not first_name.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="First Name cannot be empty",
                )
            if not re.match(r"^[A-Za-z ]+$", first_name):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="First Name must contain only letters and spaces",
                )
            update_data["first_name"] = first_name.strip()

        # Validate last_name if provided
        if "last_name" in update_data:
            last_name = update_data["last_name"]
            if not isinstance(last_name, str) or not last_name.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Last Name cannot be empty",
                )
            if not re.match(r"^[A-Za-z ]+$", last_name):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Last Name must contain only letters and spaces",
                )
            update_data["last_name"] = last_name.strip()

        # Validate avatar_url if provided
        if "avatar_url" in update_data:
            avatar_url = update_data["avatar_url"]
            if avatar_url is not None:  # Allow null/empty values
                if not isinstance(avatar_url, str):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Avatar URL must be a string",
                    )
                # Basic URL validation
                if avatar_url.strip() and not (
                    avatar_url.startswith("http://")
                    or avatar_url.startswith("https://")
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Avatar URL must be a valid HTTP or HTTPS URL",
                    )
                update_data["avatar_url"] = (
                    avatar_url.strip() if avatar_url.strip() else None
                )

        # Validate and format country_code if provided
        if "country_code" in update_data:
            country_code = update_data["country_code"]
            if not isinstance(country_code, str):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Country code must be a string",
                )

            # Clean country code - remove any non-digit characters except +
            cleaned_code = "".join(c for c in country_code if c.isdigit() or c == "+")

            if not cleaned_code:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Country code must contain digits or + symbol",
                )

            # Ensure country code starts with + or is just digits
            if not (cleaned_code.startswith("+") or cleaned_code.isdigit()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Country code must start with + or be just digits",
                )

            # Remove + for storage consistency
            if cleaned_code.startswith("+"):
                cleaned_code = cleaned_code[1:]

            update_data["country_code"] = cleaned_code

        # Validate and format phone if provided
        if "phone" in update_data:
            phone = update_data["phone"]
            if not isinstance(phone, str):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone number must be a string",
                )

            # Clean phone number - remove any non-digit characters
            cleaned_phone = "".join(c for c in phone if c.isdigit())

            if not cleaned_phone:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone Number must contain digits",
                )

            # Check if phone number already includes country code
            country_code = update_data.get("country_code", "")
            if country_code:
                # Check if phone already starts with country code
                if cleaned_phone.startswith(country_code):
                    # Phone already has country code, use as is
                    logger.info(
                        f"Phone number {cleaned_phone} already contains country code {country_code}"
                    )
                    update_data["phone"] = cleaned_phone
                else:
                    # Combine country code with phone
                    combined_phone = country_code + cleaned_phone

                    # Validate total length
                    if not (11 <= len(combined_phone) <= 15):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Total phone number length (country code + phone) must be 11-15 digits, got {len(combined_phone)}",
                        )

                    update_data["phone"] = combined_phone
            else:
                # No country code provided, validate phone length
                if not (10 <= len(cleaned_phone) <= 15):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Phone Number must be 10-15 digits, got {len(cleaned_phone)}",
                    )

                update_data["phone"] = cleaned_phone

            # Check if phone number already exists for another user
            existing_user = await user_collection.find_one(
                {"phone": update_data["phone"], "_id": {"$ne": ObjectId(user_id)}}
            )

            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone number already exists for another user",
                )

        return update_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating phone data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating phone data: {str(e)}",
        )


async def get_stripe_customer_id(current_user: dict = Depends(get_current_user)) -> str:
    """Resolve stripe_customer_id either from JWT or fallback to DB"""
    user_id = current_user.get("user_id")
    stripe_customer_id = current_user.get("stripe_customer_id")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user token"
        )

    # Fallback: check MongoDB if not in JWT
    if not stripe_customer_id:
        users_collection = get_user_collection()
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            stripe_customer_id = user.get("stripe_customer_id")

    if not stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Stripe customer ID found for this user",
        )

    return stripe_customer_id


from pydantic import BaseModel
from typing import List, Optional


class CardDetails(BaseModel):
    id: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    funding: str
    country: Optional[str]
    cardholder_name: Optional[str]
    is_default: bool


class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None


class SaveCardRequest(BaseModel):
    payment_method_id: str


class UpdateCardRequest(BaseModel):
    old_payment_method_id: str
    new_payment_method_id: str

    # 1️⃣ GET ALL CARDS


@router.get("/cards/", response_model=APIResponse)
async def list_cards(
    stripe_customer_id: str = Depends(get_stripe_customer_id),
    current_user: dict = Depends(get_current_user),
):
    payment_methods = stripe.PaymentMethod.list(
        customer=stripe_customer_id, type="card"
    )
    customer = stripe.Customer.retrieve(stripe_customer_id)

    cards = []
    for pm in payment_methods.data:
        cards.append(
            {
                "id": pm.id,
                "brand": pm.card.brand,
                "last4": pm.card.last4,
                "exp_month": pm.card.exp_month,
                "exp_year": pm.card.exp_year,
                "funding": pm.card.funding,
                "country": pm.card.country,
                "cardholder_name": pm.billing_details.name
                or current_user.get("full_name", ""),
                "is_default": pm.id == customer.invoice_settings.default_payment_method,
            }
        )

    return APIResponse(
        success=True, message="Cards retrieved successfully", data={"cards": cards}
    )


# 2️⃣ SAVE CARD TO CUSTOMER
@router.post("/save", response_model=APIResponse)
async def save_card(
    req: SaveCardRequest, stripe_customer_id: str = Depends(get_stripe_customer_id)
):
    pm = stripe.PaymentMethod.attach(req.payment_method_id, customer=stripe_customer_id)
    return APIResponse(
        success=True, message="Card saved successfully", data={"card_id": pm.id}
    )


# # 3️⃣ GET CARD USAGE
# @router.get("/{payment_method_id}/usage", response_model=APIResponse)
# async def get_card_usage(
#     payment_method_id: str,
#     stripe_customer_id: str = Depends(get_stripe_customer_id)
# ):
#     # Subscriptions using this card
#     subscriptions = stripe.Subscription.list(customer=stripe_customer_id)
#     subs_using_card = [s for s in subscriptions.data if s.default_payment_method == payment_method_id]

#     # Charges using this card
#     charges = stripe.Charge.list(customer=stripe_customer_id, limit=20)
#     charges_using_card = [c for c in charges.data if c.payment_method == payment_method_id]

#     return APIResponse(
#         success=True,
#         message="Card usage retrieved",
#         data={
#             "subscriptions": [s.id for s in subs_using_card],
#             "charges": [c.id for c in charges_using_card]
#         }
#     )


@router.get("/{payment_method_id}/usage", response_model=APIResponse)
async def get_card_usage(
    payment_method_id: str, stripe_customer_id: str = Depends(get_stripe_customer_id)
):
    try:
        # Fetch payment method details
        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

        # Fetch all subscriptions for this customer
        subscriptions = stripe.Subscription.list(customer=stripe_customer_id)
        subs_using_card = [
            s
            for s in subscriptions.auto_paging_iter()
            if s.default_payment_method == payment_method_id
        ]

        # Prepare detailed subscription info
        subscription_details = []
        for sub in subs_using_card:
            plan_item = sub["items"]["data"][0]["plan"]
            subscription_details.append(
                {
                    "id": sub.id,
                    "status": sub.status,
                    "start_date": sub.start_date,
                    "current_period_start": sub.current_period_start,
                    "current_period_end": sub.current_period_end,
                    "cancel_at_period_end": sub.cancel_at_period_end,
                    "plan": {
                        "id": plan_item.id,
                        "amount": plan_item.amount,
                        "currency": plan_item.currency,
                        "interval": plan_item.interval,
                    },
                    "latest_invoice": sub.latest_invoice,
                    "metadata": sub.metadata,  # club_name, customer_name, etc.
                }
            )

        # Fetch charges using this payment method
        charges = stripe.Charge.list(customer=stripe_customer_id, limit=20)
        charges_using_card = []
        for c in charges.auto_paging_iter():
            if c.payment_method == payment_method_id:
                charges_using_card.append(
                    {
                        "id": c.id,
                        "amount": c.amount,
                        "currency": c.currency,
                        "status": c.status,
                        "payment_method": c.payment_method,
                        "metadata": c.metadata,
                    }
                )

        # Fetch customer info
        customer = stripe.Customer.retrieve(stripe_customer_id)

        return APIResponse(
            success=True,
            message="Card usage retrieved with card details",
            data={
                "customer": {
                    "id": customer.id,
                    "name": customer.name or customer.metadata.get("customer_name"),
                    "email": customer.email or customer.metadata.get("customer_email"),
                    "metadata": customer.metadata,
                },
                "payment_method": {
                    "id": payment_method.id,
                    "type": payment_method.type,
                    "card": payment_method.card,  # brand, last4, exp_month, exp_year
                    "billing_details": payment_method.billing_details,
                },
                "subscriptions": subscription_details,
                "charges": charges_using_card,
            },
        )

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")


# uper vala old card delete krne ke liye
# @router.get("/{payment_method_id}/usage", response_model=APIResponse)
# async def get_card_usage(
#     payment_method_id: str,
#     stripe_customer_id: str = Depends(get_stripe_customer_id)
# ):
#     try:
#         # Fetch payment method details
#         payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

#         # Fetch subscriptions for this customer
#         subscriptions = stripe.Subscription.list(customer=stripe_customer_id)
#         subs_using_card = [
#             s for s in subscriptions.auto_paging_iter()
#             if s.default_payment_method == payment_method_id
#         ]

#         # Prepare subscription usage
#         usage_list = []
#         for sub in subs_using_card:
#             plan_item = sub["items"]["data"][0]["plan"]
#             usage_list.append({
#                 "type": "subscription",   # ✅ identify it as recurring
#                 "id": sub.id,
#                 "status": sub.status,
#                 "start_date": sub.start_date,
#                 "current_period_start": sub.current_period_start,
#                 "current_period_end": sub.current_period_end,
#                 "cancel_at_period_end": sub.cancel_at_period_end,
#                 "plan": {
#                     "id": plan_item.id,
#                     "amount": plan_item.amount,
#                     "currency": plan_item.currency,
#                     "interval": plan_item.interval
#                 },
#                 "latest_invoice": sub.latest_invoice,
#                 "metadata": sub.metadata
#             })

#         # Fetch charges using this payment method
#         charges = stripe.Charge.list(customer=stripe_customer_id, limit=20)
#         for c in charges.auto_paging_iter():
#             if c.payment_method == payment_method_id:
#                 usage_list.append({
#                     "type": "charge",   # ✅ identify it as one-time payment
#                     "id": c.id,
#                     "amount": c.amount,
#                     "currency": c.currency,
#                     "status": c.status,
#                     "created": c.created,
#                     "payment_method": c.payment_method,
#                     "metadata": c.metadata
#                 })

#         # Fetch customer info
#         customer = stripe.Customer.retrieve(stripe_customer_id)

#         return APIResponse(
#             success=True,
#             message="Card usage retrieved with card details",
#             data={
#                 "customer": {
#                     "id": customer.id,
#                     "name": customer.name or customer.metadata.get("customer_name"),
#                     "email": customer.email or customer.metadata.get("customer_email"),
#                     "metadata": customer.metadata
#                 },
#                 "payment_method": {
#                     "id": payment_method.id,
#                     "type": payment_method.type,
#                     "card": payment_method.card,
#                     "billing_details": payment_method.billing_details
#                 },
#                 "usage": usage_list  # ✅ unified list (subscriptions + charges)
#             }
#         )

#     except stripe.error.StripeError as e:
#         raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")


class CardUpdateItem(BaseModel):
    stripe_customer_id: str
    subscription_id: str
    new_payment_method_id: str


class UpdateCardsRequest(BaseModel):
    updates: List[CardUpdateItem]


# 4️⃣ UPDATE CARD (REPLACE OLD WITH NEW) FOR SPECIFIC SUBSCRIPTIONS
@router.put("/update", response_model=APIResponse)
async def update_card(req: UpdateCardsRequest):
    results = []

    for item in req.updates:
        try:
            # Attach new payment method to customer
            stripe.PaymentMethod.attach(
                item.new_payment_method_id, customer=item.stripe_customer_id
            )

            # Update subscription with new payment method
            stripe.Subscription.modify(
                item.subscription_id, default_payment_method=item.new_payment_method_id
            )

            # Optionally, update customer's default payment method if none exists
            customer = stripe.Customer.retrieve(item.stripe_customer_id)
            if customer.invoice_settings.default_payment_method is None:
                stripe.Customer.modify(
                    item.stripe_customer_id,
                    invoice_settings={
                        "default_payment_method": item.new_payment_method_id
                    },
                )

            results.append(
                {
                    "subscription_id": item.subscription_id,
                    "status": "updated",
                    "new_payment_method_id": item.new_payment_method_id,
                }
            )

        except stripe.error.StripeError as e:
            results.append(
                {
                    "subscription_id": item.subscription_id,
                    "status": "failed",
                    "error": str(e),
                }
            )

    return APIResponse(
        success=True,
        message="Card updates processed",
        data={"updates": results},  # ✅ must be a dict
    )


# 5️⃣ DELETE CARD
@router.delete("/{payment_method_id}", response_model=APIResponse)
async def delete_card(
    payment_method_id: str, stripe_customer_id: str = Depends(get_stripe_customer_id)
):
    # Check if in use
    subscriptions = stripe.Subscription.list(customer=stripe_customer_id)
    in_use = any(
        s.default_payment_method == payment_method_id for s in subscriptions.data
    )

    if in_use:
        return APIResponse(
            success=False,
            message="Card is in use for active subscriptions, cannot delete",
        )

    # Detach card
    stripe.PaymentMethod.detach(payment_method_id)

    return APIResponse(success=True, message="Card deleted successfully")


@router.get("/view-profile/{user_id}", response_model=ViewProfileResponse)
async def view_profile(user_id: str, current_user: dict = Depends(get_current_user)):
    """
    View another user's profile based on their user_id
    
    Args:
        user_id: The user ID to view profile for
        current_user: Current authenticated user from JWT token
        
    Returns:
        ViewProfileResponse with user profile data based on their role
    """
    try:
        # Initialize collections
        collections = Collections()
        clubs_collection = collections.get_clubs_collection()
        club_picks_collection = collections.get_club_picks_collection()
        user_collection = get_user_collection()
        
        # Validate user_id format
        try:
            ObjectId(user_id)
        except:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Invalid user ID format"
            )
        
        # Fetch user details from database
        user = await user_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="User not found"
            )
        
        # Extract basic user information
        first_name = user.get("first_name", "")
        last_name = user.get("last_name", "")
        email = user.get("email", "")
        avatar_url = user.get("avatar_url")
        bio = user.get("bio")
        role = user.get("role", "Member")
        signup_date = user.get("created_at", datetime.utcnow()).isoformat()
        
        # Role-based profile data
        if role == "Captain" or role == "captain":
            # Calculate captain statistics
            clubs_created_count = 0
            total_moderators_count = 0
            total_picks_submitted_count = 0
            
            try:
                # Get all clubs created by this captain
                all_clubs = await clubs_collection.find({
                    "captain_id": user_id, 
                    "is_permanently_deleted": {"$ne": True}
                }).to_list(None)
                
                # Count clubs with complete_step >= 4
                clubs_created_count = await clubs_collection.count_documents({
                    "captain_id": user_id,
                    "club_complete_step": {"$gte": 4},
                    "is_permanently_deleted": {"$ne": True}
                })
                
                # Additional check: if clubs_created_count == 1 but club_complete_step < 5, set to 0
                if clubs_created_count == 1:
                    club_with_step = await clubs_collection.find_one({
                        "captain_id": user_id,
                        "club_complete_step": {"$gte": 4},
                        "is_permanently_deleted": {"$ne": True}
                    }, {"club_complete_step": 1})
                    if club_with_step and club_with_step.get("club_complete_step", 0) < 5:
                        clubs_created_count = 0
                
                # Calculate total moderator count across all clubs
                for club in all_clubs:
                    if club.get("club_complete_step", 0) >= 4:
                        try:
                            detailed_moderators = club.get("detailed_moderators", {})
                            if isinstance(detailed_moderators, dict):
                                total_moderators_count += detailed_moderators.get("count", 0)
                            elif isinstance(detailed_moderators, list):
                                total_moderators_count += len(detailed_moderators)
                        except Exception:
                            pass
                
                # Calculate total picks submitted by captain
                total_picks_submitted_count = await club_picks_collection.count_documents({
                    "submitted_by": user_id
                })
                
            except Exception as e:
                logger.error(f"Error getting captain statistics for {user_id}: {e}")
            
            profile_data = CaptainViewProfileResponse(
                first_name=first_name,
                last_name=last_name,
                email=email,
                avatar_url=avatar_url,
                bio=bio,
                role=role,
                signup_date=signup_date,
                total_clubs_created_count=clubs_created_count,
                total_moderators_count=total_moderators_count,
                total_picks_submitted_count=total_picks_submitted_count
            )
            
        elif role == "Moderator" or role == "moderator":
            # Calculate moderator statistics
            total_clubs_moderated_count = 0
            total_picks_submitted_count = 0
            
            try:
                # Count how many clubs this user is a moderator in
                total_clubs_moderated_count = await clubs_collection.count_documents({
                    "detailed_moderators": {"$elemMatch": {"user_id": user_id}},
                    "is_permanently_deleted": {"$ne": True}
                })
                
                # Get total picks submitted by this moderator
                total_picks_submitted_count = await club_picks_collection.count_documents({
                    "submitted_by": user_id
                })
                
            except Exception as e:
                logger.error(f"Error getting moderator statistics for {user_id}: {e}")
            
            profile_data = ModeratorViewProfileResponse(
                first_name=first_name,
                last_name=last_name,
                email=email,
                avatar_url=avatar_url,
                bio=bio,
                role=role,
                signup_date=signup_date,
                total_clubs_moderated_count=total_clubs_moderated_count,
                total_picks_submitted_count=total_picks_submitted_count
            )
            
        else:  # Member or other roles
            # Calculate member statistics
            total_clubs_joined_count = 0
            
            try:
                # Count clubs joined by this member
                # Note: This would need to be implemented based on your club membership structure
                # For now, using a placeholder query
                total_clubs_joined_count = user.get("total_clubs_joined", 0)
                
            except Exception as e:
                logger.error(f"Error getting member statistics for {user_id}: {e}")
            
            profile_data = MemberViewProfileResponse(
                first_name=first_name,
                last_name=last_name,
                email=email,
                avatar_url=avatar_url,
                bio=bio,
                role=role,
                signup_date=signup_date,
                total_clubs_joined_count=total_clubs_joined_count
            )
        
        return ViewProfileResponse(
            success=True,
            message="Profile retrieved successfully",
            data=profile_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving profile for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while retrieving profile"
        )
