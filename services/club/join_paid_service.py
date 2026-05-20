"""
Join Paid Service

This service handles paid club memberships for members.
It processes Stripe payments, validates pricing plans, and manages paid memberships.
"""

import os
import stripe
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from .models import JoinPaidRequest, JoinPaidResponse, PaidMemberDetails, PricingPlan
from .db import get_club_collection, get_user_collection, get_membership_collection
from .trial_service import is_user_trial_member, get_trial_membership_status
from .membership_service import add_member_to_club
# Removed Stripe Connect import - using regular Stripe payments

# Configure logging
logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
if not stripe.api_key:
    logger.warning("⚠️ STRIPE_SECRET_KEY not found in environment variables")

class JoinPaidService:
    """Service for handling paid club memberships"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
        self.membership_collection = get_membership_collection()
    
    async def join_club_paid(self, request: JoinPaidRequest) -> Tuple[bool, Optional[JoinPaidResponse], str]:
        """
        Process paid club membership for a member
        
        Args:
            request: JoinPaidRequest with payment details
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"🚀 Processing paid club join request for email: {request.email}")
            
            # Step 1: Validate user exists and get user details
            logger.info(f"📋 Step 1: Validating user with email: {request.email}")
            user = await self._get_user_by_email(request.email)
            if not user:
                logger.error(f"❌ User not found with email: {request.email}")
                return False, None, "User not found with the provided email"
            
            user_id = str(user["_id"])
            user_name = user.get("full_name", "Unknown")
            logger.info(f"✅ User found: {user_name} (ID: {user_id})")
            
            # Step 2: Validate club exists and get club details
            logger.info(f"📋 Step 2: Validating club: {request.club_name_based_id}")
            club = await self._get_club_by_name_based_id(request.club_name_based_id)
            if not club:
                logger.error(f"❌ Club not found: {request.club_name_based_id}")
                return False, None, f"Club '{request.club_name_based_id}' not found"
            
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            captain_id = str(club.get("captain_id", ""))
            logger.info(f"✅ Club found: {club_name} (ID: {club_id})")
            
            # Step 3: Check if user is already a member of this club
            logger.info(f"📋 Step 3: Checking if user is already a member")
            existing_membership = await self._get_existing_membership(user_id, club_id)
            if existing_membership:
                logger.info(f"🔄 User {user_id} is already a member - checking for plan change")
                # Handle plan change for existing member
                return await self._handle_plan_change(user, club, existing_membership, request)
            logger.info(f"✅ User is not a member yet - proceeding with new membership")
            
            # Step 4: Validate pricing plan and price
            logger.info(f"📋 Step 4: Validating pricing plan: {request.pricing_plan}, price: {request.price}")
            pricing_validation = await self._validate_pricing_plan(club, request.pricing_plan, request.price, request.price_id)
            if not pricing_validation[0]:
                logger.error(f"❌ Pricing validation failed: {pricing_validation[1]}")
                return False, None, pricing_validation[1]
            logger.info(f"✅ Pricing plan validated successfully")
            
            # Step 5: Check trial membership restrictions
            logger.info(f"📋 Step 5: Checking trial restrictions")
            trial_check = await self._check_trial_restrictions(user, request)
            if not trial_check[0]:
                logger.error(f"❌ Trial restriction check failed: {trial_check[1]}")
                return False, None, trial_check[1]
            logger.info(f"✅ Trial restrictions passed")
            
            # Step 6: Process Stripe payment
            logger.info(f"📋 Step 6: Processing Stripe payment")
            
            # For development/testing - allow bypass if Stripe not configured
            if not stripe.api_key and os.getenv('ALLOW_PAYMENT_BYPASS', 'false').lower() == 'true':
                logger.warning("⚠️ Bypassing Stripe payment for development/testing")
                payment_intent_id = f"test_payment_{user_id}_{club_id}"
                subscription_id = f"test_subscription_{user_id}_{club_id}"
                logger.info(f"✅ Test payment processed: {payment_intent_id}")
                logger.info(f"✅ Test subscription created: {subscription_id}")
            else:
                # Get customer ID from user
                customer_id = user.get("stripe_customer_id")
                if not customer_id:
                    logger.error("❌ User does not have a Stripe customer ID")
                    return False, None, "User does not have a Stripe customer ID"
                
                # Get Captain's Stripe Connect account ID for payment routing
                captain_stripe_account_id = None
                if captain_id:
                    try:
                        captain = await self.user_collection.find_one({"_id": ObjectId(captain_id)})
                        if captain:
                            captain_stripe_account_id = captain.get("stripe_connect_account_id")
                            if captain_stripe_account_id:
                                logger.info(f"✅ Found Captain's Stripe Connect account: {captain_stripe_account_id}")
                            else:
                                logger.warning(f"⚠️ Captain {captain_id} does not have a Stripe Connect account")
                        else:
                            logger.warning(f"⚠️ Captain {captain_id} not found")
                    except Exception as e:
                        logger.error(f"❌ Error fetching Captain's Stripe account: {e}")
                
                # Process payment using Stripe Connect (if captain has connect account)
                payment_result = await self._process_stripe_payment(
                    payment_method_id=request.payment_method_id,
                    amount=request.price,
                    price_id=request.price_id,
                    customer_name=user_name,
                    club_name=club_name,
                    customer_id=customer_id,
                    provider_account_id=captain_stripe_account_id,
                    user_id=user_id,
                    club_id=club_id,
                    club_name_based_id=request.club_name_based_id,
                    pricing_plan=request.pricing_plan.value
                )
                
                if not payment_result[0]:
                    error_msg = payment_result[3] if len(payment_result) > 3 else "Payment processing failed"
                    logger.error(f"❌ Payment processing failed: {error_msg}")
                    
                    # Send subscription failure notification to the user
                    try:
                        from services.notifications.notification_service import (
                            send_notification_to_users,
                            filter_users_by_notification_preference,
                            get_collections,
                        )
                        
                        # Filter by subscription alerts preference
                        enabled_user_ids = await filter_users_by_notification_preference(
                            [user_id],
                            "subscription_alerts"
                        )
                        
                        push_user_ids: List[str] = []
                        if enabled_user_ids:
                            collections = get_collections()
                            user_tokens_collection = collections.get_user_tokens_collection()
                            token_docs = await user_tokens_collection.find(
                                {"user_id": user_id, "is_active": True},
                                {"user_id": 1},
                            ).to_list(length=None)
                            if any(doc.get("user_id") for doc in token_docs):
                                push_user_ids = [user_id]
                        
                        title = f"Subscription Failed!"
                        body = f"Payment failed for {club_name}. Please try again or contact support."
                        
                        notification_data = {
                            "user_id": user_id,
                            "user_name": user_name,
                            "club_id": club_id,
                            "club_name": club_name,
                            "club_name_based_id": request.club_name_based_id,
                            "subscription_type": "paid",
                            "pricing_plan": request.pricing_plan.value,
                            "amount_attempted": request.price,
                            "error_message": error_msg,
                            "action": "subscription_failure"
                        }
                        
                        notification_result = await send_notification_to_users(
                            user_ids=push_user_ids,
                            title=title,
                            body=body,
                            notification_type="subscription_alerts",
                            data=notification_data,
                            click_action=f"club/{request.club_name_based_id}",
                            priority="high",
                            all_user_ids=[user_id],
                        )
                        logger.info(f"✅ Subscription failure notification stored for user {user_id}: {notification_result}")
                            
                    except Exception as e:
                        logger.error(f"⚠️ Failed to send subscription failure notification: {e}")
                    
                    return False, None, error_msg
                
                payment_intent_id = payment_result[1]
                subscription_id = payment_result[2]
                logger.info(f"✅ Payment processed successfully: {payment_intent_id}")
                logger.info(f"✅ Subscription created: {subscription_id}")
            
            # Step 7: Calculate membership duration
            logger.info(f"📋 Step 7: Calculating membership duration")
            end_date = self._calculate_membership_end_date(request.pricing_plan)
            logger.info(f"✅ Membership end date: {end_date}")
            
            # Step 8: Add member to club with paid membership
            logger.info(f"📋 Step 8: Adding member to club")
            membership_result = await self._add_paid_member_to_club(
                user_id=user_id,
                user_name=user_name,
                user_email=request.email,
                club_id=club_id,
                club_name=club_name,
                club_name_based_id=request.club_name_based_id,
                captain_id=captain_id,
                pricing_plan=request.pricing_plan,
                amount_paid=request.price,
                payment_id=payment_intent_id,
                subscription_id=subscription_id,
                end_date=end_date
            )
            if not membership_result[0]:
                logger.error(f"❌ Adding member to club failed: {membership_result[1]}")
                return False, None, membership_result[1]
            logger.info(f"✅ Member added to club successfully")

            # Step 8.1: Synchronize membership records across collections
            logger.info(f"📋 Step 8.1: Synchronizing membership records")
            await self._sync_membership_records(
                user_id=user_id,
                club_id=club_id,
                pricing_plan=request.pricing_plan,
                join_date=datetime.utcnow(),
                end_date=end_date,
                amount_paid=request.price,
                payment_id=payment_intent_id,
                subscription_id=subscription_id
            )
            
            # Step 9: Update user's club counts
            logger.info(f"📋 Step 9: Updating user club counts")
            await self._update_user_club_counts(user_id, is_paid=True)
            
            # Step 9.1: Recalculate and fix user's club counts to ensure accuracy
            logger.info(f"📋 Step 9.1: Recalculating user club counts for accuracy")
            await self._recalculate_user_club_counts(user_id)
            logger.info(f"✅ User club counts updated and recalculated")
            
            # Step 10: Get updated club statistics
            logger.info(f"📋 Step 10: Getting club statistics")
            club_stats = await self._get_club_statistics(club_id)
            user_stats = await self._get_user_club_statistics(user_id)
            logger.info(f"✅ Club stats: {club_stats}, User stats: {user_stats}")
            
            # Step 11: Create response
            logger.info(f"📋 Step 11: Creating response")
            response = JoinPaidResponse(
                success=True,
                message="Successfully joined club with paid membership",
                club_id=club_id,
                club_name=club_name,
                club_name_based_id=request.club_name_based_id,
                captain_name=club.get("captain_name", "Unknown"),
                member_details=PaidMemberDetails(
                    user_id=user_id,
                    full_name=user_name,
                    email=request.email,
                    status="active",
                    membership_type="paid",
                    membership_status="active",
                    join_date=datetime.utcnow(),
                    end_date=end_date,
                    pricing_plan=request.pricing_plan,
                    amount_paid=request.price,
                    payment_id=payment_intent_id
                ),
                join_date=datetime.utcnow(),
                end_date=end_date,
                pricing_plan=request.pricing_plan,
                amount_paid=request.price,
                payment_id=payment_intent_id,
                member_count=club_stats["total_members"],
                paid_member_count=club_stats["paid_members"],
                total_clubs_joined=user_stats["total_clubs_joined"],
                paid_clubs_joined=user_stats["paid_clubs_joined"]
            )
            
            logger.info(f"🎉 Successfully processed paid club join for user {user_id} to club {club_id}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"💥 Error in join_club_paid: {e}")
            import traceback
            traceback.print_exc()
            return False, None, f"Internal server error: {str(e)}"
    
    async def _get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email from auth database"""
        try:
            logger.info(f"🔍 Searching for user with email: {email}")
            user = await self.user_collection.find_one({"email": email})
            if user:
                logger.info(f"✅ User found: {user.get('full_name', 'Unknown')} (ID: {user['_id']})")
                # Verify user is active
                if not user.get("is_active", True):
                    logger.warning(f"⚠️ User {email} is inactive")
                    return None
                return user
            else:
                logger.error(f"❌ User not found with email: {email}")
                return None
        except Exception as e:
            logger.error(f"💥 Error getting user by email {email}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _get_club_by_name_based_id(self, name_based_id: str) -> Optional[Dict[str, Any]]:
        """Get club by name-based ID"""
        try:
            logger.info(f"🔍 Searching for club with name_based_id: {name_based_id}")
            club = await self.club_collection.find_one({"name_based_id": name_based_id})
            if club:
                logger.info(f"✅ Club found: {club.get('name', 'Unknown')} (ID: {club['_id']})")
                logger.info(f"📋 Club status: {club.get('status', 'unknown')}")
                logger.info(f"📋 Pricing plans count: {len(club.get('pricing_plans', []))}")
                return club
            else:
                logger.error(f"❌ Club not found with name_based_id: {name_based_id}")
                return None
        except Exception as e:
            logger.error(f"💥 Error getting club by name_based_id {name_based_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _get_existing_membership(self, user_id: str, club_id: str) -> Optional[Dict]:
        """Get existing membership details if user is already a member of the club"""
        try:
            # Check in clubs collection - paid members
            club = await self.club_collection.find_one({
                "_id": ObjectId(club_id),
                "paid_members.user_id": user_id
            })
            
            if club:
                # Find the specific member in paid_members array
                for member in club.get("paid_members", []):
                    if member.get("user_id") == user_id:
                        return {
                            "type": "paid",
                            "membership_data": member,
                            "club_data": club
                        }
            
            # Check in clubs collection - trial members
            club = await self.club_collection.find_one({
                "_id": ObjectId(club_id),
                "members.user_id": user_id
            })
            
            if club:
                # Find the specific member in members array
                for member in club.get("members", []):
                    if member.get("user_id") == user_id:
                        return {
                            "type": "trial",
                            "membership_data": member,
                            "club_data": club
                        }
            
            # Check in users collection - clubs_joined array
            user = await self.user_collection.find_one(
                {"_id": ObjectId(user_id)},
                {"clubs_joined": {"$elemMatch": {"club_id": club_id}}}
            )
            
            if user and user.get("clubs_joined"):
                return {
                    "type": "user_record",
                    "membership_data": user["clubs_joined"][0],
                    "user_data": user
                }
            
            # Check in memberships collection
            membership = await self.membership_collection.find_one({
                "user_id": ObjectId(user_id),
                "club_id": ObjectId(club_id),
                "status": {"$in": ["active", "pending"]}
            })
            
            if membership:
                return {
                    "type": "membership_record",
                    "membership_data": membership,
                    "user_data": None
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking existing membership for user {user_id} in club {club_id}: {e}")
            return None
    
    async def _handle_plan_change(self, user: Dict, club: Dict, existing_membership: Dict, request: JoinPaidRequest) -> Tuple[bool, Optional[JoinPaidResponse], str]:
        """Handle plan change for existing member"""
        try:
            logger.info(f"🔄 Processing plan change for existing member")
            
            user_id = str(user["_id"])
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            
            # Get current membership details
            current_membership = existing_membership["membership_data"]
            current_plan = current_membership.get("pricing_plan")
            current_end_date = current_membership.get("end_date")
            
            # Check if user is trying to change to the same plan
            if current_plan == request.pricing_plan.value:
                return False, None, f"You are already on the {request.pricing_plan.value} plan"
            
            # Validate new pricing plan and price
            logger.info(f"📋 Validating new pricing plan: {request.pricing_plan}, price: {request.price}")
            pricing_validation = await self._validate_pricing_plan(club, request.pricing_plan, request.price, request.price_id)
            if not pricing_validation[0]:
                logger.error(f"❌ Pricing validation failed: {pricing_validation[1]}")
                return False, None, pricing_validation[1]
            logger.info(f"✅ New pricing plan validated successfully")
            
            # Check if current subscription is still active
            now = datetime.now()
            if current_end_date and now > current_end_date:
                # Allow expired trial members to upgrade to paid membership
                current_membership_type = current_membership.get("membership_type", "")
                current_status = current_membership.get("status", "")
                current_membership_status = current_membership.get("membership_status", "")
                
                # If it's an expired trial membership, allow upgrade to paid
                if (current_membership_type == "trial" and 
                    current_status == "expired" and 
                    current_membership_status == "expired"):
                    logger.info(f"🔄 Allowing expired trial member to upgrade to paid membership")
                    return await self._handle_expired_trial_upgrade(user, club, existing_membership, request)
                else:
                    return False, None, "Your current subscription has expired. Please renew your subscription first."
            
            # Process Stripe payment for the new plan
            logger.info(f"📋 Processing Stripe payment for new plan")
            payment_result = await self._process_plan_change_payment(request, user, club)
            if not payment_result[0]:
                logger.error(f"❌ Payment processing failed: {payment_result[1]}")
                return False, None, payment_result[1]
            
            payment_intent_id = payment_result[1]
            logger.info(f"✅ Payment processed successfully: {payment_intent_id}")
            
            # Schedule the plan change (new plan starts after current plan ends)
            logger.info(f"📋 Scheduling plan change")
            plan_change_result = await self._schedule_plan_change(
                user_id, club_id, request, current_end_date, payment_intent_id, current_membership, club, user
            )
            if not plan_change_result[0]:
                logger.error(f"❌ Plan change scheduling failed: {plan_change_result[1]}")
                return False, None, plan_change_result[1]
            
            # Calculate new plan dates
            new_start_date = current_end_date + timedelta(days=1) if current_end_date else datetime.now()
            new_end_date = self._calculate_new_end_date(new_start_date, request.pricing_plan)
            
            # Build response
            response_data = JoinPaidResponse(
                success=True,
                message=f"Plan change scheduled successfully. Your new {request.pricing_plan.value} plan will start on {new_start_date.strftime('%Y-%m-%d')}.",
                club_id=club_id,
                club_name=club_name,
                club_name_based_id=request.club_name_based_id,
                captain_name="",  # Not needed for plan change
                member_details=PaidMemberDetails(
                    user_id=user_id,
                    full_name=user.get("full_name", "Unknown"),
                    email=user.get("email", ""),
                    status="active",
                    membership_type="paid",
                    membership_status="active",
                    join_date=current_membership.get("join_date", datetime.now()),
                    end_date=new_end_date,
                    pricing_plan=request.pricing_plan,
                    amount_paid=request.price,
                    payment_id=payment_intent_id
                ),
                join_date=current_membership.get("join_date", datetime.now()),
                end_date=new_end_date,
                pricing_plan=request.pricing_plan,
                amount_paid=request.price,
                payment_id=payment_intent_id,
                member_count=0,  # Will be calculated if needed
                paid_member_count=0,  # Will be calculated if needed
                total_clubs_joined=0,  # Will be calculated if needed
                paid_clubs_joined=0  # Will be calculated if needed
            )
            
            logger.info(f"✅ Plan change scheduled successfully for user {user_id}")
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"❌ Error in _handle_plan_change: {str(e)}")
            import traceback
            traceback.print_exc()
            return False, None, f"Error processing plan change: {str(e)}"
    
    async def _handle_expired_trial_upgrade(self, user: Dict, club: Dict, existing_membership: Dict, request: JoinPaidRequest) -> Tuple[bool, Optional[JoinPaidResponse], str]:
        """Handle upgrade from expired trial to paid membership"""
        try:
            logger.info(f"🔄 Processing expired trial to paid upgrade")
            
            user_id = str(user["_id"])
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            
            # Process Stripe payment for the new paid membership
            logger.info(f"📋 Processing Stripe payment for paid membership")
            payment_result = await self._process_stripe_payment(
                request.payment_method_id,
                request.price,
                request.price_id,
                user.get("full_name", "Unknown"),
                club_name,
                user.get("stripe_customer_id")
            )
            
            if not payment_result[0]:
                logger.error(f"❌ Payment processing failed: {payment_result[1]}")
                return False, None, payment_result[1]
            
            payment_intent_id = payment_result[1]
            subscription_id = payment_result[2]
            logger.info(f"✅ Payment processed successfully: {payment_intent_id}")
            
            # Calculate new membership dates
            now = datetime.now()
            new_end_date = self._calculate_new_end_date(now, request.pricing_plan)
            
            # Remove from trial members array and add to paid members array
            logger.info(f"📋 Moving user from trial to paid membership")
            upgrade_result = await self._upgrade_trial_to_paid(
                user_id, club_id, user, club, request, payment_intent_id, subscription_id, now, new_end_date
            )
            
            if not upgrade_result[0]:
                logger.error(f"❌ Trial to paid upgrade failed: {upgrade_result[1]}")
                return False, None, upgrade_result[1]
            
            # Update membership collection
            await self._update_membership_collection_for_paid(
                user_id, club_id, request, payment_intent_id, subscription_id, now, new_end_date
            )
            
            # Build response
            response_data = JoinPaidResponse(
                success=True,
                message="Successfully upgraded from trial to paid membership",
                club_id=club_id,
                club_name=club_name,
                club_name_based_id=request.club_name_based_id,
                captain_name=club.get("captain_details", {}).get("full_name", "Unknown Captain"),
                member_details=PaidMemberDetails(
                    user_id=user_id,
                    full_name=user.get("full_name", "Unknown"),
                    email=user.get("email", ""),
                    status="active",
                    membership_type="paid",
                    membership_status="active",
                    join_date=now,
                    end_date=new_end_date,
                    pricing_plan=request.pricing_plan,
                    amount_paid=request.price,
                    payment_id=payment_intent_id
                ),
                join_date=now,
                end_date=new_end_date,
                pricing_plan=request.pricing_plan,
                amount_paid=request.price,
                payment_id=payment_intent_id,
                member_count=upgrade_result[1].get("member_count", 0),
                paid_member_count=upgrade_result[1].get("paid_member_count", 0),
                total_clubs_joined=upgrade_result[1].get("total_clubs_joined", 0),
                paid_clubs_joined=upgrade_result[1].get("paid_clubs_joined", 0)
            )
            
            logger.info(f"✅ Successfully upgraded expired trial to paid membership for user {user_id}")
            return True, response_data, ""
            
        except Exception as e:
            logger.error(f"Error in expired trial upgrade: {e}")
            return False, None, f"Error processing trial upgrade: {str(e)}"
    
    async def _process_plan_change_payment(self, request: JoinPaidRequest, user: Dict, club: Dict) -> Tuple[bool, str]:
        """Process Stripe payment for plan change"""
        try:
            # For development/testing - allow bypass if Stripe not configured
            if not os.getenv('STRIPE_SECRET_KEY'):
                logger.warning("⚠️ Stripe not configured - bypassing payment for development")
                return True, f"dev_payment_{ObjectId()}"
            
            # Get Captain's Stripe Connect account ID for payment routing
            captain_stripe_account_id = None
            captain_id = str(club.get("captain_id", ""))
            if captain_id:
                try:
                    captain = await self.user_collection.find_one({"_id": ObjectId(captain_id)})
                    if captain:
                        captain_stripe_account_id = captain.get("stripe_connect_account_id")
                        if captain_stripe_account_id:
                            logger.info(f"✅ Found Captain's Stripe Connect account for plan change: {captain_stripe_account_id}")
                        else:
                            logger.warning(f"⚠️ Captain {captain_id} does not have a Stripe Connect account for plan change")
                    else:
                        logger.warning(f"⚠️ Captain {captain_id} not found for plan change")
                except Exception as e:
                    logger.error(f"❌ Error fetching Captain's Stripe account for plan change: {e}")
            
            # Build payment intent parameters
            payment_intent_params = {
                'amount': int(request.price * 100),  # Convert to cents
                'currency': 'usd',
                'payment_method': request.payment_method_id,
                'customer': user.get("stripe_customer_id"),
                'confirmation_method': 'manual',
                'payment_method_types': ["card"],
                'confirm': True,
                'metadata': {
                    "user_id": str(user["_id"]),
                    "club_name_based_id": request.club_name_based_id,
                    "pricing_plan": request.pricing_plan.value,
                    "payment_type": "plan_change"
                }
            }
            
            # Add Stripe Connect parameters ONLY if Captain has a Connect account
            if captain_stripe_account_id:
                logger.info(f"💰 Plan change using Stripe Connect - routing payment to Captain's account: {captain_stripe_account_id}")
                payment_intent_params['application_fee_amount'] = int(request.price * 100 * 0.05)  # Platform takes 5% fee
                payment_intent_params['transfer_data'] = {
                    'destination': captain_stripe_account_id,  # Send 95% to Captain's account
                }
            else:
                logger.info(f"💰 Plan change without Stripe Connect - processing as regular payment")
            
            # Create payment intent for the new plan
            payment_intent = stripe.PaymentIntent.create(**payment_intent_params)
            
            if payment_intent.status == 'succeeded':
                return True, payment_intent.id
            else:
                return False, f"Payment failed with status: {payment_intent.status}"
                
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {e}")
            return False, f"Payment processing failed: {str(e)}"
        except Exception as e:
            logger.error(f"Error processing payment: {e}")
            return False, f"Payment processing failed: {str(e)}"
    
    async def _schedule_plan_change(self, user_id: str, club_id: str, request: JoinPaidRequest, 
                                  current_end_date: datetime, payment_intent_id: str, current_membership: Dict, 
                                  club: Dict, user: Dict) -> Tuple[bool, str]:
        """Schedule the plan change to take effect after current subscription ends"""
        try:
            # Calculate new plan dates
            new_start_date = current_end_date + timedelta(days=1) if current_end_date else datetime.now()
            new_end_date = self._calculate_new_end_date(new_start_date, request.pricing_plan)
            
            # Create new plan change object in user's clubs_joined array
            new_plan_change_object = {
                "club_id": club_id,
                "club_name": club.get("name", "Unknown"),
                "club_name_based_id": club.get("name_based_id", ""),
                "captain_name": club.get("captain_name", ""),
                "membership_type": "paid",
                "membership_status": "upcoming",
                "pricing_plan": request.pricing_plan.value,
                "frequency": request.pricing_plan.value,
                "join_date": new_start_date,
                "end_date": new_end_date,
                "is_trial": False,
                "is_active": True,
                "payment_id": payment_intent_id,
                "amount_paid": request.price,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "status": "upcoming",
                "previous_plan": current_membership.get("pricing_plan"),
                "is_upgraded": True
            }
            
            user_update_result = await self.user_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$push": {"clubs_joined": new_plan_change_object}}
            )
            
            if user_update_result.modified_count == 0:
                return False, "Failed to schedule plan change in user record"
            
            # Create new plan change object in club's paid_members array
            new_plan_change_member = {
                "user_id": user_id,
                "full_name": user.get("full_name", "Unknown"),
                "email": user.get("email", ""),
                "status": "active",
                "membership_type": "paid",
                "membership_status": "upcoming",
                "join_date": new_start_date,
                "end_date": new_end_date,
                "pricing_plan": request.pricing_plan.value,
                "amount_paid": request.price,
                "payment_id": payment_intent_id,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "status": "upcoming",
                "previous_plan": current_membership.get("pricing_plan"),
                "is_upgraded": True
            }
            
            club_update_result = await self.club_collection.update_one(
                {"_id": ObjectId(club_id)},
                {"$push": {"paid_members": new_plan_change_member}}
            )
            
            if club_update_result.modified_count == 0:
                return False, "Failed to schedule plan change in club record"
            
            # Create new plan change record in club_memberships collection
            new_membership_record = {
                "user_id": ObjectId(user_id),
                "club_id": ObjectId(club_id),
                "club_name": club.get("name", "Unknown"),
                "club_name_based_id": club.get("name_based_id", ""),
                "captain_id": ObjectId(club.get("captain_id", "")),
                "membership_type": "paid",
                "membership_status": "upcoming",
                "pricing_plan": request.pricing_plan.value,
                "amount_paid": request.price,
                "payment_id": payment_intent_id,
                "status": "upcoming",
                "start_date": new_start_date,
                "end_date": new_end_date,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "previous_plan": current_membership.get("pricing_plan"),
                "is_upgraded": True
            }
            
            membership_insert_result = await self.membership_collection.insert_one(new_membership_record)
            
            if not membership_insert_result.inserted_id:
                logger.warning(f"Failed to create new plan change record in club_memberships for user {user_id} in club {club_id}")
                # Don't fail the entire operation, just log the warning
            
            return True, "Plan change scheduled successfully"
            
        except Exception as e:
            logger.error(f"Error scheduling plan change: {e}")
            return False, f"Error scheduling plan change: {str(e)}"
    
    def _calculate_new_end_date(self, start_date: datetime, pricing_plan: PricingPlan) -> datetime:
        """Calculate end date based on pricing plan"""
        if pricing_plan == PricingPlan.DAILY:
            return start_date + timedelta(days=1)
        elif pricing_plan == PricingPlan.WEEKLY:
            return start_date + timedelta(weeks=1)
        elif pricing_plan == PricingPlan.MONTHLY:
            return start_date + timedelta(days=30)  # Approximate month
        elif pricing_plan == PricingPlan.QUARTERLY:
            return start_date + timedelta(days=90)  # Approximate quarter
        elif pricing_plan == PricingPlan.YEARLY:
            return start_date + timedelta(days=365)  # Approximate year
        else:
            return start_date + timedelta(days=30)  # Default to monthly
    
    async def _validate_pricing_plan(self, club: Dict[str, Any], pricing_plan: PricingPlan, price: float, price_id: str) -> Tuple[bool, str]:
        """Validate pricing plan against club's available plans"""
        try:
            # Get club's pricing plans
            club_pricing_plans = club.get("pricing_plans", [])
            
            # Find matching pricing plan
            matching_plan = None
            for plan in club_pricing_plans:
                # Check both 'plan' and 'frequency' fields (database uses 'frequency')
                plan_type = plan.get("plan") or plan.get("frequency")
                if plan_type == pricing_plan.value:
                    matching_plan = plan
                    break
            
            if not matching_plan:
                available_plans = [plan.get("plan") or plan.get("frequency") for plan in club_pricing_plans]
                return False, f"Pricing plan '{pricing_plan.value}' not available for this club. Available plans: {available_plans}"
            
            # Validate price
            expected_price = matching_plan.get("price", 0)
            if abs(price - expected_price) > 0.01:  # Allow small floating point differences
                return False, f"Price mismatch. Expected: ${expected_price}, Received: ${price}"
            
            # Validate price_id with Stripe (optional - can be enhanced)
            # For now, we'll just log it
            logger.info(f"Validating price_id {price_id} for plan {pricing_plan.value}")
            
            return True, ""
            
        except Exception as e:
            logger.error(f"Error validating pricing plan: {e}")
            return False, f"Error validating pricing plan: {str(e)}"
    
    async def _check_trial_restrictions(self, user: Dict[str, Any], request: JoinPaidRequest) -> Tuple[bool, str]:
        """Check trial membership restrictions"""
        try:
            user_id = str(user["_id"])
            
            # Check if user is on trial
            is_trial = await is_user_trial_member(user_id)
            
            if is_trial:
                # Get trial status (returns TrialMembershipStatus Pydantic model)
                trial_status = await get_trial_membership_status(user_id)
                
                if trial_status and trial_status.is_trial_user:
                    clubs_joined_count = trial_status.clubs_joined_count
                    
                    # If user has joined 4 or more trial clubs, they can only join via paid
                    if clubs_joined_count >= 4:
                        logger.info(f"Trial user {user_id} has joined {clubs_joined_count} clubs, allowing paid join")
                        return True, ""
                    else:
                        # User can still join free clubs, but paid is also allowed
                        logger.info(f"Trial user {user_id} has joined {clubs_joined_count} clubs, paid join allowed")
                        return True, ""
            
            # Non-trial users can always join paid clubs
            return True, ""
            
        except Exception as e:
            logger.error(f"Error checking trial restrictions: {e}")
            return False, f"Error checking trial restrictions: {str(e)}"
    
    async def _process_stripe_payment(self, payment_method_id: str, amount: float, price_id: str, customer_name: str, club_name: str, customer_id: str = None, provider_account_id: str = None, user_id: str = None, club_id: str = None, club_name_based_id: str = None, pricing_plan: str = None) -> Tuple[bool, Optional[str], Optional[str], str]:
        """
        Process payment through Stripe and create subscription for recurring billing
        
        Args:
            payment_method_id: Stripe payment method ID
            amount: Payment amount
            price_id: Stripe price ID
            customer_name: Customer's name
            club_name: Club name
            customer_id: Stripe customer ID
            provider_account_id: Captain's Stripe Connect account ID (for payment routing)
        """
        try:
            logger.info(f"💳 Creating Stripe subscription for ${amount}")
            logger.info(f"💳 Payment method ID: {payment_method_id}")
            logger.info(f"💳 Price ID: {price_id}")
            logger.info(f"💳 Customer ID: {customer_id}")
            logger.info(f"💳 Provider Account ID (Captain): {provider_account_id}")
            
            # Check if Stripe is configured
            if not stripe.api_key:
                logger.error("❌ Stripe API key not configured")
                return False, None, None, "Payment processing not configured"
            
            # Create or get customer
            if not customer_id:
                logger.error("❌ Customer ID is required for subscription")
                return False, None, None, "Customer ID is required"
            
            # First, attach the payment method to the customer (if not already attached)
            logger.info(f"💳 Attaching payment method {payment_method_id} to customer {customer_id}")
            try:
                stripe.PaymentMethod.attach(
                    payment_method_id,
                    customer=customer_id,
                )
                logger.info(f"✅ Payment method attached to customer")
            except stripe.error.InvalidRequestError as e:
                if "already attached" in str(e).lower():
                    logger.info(f"ℹ️ Payment method already attached to customer")
                else:
                    logger.error(f"❌ Error attaching payment method: {e}")
                    return False, None, None, f"Error attaching payment method: {str(e)}"
            
            # Set the payment method as default for the customer
            try:
                stripe.Customer.modify(
                    customer_id,
                    invoice_settings={
                        'default_payment_method': payment_method_id,
                    },
                )
                logger.info(f"✅ Payment method set as default for customer")
            except Exception as e:
                logger.error(f"❌ Error setting default payment method: {e}")
                return False, None, None, f"Error setting default payment method: {str(e)}"
            
            # Try to create subscription for recurring billing
            try:
                # Build subscription parameters
                subscription_params = {
                    'customer': customer_id,
                    'items': [{
                        'price': price_id,
                    }],
                    'payment_behavior': 'default_incomplete',
                    'payment_settings': {'save_default_payment_method': 'on_subscription'},
                    'expand': ['latest_invoice.payment_intent'],
                    'metadata': {
                        'payment_type': 'join_paid_subscription',  # ✅ Added for webhook routing
                        'user_id': user_id or '',  # ✅ Added for webhook handler
                        'club_id': club_id or '',  # ✅ Added for webhook handler
                        'club_name_based_id': club_name_based_id or '',  # ✅ Added for identification
                        'pricing_plan': pricing_plan or '',  # ✅ Added for renewal calculation
                        'club_name': club_name,
                        'customer_name': customer_name,
                    }
                }
                
                # Add Stripe Connect parameters ONLY if Captain has a Connect account
                if provider_account_id:
                    logger.info(f"💰 Using Stripe Connect - routing payment to Captain's account: {provider_account_id}")
                    subscription_params['application_fee_percent'] = 5  # Platform takes 5% fee
                    subscription_params['transfer_data'] = {
                        'destination': provider_account_id,  # Send 95% to Captain's account
                    }
                else:
                    logger.info(f"💰 Captain has no Stripe Connect account - processing as regular payment")
                
                subscription = stripe.Subscription.create(**subscription_params)
                
                logger.info(f"💳 Subscription created: {subscription.id}")
                logger.info(f"💳 Subscription status: {subscription.status}")
                
                # Get payment intent from the latest invoice
                invoice = subscription.latest_invoice
                payment_intent = invoice.payment_intent
                
                logger.info(f"💳 Payment intent: {payment_intent.id}")
                logger.info(f"💳 Payment intent status: {payment_intent.status}")
                
                # Confirm the payment intent with the payment method
                if payment_intent.status in ['requires_confirmation', 'requires_payment_method']:
                    payment_intent = stripe.PaymentIntent.confirm(
                        payment_intent.id,
                        payment_method=payment_method_id
                    )
                
                logger.info(f"💳 Payment intent after confirmation: {payment_intent.status}")
                
                if payment_intent.status == 'succeeded':
                    logger.info(f"✅ Payment succeeded: {payment_intent.id}")
                    logger.info(f"✅ Subscription created: {subscription.id}")
                    return True, payment_intent.id, subscription.id, ""
                else:
                    logger.error(f"❌ Payment failed with status: {payment_intent.status}")
                    return False, None, None, f"Payment failed with status: {payment_intent.status}"
                    
            except stripe.error.StripeError as e:
                logger.error(f"❌ Error creating subscription: {e}")
                # Fallback: Create a simple payment intent instead
                logger.info(f"🔄 Falling back to payment intent creation")
                return await self._create_fallback_payment_intent(
                    payment_method_id, amount, customer_name, club_name, customer_id
                )
                
        except stripe.error.CardError as e:
            logger.error(f"💳❌ Card error: {e}")
            return False, None, None, f"Card error: {str(e)}"
        except stripe.error.StripeError as e:
            logger.error(f"💳❌ Stripe error: {e}")
            return False, None, None, f"Payment processing error: {str(e)}"
        except Exception as e:
            logger.error(f"💳❌ Unexpected error in payment processing: {e}")
            import traceback
            traceback.print_exc()
            return False, None, None, f"Payment processing error: {str(e)}"
    
    async def _create_fallback_payment_intent(self, payment_method_id: str, amount: float, customer_name: str, club_name: str, customer_id: str) -> Tuple[bool, Optional[str], Optional[str], str]:
        """Fallback method to create a simple payment intent when subscription creation fails"""
        try:
            logger.info(f"💳 Creating fallback payment intent for ${amount}")
            
            # Create a simple payment intent
            payment_intent = stripe.PaymentIntent.create(
                amount=int(amount * 100),  # Convert to cents
                currency='usd',
                customer=customer_id,
                payment_method=payment_method_id,
                confirm=True,
                payment_method_types=["card"],
                description=f"Paid membership for {club_name}",
                metadata={
                    'club_name': club_name,
                    'customer_name': customer_name,
                    'payment_type': 'fallback'
                }
            )
            
            logger.info(f"💳 Fallback payment intent created: {payment_intent.id}")
            logger.info(f"💳 Payment intent status: {payment_intent.status}")
            
            if payment_intent.status == 'succeeded':
                logger.info(f"✅ Fallback payment succeeded: {payment_intent.id}")
                # For fallback, we don't have a subscription ID, so we'll create a placeholder
                subscription_id = f"fallback_{payment_intent.id}"
                return True, payment_intent.id, subscription_id, ""
            else:
                logger.error(f"❌ Fallback payment failed with status: {payment_intent.status}")
                return False, None, None, f"Fallback payment failed with status: {payment_intent.status}"
                
        except Exception as e:
            logger.error(f"💳❌ Error in fallback payment intent: {e}")
            return False, None, None, f"Fallback payment error: {str(e)}"
    
    def _calculate_membership_end_date(self, pricing_plan: PricingPlan) -> datetime:
        """Calculate membership end date based on pricing plan"""
        now = datetime.utcnow()
        
        if pricing_plan == PricingPlan.DAILY:
            return now + timedelta(days=1)
        elif pricing_plan == PricingPlan.WEEKLY:
            return now + timedelta(weeks=1)  # 7 days
        elif pricing_plan == PricingPlan.MONTHLY:
            return now + timedelta(days=30)
        elif pricing_plan == PricingPlan.QUARTERLY:
            return now + timedelta(days=90)
        elif pricing_plan == PricingPlan.YEARLY:
            return now + timedelta(days=365)
        else:
            # Default to monthly
            return now + timedelta(days=30)
    
    async def _add_paid_member_to_club(self, user_id: str, user_name: str, user_email: str, club_id: str, 
                                     club_name: str, club_name_based_id: str, captain_id: str, 
                                     pricing_plan: PricingPlan, amount_paid: float, payment_id: str, 
                                     subscription_id: str, end_date: datetime) -> Tuple[bool, str]:
        """Add paid member to club with detailed information"""
        try:
            now = datetime.utcnow()
            
            # Get captain name for the club
            captain_name = await self._get_captain_name(captain_id)
            
            # Create paid member details for club's paid_members array
            paid_member_details = {
                "user_id": user_id,
                "full_name": user_name,
                "email": user_email,
                "status": "active",
                "membership_type": "paid",
                "membership_status": "active",
                "join_date": now,
                "end_date": end_date,
                "pricing_plan": pricing_plan.value,
                "amount_paid": amount_paid,
                "payment_id": payment_id,
                "subscription_id": subscription_id
            }
            
            # Add to club's paid_members array
            await self.club_collection.update_one(
                {"_id": ObjectId(club_id)},
                {
                    "$addToSet": {"paid_members": paid_member_details},
                    "$set": {"updated_at": now}
                }
            )
            
            # Recalculate member counts to ensure accuracy
            await self._recalculate_club_member_counts(club_id)
            
            # Create detailed club membership info for user's clubs_joined array
            club_membership_info = {
                "club_id": club_id,
                "club_name": club_name,
                "club_name_based_id": club_name_based_id,
                "captain_name": captain_name,
                "membership_type": "paid",
                "membership_status": "active",
                "pricing_plan": pricing_plan.value,
                "frequency": pricing_plan.value,  # Store frequency as well
                "join_date": now,
                "end_date": end_date,
                "is_trial": False,
                "is_active": True,
                "payment_id": payment_id,
                "subscription_id": subscription_id,
                "amount_paid": amount_paid,
                "created_at": now,
                "updated_at": now
            }
            
            # Add to user's clubs_joined array in auth database
            await self._add_club_to_user_joined_clubs(user_id, club_membership_info)
            
            # Recalculate counts to ensure accuracy
            await self._recalculate_user_club_counts(user_id)
            
            # Create membership record in club service
            membership_doc = {
                "user_id": ObjectId(user_id),
                "club_id": ObjectId(club_id),
                "club_name": club_name,
                "club_name_based_id": club_name_based_id,
                "captain_id": ObjectId(captain_id),
                "membership_type": "paid",
                "pricing_plan": pricing_plan.value,
                "amount_paid": amount_paid,
                "payment_id": payment_id,
                "subscription_id": subscription_id,
                "status": "active",
                "start_date": now,
                "end_date": end_date,
                "created_at": now,
                "updated_at": now
            }
            
            await self.membership_collection.insert_one(membership_doc)
            
            logger.info(f"Successfully added paid member {user_id} to club {club_id}")
            
            # Send subscription success notification to the new paid member
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                # Filter by subscription alerts preference
                enabled_user_ids = await filter_users_by_notification_preference(
                    [user_id],
                    "subscription_alerts"
                )
                
                push_user_ids: List[str] = []
                if enabled_user_ids:
                    collections = get_collections()
                    user_tokens_collection = collections.get_user_tokens_collection()
                    token_docs = await user_tokens_collection.find(
                        {"user_id": user_id, "is_active": True},
                        {"user_id": 1},
                    ).to_list(length=None)
                    if any(doc.get("user_id") for doc in token_docs):
                        push_user_ids = [user_id]
                
                title = f"Subscription Successful!"
                body = f"Welcome to {club_name}! Your {pricing_plan.value} subscription is now active"
                
                notification_data = {
                    "user_id": user_id,
                    "user_name": user_name,
                    "club_id": club_id,
                    "club_name": club_name,
                    "club_name_based_id": club_name_based_id,
                    "captain_name": captain_name,
                    "subscription_type": "paid",
                    "pricing_plan": pricing_plan.value,
                    "amount_paid": amount_paid,
                    "payment_id": payment_id,
                    "subscription_id": subscription_id,
                    "start_date": now.isoformat(),
                    "end_date": end_date.isoformat(),
                    "action": "subscription_success"
                }
                
                notification_result = await send_notification_to_users(
                    user_ids=push_user_ids,
                    title=title,
                    body=body,
                    notification_type="subscription_alerts",
                    data=notification_data,
                    click_action=f"club/{club_name_based_id}",
                    priority="high",
                    all_user_ids=[user_id],
                )
                logger.info(f"✅ Subscription success notification stored for user {user_id}: {notification_result}")
                    
            except Exception as e:
                logger.error(f"⚠️ Failed to send subscription success notification: {e}")
            
            return True, ""
            
        except Exception as e:
            logger.error(f"Error adding paid member to club: {e}")
            return False, f"Error adding paid member to club: {str(e)}"
    
    async def _update_user_club_counts(self, user_id: str, is_paid: bool = False):
        """Update user's club counts in auth database"""
        try:
            # Try to import auth service functions first
            try:
                import sys
                import os
                auth_service_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'betting_auth_service', 'auth')
                if auth_service_path not in sys.path:
                    sys.path.append(auth_service_path)
                
                from utils import update_user_club_count
                
                # Update club_count to 1 (stays 1 forever for members)
                await update_user_club_count(user_id, 1)
                logger.info(f"Updated user {user_id} club_count to 1 via auth service")
                
            except ImportError as import_error:
                logger.warning(f"Could not import auth service functions: {import_error}")
                # Fallback: try to update directly in auth database
                try:
                    from motor.motor_asyncio import AsyncIOMotorClient
                    import os
                    
                    # Get auth database connection
                    auth_db_url = os.getenv('MONGO_URL', 'mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main')
                    auth_client = AsyncIOMotorClient(auth_db_url)
                    auth_db = auth_client.get_database('betting_main')
                    auth_users_collection = auth_db['users']
                    
                    # Update club counts using proper MongoDB operations
                    now = datetime.utcnow()
                    
                    # Build update operations
                    update_operations = {
                        "$set": {
                            "club_count": 1,
                            "updated_at": now
                        }
                    }
                    
                    # Add increment operations
                    inc_operations = {}
                    if is_paid:
                        inc_operations["paid_clubs_joined"] = 1
                    inc_operations["total_clubs_joined"] = 1
                    
                    if inc_operations:
                        update_operations["$inc"] = inc_operations
                    
                    result = await auth_users_collection.update_one(
                        {"_id": ObjectId(user_id)},
                        update_operations
                    )
                    
                    if result.modified_count > 0:
                        logger.info(f"Updated user {user_id} club counts (direct database update)")
                    else:
                        logger.warning(f"No document updated for user {user_id} club counts")
                    
                except Exception as direct_error:
                    logger.error(f"Could not update user club counts directly: {direct_error}")
            except Exception as update_error:
                logger.error(f"Error updating user club counts via auth service: {update_error}")
                
        except Exception as e:
            logger.error(f"Error in _update_user_club_counts: {e}")
    
    async def _get_club_statistics(self, club_id: str) -> Dict[str, int]:
        """Get club statistics"""
        try:
            club = await self.club_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                return {"total_members": 0, "paid_members": 0}
            
            total_members = len(club.get("members", [])) + len(club.get("paid_members", []))
            paid_members = len(club.get("paid_members", []))
            
            return {
                "total_members": total_members,
                "paid_members": paid_members
            }
            
        except Exception as e:
            logger.error(f"Error getting club statistics: {e}")
            return {"total_members": 0, "paid_members": 0}
    
    async def _get_user_club_statistics(self, user_id: str) -> Dict[str, int]:
        """Get user's club statistics"""
        try:
            user = await self.user_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return {"total_clubs_joined": 0, "paid_clubs_joined": 0}
            
            total_clubs_joined = user.get("total_clubs_joined", 0)
            paid_clubs_joined = user.get("paid_clubs_joined", 0)
            
            return {
                "total_clubs_joined": total_clubs_joined,
                "paid_clubs_joined": paid_clubs_joined
            }
            
        except Exception as e:
            logger.error(f"Error getting user club statistics: {e}")
            return {"total_clubs_joined": 0, "paid_clubs_joined": 0}
    
    async def _recalculate_club_member_counts(self, club_id: str):
        """Recalculate club member counts from actual arrays"""
        try:
            # Get the club document
            club = await self.club_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                logger.error(f"Club {club_id} not found for count recalculation")
                return
            
            # Count members from arrays
            paid_members = club.get("paid_members", [])
            members = club.get("members", [])
            
            paid_member_count = len(paid_members)
            member_count = len(members)
            total_members = paid_member_count + member_count
            
            # Update club with accurate counts
            await self.club_collection.update_one(
                {"_id": ObjectId(club_id)},
                {
                    "$set": {
                        "paid_member_count": paid_member_count,
                        "member_count": member_count,
                        "total_members": total_members,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"Recalculated club {club_id} counts: paid={paid_member_count}, trial={member_count}, total={total_members}")
            
        except Exception as e:
            logger.error(f"Error recalculating club member counts: {e}")
    
    async def _sync_membership_records(
        self,
        user_id: str,
        club_id: str,
        pricing_plan: PricingPlan,
        join_date: datetime,
        end_date: datetime,
        amount_paid: float,
        payment_id: str,
        subscription_id: str,
    ) -> None:
        """
        Ensure membership information is consistent across clubs, users, and club_memberships collections.
        """
        try:
            now = datetime.utcnow()

            await self.club_collection.update_one(
                {"_id": ObjectId(club_id), "paid_members.user_id": user_id},
                {
                    "$set": {
                        "paid_members.$.end_date": end_date,
                        "paid_members.$.join_date": join_date,
                        "paid_members.$.pricing_plan": pricing_plan.value,
                        "paid_members.$.amount_paid": amount_paid,
                        "paid_members.$.payment_id": payment_id,
                        "paid_members.$.subscription_id": subscription_id,
                        "paid_members.$.status": "active",
                        "paid_members.$.membership_status": "active",
                        "paid_members.$.is_active": True,
                        "paid_members.$.updated_at": now,
                    }
                },
            )

            await self.user_collection.update_one(
                {"_id": ObjectId(user_id), "clubs_joined.club_id": club_id},
                {
                    "$set": {
                        "clubs_joined.$.end_date": end_date,
                        "clubs_joined.$.join_date": join_date,
                        "clubs_joined.$.pricing_plan": pricing_plan.value,
                        "clubs_joined.$.frequency": pricing_plan.value,
                        "clubs_joined.$.amount_paid": amount_paid,
                        "clubs_joined.$.payment_id": payment_id,
                        "clubs_joined.$.subscription_id": subscription_id,
                        "clubs_joined.$.membership_status": "active",
                        "clubs_joined.$.is_active": True,
                        "clubs_joined.$.status": "active",
                        "clubs_joined.$.updated_at": now,
                    }
                },
            )

            await self.membership_collection.update_one(
                {"user_id": ObjectId(user_id), "club_id": ObjectId(club_id)},
                {
                    "$set": {
                        "membership_type": "paid",
                        "pricing_plan": pricing_plan.value,
                        "amount_paid": amount_paid,
                        "payment_id": payment_id,
                        "subscription_id": subscription_id,
                        "status": "active",
                        "start_date": join_date,
                        "end_date": end_date,
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "user_id": ObjectId(user_id),
                        "club_id": ObjectId(club_id),
                        "created_at": now,
                    },
                },
                upsert=True,
            )

        except Exception as e:
            logger.error(
                f"Error synchronizing membership records for user {user_id} and club {club_id}: {e}"
            )

    async def _get_captain_name(self, captain_id: str) -> str:
        """Get captain name by captain ID"""
        try:
            if not captain_id:
                return "Unknown Captain"
            
            captain = await self.user_collection.find_one({"_id": ObjectId(captain_id)})
            if captain:
                return captain.get("full_name", "Unknown Captain")
            return "Unknown Captain"
        except Exception as e:
            logger.error(f"Error getting captain name for {captain_id}: {e}")
            return "Unknown Captain"
    
    async def _add_club_to_user_joined_clubs(self, user_id: str, club_membership_info: Dict[str, Any]) -> bool:
        """Add club membership info to user's clubs_joined array in auth database"""
        try:
            logger.info(f"📝 Adding club to user's clubs_joined array: {club_membership_info['club_name']}")
            
            # First, get current user data to calculate accurate counts
            user = await self.user_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                logger.error(f"❌ User not found: {user_id}")
                return False
            
            current_clubs_joined = user.get("clubs_joined", [])
            
            # Calculate current counts
            current_total = len(current_clubs_joined)
            current_paid = len([club for club in current_clubs_joined if club.get("membership_type") == "paid"])
            
            # Add the new club to the array
            updated_clubs_joined = current_clubs_joined + [club_membership_info]
            
            # Calculate new counts
            new_total = len(updated_clubs_joined)
            new_paid = len([club for club in updated_clubs_joined if club.get("membership_type") == "paid"])
            
            logger.info(f"📊 Count update: total {current_total} → {new_total}, paid {current_paid} → {new_paid}")
            
            # Update user's clubs_joined array with accurate counts
            result = await self.user_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "clubs_joined": updated_clubs_joined,
                        "total_clubs_joined": new_total,
                        "paid_clubs_joined": new_paid,
                        "club_count": 1,  # Always 1 for members
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Successfully added club to user's clubs_joined array with accurate counts")
                return True
            else:
                logger.warning(f"⚠️ No document updated for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"💥 Error adding club to user's clubs_joined array: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _recalculate_user_club_counts(self, user_id: str) -> bool:
        """Recalculate and fix user's club counts based on actual clubs_joined array"""
        try:
            logger.info(f"🔄 Recalculating club counts for user: {user_id}")
            
            user = await self.user_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                logger.error(f"❌ User not found: {user_id}")
                return False
            
            clubs_joined = user.get("clubs_joined", [])
            
            # Calculate accurate counts
            total_clubs = len(clubs_joined)
            paid_clubs = len([club for club in clubs_joined if club.get("membership_type") == "paid"])
            trial_clubs = len([club for club in clubs_joined if club.get("membership_type") == "trial"])
            
            logger.info(f"📊 Recalculated counts: total={total_clubs}, paid={paid_clubs}, trial={trial_clubs}")
            
            # Update with accurate counts
            result = await self.user_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "total_clubs_joined": total_clubs,
                        "paid_clubs_joined": paid_clubs,
                        "club_count": 1 if total_clubs > 0 else 0,  # 1 if any clubs joined, 0 if none
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Successfully recalculated club counts for user {user_id}")
                return True
            else:
                logger.warning(f"⚠️ No document updated for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"💥 Error recalculating club counts: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _upgrade_trial_to_paid(self, user_id: str, club_id: str, user: Dict, club: Dict, request: JoinPaidRequest, 
                                   payment_intent_id: str, subscription_id: str, now: datetime, new_end_date: datetime) -> Tuple[bool, Dict]:
        """Move user from trial members array to paid members array"""
        try:
            logger.info(f"🔄 Moving user {user_id} from trial to paid membership")
            
            # Prepare paid member details
            paid_member_details = {
                "user_id": user_id,
                "full_name": user.get("full_name", "Unknown"),
                "email": user.get("email", ""),
                "status": "active",
                "membership_type": "paid",
                "membership_status": "active",
                "join_date": now,
                "end_date": new_end_date,
                "pricing_plan": request.pricing_plan.value,
                "amount_paid": request.price,
                "payment_id": payment_intent_id,
                "subscription_id": subscription_id,
                "is_active": True,
                "created_at": now,
                "updated_at": now
            }
            
            # Remove from members array (trial) and add to paid_members array
            club_object_id = ObjectId(club_id)
            
            # Use atomic operation to remove from trial and add to paid
            result = await self.club_collection.update_one(
                {
                    "_id": club_object_id,
                    "members.user_id": user_id
                },
                {
                    "$pull": {"members": {"user_id": user_id}},
                    "$push": {"paid_members": paid_member_details},
                    "$set": {"updated_at": now}
                }
            )
            
            if result.modified_count == 0:
                logger.error(f"❌ Failed to move user {user_id} from trial to paid membership")
                return False, {}
            
            # Update user's clubs_joined array
            await self._update_user_clubs_joined_for_paid(user_id, club_id, paid_member_details)
            
            # Recalculate club counts
            await self._recalculate_club_member_counts(club_id)
            
            # Get updated counts
            updated_club = await self.club_collection.find_one({"_id": club_object_id})
            counts = {
                "total_members": updated_club.get("total_members", 0),
                "paid_member_count": updated_club.get("paid_member_count", 0),
                "member_count": updated_club.get("member_count", 0),
                "total_clubs_joined": 1,
                "paid_clubs_joined": 1
            }
            
            logger.info(f"✅ Successfully moved user {user_id} from trial to paid membership")
            
            # Send subscription upgrade notification to the user
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                # Filter by subscription alerts preference
                enabled_user_ids = await filter_users_by_notification_preference(
                    [user_id],
                    "subscription_alerts"
                )
                
                push_user_ids: List[str] = []
                if enabled_user_ids:
                    collections = get_collections()
                    user_tokens_collection = collections.get_user_tokens_collection()
                    token_docs = await user_tokens_collection.find(
                        {"user_id": user_id, "is_active": True},
                        {"user_id": 1},
                    ).to_list(length=None)
                    if any(doc.get("user_id") for doc in token_docs):
                        push_user_ids = [user_id]
                
                club_name = club.get("name", "Club")
                club_name_based_id = club.get("name_based_id", "")
                
                title = f"Subscription Upgraded!"
                body = f"Your trial has been upgraded to {request.pricing_plan.value} subscription in {club_name}!"
                
                notification_data = {
                    "user_id": user_id,
                    "user_name": user.get("full_name", "User"),
                    "club_id": club_id,
                    "club_name": club_name,
                    "club_name_based_id": club_name_based_id,
                    "subscription_type": "upgraded_from_trial",
                    "pricing_plan": request.pricing_plan.value,
                    "amount_paid": request.price,
                    "payment_id": payment_intent_id,
                    "subscription_id": subscription_id,
                    "start_date": now.isoformat(),
                    "end_date": new_end_date.isoformat(),
                    "action": "subscription_upgrade"
                }
                
                notification_result = await send_notification_to_users(
                    user_ids=push_user_ids,
                    title=title,
                    body=body,
                    notification_type="subscription_alerts",
                    data=notification_data,
                    click_action=f"club/{club_name_based_id}",
                    priority="high",
                    all_user_ids=[user_id],
                )
                logger.info(f"✅ Subscription upgrade notification stored for user {user_id}: {notification_result}")
                    
            except Exception as e:
                logger.error(f"⚠️ Failed to send subscription upgrade notification: {e}")
            
            # Synchronize membership records after upgrade
            await self._sync_membership_records(
                user_id=user_id,
                club_id=club_id,
                pricing_plan=request.pricing_plan,
                join_date=now,
                end_date=new_end_date,
                amount_paid=request.price,
                payment_id=payment_intent_id,
                subscription_id=subscription_id,
            )
            
            return True, counts
            
        except Exception as e:
            logger.error(f"Error upgrading trial to paid: {e}")
            return False, {}
    
    async def _update_user_clubs_joined_for_paid(self, user_id: str, club_id: str, paid_member_details: Dict):
        """Update user's clubs_joined array with paid membership details"""
        try:
            user_object_id = ObjectId(user_id)
            
            # Update the club in user's clubs_joined array
            await self.user_collection.update_one(
                {
                    "_id": user_object_id,
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.status": "active",
                        "clubs_joined.$.membership_status": "active",
                        "clubs_joined.$.membership_type": "paid",
                        "clubs_joined.$.pricing_plan": paid_member_details["pricing_plan"],
                        "clubs_joined.$.amount_paid": paid_member_details["amount_paid"],
                        "clubs_joined.$.payment_id": paid_member_details["payment_id"],
                        "clubs_joined.$.subscription_id": paid_member_details["subscription_id"],
                        "clubs_joined.$.end_date": paid_member_details["end_date"],
                        "clubs_joined.$.is_active": True,
                        "clubs_joined.$.updated_at": paid_member_details["updated_at"]
                    }
                }
            )
            
            logger.info(f"✅ Updated user {user_id} clubs_joined array for paid membership")
            
        except Exception as e:
            logger.error(f"Error updating user clubs_joined for paid: {e}")
    
    async def _update_membership_collection_for_paid(self, user_id: str, club_id: str, request: JoinPaidRequest, 
                                                   payment_intent_id: str, subscription_id: str, now: datetime, new_end_date: datetime):
        """Update membership collection for paid membership"""
        try:
            # Update or create membership record
            membership_doc = {
                "user_id": ObjectId(user_id),
                "club_id": ObjectId(club_id),
                "pricing_plan": request.pricing_plan.value,
                "subscription_status": "active",
                "membership_status": "active",
                "is_trial_membership": False,
                "joined_date": now,
                "expires_date": new_end_date,
                "payment_id": payment_intent_id,
                "subscription_id": subscription_id,
                "amount_paid": request.price,
                "refund_eligible": False,
                "refund_deadline": None,
                "created_at": now,
                "updated_at": now
            }
            
            # Update existing membership or create new one
            await self.membership_collection.update_one(
                {
                    "user_id": ObjectId(user_id),
                    "club_id": ObjectId(club_id)
                },
                {"$set": membership_doc},
                upsert=True
            )
            
            logger.info(f"✅ Updated membership collection for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error updating membership collection for paid: {e}")
