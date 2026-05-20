from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from .db import get_club_collection, get_user_collection
from .models import (
    ClubStep4UpdateRequest,
    ClubStep4Response,
    ClubStep4Document,
    ModeratorInvitation,
    ModeratorStatus,
    ClubStatus,
    DetailedModeratorInfo,
)
from .auth import get_current_captain, verify_club_ownership
from .id_utils import is_valid_name_based_id
from .stripe_service import StripeService
from .utils.email import send_moderator_invitation_email
import logging
import jwt
import os

logger = logging.getLogger(__name__)


class ClubStep4Service:
    """Service for managing club step 4 (moderator setup)"""

    # Moderator pricing constants
    FREE_MODERATORS = 1
    ADDITIONAL_MODERATOR_PRICE = 9.95
    ADDITIONAL_MODERATOR_CURRENCY = "USD"

    async def update_club_step4(
        self, request: ClubStep4UpdateRequest, captain_id: str
    ) -> Optional[dict]:
        """Update club with step 4 (moderator setup)"""
        try:
            logger.info(
                f"Starting club step 4 update for club_id: {request.club_id}, captain_id: {captain_id}"
            )
            club_collection = get_club_collection()
            user_collection = get_user_collection()

            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(request.club_id):
                logger.info(f"Searching by name_based_id: {request.club_id}")
                club = await club_collection.find_one(
                    {"name_based_id": request.club_id, "captain_id": captain_id}
                )
                if not club:
                    logger.warning(
                        f"Club not found by name_based_id: {request.club_id} for captain: {captain_id}"
                    )
                    raise ValueError(
                        "Club not found or you don't have permission to update it"
                    )
                club_object_id = club["_id"]
                logger.info(
                    f"Found club by name_based_id: {club.get('name', 'Unknown')}"
                )
            else:
                logger.info(f"Searching by ObjectId: {request.club_id}")
                try:
                    club_object_id = ObjectId(request.club_id)
                except Exception as e:
                    logger.error(
                        f"Invalid ObjectId format: {request.club_id}, error: {e}"
                    )
                    raise ValueError("Invalid club ID format")

                club = await club_collection.find_one(
                    {"_id": club_object_id, "captain_id": captain_id}
                )

            if not club:
                logger.warning(
                    f"Club not found or captain mismatch for club_id: {request.club_id}, captain_id: {captain_id}"
                )
                raise ValueError(
                    "Club not found or you don't have permission to update it"
                )

            logger.info(
                f"Club found: {club.get('name', 'Unknown')}, current step: {club.get('club_complete_step', 0)}"
            )

            # Check if club is at step 3 (required for step 4)
            if club.get("club_complete_step", 0) < 3:
                logger.warning(
                    f"Club {club.get('name', 'Unknown')} is at step {club.get('club_complete_step', 0)}, cannot proceed to step 4"
                )
                raise ValueError(
                    "Club must complete step 3 (pricing setup) before setting up moderators"
                )

            # Check if club already has moderators and clear them first
            existing_moderators = club.get("moderator_emails", [])
            existing_detailed_moderators = club.get("detailed_moderators", [])
            existing_paid_moderators = club.get("paid_moderators", 0)

            if existing_moderators or existing_detailed_moderators:
                logger.info(
                    f"Club already has {len(existing_moderators)} existing moderators. Clearing them first..."
                )

                # If there were paid moderators, we might need to handle Stripe cleanup
                if existing_paid_moderators > 0:
                    logger.info(
                        f"Club had {existing_paid_moderators} paid moderators - may need Stripe cleanup"
                    )
                    # Note: In a production system, you might want to deactivate Stripe subscriptions here
                    # For now, we'll just log this for manual review if needed

            # Handle moderator emails (now optional)
            moderator_emails = request.moderator_emails or []

            # If no moderators provided, still proceed but with empty lists
            if not moderator_emails:
                logger.info(
                    "No moderator emails provided - proceeding with empty moderator setup"
                )
                validated_moderators = []
            else:
                # Check for duplicate emails
                unique_emails = list(set(moderator_emails))
                if len(unique_emails) != len(moderator_emails):
                    logger.warning("Duplicate moderator emails detected")
                    raise ValueError("Duplicate moderator emails are not allowed")

            # Validate each email and check user eligibility (only if moderators provided)
            validated_moderators = []
            detailed_moderators = []
            if moderator_emails:
                for index, email in enumerate(unique_emails):
                    logger.info(f"Validating moderator email: {email}")

                    # Check if user exists and is eligible (only active users can be moderators)
                    user = await user_collection.find_one(
                        {
                            "email": email,
                            "status": "active",
                            "membership_status": "active",
                        }
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
                                raise ValueError(
                                    f"User {email} is not active."
                                )
                    
                    if not user:
                        # User doesn't exist in system - create external user
                        logger.info(
                            f"User {email} not found in system. Creating external moderator user..."
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
                                logger.info(
                                    f"Reusing existing signup token for {email}"
                                )
                                user = user  # Use existing user with token
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
                            user = user  # Use existing registered moderator
                    else:
                        # User exists with any other role - can be assigned as moderator
                        logger.info(
                            f"User {email} exists with role '{user.get('role')}'. Assigning as moderator..."
                        )
                        user = (
                            user  # Use existing user, they can be assigned as moderator
                        )

                    # Determine moderator type and price
                    is_free_moderator = index < self.FREE_MODERATORS
                    moderator_type = "free" if is_free_moderator else "paid"
                    moderator_price = (
                        0.0 if is_free_moderator else self.ADDITIONAL_MODERATOR_PRICE
                    )

                    # Get full name from user data
                    full_name = user.get("full_name", user.get("name", ""))
                    if not full_name:
                        # For external users without name, use email prefix
                        full_name = user.get("email", "Unknown").split("@")[0].title()

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

                    detailed_moderators.append(detailed_moderator)

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

                logger.info(
                    f"Validated {len(validated_moderators)} moderator invitations with detailed info"
                )
            else:
                logger.info(
                    "No moderators to validate - proceeding with empty moderator setup"
                )

            # Calculate moderator costs and create Stripe products/prices if needed
            total_moderators = len(validated_moderators)
            free_moderators = min(total_moderators, self.FREE_MODERATORS)
            paid_moderators = max(0, total_moderators - self.FREE_MODERATORS)

            logger.info(
                f"Moderator breakdown: {free_moderators} free, {paid_moderators} paid"
            )

            stripe_product_id = None
            stripe_price_id = None

            # Stripe product creation removed - no longer creating products
            logger.info(
                f"Moderator setup completed: {free_moderators} free, {paid_moderators} paid moderators"
            )
            logger.info("Stripe product creation skipped as requested")

            # Calculate total additional moderator pricing
            total_additional_moderator_pricing = (
                paid_moderators * self.ADDITIONAL_MODERATOR_PRICE
            )

            # Create step 4 document
            step4_doc = ClubStep4Document(
                moderator_emails=moderator_emails,
                detailed_moderators=detailed_moderators,
                moderator_count=total_moderators,
                free_moderators=free_moderators,
                paid_moderators=paid_moderators,
                additional_moderator_price=self.ADDITIONAL_MODERATOR_PRICE,
                additional_moderator_currency=self.ADDITIONAL_MODERATOR_CURRENCY,
                total_additional_moderator_pricing=total_additional_moderator_pricing,
                stripe_product_id=stripe_product_id,
                stripe_price_id=stripe_price_id,
                club_complete_step=4,
                updated_at=datetime.now(timezone.utc),
            )

            # Update club with step 4 data
            result = await club_collection.update_one(
                {"_id": club_object_id},
                {
                    "$set": {
                        "moderator_emails": moderator_emails,
                        "detailed_moderators": [
                            mod.model_dump() for mod in detailed_moderators
                        ],
                        "moderator_count": total_moderators,
                        "free_moderators": free_moderators,
                        "paid_moderators": paid_moderators,
                        "additional_moderator_price": self.ADDITIONAL_MODERATOR_PRICE,
                        "additional_moderator_currency": self.ADDITIONAL_MODERATOR_CURRENCY,
                        "total_additional_moderator_pricing": total_additional_moderator_pricing,
                        "stripe_product_id": stripe_product_id,
                        "stripe_price_id": stripe_price_id,
                        "club_complete_step": 4,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            if result.modified_count > 0:
                logger.info(
                    f"Club updated successfully, modified count: {result.modified_count}"
                )

                # Update club count for captain since step changed
                try:
                    from .db import update_club_count_on_step_change

                    await update_club_count_on_step_change(
                        captain_id, request.club_id, 4
                    )
                    logger.info(
                        f"✅ Club count updated for captain {captain_id} after step 4 completion"
                    )
                except Exception as count_error:
                    logger.warning(
                        f"⚠️ Could not update club count for captain {captain_id}: {count_error}"
                    )

                # Note: Moderator invitation emails will be sent after club confirmation
                # (either free or paid confirmation) to ensure club is active before inviting moderators
                if validated_moderators:
                    logger.info(
                        f"Moderator setup completed for {len(validated_moderators)} moderators. Emails will be sent after club confirmation."
                    )
                else:
                    logger.info("No moderators to send invitations to")

                # Get updated club
                updated_club = await club_collection.find_one({"_id": club_object_id})

                if not updated_club:
                    logger.error("Failed to retrieve updated club after update")
                    return None

                logger.info("Building response...")

                # Build response
                status_value = updated_club.get("status", "pending")
                try:
                    if isinstance(status_value, str):
                        if status_value.lower() == "pending":
                            status_enum = ClubStatus.PENDING
                        elif status_value.lower() == "approved":
                            status_enum = ClubStatus.APPROVED
                        elif status_value.lower() == "rejected":
                            status_enum = ClubStatus.REJECT
                        else:
                            status_enum = ClubStatus.PENDING
                    else:
                        status_enum = ClubStatus.PENDING
                except Exception as e:
                    logger.warning(f"Status conversion failed, using default: {e}")
                    status_enum = ClubStatus.PENDING

                # Build moderator invitations list
                moderator_invitations = []
                for moderator in validated_moderators:
                    invitation = ModeratorInvitation(
                        email=moderator["email"],
                        user_id=moderator["user_id"],
                        name=moderator["name"],
                        status=ModeratorStatus.PENDING,
                        invited_at=moderator["invited_at"],
                        responded_at=moderator["responded_at"],
                        response=moderator["response"],
                    )
                    moderator_invitations.append(invitation)

                # Calculate total additional moderator pricing
                total_additional_moderator_pricing = (
                    paid_moderators * self.ADDITIONAL_MODERATOR_PRICE
                )

                response = ClubStep4Response(
                    id=str(updated_club["_id"]),
                    name=updated_club["name"],
                    name_based_id=updated_club.get("name_based_id", ""),
                    description=updated_club["description"],
                    sub_description=updated_club.get("sub_description"),
                    logo_url=updated_club.get("logo_url"),
                    status=status_enum,
                    club_complete_step=updated_club.get("club_complete_step", 4),
                    captain_id=updated_club["captain_id"],
                    moderator_emails=moderator_emails,
                    detailed_moderators=detailed_moderators,
                    moderator_count=total_moderators,
                    free_moderators=free_moderators,
                    paid_moderators=paid_moderators,
                    additional_moderator_price=self.ADDITIONAL_MODERATOR_PRICE,
                    additional_moderator_currency=self.ADDITIONAL_MODERATOR_CURRENCY,
                    total_additional_moderator_pricing=total_additional_moderator_pricing,
                    stripe_product_id=stripe_product_id,
                    stripe_price_id=stripe_price_id,
                    moderator_invitations=moderator_invitations,
                    created_at=updated_club["created_at"],
                    updated_at=updated_club["updated_at"],
                )

                logger.info("Response built successfully")
                logger.info(f"Final response data: {response.model_dump()}")

                return response.model_dump()

            else:
                logger.warning("No changes made to club during update")
                return None

        except ValueError as e:
            logger.warning(f"Validation error in club step 4 update: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error updating club step 4: {e}")
            import traceback

            traceback.print_exc()
            return None

    async def _send_moderator_invitations(self, club: dict, moderators: List[dict]):
        """Send invitation emails to all moderators"""
        try:
            club_name = club.get("name", "Unknown Club")
            captain_name = club.get("captain_name", "Club Captain")

            for moderator in moderators:
                try:
                    logger.info(f"Processing email for moderator: {moderator['email']}")

                    # Check if this is an external user (newly created)
                    user_collection = get_user_collection()
                    user = await user_collection.find_one({"email": moderator["email"]})

                    logger.info(
                        f"User lookup result for {moderator['email']}: {user is not None}"
                    )
                    if user:
                        logger.info(
                            f"User is_external_invite: {user.get('is_external_invite', False)}"
                        )

                    # Send unified moderator invitation email for all user types
                    logger.info(
                        f"Sending unified moderator invitation email to: {moderator['email']}"
                    )

                    # Determine user status and generate appropriate links
                    is_registered = user and user.get("is_register", True)
                    current_role = user.get("role", "User") if user else "New User"
                    signup_token = user.get("signup_token") if user else None

                    # Generate signup link based on user status
                    frontend_url = os.getenv("APP_BASE_URL", "http://localhost:3000")
                    if is_registered:
                        # Registered user - direct to dashboard
                        action_link = frontend_url
                        action_text = "Access Moderator Dashboard"
                    elif signup_token:
                        # Unregistered user with token - signup with token
                        action_link = (
                            f"{frontend_url}/signup?token={signup_token}"
                        )
                        action_text = "Complete Signup & Join Club"
                    else:
                        # Unregistered user without token - regular signup
                        action_link = f"{frontend_url}/signup"
                        action_text = "Register & Join Club"

                    await self._send_unified_moderator_invitation_email(
                        to_email=moderator["email"],
                        moderator_name=moderator["name"],
                        club_name=club_name,
                        captain_name=captain_name,
                        club_id=str(club["_id"]),
                        current_role=current_role,
                        is_registered=is_registered,
                        action_link=action_link,
                        action_text=action_text,
                    )
                    logger.info(
                        f"Unified moderator invitation email sent to: {moderator['email']}"
                    )

                except Exception as email_error:
                    logger.error(
                        f"Failed to send email to {moderator['email']}: {email_error}"
                    )
                    import traceback

                    logger.error(f"Email error traceback: {traceback.format_exc()}")
                    # Continue with other invitations even if one fails

            logger.info(f"Sent {len(moderators)} moderator emails")

        except Exception as e:
            logger.error(f"Error sending moderator emails: {e}")

    def _generate_invitation_token(self, email: str, club_id: str) -> str:
        """Generate a unique invitation token for moderator acceptance"""
        import hashlib
        import secrets

        # Create a unique token based on email, club_id, and timestamp
        token_data = f"{email}:{club_id}:{datetime.now(timezone.utc).isoformat()}"
        token_hash = hashlib.sha256(token_data.encode()).hexdigest()

        # Add some randomness
        random_part = secrets.token_urlsafe(16)

        return f"{token_hash[:16]}_{random_part}"

    def _generate_signup_token(self, email: str, role: str = "moderator") -> str:
        """Generate a proper JWT signup token for external users using centralized JWT handler"""
        from core.auth.jwt_handler import get_jwt_handler

        jwt_handler = get_jwt_handler()

        # Use proper JWT token for moderator signup
        token = jwt_handler.create_moderator_signup_token(email, role)

        logger.info(
            f"Generated JWT signup token for {email} with 1-minute expiration for testing"
        )
        return token

        # Old simple token method (commented out)
        # token = jwt_handler.create_simple_signup_token(email, role)
        # logger.info(f"Generated simple signup token for {email} with 7-day expiration")

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
                f"Created external moderator user: {email} with ID: {result.inserted_id} and token: {signup_token[:20]}..."
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
                logger.info(
                    f"Updated user {email} with new signup token: {signup_token[:20]}..."
                )
                return existing_user
            else:
                logger.warning(f"No changes made when updating token for user {email}")
                return existing_user

        except Exception as e:
            logger.error(f"Error updating user {email} with signup token: {e}")
            raise ValueError(f"Failed to update user with signup token: {str(e)}")

    async def validate_moderator_signup_token(self, token: str) -> dict:
        """Validate JWT moderator signup token and return payload if valid"""
        try:
            logger.info(f"Validating moderator signup token: {token[:20]}...")

            if not token:
                return {"valid": False, "error": "Token is required", "payload": None}

            # Use the new JWT moderator signup token verification
            from core.auth.jwt_handler import get_jwt_handler

            jwt_handler = get_jwt_handler()
            payload = jwt_handler.verify_moderator_signup_token(token)

            if payload is None:
                return {
                    "valid": False,
                    "error": "Invalid or expired moderator signup token",
                    "payload": None,
                }

            logger.info(f"JWT moderator signup token validated successfully: {payload}")

            # Validate required fields
            required_fields = ["email", "role", "type", "is_valid"]
            for field in required_fields:
                if field not in payload:
                    return {
                        "valid": False,
                        "error": f"Missing required field: {field}",
                        "payload": None,
                    }

            # Validate token type
            if payload.get("type") != "moderator_signup":
                return {
                    "valid": False,
                    "error": "Token is not for moderator signup",
                    "payload": None,
                }

            # Validate role
            if payload.get("role") != "moderator":
                return {
                    "valid": False,
                    "error": "Token is not for moderator role",
                    "payload": payload,
                }

            # Check if user exists in database and is eligible for signup
            user_collection = get_user_collection()
            user = await user_collection.find_one({"signup_token": token})

            if not user:
                return {
                    "valid": False,
                    "error": "Token not found in database or already used",
                    "payload": None,
                }

            # Check if user is eligible for signup
            if user.get("is_register", True):  # Already registered
                return {
                    "valid": False,
                    "error": "User has already completed signup",
                    "payload": None,
                }

            if user.get("role") != "moderator":
                return {
                    "valid": False,
                    "error": "User is not eligible for moderator role",
                    "payload": None,
                }

            # Validate email matches user in database
            if payload.get("email") != user.get("email"):
                return {
                    "valid": False,
                    "error": "Token email does not match user email",
                    "payload": payload,
                }

            # Token is valid
            logger.info(f"Token validation successful for email: {payload['email']}")

            # Build response payload
            response_payload = {
                "email": payload["email"],
                "role": payload["role"],
                "type": payload["type"],
                "is_valid": payload["is_valid"],
                "iat": payload.get("iat"),
                "user_id": str(user["_id"]),
                "user_status": user.get("status"),
                "is_register": user.get("is_register", False),
                "token_type": "jwt",
            }

            return {"valid": True, "error": None, "payload": response_payload}

        except Exception as e:
            logger.error(f"Unexpected error validating moderator signup token: {e}")
            return {
                "valid": False,
                "error": f"Token validation failed: {str(e)}",
                "payload": None,
            }

    async def complete_moderator_signup(self, token: str, signup_data: dict) -> dict:
        """Complete moderator signup and nullify the token"""
        try:
            logger.info(f"Completing moderator signup for token: {token[:20]}...")

            user_collection = get_user_collection()

            # Find user by token
            user = await user_collection.find_one({"signup_token": token})
            if not user:
                return {"success": False, "error": "Token not found or already used"}

            # Check if user is already registered
            if user.get("is_register", True):
                return {"success": False, "error": "User has already completed signup"}

            # Update user with signup data and nullify token
            update_data = {
                "signup_token": None,  # Nullify the token
                "is_register": True,  # Mark as registered
                "status": "active",  # Activate user
                "membership_status": "active",  # Set membership as active
                "updated_at": datetime.now(timezone.utc),
            }

            # Add signup data if provided
            if signup_data:
                if "full_name" in signup_data:
                    update_data["full_name"] = signup_data["full_name"]
                    update_data["name"] = signup_data["full_name"]
                if "password" in signup_data:
                    # Hash password before storing
                    from services.auth.utils import hash_password

                    update_data["password"] = hash_password(signup_data["password"])

            # Update user in database
            result = await user_collection.update_one(
                {"_id": user["_id"]}, {"$set": update_data}
            )

            if result.modified_count > 0:
                logger.info(f"Successfully completed signup for user: {user['email']}")
                return {
                    "success": True,
                    "message": "Signup completed successfully",
                    "user_id": str(user["_id"]),
                    "email": user["email"],
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to update user during signup",
                }

        except Exception as e:
            logger.error(f"Error completing moderator signup: {e}")
            return {"success": False, "error": f"Signup completion failed: {str(e)}"}

    async def _send_unified_moderator_invitation_email(
        self,
        to_email: str,
        moderator_name: str,
        club_name: str,
        captain_name: str,
        club_id: str,
        current_role: str,
        is_registered: bool,
        action_link: str,
        action_text: str,
    ):
        """Send unified moderator invitation email for all user types"""
        try:
            from .utils.email import send_email

            subject = f"You've been invited to moderate {club_name}"

            # Dynamic content based on user status
            if is_registered:
                status_message = f'<strong>{captain_name}</strong> has invited you to moderate the club <strong>"{club_name}"</strong>.'
                next_steps = """
                <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin-top: 0; color: #2e7d32;">Your Moderator Status</h3>
                    <ul style="margin: 0; padding-left: 20px;">
                        <li>You already have an account and can access the moderator dashboard</li>
                        <li>Your existing account has been granted moderator privileges for this club</li>
                        <li>You can now help manage club activities and members</li>
                        <li>Switch between your clubs using the club selector in your dashboard</li>
                    </ul>
                </div>
                """
            else:
                status_message = f'<strong>{captain_name}</strong> has invited you to become a moderator for the club <strong>"{club_name}"</strong>.'
                next_steps = """
                <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin-top: 0; color: #2e7d32;">What happens next?</h3>
                    <ul style="margin: 0; padding-left: 20px;">
                        <li>Click the button below to complete your account setup</li>
                        <li>Fill in your profile information</li>
                        <li>You'll automatically be added as a moderator to "{club_name}"</li>
                        <li>Start helping manage the club community!</li>
                    </ul>
                </div>
                """

            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <div style="background-color: #e74c3c; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
                        <h1 style="margin: 0;">🎉 You're Invited to Moderate!</h1>
                    </div>
                    
                    <div style="background-color: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px;">
                        <h2 style="color: #e74c3c; margin-top: 0;">Hello {moderator_name}!</h2>
                        
                        <p>{status_message}</p>
                        
                        <div style="background-color: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                            <h3 style="margin-top: 0; color: #856404;">Invitation Details</h3>
                            <p><strong>Your Role:</strong> {current_role} → Moderator</p>
                            <p><strong>Club:</strong> {club_name}</p>
                            <p><strong>Invited by:</strong> {captain_name}</p>
                            <p><strong>Club ID:</strong> {club_id}</p>
                            <p><strong>Account Status:</strong> {'Already Registered' if is_registered else 'Registration Required'}</p>
                        </div>
                        
                        <p><strong>Your new moderator privileges include:</strong></p>
                        <ul>
                            <li>Help manage club activities and discussions</li>
                            <li>Monitor member behavior and ensure fair play</li>
                            <li>Assist with club administration tasks</li>
                            <li>Access moderator dashboard and tools</li>
                            <li>Help maintain club quality and community standards</li>
                        </ul>
                        
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{action_link}" 
                               style="background-color: #e74c3c; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-size: 16px; font-weight: bold;">
                                {action_text}
                            </a>
                        </div>
                        
                        {next_steps}
                        
                        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #6c757d;">
                            <h3 style="margin-top: 0; color: #495057;">Important Note</h3>
                            <p>Your moderator invitation is specific to this club. {'You can manage multiple clubs from your dashboard.' if is_registered else 'After completing registration, you can be invited to moderate additional clubs.'}</p>
                        </div>
                        
                        <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
                        <p style="font-size: 12px; color: #666;">
                            {'Welcome to your new moderator role!' if is_registered else 'Complete your registration to get started!'} If you have any questions about your moderator responsibilities, please contact the club captain or support.
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """

            text_content = f"""
            You're Invited to Moderate!
            
            Hello {moderator_name}!
            
            {captain_name} has invited you to become a moderator for the club "{club_name}".
            
            Invitation Details:
            - Your Role: {current_role} → Moderator
            - Club: {club_name}
            - Invited by: {captain_name}
            - Club ID: {club_id}
            - Account Status: {'Already Registered' if is_registered else 'Registration Required'}
            
            Your new moderator privileges include:
            - Help manage club activities and discussions
            - Monitor member behavior and ensure fair play
            - Assist with club administration tasks
            - Access moderator dashboard and tools
            - Help maintain club quality and community standards
            
            {action_text}: {action_link}
            
            {'What happens next?' if not is_registered else 'Your Moderator Status'}:
            {'- Click the link above to complete your account setup' if not is_registered else '- You already have an account and can access the moderator dashboard'}
            {'- Fill in your profile information' if not is_registered else '- Your existing account has been granted moderator privileges for this club'}
            {'- You will automatically be added as a moderator to "' + club_name + '"' if not is_registered else '- You can now help manage club activities and members'}
            {'- Start helping manage the club!' if not is_registered else '- Switch between your clubs using the club selector in your dashboard'}
            
            Important Note:
            {'Your moderator invitation is specific to this club. After completing registration, you can be invited to moderate additional clubs.' if not is_registered else 'Your moderator invitation is specific to this club. You can manage multiple clubs from your dashboard.'}
            
            {'Complete your registration to get started!' if not is_registered else 'Welcome to your new moderator role!'} If you have any questions about your moderator responsibilities, please contact the club captain or support.
            """

            await send_email(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )

            logger.info(
                f"Unified moderator invitation email sent to {current_role}: {to_email}"
            )

        except Exception as e:
            logger.error(
                f"Failed to send unified moderator invitation email to {to_email}: {e}"
            )
            raise e

    async def _send_moderator_promotion_email(
        self,
        to_email: str,
        moderator_name: str,
        club_name: str,
        captain_name: str,
        club_id: str,
        current_role: str,
    ):
        """Send moderator promotion notification email to Member/Captain users"""
        try:
            from .utils.email import send_email

            subject = f"You've been promoted to moderator for {club_name}!"

            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #e74c3c;">🎉 Congratulations! You've been promoted to Moderator!</h2>
                    
                    <p>Hello {moderator_name},</p>
                    
                    <p><strong>{captain_name}</strong> has promoted you from <strong>{current_role}</strong> to <strong>Moderator</strong> for the club: <strong>"{club_name}"</strong>.</p>
                    
                    <div style="background-color: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                        <h3 style="margin-top: 0; color: #856404;">Promotion Details</h3>
                        <p><strong>Previous Role:</strong> {current_role}</p>
                        <p><strong>New Role:</strong> Moderator</p>
                        <p><strong>Club:</strong> {club_name}</p>
                        <p><strong>Promoted by:</strong> {captain_name}</p>
                        <p><strong>Club ID:</strong> {club_id}</p>
                    </div>
                    
                    <p><strong>Your new moderator privileges include:</strong></p>
                    <ul>
                        <li>Help manage club activities and discussions</li>
                        <li>Monitor member behavior and ensure fair play</li>
                        <li>Assist with club administration tasks</li>
                        <li>Access moderator dashboard and tools</li>
                        <li>Help maintain club quality and community standards</li>
                    </ul>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="http://localhost:3000/clubs/{club_id}" 
                           style="background-color: #e74c3c; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block;">
                            Access Moderator Dashboard
                        </a>
                    </div>
                    
                    <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #2e7d32;">What's Next?</h3>
                        <ul style="margin: 0; padding-left: 20px;">
                            <li>Explore your new moderator dashboard</li>
                            <li>Review club guidelines and policies</li>
                            <li>Connect with other club moderators</li>
                            <li>Start helping maintain the club community</li>
                        </ul>
                    </div>
                    
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #6c757d;">
                        <h3 style="margin-top: 0; color: #495057;">Important Note</h3>
                        <p>Your promotion to moderator is specific to this club. Your role in other clubs remains unchanged unless specifically promoted there as well.</p>
                    </div>
                    
                    <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
                    <p style="font-size: 12px; color: #666;">
                        Congratulations on your promotion! If you have any questions about your new moderator responsibilities, please contact the club captain or support.
                    </p>
                </div>
            </body>
            </html>
            """

            text_content = f"""
            Congratulations! You've been promoted to Moderator!
            
            Hello {moderator_name},
            
            {captain_name} has promoted you from {current_role} to Moderator for the club: "{club_name}".
            
            Promotion Details:
            - Previous Role: {current_role}
            - New Role: Moderator
            - Club: {club_name}
            - Promoted by: {captain_name}
            - Club ID: {club_id}
            
            Your new moderator privileges include:
            - Help manage club activities and discussions
            - Monitor member behavior and ensure fair play
            - Assist with club administration tasks
            - Access moderator dashboard and tools
            - Help maintain club quality and community standards
            
            Access Moderator Dashboard: http://localhost:3000/clubs/{club_id}
            
            What's Next?
            - Explore your new moderator dashboard
            - Review club guidelines and policies
            - Connect with other club moderators
            - Start helping maintain the club community
            
            Important Note:
            Your promotion to moderator is specific to this club. Your role in other clubs remains unchanged unless specifically promoted there as well.
            
            Congratulations on your promotion! If you have any questions about your new moderator responsibilities, please contact the club captain or support.
            """

            await send_email(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )

            logger.info(
                f"Moderator promotion notification email sent to {current_role}: {to_email}"
            )

        except Exception as e:
            logger.error(
                f"Failed to send moderator promotion notification email to {to_email}: {e}"
            )
            raise e

    async def _send_moderator_club_assignment_email(
        self,
        to_email: str,
        moderator_name: str,
        club_name: str,
        captain_name: str,
        club_id: str,
    ):
        """Send club assignment notification email to registered moderator"""
        try:
            from .utils.email import send_email

            subject = f"You've been assigned to moderate {club_name}"

            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #e74c3c;">New Club Assignment!</h2>
                    
                    <p>Hello {moderator_name},</p>
                    
                    <p><strong>{captain_name}</strong> has assigned you as a moderator for a new club: <strong>"{club_name}"</strong>.</p>
                    
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #e74c3c;">
                        <h3 style="margin-top: 0; color: #e74c3c;">Club Details</h3>
                        <p><strong>Club Name:</strong> {club_name}</p>
                        <p><strong>Captain:</strong> {captain_name}</p>
                        <p><strong>Club ID:</strong> {club_id}</p>
                    </div>
                    
                    <p><strong>What this means:</strong></p>
                    <ul>
                        <li>You now have moderator privileges for this club</li>
                        <li>You can help manage club activities and members</li>
                        <li>You'll receive notifications about club events</li>
                        <li>You can assist with club administration tasks</li>
                    </ul>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="http://localhost:3000/clubs/{club_id}" 
                           style="background-color: #e74c3c; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block;">
                            View Club Dashboard
                        </a>
                    </div>
                    
                    <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #2e7d32;">Your Moderator Status</h3>
                        <p>You're now moderating multiple clubs. You can switch between clubs using the club selector in your dashboard.</p>
                    </div>
                    
                    <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
                    <p style="font-size: 12px; color: #666;">
                        If you have any questions about your new moderator assignment, please contact the club captain or support.
                    </p>
                </div>
            </body>
            </html>
            """

            text_content = f"""
            New Club Assignment!
            
            Hello {moderator_name},
            
            {captain_name} has assigned you as a moderator for a new club: "{club_name}".
            
            Club Details:
            - Club Name: {club_name}
            - Captain: {captain_name}
            - Club ID: {club_id}
            
            What this means:
            - You now have moderator privileges for this club
            - You can help manage club activities and members
            - You'll receive notifications about club events
            - You can assist with club administration tasks
            
            View Club Dashboard: http://localhost:3000/clubs/{club_id}
            
            Your Moderator Status:
            You're now moderating multiple clubs. You can switch between clubs using the club selector in your dashboard.
            
            If you have any questions about your new moderator assignment, please contact the club captain or support.
            """

            await send_email(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )

            logger.info(
                f"Club assignment notification email sent to registered moderator: {to_email}"
            )

        except Exception as e:
            logger.error(
                f"Failed to send club assignment notification email to {to_email}: {e}"
            )
            raise e

    async def _send_external_moderator_signup_email(
        self,
        to_email: str,
        moderator_name: str,
        club_name: str,
        captain_name: str,
        signup_link: str,
    ):
        """Send signup email to external moderator"""
        try:
            from .utils.email import send_email

            subject = f"You've been invited to moderate {club_name}"

            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #2c3e50;">You've been invited to moderate a club!</h2>
                    
                    <p>Hello {moderator_name},</p>
                    
                    <p><strong>{captain_name}</strong> has invited you to become a moderator for the club <strong>"{club_name}"</strong>.</p>
                    
                    <p>To accept this invitation and complete your account setup, please click the link below:</p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{signup_link}" 
                           style="background-color: #3498db; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block;">
                            Complete Signup & Join Club
                        </a>
                    </div>
                    
                    <p><strong>What happens next?</strong></p>
                    <ul>
                        <li>Click the link above to create your account</li>
                        <li>Complete your profile setup</li>
                        <li>You'll automatically be added as a moderator to "{club_name}"</li>
                        <li>Start helping manage the club!</li>
                    </ul>
                    
                    <p><em>Note: This invitation link will expire after a certain period for security reasons.</em></p>
                    
                    <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
                    <p style="font-size: 12px; color: #666;">
                        If you didn't expect this invitation, you can safely ignore this email.
                    </p>
                </div>
            </body>
            </html>
            """

            text_content = f"""
            You've been invited to moderate a club!
            
            Hello {moderator_name},
            
            {captain_name} has invited you to become a moderator for the club "{club_name}".
            
            To accept this invitation and complete your account setup, please visit:
            {signup_link}
            
            What happens next?
            - Click the link above to create your account
            - Complete your profile setup
            - You'll automatically be added as a moderator to "{club_name}"
            - Start helping manage the club!
            
            Note: This invitation link will expire after a certain period for security reasons.
            
            If you didn't expect this invitation, you can safely ignore this email.
            """

            await send_email(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )

            logger.info(f"External moderator signup email sent to: {to_email}")

        except Exception as e:
            logger.error(
                f"Failed to send external moderator signup email to {to_email}: {e}"
            )
            raise e

    async def respond_to_moderator_invitation(
        self, club_id: str, moderator_email: str, response: str, invitation_token: str
    ) -> Optional[dict]:
        """Handle moderator response to invitation (accept/decline)"""
        try:
            logger.info(
                f"Processing moderator invitation response: {response} from {moderator_email}"
            )

            if response not in ["accept", "decline"]:
                raise ValueError("Response must be 'accept' or 'decline'")

            club_collection = get_club_collection()

            # Find club by ID
            club = None
            if is_valid_name_based_id(club_id):
                club = await club_collection.find_one({"name_based_id": club_id})
            else:
                try:
                    club_object_id = ObjectId(club_id)
                    club = await club_collection.find_one({"_id": club_object_id})
                except Exception:
                    pass

            if not club:
                raise ValueError("Club not found")

            # Find the moderator in the club's moderator list
            moderator_emails = club.get("moderator_emails", [])
            if moderator_email not in moderator_emails:
                raise ValueError("Moderator email not found in club")

            # Update moderator status
            current_moderators = club.get("moderators", [])
            moderator_updated = False

            for mod in current_moderators:
                if mod.get("email") == moderator_email:
                    mod["status"] = response
                    mod["responded_at"] = datetime.now(timezone.utc)
                    mod["response"] = response
                    moderator_updated = True
                    break

            if not moderator_updated:
                # Add new moderator entry
                current_moderators.append(
                    {
                        "email": moderator_email,
                        "status": response,
                        "invited_at": datetime.now(timezone.utc),
                        "responded_at": datetime.now(timezone.utc),
                        "response": response,
                    }
                )

            # Update club
            await club_collection.update_one(
                {"_id": club["_id"]},
                {
                    "$set": {
                        "moderators": current_moderators,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            logger.info(
                f"Moderator {moderator_email} response ({response}) recorded successfully"
            )

            return {
                "success": True,
                "message": f"Moderator invitation {response}ed successfully",
                "moderator_email": moderator_email,
                "response": response,
                "club_name": club.get("name"),
            }

        except Exception as e:
            logger.error(f"Error processing moderator invitation response: {e}")
            return {
                "success": False,
                "message": f"Failed to process invitation response: {str(e)}",
            }

    async def get_club_step4_status(
        self, club_id: str, captain_id: str
    ) -> Optional[dict]:
        """Get club step 4 completion status"""
        try:
            club_collection = get_club_collection()

            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(club_id):
                club = await club_collection.find_one(
                    {"name_based_id": club_id, "captain_id": captain_id}
                )
            else:
                try:
                    club_object_id = ObjectId(club_id)
                    club = await club_collection.find_one(
                        {"_id": club_object_id, "captain_id": captain_id}
                    )
                except Exception:
                    raise ValueError("Invalid club ID format")

            if not club:
                return None

            # Calculate total additional moderator pricing
            paid_moderators = club.get("paid_moderators", 0)
            additional_moderator_price = club.get("additional_moderator_price", 0)
            total_additional_moderator_pricing = (
                paid_moderators * additional_moderator_price
            )

            return {
                "club_id": str(club["_id"]),
                "name": club["name"],
                "name_based_id": club.get("name_based_id", ""),
                "club_complete_step": club.get("club_complete_step", 0),
                "moderator_count": club.get("moderator_count", 0),
                "free_moderators": club.get("free_moderators", 0),
                "paid_moderators": paid_moderators,
                "additional_moderator_price": additional_moderator_price,
                "total_additional_moderator_pricing": total_additional_moderator_pricing,
                "can_proceed_to_step4": club.get("club_complete_step", 0) >= 3,
                "step4_completed": club.get("club_complete_step", 0) >= 4,
            }

        except Exception as e:
            logger.error(f"Error getting club step 4 status: {e}")
            return None


# Create service instance
club_step4_service = ClubStep4Service()
