from typing import Optional, Tuple, List, Dict
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from .db import (
    get_club_collection,
    get_user_collection,
    get_club_payments_collection,
    get_membership_collection,
)
from .my_clubs_service import MyClubsService
from core.utils.price_config import CurrencyConfig, PriceConfig
from .models import (
    AddModeratorsRequest,
    AddModeratorsResponse,
    DetailedModeratorInfo,
    MyClubsFilters,
    MyClubsSortOption,
    MyClubItem,
    MyClubsResponse,
    ClubStatus,
    MyClubDetailResponse,
)
import logging
import stripe
import os

logger = logging.getLogger(__name__)


class ModeratorsService:
    """Service for adding moderators to existing clubs with payment processing"""

    # Moderator pricing constants
    MODERATOR_PRICE = PriceConfig.ADDITIONAL_MODERATION_AMOUNT
    MODERATOR_CURRENCY = CurrencyConfig.CURRENCY_SYMBOL

    def __init__(self):
        # Initialize MyClubsService for role determination
        self.my_clubs_service = MyClubsService()
        # Initialize Stripe API key
        stripe.api_key = os.getenv(
            "STRIPE_SECRET_KEY",
            "",
        )

    async def add_moderators_to_club(
        self, request: AddModeratorsRequest, captain_id: str
    ) -> Tuple[bool, Optional[AddModeratorsResponse], Optional[str]]:
        """
        Add moderators to an existing club with payment processing

        Args:
            request: Add moderators request
            captain_id: ID of the captain making the request

        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(
                f"Processing add moderators request for club: {request.club_name_based_id}, captain: {captain_id}"
            )

            club_collection = get_club_collection()
            user_collection = get_user_collection()

            # Find the club by name_based_id
            club = await club_collection.find_one(
                {"name_based_id": request.club_name_based_id, "captain_id": captain_id}
            )

            if not club:
                return (
                    False,
                    None,
                    "Club not found or you don't have permission to add moderators",
                )

            logger.info(f"Club found: {club.get('name', 'Unknown')}")

            # Get existing moderators
            existing_moderator_emails = set(club.get("moderator_emails", []))
            existing_detailed_moderators = club.get("detailed_moderators", [])

            # Check for duplicate emails in the request
            duplicate_emails = []
            new_moderator_emails = []

            for email in request.moderator_emails:
                if email in existing_moderator_emails:
                    duplicate_emails.append(email)
                else:
                    new_moderator_emails.append(email)

            if not new_moderator_emails:
                return (
                    False,
                    None,
                    f"All provided moderator emails already exist in the club: {', '.join(duplicate_emails)}",
                )

            # Calculate pricing based on current club moderator count
            moderators_to_add = len(new_moderator_emails)
            current_moderator_count = len(existing_moderator_emails)

            # Calculate expected total amount (backend calculation)
            if current_moderator_count == 0:
                # First moderator is free, rest are paid
                free_moderators_in_request = min(1, moderators_to_add)
                paid_moderators_in_request = max(0, moderators_to_add - 1)
                expected_total = paid_moderators_in_request * self.MODERATOR_PRICE
            else:
                # Club already has moderators, all new ones are paid
                expected_total = moderators_to_add * self.MODERATOR_PRICE

            logger.info(
                f"Backend calculated amount: ${expected_total:.2f} for {moderators_to_add} moderators (club had {current_moderator_count} moderators)"
            )

            logger.info(
                f"Adding {moderators_to_add} new moderators at ${self.MODERATOR_PRICE} each = ${expected_total:.2f}"
            )

            # Process payment if payment_method_id provided
            payment_status = "succeeded"  # Default for free addition
            payment_intent_id = None

            if request.payment_method_id and expected_total > 0:
                try:
                    # Get captain details for Stripe customer
                    try:
                        captain_object_id = ObjectId(captain_id)
                    except Exception as e:
                        return (False, None, f"Invalid captain ID format: {str(e)}")

                    captain_user = await user_collection.find_one(
                        {"_id": captain_object_id}
                    )
                    if not captain_user:
                        return (False, None, "Captain user not found")

                    # Get or create Stripe customer
                    stripe_customer_id = captain_user.get("stripe_customer_id")
                    if not stripe_customer_id:
                        try:
                            customer = stripe.Customer.create(
                                email=captain_user.get("email", ""),
                                name=captain_user.get("full_name", ""),
                                metadata={
                                    "user_id": str(captain_user["_id"]),
                                    "type": "moderator_addition",
                                },
                            )
                            stripe_customer_id = customer.id
                            logger.info(
                                f"✅ Created new Stripe customer: {stripe_customer_id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"❌ Failed to create Stripe customer: {str(e)}"
                            )
                            return (
                                False,
                                None,
                                f"Failed to create Stripe customer: {str(e)}",
                            )
                    else:
                        logger.info(
                            f"✅ Using existing Stripe customer: {stripe_customer_id}"
                        )

                    # Attach payment method to customer
                    try:
                        stripe.PaymentMethod.attach(
                            request.payment_method_id,
                            customer=stripe_customer_id,
                        )
                        logger.info(
                            f"✅ Payment method attached: {request.payment_method_id}"
                        )
                    except Exception as e:
                        logger.error(f"❌ Failed to attach payment method: {str(e)}")
                        return (
                            False,
                            None,
                            f"Invalid payment method: {str(e)}",
                        )

                    # Process payment using PaymentIntent
                    try:
                        payment_intent = stripe.PaymentIntent.create(
                            amount=int(expected_total * 100),
                            currency=CurrencyConfig.DEFAULT_CURRENCY,
                            customer=stripe_customer_id,
                            payment_method=request.payment_method_id,
                            confirm=True,
                            automatic_payment_methods={
                                "enabled": True,
                                "allow_redirects": "never",
                            },
                            metadata={
                                "user_id": str(captain_user["_id"]),
                                "type": "moderator_addition",
                                "club_id": str(club["_id"]),
                                "moderator_count": str(moderators_to_add),
                                "amount": str(expected_total),
                            },
                        )

                        payment_intent_id = payment_intent.id
                        payment_status = payment_intent.status

                        if payment_status != "succeeded":
                            # Send subscription failure notification to captain
                            try:
                                from services.notifications.notification_service import (
                                    send_notification_to_users,
                                    filter_users_by_notification_preference,
                                    get_collections,
                                )
                                
                                # Filter by subscription alerts preference
                                enabled_user_ids = await filter_users_by_notification_preference(
                                    [captain_id],
                                    "subscription_alerts"
                                )
                                
                                push_user_ids: List[str] = []
                                if enabled_user_ids:
                                    collections = get_collections()
                                    user_tokens_collection = collections.get_user_tokens_collection()
                                    token_docs = await user_tokens_collection.find(
                                        {"user_id": captain_id, "is_active": True},
                                        {"user_id": 1},
                                    ).to_list(length=None)
                                    if any(doc.get("user_id") for doc in token_docs):
                                        push_user_ids = [captain_id]
                                
                                title = "Moderator Addition Payment Failed!"
                                body = f"Payment failed for adding moderators to '{club.get('name')}'. Please try again."
                                
                                notification_data = {
                                    "captain_id": captain_id,
                                    "club_id": str(club["_id"]),
                                    "club_name": club.get("name"),
                                    "club_name_based_id": club.get("name_based_id"),
                                    "amount_attempted": expected_total,
                                    "payment_status": payment_status,
                                    "error_message": f"Payment status: {payment_status}",
                                    "action": "moderator_addition_failure"
                                }
                                
                                notification_result = await send_notification_to_users(
                                    user_ids=push_user_ids,
                                    title=title,
                                    body=body,
                                    notification_type="subscription_alerts",
                                    data=notification_data,
                                    click_action=f"club/{club.get('name_based_id')}/moderators",
                                    priority="high",
                                    all_user_ids=[captain_id],
                                )
                                logger.info(
                                    f"✅ Moderator addition failure notification stored for captain {captain_id}: {notification_result}"
                                )
                                    
                            except Exception as e:
                                logger.error(f"⚠️ Failed to send moderator addition failure notification: {e}")
                            
                            return (
                                False,
                                None,
                                f"Payment failed. Status: {payment_status}",
                            )

                        logger.info(
                            f"✅ Payment successful: ${expected_total:.2f} for {moderators_to_add} moderators"
                        )

                    except Exception as e:
                        logger.error(f"❌ Payment processing failed: {str(e)}")
                        
                        # Send subscription failure notification to captain
                        try:
                            from services.notifications.notification_service import (
                                send_notification_to_users,
                                filter_users_by_notification_preference,
                                get_collections,
                            )
                            
                            # Filter by subscription alerts preference
                            enabled_user_ids = await filter_users_by_notification_preference(
                                [captain_id],
                                "subscription_alerts"
                            )
                            
                            push_user_ids: List[str] = []
                            if enabled_user_ids:
                                collections = get_collections()
                                user_tokens_collection = collections.get_user_tokens_collection()
                                token_docs = await user_tokens_collection.find(
                                    {"user_id": captain_id, "is_active": True},
                                    {"user_id": 1},
                                ).to_list(length=None)
                                if any(doc.get("user_id") for doc in token_docs):
                                    push_user_ids = [captain_id]
                            
                            title = "Moderator Addition Payment Failed!"
                            body = f"Payment processing failed for '{club.get('name')}'. Please try again or contact support."
                            
                            notification_data = {
                                "captain_id": captain_id,
                                "club_id": str(club["_id"]),
                                "club_name": club.get("name"),
                                "club_name_based_id": club.get("name_based_id"),
                                "amount_attempted": expected_total,
                                "error_message": str(e),
                                "action": "moderator_addition_failure"
                            }
                            
                            notification_result = await send_notification_to_users(
                                user_ids=push_user_ids,
                                title=title,
                                body=body,
                                notification_type="subscription_alerts",
                                data=notification_data,
                                click_action=f"club/{club.get('name_based_id')}/moderators",
                                priority="high",
                                all_user_ids=[captain_id],
                            )
                            logger.info(f"✅ Moderator addition failure notification stored for captain {captain_id}: {notification_result}")
                                
                        except Exception as notif_error:
                            logger.error(f"⚠️ Failed to send moderator addition failure notification: {notif_error}")
                        
                        return (
                            False,
                            None,
                            f"Payment processing failed: {str(e)}",
                        )

                except Exception as payment_error:
                    logger.error(f"Payment processing failed: {payment_error}")
                    
                    # Send subscription failure notification to captain
                    try:
                        from services.notifications.notification_service import (
                            send_notification_to_users,
                            filter_users_by_notification_preference,
                            get_collections,
                        )
                        
                        # Filter by subscription alerts preference
                        enabled_user_ids = await filter_users_by_notification_preference(
                            [captain_id],
                            "subscription_alerts"
                        )
                        
                        push_user_ids: List[str] = []
                        if enabled_user_ids:
                            collections = get_collections()
                            user_tokens_collection = collections.get_user_tokens_collection()
                            token_docs = await user_tokens_collection.find(
                                {"user_id": captain_id, "is_active": True},
                                {"user_id": 1},
                            ).to_list(length=None)
                            if any(doc.get("user_id") for doc in token_docs):
                                push_user_ids = [captain_id]
                        
                        title = "Moderator Addition Payment Failed!"
                        body = f"Payment failed for adding moderators to '{club.get('name')}'. Please try again or contact support."
                        
                        notification_data = {
                            "captain_id": captain_id,
                            "club_id": str(club["_id"]),
                            "club_name": club.get("name"),
                            "club_name_based_id": club.get("name_based_id"),
                            "amount_attempted": expected_total,
                            "error_message": str(payment_error),
                            "action": "moderator_addition_failure"
                        }
                        
                        notification_result = await send_notification_to_users(
                            user_ids=push_user_ids,
                            title=title,
                            body=body,
                            notification_type="subscription_alerts",
                            data=notification_data,
                            click_action=f"club/{club.get('name_based_id')}/moderators",
                            priority="high",
                            all_user_ids=[captain_id],
                        )
                        logger.info(f"✅ Moderator addition failure notification stored for captain {captain_id}: {notification_result}")
                            
                    except Exception as notif_error:
                        logger.error(f"⚠️ Failed to send moderator addition failure notification: {notif_error}")
                    
                    return (
                        False,
                        None,
                        f"Payment processing failed: {str(payment_error)}",
                    )

            # Process each new moderator
            new_detailed_moderators = []
            validated_moderators = []

            for index, email in enumerate(new_moderator_emails):
                logger.info(f"Processing moderator: {email}")

                # Check if user exists and is eligible (only active users can be moderators)
                user = await user_collection.find_one(
                    {"email": email, "status": "active", "membership_status": "active"}
                )

                if not user:
                    # If not found with active membership, check if user has no membership (regardless of status)
                    user = await user_collection.find_one(
                        {
                            "email": email,
                            "membership_status": {"$in": ["", None]},  # Allow empty or null membership_status
                        }
                    )
                
                if not user:
                    # Check if user exists but has an actual membership status (not empty/null)
                    inactive_user = await user_collection.find_one({"email": email})
                    if inactive_user:
                        membership_status = inactive_user.get('membership_status')
                        
                        # Allow if membership_status is empty, null, or active
                        if membership_status in ["", None, "active"]:
                            user = inactive_user
                        else:
                            # Block if they have a non-active membership status (like "inactive", "suspended", "expired")
                            logger.warning(
                                f"User {email} has membership_status '{membership_status}'. Only users with no membership or active membership can be added as moderators."
                            )
                            return (
                                False,
                                None,
                                f"User {email} is not active.",
                            )
                
                if not user:
                    # User doesn't exist - create external user
                    logger.info(
                        f"User {email} not found. Creating external moderator user..."
                    )
                    user = await self._create_external_moderator_user(email)
                elif user.get("role") == "moderator":
                    # User exists with moderator role - handle both registered and unregistered
                    if user.get("is_register") == False:
                        # User exists as moderator but not registered - reuse existing token
                        logger.info(
                            f"User {email} exists as unregistered moderator. Checking for existing token..."
                        )
                        if user.get("signup_token"):
                            logger.info(f"Reusing existing signup token for {email}")
                        else:
                            # User exists but no token - update with new token
                            logger.info(
                                f"User {email} exists but no token. Creating new token..."
                            )
                            user = await self._update_user_with_signup_token(
                                email, user
                            )
                    else:
                        # User exists as registered moderator - can be assigned to additional clubs
                        logger.info(
                            f"User {email} exists as registered moderator. Assigning to additional club..."
                        )
                else:
                    # User exists with any other role - can be assigned as moderator
                    logger.info(
                        f"User {email} exists with role '{user.get('role')}'. Assigning as moderator..."
                    )

                # Get full name from user data
                full_name = user.get("full_name", user.get("name", ""))
                if not full_name:
                    # For external users without name, use email prefix
                    full_name = user.get("email", "Unknown").split("@")[0].title()

                # Determine moderator type and price based on club's current moderator count
                if current_moderator_count == 0 and index == 0:
                    # First moderator in a club with 0 moderators is free
                    moderator_type = "free"
                    moderator_price = 0.0
                else:
                    # All other moderators are paid
                    moderator_type = "paid"
                    moderator_price = self.MODERATOR_PRICE

                # Create detailed moderator info
                detailed_moderator = DetailedModeratorInfo(
                    email=email,
                    full_name=full_name,
                    user_id=str(user["_id"]),
                    status="active",
                    type_of_moderator=moderator_type,
                    price=moderator_price,
                    invited_at=datetime.now(timezone.utc),
                    responded_at=None,
                    response=None,
                )

                new_detailed_moderators.append(detailed_moderator)

                # Create legacy moderator info for invitations
                validated_moderators.append(
                    {
                        "email": email,
                        "user_id": str(user["_id"]),
                        "name": full_name,
                        "status": "pending",
                        "invited_at": datetime.now(timezone.utc),
                        "responded_at": None,
                        "response": None,
                    }
                )

                logger.info(
                    f"Moderator {email} ({full_name}) - Type: {moderator_type}, Price: ${moderator_price}"
                )

            # Update club with new moderators
            current_moderator_emails = (
                list(existing_moderator_emails) + new_moderator_emails
            )
            current_detailed_moderators = existing_detailed_moderators + [
                mod.model_dump() for mod in new_detailed_moderators
            ]

            # Calculate new totals
            total_moderators = len(current_moderator_emails)

            # Calculate free and paid moderators based on current club state
            existing_free_moderators = club.get("free_moderators", 0)
            existing_paid_moderators = club.get("paid_moderators", 0)

            if current_moderator_count == 0:
                # Club had 0 moderators, so first new moderator is free
                new_free_moderators = min(1, len(new_moderator_emails))
                new_paid_moderators = max(0, len(new_moderator_emails) - 1)
            else:
                # Club already has moderators, all new ones are paid
                new_free_moderators = 0
                new_paid_moderators = len(new_moderator_emails)

            # Update totals
            free_moderators = existing_free_moderators + new_free_moderators
            paid_moderators = existing_paid_moderators + new_paid_moderators

            # Update club
            update_data = {
                "moderator_emails": current_moderator_emails,
                "detailed_moderators": current_detailed_moderators,
                "moderator_count": total_moderators,
                "free_moderators": free_moderators,
                "paid_moderators": paid_moderators,
                "updated_at": datetime.now(timezone.utc),
            }

            # If payment was made, update payment info
            if payment_intent_id:
                update_data["payment_intent_id"] = payment_intent_id
                update_data["payment_status"] = payment_status
                update_data["payment_confirmed_at"] = datetime.now(timezone.utc)

            result = await club_collection.update_one(
                {"_id": club["_id"]}, {"$set": update_data}
            )

            if result.modified_count > 0:
                logger.info(
                    f"Club updated successfully with {moderators_to_add} new moderators"
                )

                # Send invitation emails to new moderators
                try:
                    from .club_step4_service import club_step4_service

                    await club_step4_service._send_moderator_invitations(
                        club, validated_moderators
                    )
                    logger.info(
                        f"✅ Moderator invitation emails sent to {len(validated_moderators)} moderators"
                    )
                except Exception as email_error:
                    logger.warning(
                        f"⚠️ Could not send moderator invitation emails: {email_error}"
                    )
                    # Don't fail the operation if email sending fails

                # Store payment record if payment was made
                if payment_intent_id and expected_total > 0:
                    try:
                        from ..auth.routes.trial_membership import store_payment_record

                        await store_payment_record(
                            user_id=str(captain_user["_id"]),
                            subscription_id=payment_intent_id,
                            price_id="",  # No price_id for one-time payments
                            amount=expected_total,
                            currency=CurrencyConfig.DEFAULT_CURRENCY,
                            status="succeeded",
                            payment_method_id=request.payment_method_id,
                            stripe_customer_id=stripe_customer_id,
                            payment_intent_id=payment_intent_id,
                            start_date=datetime.now(timezone.utc),
                            end_date=None,  # One-time payment, no end date
                            payment_type="moderator_addition",
                            membership_type="paid",
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                        logger.info(f"✅ Payment record stored for moderator addition")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not store payment record: {e}")
                        # Don't fail the operation if payment record storage fails

                # Send subscription success notification to captain
                try:
                    from services.notifications.notification_service import (
                        send_notification_to_users,
                        filter_users_by_notification_preference,
                        get_collections,
                    )
                    
                    # Filter by subscription alerts preference
                    enabled_user_ids = await filter_users_by_notification_preference(
                        [captain_id],
                        "subscription_alerts"
                    )
                    
                    push_user_ids: List[str] = []
                    if enabled_user_ids:
                        collections = get_collections()
                        user_tokens_collection = collections.get_user_tokens_collection()
                        token_docs = await user_tokens_collection.find(
                            {"user_id": captain_id, "is_active": True},
                            {"user_id": 1},
                        ).to_list(length=None)
                        if any(doc.get("user_id") for doc in token_docs):
                            push_user_ids = [captain_id]
                    
                    title = "Moderators Added Successfully!"
                    body = f"Added {moderators_to_add} moderator(s) to '{club.get('name')}' for ${expected_total:.2f}"
                    
                    notification_data = {
                        "captain_id": captain_id,
                        "club_id": str(club["_id"]),
                        "club_name": club.get("name"),
                        "club_name_based_id": club.get("name_based_id"),
                        "payment_intent_id": payment_intent_id,
                        "amount_paid": expected_total,
                        "payment_status": payment_status,
                        "moderators_added": moderators_to_add,
                        "total_moderators": total_moderators,
                        "action": "moderator_addition_success"
                    }
                    
                    notification_result = await send_notification_to_users(
                        user_ids=push_user_ids,
                        title=title,
                        body=body,
                        notification_type="subscription_alerts",
                        data=notification_data,
                        click_action=f"club/{club.get('name_based_id')}/moderators",
                        priority="high",
                        all_user_ids=[captain_id],
                    )
                    logger.info(f"✅ Moderator addition success notification stored for captain {captain_id}: {notification_result}")
                        
                except Exception as e:
                    logger.error(f"⚠️ Failed to send moderator addition success notification: {e}")

                # Build response
                response = AddModeratorsResponse(
                    success=True,
                    message=f"Successfully added {moderators_to_add} moderators to the club",
                    club_id=str(club["_id"]),
                    club_name=club["name"],
                    club_name_based_id=club.get("name_based_id", ""),
                    captain_email=request.captain_email,
                    moderators_added=moderators_to_add,
                    moderators_skipped=len(duplicate_emails),
                    total_moderators=total_moderators,
                    payment_intent_id=payment_intent_id,
                    payment_status=payment_status,
                    total_amount_paid=expected_total,  # Backend calculated amount
                    moderator_details=new_detailed_moderators,
                    added_at=datetime.now(timezone.utc),
                )

                return True, response, None
            else:
                return (False, None, "Failed to update club with new moderators")

        except Exception as e:
            logger.error(f"Error adding moderators to club: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return (False, None, f"Internal server error: {str(e)}")

    async def _create_external_moderator_user(self, email: str) -> dict:
        """Create an external moderator user in the system"""
        try:
            user_collection = get_user_collection()

            # Check if user already exists (in case of duplicate calls)
            existing_user = await user_collection.find_one({"email": email})
            if existing_user:
                logger.info(
                    f"External user {email} already exists, returning existing user"
                )
                return existing_user

            # Generate signup token
            signup_token = self._generate_signup_token(email, "moderator")

            # Create new external user document
            external_user = {
                "email": email,
                "role": "moderator",
                "status": "inactive",  # Inactive until they complete signup
                "membership_status": None,  # Empty/null until they complete signup
                "membership_type": "free",
                "club_count": 0,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "is_external_invite": True,
                "full_name": "",  # Empty until they complete signup
                "name": "",  # Empty until they complete signup
                "invited_as_moderator": True,
                "is_register": False,  # Not registered yet
                "signup_token": signup_token,  # Store the signup token
            }

            # Insert user into database
            result = await user_collection.insert_one(external_user)
            external_user["_id"] = result.inserted_id

            logger.info(
                f"Created external moderator user: {email} with ID: {result.inserted_id}"
            )
            return external_user

        except Exception as e:
            logger.error(f"Error creating external moderator user {email}: {e}")
            raise ValueError(f"Failed to create external moderator user: {str(e)}")

    async def _update_user_with_signup_token(
        self, email: str, existing_user: dict
    ) -> dict:
        """Update existing user with new signup token"""
        try:
            user_collection = get_user_collection()

            # Generate new signup token
            signup_token = self._generate_signup_token(email, "moderator")

            # Update user with new token
            result = await user_collection.update_one(
                {"_id": existing_user["_id"]},
                {
                    "$set": {
                        "signup_token": signup_token,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            if result.modified_count > 0:
                # Update the existing_user dict with new token
                existing_user["signup_token"] = signup_token
                logger.info(f"Updated user {email} with new signup token")
                return existing_user
            else:
                logger.warning(f"No changes made when updating token for user {email}")
                return existing_user

        except Exception as e:
            logger.error(f"Error updating user {email} with signup token: {e}")
            raise ValueError(f"Failed to update user with signup token: {str(e)}")

    def _generate_signup_token(self, email: str, role: str = "moderator") -> str:
        """Generate a proper JWT signup token for external users using centralized JWT handler"""
        from core.auth.jwt_handler import get_jwt_handler

        jwt_handler = get_jwt_handler()

        # Use proper JWT token for moderator signup
        token = jwt_handler.create_moderator_signup_token(email, role)

        logger.info(f"Generated JWT signup token for {email} with 7-day expiration")
        return token

    async def get_moderator_clubs(
        self,
        moderator_id: str,
        filters: Optional[MyClubsFilters] = None,
        sort_by: MyClubsSortOption = MyClubsSortOption.NEWEST,
        page: int = 1,
        page_size: int = 20,
    ) -> Optional[MyClubsResponse]:
        """Get moderator's clubs with search, filtering, and pagination"""
        try:
            club_collection = get_club_collection()
            payments_collection = get_club_payments_collection()
            membership_collection = get_membership_collection()

            # Find clubs where the moderator is assigned
            # Check both moderator_emails array and detailed_moderators array
            base_query = {
                "$or": [
                    {"moderator_emails": {"$in": [moderator_id]}},  # Legacy format
                    {"detailed_moderators.user_id": moderator_id},  # New format
                    {
                        "detailed_moderators.email": moderator_id
                    },  # Fallback for email-based lookup
                ],
                "club_complete_step": 5,  # Only completed clubs
            }

            # Apply filters
            if filters:
                logger.info(f"Applying filters to moderator's clubs: {filters}")
                if filters.search:
                    # Validate search term
                    search_term = filters.search.strip()
                    if len(search_term) >= 2:  # Minimum 2 characters for search
                        # Search by club name, description, or captain name
                        search_query = {
                            "$or": [
                                {"name": {"$regex": search_term, "$options": "i"}},
                                {
                                    "description": {
                                        "$regex": search_term,
                                        "$options": "i",
                                    }
                                },
                                {
                                    "captain_details.full_name": {
                                        "$regex": search_term,
                                        "$options": "i",
                                    }
                                },
                            ]
                        }
                        base_query = {"$and": [base_query, search_query]}

                if filters.status:
                    base_query["status"] = filters.status.value

                # Note: member_status filtering is handled after processing clubs
                # since it requires checking the moderator's status in each club

            # Get total count for pagination
            total_count = await club_collection.count_documents(base_query)

            if total_count == 0:
                return MyClubsResponse(
                    clubs=[],
                    total_count=0,
                    page=page,
                    page_size=page_size,
                    total_pages=0,
                    has_next=False,
                    has_previous=False,
                )

            # Calculate pagination
            skip = (page - 1) * page_size
            total_pages = (total_count + page_size - 1) // page_size

            # Build sort criteria
            sort_criteria = []
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                # For most members sorting, we'll sort by created_at first, then sort by actual member count after processing
                sort_criteria = [("created_at", -1)]
            elif sort_by == MyClubsSortOption.NEWEST:
                sort_criteria = [("created_at", -1)]
            elif sort_by == MyClubsSortOption.OLDEST:
                sort_criteria = [("created_at", 1)]
            else:
                sort_criteria = [("created_at", -1)]  # Default to newest

            # Get clubs with pagination
            clubs_cursor = (
                club_collection.find(base_query)
                .sort(sort_criteria)
                .skip(skip)
                .limit(page_size)
            )
            clubs = await clubs_cursor.to_list(length=None)

            # Process clubs
            processed_clubs = []
            for club in clubs:
                club_id = str(club["_id"])
                moderator_status_info = self._get_moderator_status_info(
                    club, moderator_id
                )
                club_item = await self._process_club_item(
                    club,
                    payments_collection,
                    membership_collection,
                    moderator_status_info,
                )
                if club_item:
                    processed_clubs.append(club_item)

            # Apply member_status filtering if specified
            if filters and filters.member_status:
                logger.info(
                    f"Filtering clubs by member_status: {filters.member_status}"
                )
                filtered_clubs = []
                for club in processed_clubs:
                    if club.member_combined_status == filters.member_status:
                        filtered_clubs.append(club)
                processed_clubs = filtered_clubs
                # Update total_count after filtering
                total_count = len(processed_clubs)
                total_pages = (total_count + page_size - 1) // page_size
                logger.info(
                    f"Filtered to {len(processed_clubs)} clubs with member_status: {filters.member_status}"
                )

            # Apply post-processing sorting for most_members option
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                logger.info("Applying post-processing sort by most members")
                processed_clubs.sort(key=lambda x: x.total_members, reverse=True)
                logger.info(
                    f"Sorted clubs by member count: {[(c.club_name, c.total_members) for c in processed_clubs]}"
                )

            # Calculate pagination flags
            has_next = page < total_pages
            has_previous = page > 1

            logger.info(
                f"Retrieved {len(processed_clubs)} clubs for moderator {moderator_id}"
            )

            return MyClubsResponse(
                clubs=processed_clubs,
                total_count=total_count,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
            )

        except Exception as e:
            logger.error(f"Error getting moderator's clubs: {e}")
            return None

    def _get_moderator_status_info(
        self, club: Dict, moderator_id: str
    ) -> Optional[Dict]:
        """Get moderator's status information for a specific club"""
        try:
            # Check detailed_moderators array first
            detailed_moderators = club.get("detailed_moderators", [])
            for moderator in detailed_moderators:
                if (
                    moderator.get("user_id") == moderator_id
                    or moderator.get("email") == moderator_id
                ):
                    return {
                        "status": moderator.get("status", "active"),
                        "membership_status": moderator.get(
                            "status", "active"
                        ),  # For moderators, status and membership_status are the same
                    }

            # Fallback: check if moderator is in moderator_emails array
            moderator_emails = club.get("moderator_emails", [])
            if moderator_id in moderator_emails:
                return {"status": "active", "membership_status": "active"}

            return None

        except Exception as e:
            logger.error(f"Error getting moderator status info: {e}")
            return None

    async def _process_club_item(
        self,
        club: Dict,
        payments_collection,
        membership_collection,
        moderator_status_info: Optional[Dict] = None,
    ) -> Optional[MyClubItem]:
        """Process a club document into MyClubItem with additional data"""
        try:
            club_id = str(club["_id"])

            # Debug: Log all available fields in the club document
            logger.info(f"Club document fields for {club_id}: {list(club.keys())}")
            logger.info(f"Full club document for {club_id}: {club}")

            # Get pricing information (priority: monthly > yearly > quarterly)
            raw_pricing_plans = club.get("pricing_plans", [])
            logger.info(f"Raw pricing plans for club {club_id}: {raw_pricing_plans}")

            pricing = self._get_priority_pricing(raw_pricing_plans)
            logger.info(f"Priority pricing for club {club_id}: {pricing}")

            # Get full pricing plans
            pricing_plans = raw_pricing_plans

            # Get total members count
            total_members = await self._get_club_member_count(
                club_id, membership_collection
            )

            # Get monthly revenue
            monthly_revenue = await self._get_club_monthly_revenue(
                club_id, payments_collection
            )

            # Calculate combined moderator status if moderator status info is provided
            moderator_combined_status = None
            if moderator_status_info:
                moderator_status = moderator_status_info.get("status")
                membership_status = moderator_status_info.get("membership_status")

                # Combined status logic: active only if both are active, inactive otherwise
                if moderator_status == "active" and membership_status == "active":
                    moderator_combined_status = "active"
                else:
                    moderator_combined_status = "inactive"

            # Create MyClubItem
            club_item = MyClubItem(
                club_id=club_id,
                club_name=club.get("name", ""),
                name_based_id=club.get("name_based_id", ""),
                created_at=club.get("created_at", datetime.now(timezone.utc)),
                status=club.get("status", ClubStatus.PENDING),
                pricing=pricing,
                pricing_plans=pricing_plans,
                total_members=total_members,
                monthly_revenue=monthly_revenue,
                logo_url=club.get("logo_url"),
                # Add moderator status information if provided
                member_status=(
                    moderator_status_info.get("status")
                    if moderator_status_info
                    else None
                ),
                membership_status=(
                    moderator_status_info.get("membership_status")
                    if moderator_status_info
                    else None
                ),
                member_combined_status=moderator_combined_status,
            )

            return club_item

        except Exception as e:
            logger.error(f"Error processing club item: {e}")
            return None

    def _get_priority_pricing(self, pricing_plans: List[Dict]) -> Optional[Dict]:
        """Get priority pricing plan (monthly > yearly > quarterly) with full details"""
        if not pricing_plans:
            logger.info("No pricing plans found")
            return None

        logger.info(f"Processing pricing plans: {pricing_plans}")

        # Sort by priority: monthly (1), yearly (2), quarterly (3)
        priority_map = {"monthly": 1, "yearly": 2, "quarterly": 3}

        # Find the plan with highest priority (lowest number)
        highest_priority_plan = None
        highest_priority = float("inf")

        for i, plan in enumerate(pricing_plans):
            logger.info(f"Processing plan {i}: {plan}")
            # Check both 'plan' and 'frequency' fields for compatibility
            plan_type = plan.get("plan") or plan.get("frequency")
            logger.info(f"Plan type extracted: {plan_type}")

            if plan_type and plan_type.lower() in priority_map:
                priority = priority_map[plan_type.lower()]
                logger.info(f"Priority for {plan_type}: {priority}")
                if priority < highest_priority:
                    highest_priority = priority
                    highest_priority_plan = plan
                    logger.info(f"New highest priority plan: {plan}")
            else:
                logger.info(f"Plan type {plan_type} not found in priority map")

        logger.info(f"Final highest priority plan: {highest_priority_plan}")
        return highest_priority_plan

    async def _get_club_member_count(self, club_id: str, membership_collection) -> int:
        """Get total member count for a club"""
        try:
            # First try to get the count from the club document itself
            club_collection = get_club_collection()
            club = await club_collection.find_one({"_id": ObjectId(club_id)})

            if club:
                # Use total_members if available, otherwise sum member_count + paid_member_count
                if "total_members" in club:
                    member_count = club.get("total_members", 0)
                    logger.info(
                        f"Using total_members from club document: {member_count}"
                    )
                else:
                    member_count = club.get("member_count", 0) + club.get(
                        "paid_member_count", 0
                    )
                    logger.info(
                        f"Calculated member count from club document: member_count={club.get('member_count', 0)} + paid_member_count={club.get('paid_member_count', 0)} = {member_count}"
                    )

                return member_count
            else:
                # Fallback: Count active memberships for this club
                logger.warning(
                    f"Club {club_id} not found, falling back to membership collection count"
                )
                member_count = await membership_collection.count_documents(
                    {
                        "club_id": club_id,
                        "subscription_status": {
                            "$in": ["active", "trial", "paid", "subscribed"]
                        },
                    }
                )
                return member_count

        except Exception as e:
            logger.error(f"Error getting club member count: {e}")
            return 0

    async def _get_club_monthly_revenue(
        self, club_id: str, payments_collection
    ) -> float:
        """Get monthly revenue for a club"""
        try:
            # Calculate date range for current month
            now = datetime.now(timezone.utc)
            start_of_month = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )

            # Get payments for current month
            monthly_payments = await payments_collection.find(
                {
                    "club_id": club_id,
                    "status": "succeeded",
                    "created_at": {"$gte": start_of_month},
                }
            ).to_list(length=None)

            # Calculate total monthly revenue
            monthly_revenue = sum(
                payment.get("amount", 0.0) for payment in monthly_payments
            )

            return round(monthly_revenue, 2)

        except Exception as e:
            logger.error(f"Error getting club monthly revenue: {e}")
            return 0.0

    async def get_moderator_club_detail(
        self, moderator_id: str, club_name_based_id: str
    ) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Get detailed information about a specific club for a moderator

        Args:
            moderator_id: Moderator's user ID
            club_name_based_id: Club's name-based ID

        Returns:
            Tuple[bool, Optional[dict], Optional[str]]: (success, club_detail_data, error_message)
        """
        try:
            logger.info(
                f"Getting club detail for moderator {moderator_id}, club {club_name_based_id}"
            )

            # First, verify that the moderator has access to this club
            user_collection = get_user_collection()

            # Validate ObjectId format
            try:
                moderator_object_id = ObjectId(moderator_id)
            except Exception as e:
                return False, None, f"Invalid moderator ID format: {str(e)}"

            user = await user_collection.find_one({"_id": moderator_object_id})

            if not user:
                return False, None, "User not found"

            # Get club details
            club_collection = get_club_collection()
            club = await club_collection.find_one({"name_based_id": club_name_based_id})

            if not club:
                return False, None, "Club not found"

            # Check if moderator is assigned to this club
            moderator_emails = club.get("moderator_emails", [])
            detailed_moderators = club.get("detailed_moderators", [])

            # Check if moderator is in the club (by user_id or email)
            moderator_assigned = False
            moderator_status_info = None

            # Check detailed_moderators array first
            for moderator in detailed_moderators:
                if (
                    moderator.get("user_id") == moderator_id
                    or moderator.get("email") == moderator_id
                ):
                    moderator_assigned = True
                    moderator_status_info = {
                        "status": moderator.get("status", "active"),
                        "membership_status": moderator.get("status", "active"),
                    }
                    break

            # Fallback: check moderator_emails array
            if not moderator_assigned and moderator_id in moderator_emails:
                moderator_assigned = True
                moderator_status_info = {
                    "status": "active",
                    "membership_status": "active",
                }

            if not moderator_assigned:
                return False, None, "You don't have access to this club as a moderator"

            # Skip hub content details for moderator API

            # Build moderator details (exclude the current moderator)
            moderator_details = []
            for moderator in detailed_moderators:
                if (
                    moderator.get("user_id") != moderator_id
                    and moderator.get("email") != moderator_id
                ):
                    moderator_details.append(
                        {
                            "email": moderator.get("email", ""),
                            "full_name": moderator.get("full_name"),
                        }
                    )

            # Also add moderators from legacy moderator_emails array
            for email in moderator_emails:
                if email != moderator_id:
                    # Check if already added from detailed_moderators
                    already_added = any(
                        mod.get("email") == email for mod in moderator_details
                    )
                    if not already_added:
                        moderator_details.append({"email": email, "full_name": None})

            # Build captain details
            captain_details = club.get("captain_details", {})
            captain_info = {
                "captain_id": club.get("captain_id", ""),
                "captain_name": captain_details.get("full_name", "Unknown Captain"),
                "captain_name_based_id": captain_details.get("name_based_id"),
            }

            # Hub content is not included for moderator API

            # Process top_3_sports to handle both string and object formats
            top_3_sports = club.get("top_3_sports", [])
            processed_sports = []
            for sport in top_3_sports:
                if isinstance(sport, dict):
                    # Handle object format: {"name": "Football", "icon": "string"}
                    processed_sports.append(
                        {"name": sport.get("name", ""), "icon": sport.get("icon")}
                    )
                elif isinstance(sport, str):
                    # Handle string format: "Football"
                    processed_sports.append({"name": sport, "icon": None})

            # Get moderator's join date (from detailed_moderators)
            moderator_join_date = None
            for moderator in detailed_moderators:
                if (
                    moderator.get("user_id") == moderator_id
                    or moderator.get("email") == moderator_id
                ):
                    moderator_join_date = moderator.get("invited_at")
                    break

            # Get club rejection information
            rejection_type = club.get("rejection_type")
            rejection_reason = club.get("rejection_reason")
            rejected_by = club.get("rejected_by")
            is_resubmit = club.get("is_resubmit")
            is_club_reject_temporary = club.get("is_club_reject_temporary")
            is_club_reject_permanently = club.get("is_club_reject_permanently")
            
            # Determine user's role in this club using centralized function
            user_role = await self.my_clubs_service._determine_user_role_in_club(moderator_id, str(club["_id"]))
            logger.info(f"User {moderator_id} has role '{user_role}' in club {club_name_based_id}")

            # Calculate betting statistics from club_picks table
            betting_stats = {"total_bets": 0, "win_pct": 0.0}
            try:
                from .db import get_database, HubDatabase
                from .hub_service import HubService
                
                database = await get_database()
                hub_db = HubDatabase(database)
                hub_service = HubService(hub_db)
                
                # Get captain_id from club
                captain_id = club.get("captain_id", "")
                if captain_id:
                    betting_stats = await hub_service._calculate_club_betting_stats(
                        club_id=str(club["_id"]),
                        captain_id=captain_id
                    )
                    logger.info(f"Calculated betting stats for club {club_name_based_id}: {betting_stats}")
            except Exception as betting_error:
                logger.warning(f"Could not calculate betting stats: {betting_error}")
                # Use defaults if calculation fails

            # Build response data
            club_detail = {
                "club_id": str(club["_id"]),
                "logo_url": club.get("logo_url"),
                "club_name": club.get("name", ""),
                "name_based_id": club.get("name_based_id", ""),
                "created_at": club.get("created_at"),
                "status": club.get("status", "pending"),
                "description": club.get("description", ""),
                "sub_description": club.get("sub_description"),
                "member_join_date": moderator_join_date,  # Moderator's join date
                "member_end_date": None,  # Moderators don't have end dates
                "moderator_details": moderator_details,
                "top_3_sports": processed_sports,
                "member_count": club.get("total_members", 0),
                "total_bets": betting_stats.get("total_bets", 0),
                "win_pct": betting_stats.get("win_pct", 0.0),
                "captain_details": captain_info,
                # Trial club statistics (not applicable for moderators, but included for consistency)
                "clubs_joined_count": 0,
                "clubs_remaining": 0,
                "max_clubs": 0,
                # Club rejection information
                "rejection_type": rejection_type,
                "rejection_reason": rejection_reason,
                "rejected_by": rejected_by,
                "is_resubmit": is_resubmit,
                "is_club_reject_temporary": is_club_reject_temporary,
                "is_club_reject_permanently": is_club_reject_permanently,
                # User role
                "user_role": user_role,
            }

            logger.info(
                f"Successfully retrieved club detail for moderator {moderator_id}, club {club_name_based_id}"
            )
            return True, club_detail, None

        except Exception as e:
            logger.error(f"Error getting moderator club detail: {e}")
            import traceback

            traceback.print_exc()
            return False, None, f"Internal server error: {str(e)}"


# Create service instance
moderators_service = ModeratorsService()
