from typing import Optional, Tuple
from datetime import datetime, timezone
from bson import ObjectId
import stripe
from .db import get_club_collection, get_club_payments_collection
from .models import (
    ClubConfirmationFreeRequest,
    ClubConfirmationFreeResponse,
    ClubConfirmationPaidRequest,
    ClubConfirmationPaidResponse,
    ClubStatus,
)
from .id_utils import is_valid_name_based_id
from .stripe_service import StripeService
import logging

logger = logging.getLogger(__name__)


class ClubConfirmationService:
    """Service for handling club creation confirmation"""

    async def confirm_club_free(
        self, request: ClubConfirmationFreeRequest, captain_id: str
    ) -> Tuple[bool, Optional[ClubConfirmationFreeResponse], Optional[str]]:
        """
        Confirm club creation for free (no additional moderators payment required)

        Args:
            request: Club confirmation request
            captain_id: ID of the captain making the request

        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(
                f"Processing free club confirmation for club_id: {request.club_id}, captain_id: {captain_id}"
            )
            club_collection = get_club_collection()

            # Find the club
            club = await self._find_club_by_id(request.club_id, captain_id)
            if not club:
                return (
                    False,
                    None,
                    "Club not found or you don't have permission to confirm it",
                )

            # Allow clubs at step 3 or higher to be confirmed (skip step 4 if needed)
            current_step = club.get("club_complete_step", 0)
            if current_step < 3:
                return (
                    False,
                    None,
                    f"Club must complete at least step 3 before confirmation (current step: {current_step})",
                )

            logger.info(
                f"Club is at step {current_step}, allowing confirmation (will skip to step 5)"
            )

            # Log if we're skipping step 4
            if current_step == 3:
                logger.info(
                    f"⚠️ Skipping step 4 (moderator setup) for club {request.club_id} - going directly from step 3 to step 5"
                )

            # Verify there are no paid moderators (for free confirmation)
            paid_moderators = club.get("paid_moderators", 0)
            if paid_moderators > 0:
                total_price = club.get("total_additional_moderator_pricing", 0)
                return (
                    False,
                    None,
                    f"Club has {paid_moderators} paid moderators (${total_price}). Use paid confirmation endpoint instead.",
                )

            # Check if already confirmed
            if club.get("status") == "approved":
                return False, None, "Club is already confirmed and approved"

            # Check if this is the first time the club is reaching step 5
            current_step = club.get("club_complete_step", 0)
            is_first_completion = current_step < 5

            # Update club status to approved and set club_complete_step = 5
            confirmation_time = datetime.now(timezone.utc)
            result = await club_collection.update_one(
                {"_id": club["_id"]},
                {
                    "$set": {
                        "status": "pending",
                        "confirmed_at": confirmation_time,
                        "confirmation_type": "free",
                        "club_complete_step": 5,  # Mark club as fully completed
                        "updated_at": confirmation_time,
                    }
                },
            )

            if result.modified_count > 0:
                logger.info(f"Club {club.get('name')} confirmed successfully (free)")

                # Build response
                response = ClubConfirmationFreeResponse(
                    club_id=str(club["_id"]),
                    club_name=club["name"],
                    name_based_id=club.get("name_based_id", ""),
                    status=ClubStatus.PENDING,
                    confirmation_type="free",
                    moderator_count=club.get("moderator_count", 0),
                    free_moderators=club.get("free_moderators", 0),
                    paid_moderators=club.get("paid_moderators", 0),
                    total_additional_moderator_pricing=club.get(
                        "total_additional_moderator_pricing", 0.0
                    ),
                    confirmed_at=confirmation_time,
                    club_complete_step=5,
                )

                # Update captain's club count only if this is the first time reaching step 5
                try:
                    from .db import update_captain_club_count

                    if is_first_completion:
                        await update_captain_club_count(captain_id, increment=True)
                        logger.info(
                            f"✅ Set club count to 1 for captain {captain_id} after free confirmation (first completion)"
                        )
                    else:
                        logger.info(
                            f"ℹ️ Club already completed before, keeping club count unchanged for captain {captain_id}"
                        )
                except Exception as count_error:
                    logger.warning(
                        f"⚠️ Could not update club count for captain {captain_id}: {count_error}"
                    )
                    # Don't fail the confirmation if count update fails

                # Send email notification to captain about club completion
                try:
                    from .utils.email_utils import send_email_to_members

                    captain_email = club.get("captain_details", {}).get("email")
                    if captain_email:
                        subject = "🎉 Your Club is Ready for Members!"
                        message = f"""
                        <h2>Congratulations! Your Club is Now Live</h2>
                        <p>Dear {club.get('captain_details', {}).get('full_name', 'Captain')},</p>
                        <p>Great news! Your club <strong>"{club.get('name')}"</strong> has been successfully set up and is now ready to accept members.</p>
                        
                        <h3>Club Details:</h3>
                        <ul>
                            <li><strong>Club Name:</strong> {club.get('name')}</li>
                            <li><strong>Club ID:</strong> {club.get('name_based_id')}</li>
                            <li><strong>Status:</strong> Ready for members</li>
                            <li><strong>Completion Date:</strong> {confirmation_time.strftime('%B %d, %Y at %I:%M %p UTC')}</li>
                        </ul>
                        
                        <p>Your club is now live and members can start joining! You can manage your club, invite moderators, and start building your community.</p>
                        
                        <p>Thank you for using our platform!</p>
                        <p><strong>The Betting App Team</strong></p>
                        """

                        email_sent = await send_email_to_members(
                            captain_email, subject, message
                        )
                        if email_sent:
                            logger.info(
                                f"✅ Club completion email sent to captain {captain_email}"
                            )
                        else:
                            logger.warning(
                                f"⚠️ Failed to send club completion email to captain {captain_email}"
                            )
                    else:
                        logger.warning(
                            f"⚠️ Captain email not found for club {club.get('name')}"
                        )
                except Exception as email_error:
                    logger.warning(
                        f"⚠️ Could not send club completion email: {email_error}"
                    )
                    # Don't fail the confirmation if email fails

                # Send moderator invitation emails after successful club confirmation
                try:
                    await self._send_moderator_invitations_after_confirmation(club)
                except Exception as email_error:
                    logger.warning(
                        f"⚠️ Could not send moderator invitation emails: {email_error}"
                    )
                    # Don't fail the confirmation if email sending fails

                # Send email notification to all admins for club approval
                try:
                    await self._send_club_approval_email(club, captain_id)
                except Exception as email_error:
                    logger.warning(
                        f"⚠️ Could not send club approval email: {email_error}"
                    )
                    # Don't fail the confirmation if email sending fails

                return True, response, None
            else:
                return False, None, "Failed to update club confirmation status"

        except Exception as e:
            logger.error(f"Error in free club confirmation: {e}")
            return False, None, f"Internal server error: {str(e)}"

    async def confirm_club_paid_with_card(
        self,
        request: ClubConfirmationPaidRequest,
        captain_id: str,
        card_number: str = "4242424242424242",
        exp_month: int = 12,
        exp_year: int = 2025,
        cvc: str = "123",
    ) -> Tuple[bool, Optional[ClubConfirmationPaidResponse], Optional[str]]:
        """
        Confirm club creation with payment using card details directly

        Args:
            request: Paid club confirmation request with payment details
            captain_id: ID of the captain making the request
            card_number: Card number (defaults to Stripe test card)
            exp_month: Card expiration month
            exp_year: Card expiration year
            cvc: Card CVC

        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(
                f"Processing club confirmation with card for club_id: {request.club_id}, captain_id: {captain_id}"
            )
            club_collection = get_club_collection()

            # Find the club
            club = await self._find_club_by_id(request.club_id, captain_id)
            if not club:
                return (
                    False,
                    None,
                    "Club not found or you don't have permission to confirm it",
                )

            # Allow clubs at step 3 or higher to be confirmed (skip step 4 if needed)
            current_step = club.get("club_complete_step", 0)
            if current_step < 3:
                return (
                    False,
                    None,
                    f"Club must complete at least step 3 before confirmation (current step: {current_step})",
                )

            logger.info(
                f"Club is at step {current_step}, allowing card confirmation (will skip to step 5)"
            )

            # Log if we're skipping step 4
            if current_step == 3:
                logger.info(
                    f"⚠️ Skipping step 4 (moderator setup) for club {request.club_id} - going directly from step 3 to step 5"
                )

            # Allow paid confirmation even with only free moderators if price and payment method are provided
            paid_moderators = club.get("paid_moderators", 0)
            free_moderators = club.get("free_moderators", 0)
            total_moderators = club.get("moderator_count", 0)

            logger.info(
                f"Club moderator info: total={total_moderators}, free={free_moderators}, paid={paid_moderators}"
            )

            # If no paid moderators but price and payment method provided, allow the payment
            if paid_moderators == 0:
                logger.info(
                    f"Club has no paid moderators but allowing card confirmation with provided price: ${request.price}"
                )
                logger.info(
                    f"Payment will be processed for club with {free_moderators} free moderators"
                )

            # Check if already confirmed
            if club.get("status") == "approved":
                return False, None, "Club is already confirmed and approved"

            # Calculate correct price based on backend logic
            calculated_price = await self._calculate_correct_price(captain_id, club)
            logger.info(
                f"Backend calculated price: ${calculated_price}, Frontend sent price: ${request.price}"
            )

            # Validate that frontend price matches backend calculated price
            if abs(calculated_price - request.price) > 0.01:  # Allow small floating point differences
                return (
                    False,
                    None,
                    f"Price mismatch. Expected: ${calculated_price:.2f}, Received: ${request.price:.2f}. Please refresh and try again."
                )

            logger.info("✅ Price validation passed - frontend and backend prices match")

            # Create payment intent with Stripe using card details
            try:
                logger.info(
                    f"Creating Stripe payment intent with card for ${request.price}"
                )

                # Convert price to cents for Stripe
                amount_cents = int(request.price * 100)

                payment_intent = await StripeService.create_payment_intent_from_card(
                    amount=amount_cents,
                    currency="usd",
                    card_number=card_number,
                    exp_month=exp_month,
                    exp_year=exp_year,
                    cvc=cvc,
                    customer_email=request.email,
                    metadata={
                        "club_id": str(club["_id"]),
                        "club_name": club["name"],
                        "captain_id": captain_id,
                        "moderator_count": str(club.get("moderator_count", 0)),
                        "paid_moderators": str(paid_moderators),
                        "confirmation_type": "paid_moderators",
                    },
                    confirm=True,  # Automatically confirm the payment
                )

                if not payment_intent:
                    return False, None, "Failed to create payment intent with Stripe"

                payment_intent_id = payment_intent.get("id")
                payment_status = payment_intent.get("status", "unknown")

                logger.info(
                    f"Payment intent created: {payment_intent_id}, status: {payment_status}"
                )

                # Check if this is the first time the club is reaching step 5
                current_step = club.get("club_complete_step", 0)
                is_first_completion = current_step < 5

                # Update club with payment information
                confirmation_time = datetime.now(timezone.utc)
                update_data = {
                    "payment_intent_id": payment_intent_id,
                    "payment_status": payment_status,
                    "confirmation_type": "paid",
                    "payment_confirmed_at": (
                        confirmation_time if payment_status == "succeeded" else None
                    ),
                    "updated_at": confirmation_time,
                }

                # If payment succeeded immediately, also set status to approved and club_complete_step = 5
                if payment_status == "succeeded":
                    update_data["status"] = "pending"
                    update_data["confirmed_at"] = confirmation_time
                    update_data["club_complete_step"] = (
                        5  # Mark club as fully completed
                    )

                result = await club_collection.update_one(
                    {"_id": club["_id"]}, {"$set": update_data}
                )

                if result.modified_count > 0:
                    logger.info(
                        f"Club {club.get('name')} payment processed successfully with card"
                    )

                    # Update captain's club count only if this is the first time reaching step 5
                    if payment_status == "succeeded":
                        try:
                            from .db import update_captain_club_count

                            if is_first_completion:
                                await update_captain_club_count(
                                    captain_id, increment=True
                                )
                                logger.info(
                                    f"✅ Set club count to 1 for captain {captain_id} after card payment confirmation (first completion)"
                                )
                            else:
                                logger.info(
                                    f"ℹ️ Club already completed before, keeping club count unchanged for captain {captain_id}"
                                )
                        except Exception as count_error:
                            logger.warning(
                                f"⚠️ Could not update club count for captain {captain_id}: {count_error}"
                            )
                            # Don't fail the confirmation if count update fails

                        # Send email notification to captain about club completion
                        try:
                            from .utils.email_utils import send_email_to_members

                            captain_email = club.get("captain_details", {}).get("email")
                            if captain_email:
                                subject = "🎉 Your Club is Ready for Members!"
                                message = f"""
                                <h2>Congratulations! Your Club is Now Live</h2>
                                <p>Dear {club.get('captain_details', {}).get('full_name', 'Captain')},</p>
                                <p>Great news! Your club <strong>"{club.get('name')}"</strong> has been successfully set up and is now ready to accept members.</p>
                                
                                <h3>Club Details:</h3>
                                <ul>
                                    <li><strong>Club Name:</strong> {club.get('name')}</li>
                                    <li><strong>Club ID:</strong> {club.get('name_based_id')}</li>
                                    <li><strong>Status:</strong> Ready for members</li>
                                    <li><strong>Payment Status:</strong> {payment_status.title()}</li>
                                    <li><strong>Completion Date:</strong> {confirmation_time.strftime('%B %d, %Y at %I:%M %p UTC')}</li>
                                </ul>
                                
                                <p>Your club is now live and members can start joining! You can manage your club, invite moderators, and start building your community.</p>
                                
                                <p>Thank you for using our platform!</p>
                                <p><strong>The Betting App Team</strong></p>
                                """

                                email_sent = await send_email_to_members(
                                    captain_email, subject, message
                                )
                                if email_sent:
                                    logger.info(
                                        f"✅ Club completion email sent to captain {captain_email}"
                                    )
                                else:
                                    logger.warning(
                                        f"⚠️ Failed to send club completion email to captain {captain_email}"
                                    )
                            else:
                                logger.warning(
                                    f"⚠️ Captain email not found for club {club.get('name')}"
                                )
                        except Exception as email_error:
                            logger.warning(
                                f"⚠️ Could not send club completion email: {email_error}"
                            )
                            # Don't fail the confirmation if email fails

                    # Build response
                    final_status = (
                        ClubStatus.PENDING
                        if payment_status == "succeeded"
                        else ClubStatus.PENDING
                    )
                    response = ClubConfirmationPaidResponse(
                        club_id=str(club["_id"]),
                        club_name=club["name"],
                        name_based_id=club.get("name_based_id", ""),
                        status=final_status,
                        confirmation_type="paid",
                        moderator_count=club.get("moderator_count", 0),
                        free_moderators=club.get("free_moderators", 0),
                        paid_moderators=paid_moderators,
                        total_additional_moderator_pricing=calculated_price,
                        payment_intent_id=payment_intent_id,
                        payment_status=payment_status,
                        confirmed_at=(
                            confirmation_time if payment_status == "succeeded" else None
                        ),
                        club_complete_step=5,
                    )

                    return True, response, None
                else:
                    return False, None, "Failed to update club with payment information"

            except Exception as stripe_error:
                logger.error(f"Stripe payment error: {stripe_error}")

                # Provide more helpful error messages
                error_message = str(stripe_error)
                if "Card error" in error_message:
                    return (
                        False,
                        None,
                        f"Card payment failed. Please check your card details and try again. Error: {error_message}",
                    )
                elif "Invalid request" in error_message:
                    return (
                        False,
                        None,
                        f"Invalid payment request. Please check your card details. Error: {error_message}",
                    )
                else:
                    return False, None, f"Payment processing failed: {error_message}"

        except Exception as e:
            logger.error(f"Error in club confirmation with card: {e}")
            return False, None, f"Internal server error: {str(e)}"

    async def confirm_club_paid(
        self, request: ClubConfirmationPaidRequest, captain_id: str
    ) -> Tuple[bool, Optional[ClubConfirmationPaidResponse], Optional[str]]:
        """
        Confirm club creation with payment for additional moderators

        Args:
            request: Paid club confirmation request with payment details
            captain_id: ID of the captain making the request

        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(
                f"Processing paid club confirmation for club_id: {request.club_id}, captain_id: {captain_id}"
            )
            club_collection = get_club_collection()

            # Find the club
            club = await self._find_club_by_id(request.club_id, captain_id)
            if not club:
                return (
                    False,
                    None,
                    "Club not found or you don't have permission to confirm it",
                )

            # Allow clubs at step 3 or higher to be confirmed (skip step 4 if needed)
            current_step = club.get("club_complete_step", 0)
            if current_step < 3:
                return (
                    False,
                    None,
                    f"Club must complete at least step 3 before confirmation (current step: {current_step})",
                )

            logger.info(
                f"Club is at step {current_step}, allowing paid confirmation (will skip to step 5)"
            )

            # Log if we're skipping step 4
            if current_step == 3:
                logger.info(
                    f"⚠️ Skipping step 4 (moderator setup) for club {request.club_id} - going directly from step 3 to step 5"
                )

            # Allow paid confirmation even with only free moderators if price and payment method are provided
            paid_moderators = club.get("paid_moderators", 0)
            free_moderators = club.get("free_moderators", 0)
            total_moderators = club.get("moderator_count", 0)

            logger.info(
                f"Club moderator info: total={total_moderators}, free={free_moderators}, paid={paid_moderators}"
            )

            # If no paid moderators but price and payment method provided, allow the payment
            if paid_moderators == 0:
                logger.info(
                    f"Club has no paid moderators but allowing paid confirmation with provided price: ${request.price}"
                )
                logger.info(
                    f"Payment will be processed for club with {free_moderators} free moderators"
                )

            # Check if already confirmed
            if club.get("status") == "approved":
                return False, None, "Club is already confirmed and approved"

            # Calculate correct price based on backend logic
            calculated_price = await self._calculate_correct_price(captain_id, club)
            logger.info(
                f"Backend calculated price: ${calculated_price}, Frontend sent price: ${request.price}"
            )

            # Validate that frontend price matches backend calculated price
            if abs(calculated_price - request.price) > 0.01:  # Allow small floating point differences
                return (
                    False,
                    None,
                    f"Price mismatch. Expected: ${calculated_price:.2f}, Received: ${request.price:.2f}. Please refresh and try again."
                )

            logger.info("✅ Price validation passed - frontend and backend prices match")

            # Create payment intent with Stripe
            try:
                logger.info(f"Creating Stripe payment intent for ${request.price}")

                # Convert price to cents for Stripe
                amount_cents = int(request.price * 100)

                # Create payment intent without immediate confirmation to avoid redirect issues
                payment_intent = await StripeService.create_payment_intent(
                    amount=amount_cents,
                    currency="usd",
                    payment_method_id=request.payment_method_id,
                    customer_email=request.email,
                    metadata={
                        "club_id": str(club["_id"]),
                        "club_name": club["name"],
                        "captain_id": captain_id,
                        "moderator_count": str(club.get("moderator_count", 0)),
                        "paid_moderators": str(paid_moderators),
                        "confirmation_type": "paid_moderators",
                    },
                    confirm=False,  # Don't confirm immediately to avoid redirect issues
                    return_url=None,
                )

                if not payment_intent:
                    return False, None, "Failed to create payment intent with Stripe"

                payment_intent_id = payment_intent.get("id")
                payment_status = payment_intent.get("status", "unknown")

                logger.info(
                    f"Payment intent created: {payment_intent_id}, status: {payment_status}"
                )

                # DON'T confirm payment intent yet - wait for admin approval
                # Just create the payment intent and leave it in "requires_confirmation" state
                logger.info(
                    f"💰 Payment intent created and waiting for admin approval: {payment_intent_id}"
                )
                logger.info(
                    f"⏳ Payment will be charged when admin approves the club"
                )

                # Get customer ID for future reference
                customer_id = None
                try:
                    payment_method = stripe.PaymentMethod.retrieve(
                        request.payment_method_id
                    )
                    customer_id = payment_method.customer
                    
                    # If no customer, create one and attach payment method
                    if not customer_id:
                        logger.info(f"Creating customer for email: {request.email}")
                        customer = stripe.Customer.create(
                            email=request.email,
                            metadata={
                                "captain_id": captain_id,
                                "club_id": str(club["_id"]),
                                "club_name": club["name"]
                            }
                        )
                        customer_id = customer.id
                        
                        # Attach payment method to customer
                        stripe.PaymentMethod.attach(
                            request.payment_method_id,
                            customer=customer_id
                        )
                        logger.info(f"✅ Customer created and payment method attached: {customer_id}")
                    else:
                        logger.info(f"✅ Using existing customer: {customer_id}")
                        
                except Exception as pm_error:
                    logger.warning(
                        f"Could not retrieve/create customer: {pm_error}"
                    )

                # Set payment status to requires_confirmation (waiting for admin approval)
                payment_status = "requires_confirmation"
                logger.info(
                    f"💳 Payment status set to: {payment_status} (will be charged after admin approval)"
                )

                # Check if this is the first time the club is reaching step 5
                current_step = club.get("club_complete_step", 0)
                is_first_completion = current_step < 5

                # Update club with payment information
                confirmation_time = datetime.now(timezone.utc)
                update_data = {
                    "payment_intent_id": payment_intent_id,
                    "payment_status": payment_status,  # "requires_confirmation"
                    "customer_id": customer_id,  # Store for later use when admin approves
                    "confirmation_type": "paid",
                    "payment_confirmed_at": None,  # Will be set when admin approves and charges
                    "updated_at": confirmation_time,
                    "status": "pending",  # Waiting for admin approval
                    "club_complete_step": 5  # Mark club as fully completed
                }

                result = await club_collection.update_one(
                    {"_id": club["_id"]}, {"$set": update_data}
                )

                if result.modified_count > 0:
                    logger.info(
                        f"Club {club.get('name')} payment processed successfully"
                    )

                    # Store payment record in database
                    await self._store_payment_record(
                        club=club,
                        request=request,
                        captain_id=captain_id,
                        payment_intent_id=payment_intent_id,
                        payment_status=payment_status,
                        success=True,
                    )

                    # Update captain's club count when club reaches step 5, regardless of payment status
                    # This ensures club count is updated for first club creation even if payment requires confirmation
                    logger.info(
                        f"🔍 Club reached step 5, checking club count update for captain {captain_id}"
                    )
                    logger.info(
                        f"🔍 Current step: {current_step}, is_first_completion: {is_first_completion}, payment_status: {payment_status}"
                    )
                    try:
                        from .db import update_captain_club_count

                        if is_first_completion:
                            logger.info(
                                f"🔄 Updating club count for captain {captain_id} (first completion)"
                            )
                            success = await update_captain_club_count(
                                captain_id, increment=True
                            )
                            if success:
                                logger.info(
                                    f"✅ Successfully set club count to 1 for captain {captain_id} after payment confirmation (first completion, payment_status: {payment_status})"
                                )
                            else:
                                logger.error(
                                    f"❌ Failed to update club count for captain {captain_id} after payment confirmation"
                                )
                        else:
                            logger.info(
                                f"ℹ️ Club already completed before, keeping club count unchanged for captain {captain_id}"
                            )
                    except Exception as count_error:
                        logger.error(
                            f"❌ Exception updating club count for captain {captain_id}: {count_error}"
                        )
                        import traceback

                        logger.error(f"❌ Traceback: {traceback.format_exc()}")
                        # Don't fail the confirmation if count update fails

                    # Build response
                    response = ClubConfirmationPaidResponse(
                        club_id=str(club["_id"]),
                        club_name=club["name"],
                        name_based_id=club.get("name_based_id", ""),
                        status=ClubStatus.PENDING,  # Waiting for admin approval
                        confirmation_type="paid",
                        moderator_count=club.get("moderator_count", 0),
                        free_moderators=club.get("free_moderators", 0),
                        paid_moderators=paid_moderators,
                        total_additional_moderator_pricing=calculated_price,
                        payment_intent_id=payment_intent_id,
                        payment_status=payment_status,  # "requires_confirmation"
                        confirmed_at=None,  # Will be set when admin approves
                        club_complete_step=5,
                    )

                    # Send email notification to captain about club completion
                    try:
                        from .utils.email_utils import send_email_to_members

                        captain_email = club.get("captain_details", {}).get("email")
                        if captain_email:
                            subject = "⏳ Your Club Submission is Under Review"
                            message = f"""
                            <h2>Thank You for Creating Your Club!</h2>
                            <p>Dear {club.get('captain_details', {}).get('full_name', 'Captain')},</p>
                            <p>Your club <strong>"{club.get('name')}"</strong> has been successfully submitted and is now under admin review.</p>
                            
                            <h3>Club Details:</h3>
                            <ul>
                                <li><strong>Club Name:</strong> {club.get('name')}</li>
                                <li><strong>Club ID:</strong> {club.get('name_based_id')}</li>
                                <li><strong>Status:</strong> Pending Admin Approval</li>
                                <li><strong>Payment Status:</strong> Payment on hold (will be charged after approval)</li>
                                <li><strong>Submission Date:</strong> {confirmation_time.strftime('%B %d, %Y at %I:%M %p UTC')}</li>
                            </ul>
                            
                            <h3>💳 Payment Information:</h3>
                            <p>Your payment of <strong>${calculated_price:.2f}</strong> is currently <strong>on hold</strong> and has NOT been charged yet.</p>
                            <ul>
                                <li>✅ If your club is <strong>approved</strong>, the payment will be charged automatically</li>
                                <li>❌ If your club is <strong>rejected</strong>, the hold will be released immediately and you won't be charged</li>
                            </ul>
                            
                            <p>Our admin team will review your club within 2-3 business days. You'll receive an email notification once a decision is made.</p>
                            
                            <p>Thank you for your patience!</p>
                            <p><strong>The Betting App Team</strong></p>
                            """

                            email_sent = await send_email_to_members(
                                captain_email, subject, message
                            )
                            if email_sent:
                                logger.info(
                                    f"✅ Club completion email sent to captain {captain_email}"
                                )
                            else:
                                logger.warning(
                                    f"⚠️ Failed to send club completion email to captain {captain_email}"
                                )
                        else:
                            logger.warning(
                                f"⚠️ Captain email not found for club {club.get('name')}"
                            )
                    except Exception as email_error:
                        logger.warning(
                            f"⚠️ Could not send club completion email: {email_error}"
                        )
                        # Don't fail the confirmation if email fails

                    # Send moderator invitation emails after successful club confirmation
                    try:
                        await self._send_moderator_invitations_after_confirmation(club)
                    except Exception as email_error:
                        logger.warning(
                            f"⚠️ Could not send moderator invitation emails: {email_error}"
                        )
                        # Don't fail the confirmation if email sending fails

                    # Send email notification to all admins for club approval (only on successful payment)
                    if payment_status == "succeeded":
                        try:
                            await self._send_club_approval_email(club, captain_id)
                        except Exception as email_error:
                            logger.warning(
                                f"⚠️ Could not send club approval email: {email_error}"
                            )
                            # Don't fail the confirmation if email sending fails

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
                        
                        title = "Club Payment Successful!"
                        body = f"Payment of ${calculated_price:.2f} for '{club.get('name')}' is on hold. Your club is pending admin approval."
                        
                        notification_data = {
                            "captain_id": captain_id,
                            "club_id": str(club["_id"]),
                            "club_name": club.get("name"),
                            "club_name_based_id": club.get("name_based_id"),
                            "payment_intent_id": payment_intent_id,
                            "amount_paid": calculated_price,
                            "payment_status": payment_status,
                            "moderator_count": club.get("moderator_count", 0),
                            "action": "club_confirmation_success"
                        }
                        
                        notification_result = await send_notification_to_users(
                            user_ids=push_user_ids,
                            title=title,
                            body=body,
                            notification_type="subscription_alerts",
                            data=notification_data,
                            click_action=f"club/{club.get('name_based_id')}",
                            priority="high",
                            all_user_ids=[captain_id],
                        )
                        logger.info(f"✅ Club confirmation success notification stored for captain {captain_id}: {notification_result}")
                            
                    except Exception as e:
                        logger.error(f"⚠️ Failed to send club confirmation success notification: {e}")

                    return True, response, None
                else:
                    return False, None, "Failed to update club with payment information"

            except Exception as stripe_error:
                logger.error(f"Stripe payment error: {stripe_error}")

                # Store failed payment record in database
                try:
                    await self._store_payment_record(
                        club=club,
                        request=request,
                        captain_id=captain_id,
                        payment_intent_id="failed_payment_intent",
                        payment_status="failed",
                        success=False,
                        error_message=str(stripe_error),
                    )
                except Exception as record_error:
                    logger.error(
                        f"Failed to store payment failure record: {record_error}"
                    )

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
                    
                    title = "Club Payment Failed!"
                    body = f"Payment failed for '{club.get('name')}'. Please try again or contact support."
                    
                    notification_data = {
                        "captain_id": captain_id,
                        "club_id": str(club["_id"]),
                        "club_name": club.get("name"),
                        "club_name_based_id": club.get("name_based_id"),
                        "amount_attempted": calculated_price,
                        "error_message": str(stripe_error),
                        "action": "club_confirmation_failure"
                    }
                    
                    notification_result = await send_notification_to_users(
                        user_ids=push_user_ids,
                        title=title,
                        body=body,
                        notification_type="subscription_alerts",
                        data=notification_data,
                        click_action=f"club/{club.get('name_based_id')}",
                        priority="high",
                        all_user_ids=[captain_id],
                    )
                    logger.info(f"✅ Club confirmation failure notification stored for captain {captain_id}: {notification_result}")
                        
                except Exception as e:
                    logger.error(f"⚠️ Failed to send club confirmation failure notification: {e}")

                # Provide more helpful error messages
                error_message = str(stripe_error)
                if (
                    "Payment method" in error_message
                    and "does not exist" in error_message
                ):
                    return (
                        False,
                        None,
                        f"Payment method not found. Please check the payment method ID or create a new one. Error: {error_message}",
                    )
                elif "not attached to a customer" in error_message:
                    return (
                        False,
                        None,
                        f"Payment method issue. Please try again or contact support. Error: {error_message}",
                    )
                elif "Card error" in error_message:
                    return (
                        False,
                        None,
                        f"Card payment failed. Please check your card details and try again. Error: {error_message}",
                    )
                else:
                    return False, None, f"Payment processing failed: {error_message}"

        except Exception as e:
            logger.error(f"Error in paid club confirmation: {e}")

            # Store failed payment record in database for general errors
            try:
                if "club" in locals() and "request" in locals():
                    await self._store_payment_record(
                        club=club,
                        request=request,
                        captain_id=captain_id,
                        payment_intent_id="error_payment_intent",
                        payment_status="error",
                        success=False,
                        error_message=str(e),
                    )
            except Exception as record_error:
                logger.error(f"Failed to store payment error record: {record_error}")

            return False, None, f"Internal server error: {str(e)}"

    async def handle_payment_webhook(
        self, payment_intent_id: str, status: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Handle Stripe webhook for payment confirmation

        Args:
            payment_intent_id: Stripe payment intent ID
            status: Payment status from webhook

        Returns:
            Tuple of (success, error_message)
        """
        try:
            logger.info(
                f"Processing payment webhook for payment_intent: {payment_intent_id}, status: {status}"
            )
            club_collection = get_club_collection()

            # Find club by payment intent ID
            club = await club_collection.find_one(
                {"payment_intent_id": payment_intent_id}
            )
            if not club:
                logger.warning(
                    f"Club not found for payment_intent_id: {payment_intent_id}"
                )
                return False, f"Club not found for payment intent: {payment_intent_id}"

            # Check if this is the first time the club is reaching step 5
            current_step = club.get("club_complete_step", 0)
            is_first_completion = current_step < 5

            # Update payment status
            update_data = {
                "payment_status": status,
                "updated_at": datetime.now(timezone.utc),
            }

            # If payment succeeded, approve the club and set club_complete_step = 5
            if status == "succeeded":
                confirmation_time = datetime.now(timezone.utc)
                update_data.update(
                    {
                        "status": "pending",
                        "confirmed_at": confirmation_time,
                        "payment_confirmed_at": confirmation_time,
                        "club_complete_step": 5,  # Mark club as fully completed
                    }
                )
                logger.info(f"Payment succeeded, approving club: {club.get('name')}")
            elif status in ["failed", "canceled"]:
                logger.info(
                    f"Payment {status}, keeping club pending: {club.get('name')}"
                )

            result = await club_collection.update_one(
                {"_id": club["_id"]}, {"$set": update_data}
            )

            if result.modified_count > 0:
                logger.info(
                    f"Club payment status updated successfully for {club.get('name')}"
                )

                # Update captain's club count only if this is the first time reaching step 5
                if status == "succeeded":
                    logger.info(
                        f"🔍 Webhook: Payment succeeded, checking club count update"
                    )
                    logger.info(
                        f"🔍 Webhook: Current step: {current_step}, is_first_completion: {is_first_completion}"
                    )
                    try:
                        captain_id = club.get("captain_id")
                        if captain_id:
                            from .db import update_captain_club_count

                            if is_first_completion:
                                logger.info(
                                    f"🔄 Webhook: Updating club count for captain {captain_id} (first completion)"
                                )
                                success = await update_captain_club_count(
                                    str(captain_id), increment=True
                                )
                                if success:
                                    logger.info(
                                        f"✅ Webhook: Successfully set club count to 1 for captain {captain_id} after webhook confirmation (first completion)"
                                    )
                                else:
                                    logger.error(
                                        f"❌ Webhook: Failed to update club count for captain {captain_id} after webhook confirmation"
                                    )
                            else:
                                logger.info(
                                    f"ℹ️ Webhook: Club already completed before, keeping club count unchanged for captain {captain_id}"
                                )
                        else:
                            logger.warning(
                                f"⚠️ Webhook: No captain_id found for club {club.get('name')}"
                            )
                    except Exception as count_error:
                        logger.error(
                            f"❌ Webhook: Exception updating club count: {count_error}"
                        )
                        import traceback

                        logger.error(f"❌ Webhook: Traceback: {traceback.format_exc()}")
                        # Don't fail the webhook if count update fails

                    # Send email notification to captain about club completion
                    try:
                        from .utils.email_utils import send_email_to_members

                        captain_email = club.get("captain_details", {}).get("email")
                        if captain_email:
                            subject = "🎉 Your Club is Ready for Members!"
                            message = f"""
                            <h2>Congratulations! Your Club is Now Live</h2>
                            <p>Dear {club.get('captain_details', {}).get('full_name', 'Captain')},</p>
                            <p>Great news! Your club <strong>"{club.get('name')}"</strong> has been successfully set up and is now ready to accept members.</p>
                            
                            <h3>Club Details:</h3>
                            <ul>
                                <li><strong>Club Name:</strong> {club.get('name')}</li>
                                <li><strong>Club ID:</strong> {club.get('name_based_id')}</li>
                                <li><strong>Status:</strong> Ready for members</li>
                                <li><strong>Payment Status:</strong> {status.title()}</li>
                                <li><strong>Completion Date:</strong> {confirmation_time.strftime('%B %d, %Y at %I:%M %p UTC')}</li>
                            </ul>
                            
                            <p>Your club is now live and members can start joining! You can manage your club, invite moderators, and start building your community.</p>
                            
                            <p>Thank you for using our platform!</p>
                            <p><strong>The Betting App Team</strong></p>
                            """

                            email_sent = await send_email_to_members(
                                captain_email, subject, message
                            )
                            if email_sent:
                                logger.info(
                                    f"✅ Webhook: Club completion email sent to captain {captain_email}"
                                )
                            else:
                                logger.warning(
                                    f"⚠️ Webhook: Failed to send club completion email to captain {captain_email}"
                                )
                        else:
                            logger.warning(
                                f"⚠️ Webhook: Captain email not found for club {club.get('name')}"
                            )
                    except Exception as email_error:
                        logger.warning(
                            f"⚠️ Webhook: Could not send club completion email: {email_error}"
                        )
                        # Don't fail the webhook if email fails

                    # Send moderator invitation emails after successful club confirmation via webhook
                    try:
                        await self._send_moderator_invitations_after_confirmation(club)
                    except Exception as email_error:
                        logger.warning(
                            f"⚠️ Webhook: Could not send moderator invitation emails: {email_error}"
                        )
                        # Don't fail the webhook if email sending fails

                return True, None
            else:
                return False, "Failed to update club payment status"

        except Exception as e:
            logger.error(f"Error handling payment webhook: {e}")
            return False, f"Webhook processing error: {str(e)}"

    async def _store_payment_record(
        self,
        club: dict,
        request: ClubConfirmationPaidRequest,
        captain_id: str,
        payment_intent_id: str,
        payment_status: str,
        success: bool,
        error_message: str = None,
    ) -> None:
        """
        Store payment record in database for audit trail

        Args:
            club: Club document
            request: Payment request
            captain_id: Captain's user ID
            payment_intent_id: Stripe payment intent ID
            payment_status: Payment status from Stripe
            success: Whether payment was successful
            error_message: Error message if payment failed
        """
        try:
            payments_collection = get_club_payments_collection()

            # Get captain details
            captain_details = club.get("captain_details", {})
            captain_name = captain_details.get("full_name", "Unknown Captain")

            payment_record = {
                "club_id": str(club["_id"]),
                "club_name": club.get("name", ""),
                "club_name_based_id": club.get("name_based_id", ""),
                "captain_id": captain_id,
                "captain_name": captain_name,
                "captain_email": request.email,
                "payment_method_id": request.payment_method_id,
                "payment_intent_id": payment_intent_id,
                "amount": request.price,
                "currency": "USD",
                "payment_status": payment_status,
                "success": success,
                "error_message": error_message,
                "moderator_count": club.get("moderator_count", 0),
                "paid_moderators": club.get("paid_moderators", 0),
                "free_moderators": club.get("free_moderators", 0),
                "total_additional_moderator_pricing": club.get(
                    "total_additional_moderator_pricing", 0
                ),
                "confirmation_type": "paid_moderators",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }

            result = await payments_collection.insert_one(payment_record)
            if result.inserted_id:
                logger.info(
                    f"✅ Payment record stored successfully: {result.inserted_id}"
                )
            else:
                logger.warning("⚠️ Failed to store payment record")

        except Exception as e:
            logger.error(f"❌ Error storing payment record: {e}")

    async def _find_club_by_id(self, club_id: str, captain_id: str) -> Optional[dict]:
        """Helper method to find club by ID (ObjectId or name_based_id)"""
        try:
            club_collection = get_club_collection()

            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(club_id):
                logger.info(f"Searching by name_based_id: {club_id}")
                club = await club_collection.find_one(
                    {"name_based_id": club_id, "captain_id": captain_id}
                )
            else:
                logger.info(f"Searching by ObjectId: {club_id}")
                try:
                    club_object_id = ObjectId(club_id)
                    club = await club_collection.find_one(
                        {"_id": club_object_id, "captain_id": captain_id}
                    )
                except Exception as e:
                    logger.error(f"Invalid ObjectId format: {club_id}, error: {e}")
                    return None

            return club

        except Exception as e:
            logger.error(f"Error finding club by ID: {e}")
            return None

    async def _send_club_approval_email(self, club: dict, captain_id: str):
        """
        Send club approval email to all admins

        Args:
            club: Club data dictionary
            captain_id: ID of the captain who created the club
        """
        try:
            # Import email and admin services
            from .utils.email_utils import send_club_approval_notification
            from .utils.admin_service import get_all_admin_emails
            from .db import get_user_collection

            logger.info(
                f"Sending club approval email for club: {club.get('name', 'Unknown')}"
            )

            # Get captain information
            captain_info = await self._get_captain_info(captain_id)

            # Prepare club data for email
            club_data = {
                "club_id": str(club.get("_id", "")),
                "club_name": club.get("name", "Unknown Club"),
                "club_name_based_id": club.get("name_based_id", ""),
                "captain_name": captain_info.get("full_name", "Unknown Captain"),
                "captain_email": captain_info.get("email", "N/A"),
                "created_at": club.get(
                    "created_at", datetime.now(timezone.utc)
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "moderator_count": club.get("moderator_count", 0),
                "member_count": club.get("member_count", 0),
                "description": club.get("description", "No description provided"),
            }

            # Get all admin email addresses
            admin_emails = await get_all_admin_emails()

            if not admin_emails:
                logger.warning("No admin emails found for club approval notification")
                return

            # Send email notification
            email_sent = await send_club_approval_notification(club_data, admin_emails)

            if email_sent:
                logger.info(
                    f"✅ Club approval email sent successfully to {len(admin_emails)} admins for club: {club.get('name')}"
                )
            else:
                logger.error(
                    f"❌ Failed to send club approval email for club: {club.get('name')}"
                )

        except Exception as e:
            logger.error(f"Error sending club approval email: {e}")
            import traceback

            traceback.print_exc()

    async def _get_captain_info(self, captain_id: str) -> dict:
        """
        Get captain information from the users collection

        Args:
            captain_id: ID of the captain

        Returns:
            dict: Captain information
        """
        try:
            from .db import get_user_collection

            user_collection = get_user_collection()
            captain = await user_collection.find_one({"_id": ObjectId(captain_id)})

            if captain:
                return {
                    "full_name": captain.get("full_name", "Unknown Captain"),
                    "email": captain.get("email", "N/A"),
                    "phone": captain.get("phone", "N/A"),
                }
            else:
                logger.warning(f"Captain not found: {captain_id}")
                return {"full_name": "Unknown Captain", "email": "N/A", "phone": "N/A"}

        except Exception as e:
            logger.error(f"Error getting captain info: {e}")
            return {"full_name": "Unknown Captain", "email": "N/A", "phone": "N/A"}

    async def _send_moderator_invitations_after_confirmation(self, club: dict):
        """
        Send moderator invitation emails after successful club confirmation

        Args:
            club: Club data dictionary
        """
        try:
            from .club_step4_service import club_step4_service

            logger.info(
                f"Sending moderator invitation emails for club: {club.get('name', 'Unknown')}"
            )

            # Get moderator emails from club
            moderator_emails = club.get("moderator_emails", [])
            detailed_moderators = club.get("detailed_moderators", [])

            if not moderator_emails and not detailed_moderators:
                logger.info("No moderators to send invitations to")
                return

            # Convert detailed moderators to the format expected by the email service
            moderators = []
            if detailed_moderators:
                for mod in detailed_moderators:
                    moderators.append(
                        {
                            "email": mod.get("email", ""),
                            "user_id": mod.get("user_id", ""),
                            "name": mod.get("full_name", mod.get("name", "")),
                            "status": "pending",
                            "invited_at": mod.get("invited_at"),
                            "responded_at": None,
                            "response": None,
                        }
                    )
            elif moderator_emails:
                # Fallback to basic moderator emails if detailed_moderators not available
                for email in moderator_emails:
                    moderators.append(
                        {
                            "email": email,
                            "user_id": "",
                            "name": email.split("@")[0].title(),
                            "status": "pending",
                            "invited_at": datetime.now(timezone.utc),
                            "responded_at": None,
                            "response": None,
                        }
                    )

            if moderators:
                logger.info(
                    f"Found {len(moderators)} moderators to send invitations to"
                )
                await club_step4_service._send_moderator_invitations(club, moderators)
                logger.info(
                    f"✅ Moderator invitation emails sent successfully for club: {club.get('name')}"
                )
            else:
                logger.info("No valid moderators found to send invitations to")

        except Exception as e:
            logger.error(f"Error sending moderator invitation emails: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            # Don't raise the exception to avoid failing the confirmation

    async def _calculate_correct_price(self, captain_id: str, club: dict) -> float:
        """
        Calculate the correct price based on backend business logic
        
        Pricing Rules:
        1. First club creation: No $99 fee
        2. Second+ club creation: $99 fee
        3. Moderators: 1 free, additional moderators at $9.95 each
        
        Args:
            captain_id: ID of the captain creating the club
            club: Club data dictionary
            
        Returns:
            float: Correct total price to charge
        """
        try:
            from .db import get_user_collection
            
            # Constants
            CLUB_CREATION_FEE = 99.0  # $99 for second+ clubs
            MODERATOR_FEE = 9.95      # $9.95 per additional moderator
            FREE_MODERATORS = 1       # 1 moderator is free
            
            # Get captain's completed clubs count to determine if this is first club
            # Count clubs with club_complete_step >= 4 (completed clubs)
            club_collection = get_club_collection()
            clubs_created_count = await club_collection.count_documents({
                "captain_id": captain_id,
                "club_complete_step": {"$gte": 4},
                "is_permanently_deleted": {"$ne": True}
            })
            
            # Additional check: if clubs_created_count == 1 but club_complete_step < 5, set to 0
            if clubs_created_count == 1:
                # Check if the single club has completed step 5
                club_with_step = await club_collection.find_one(
                    {
                        "captain_id": captain_id,
                        "club_complete_step": {"$gte": 4},
                        "is_permanently_deleted": {"$ne": True}
                    },
                    {"club_complete_step": 1}
                )
                if club_with_step and club_with_step.get("club_complete_step", 0) < 5:
                    clubs_created_count = 0
                    logger.info(
                        f"Captain {captain_id} has 1 club but club_complete_step < 5, setting clubs_created_count to 0 for pricing"
                    )
            
            is_first_club = clubs_created_count == 0
            
            logger.info(f"Captain {captain_id} has {clubs_created_count} completed clubs. Is first club: {is_first_club}")
            
            # Calculate club creation fee
            # First club (clubs_created_count == 0) is free, subsequent clubs charge $99
            club_creation_fee = 0.0 if is_first_club else CLUB_CREATION_FEE
            
            # Calculate moderator fees
            total_moderators = club.get("moderator_count", 0)
            paid_moderators = max(0, total_moderators - FREE_MODERATORS)  # Subtract 1 free moderator
            moderator_fees = paid_moderators * MODERATOR_FEE
            
            # Calculate total price
            total_price = club_creation_fee + moderator_fees
            
            logger.info(f"Price calculation: Club fee: ${club_creation_fee}, Moderators: {total_moderators} (paid: {paid_moderators}), Moderator fees: ${moderator_fees}, Total: ${total_price}")
            
            return round(total_price, 2)  # Round to 2 decimal places
            
        except Exception as e:
            logger.error(f"Error calculating correct price: {e}")
            return 0.0


# Create service instance
club_confirmation_service = ClubConfirmationService()
