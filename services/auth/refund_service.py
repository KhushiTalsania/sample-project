"""
Refund Service for Trial Memberships

This service handles the complex refund logic for trial memberships based on the business rules:
1. Only Members with role="Member" are eligible for refunds
2. Refunds are only available for portal/platform fees ($19.95)
3. Refund eligibility depends on when user first joined a club as trial
4. Processing fees are deducted from refund amount
5. Refunds affect membership status and club memberships differently based on join type
"""

from typing import Tuple, Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import logging
import stripe
import os

# Import database functions when needed to avoid circular imports

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')

# Configuration
TRIAL_REFUND_PERIOD_DAYS = 7
PORTAL_FEE_AMOUNT = 19.95
STRIPE_PROCESSING_FEE_PERCENTAGE = 2.9  # 2.9% + $0.30 per transaction
STRIPE_FIXED_FEE = 0.30

class RefundService:
    """Service for handling trial membership refunds"""
    
    def __init__(self):
        # Initialize collections when needed to avoid import issues
        self.users_collection = None
        self.collections = None
        self.payments_collection = None
        self.clubs_collection = None
        self.memberships_collection = None
        self.trial_access_collection = None
        self.refunds_collection = None
    
    def _ensure_collections_initialized(self):
        """Direct database connection to avoid import issues"""
        if self.users_collection is None:
            from motor.motor_asyncio import AsyncIOMotorClient
            import os
            
            # Direct MongoDB connection
            mongo_url = os.getenv('MONGO_URL', 'mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main')
            client = AsyncIOMotorClient(mongo_url)
            db = client.get_database('betting_main')
            
            self.users_collection = db["users"]
            self.payments_collection = db["payments"]
            self.clubs_collection = db["clubs"]
            self.memberships_collection = db["club_memberships"]
            self.trial_access_collection = db["trial_club_access"]
            self.refunds_collection = db["refunds"]
    
    async def process_refund_request(
        self, 
        user_id: str, 
        reason: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Process a refund request for a trial member
        
        Args:
            user_id: User's ID
            reason: Optional reason for refund
            
        Returns:
            Tuple[bool, Optional[Dict], Optional[str]]: (success, refund_data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            logger.info(f"Processing refund request for user {user_id}")
            
            # Step 1: Validate user and refund eligibility
            validation_result = await self._validate_refund_eligibility(user_id)
            if not validation_result[0]:
                return False, None, validation_result[1]
            
            user_data = validation_result[2]
            
            # Step 2: Calculate refund amount and processing fees
            refund_calculation = await self._calculate_refund_amount(user_id, user_data)
            if not refund_calculation[0]:
                return False, None, "Failed to calculate refund amount"
            
            refund_amount, processing_fee, net_refund, refund_details = refund_calculation[1:5]
            
            # Step 3: Process Stripe refund
            stripe_refund_result = await self._process_stripe_refund(
                user_data, refund_amount, reason
            )
            if not stripe_refund_result[0]:
                return False, None, stripe_refund_result[1]
            
            stripe_refund_id = stripe_refund_result[1]
            
            # Step 4: Update database records
            db_update_result = await self._update_database_for_refund(
                user_id, user_data, refund_amount, processing_fee, net_refund, 
                stripe_refund_id, reason, refund_details
            )
            if not db_update_result[0]:
                # Try to reverse Stripe refund if DB update fails
                await self._reverse_stripe_refund(stripe_refund_id)
                return False, None, db_update_result[1]
            
            # Get the refund count from the database update result
            refund_count = db_update_result[2] if len(db_update_result) > 2 else 1
            
            # Step 5: Create refund record
            refund_record = await self._create_refund_record(
                user_id, user_data, refund_amount, processing_fee, net_refund,
                stripe_refund_id, reason, refund_details, refund_count
            )
            
            logger.info(f"Successfully processed refund for user {user_id}: ${net_refund}")
            
            return True, refund_record, None
            
        except Exception as e:
            error_msg = f"Error processing refund request: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
    
    async def _validate_refund_eligibility(self, user_id: str) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Validate if user is eligible for refund
        
        Returns:
            Tuple[bool, Optional[str], Optional[Dict]]: (is_eligible, error_message, user_data)
        """
        try:
            self._ensure_collections_initialized()
            # Get user data
            user_object_id = ObjectId(user_id)
            user = await self.users_collection.find_one({"_id": user_object_id})
            
            if not user:
                return False, "User not found", None
            
            # Check if user role is Member
            if user.get("role") != "Member":
                return False, "Only Members are eligible for refunds. Captains and Moderators cannot request refunds.", None
            
            # Check if user has already been refunded
            if user.get("is_refunded", False):
                return False, "User has already been refunded", None
            
            # Check membership status and type
            membership_status = user.get("membership_status")
            membership_type = user.get("membership_type")
            
            if membership_status != "active":
                return False, "User does not have active membership", None
            
            if membership_type != "trial":
                return False, "Only trial memberships are eligible for refund", None
            
            # Check if user has Stripe customer ID and subscription ID
            stripe_customer_id = user.get("stripe_customer_id")
            subscription_id = user.get("subscription_id")
            
            if not stripe_customer_id or not subscription_id:
                return False, "User does not have valid payment information", None
            
            # Check refund eligibility based on different scenarios
            now = datetime.now(timezone.utc)
            plan_start_date = user.get("plan_start_date")
            
            # Ensure plan_start_date is timezone-aware
            if plan_start_date and plan_start_date.tzinfo is None:
                plan_start_date = plan_start_date.replace(tzinfo=timezone.utc)
            
            # Get user's clubs joined data
            clubs_joined = user.get("clubs_joined", [])
            first_trial_join_date = await self._get_first_trial_join_date(user_id)
            
            # Scenario 1: User hasn't joined any clubs yet
            if not clubs_joined or not first_trial_join_date:
                if not plan_start_date:
                    return False, "User does not have valid membership start date", None
                
                # Check if within 7 days of membership purchase
                membership_refund_deadline = plan_start_date + timedelta(days=TRIAL_REFUND_PERIOD_DAYS)
                
                if now > membership_refund_deadline:
                    return False, f"Refund period has expired. Refund must be requested within {TRIAL_REFUND_PERIOD_DAYS} days of membership purchase.", None
                
                # User is eligible for full refund (no clubs joined)
                logger.info(f"User {user_id} eligible for refund - no clubs joined within membership period")
                return True, None, user
            
            # Scenario 2: User has joined clubs - check based on first trial join date
            # Ensure first_trial_join_date is timezone-aware
            if first_trial_join_date.tzinfo is None:
                first_trial_join_date = first_trial_join_date.replace(tzinfo=timezone.utc)
            
            refund_deadline = first_trial_join_date + timedelta(days=TRIAL_REFUND_PERIOD_DAYS)
            
            if now > refund_deadline:
                return False, f"Refund period has expired. Refund must be requested within {TRIAL_REFUND_PERIOD_DAYS} days of joining first trial club.", None
            
            # Check if user has paid clubs (if so, they can only refund portal fees)
            paid_clubs = await self._get_user_paid_clubs(user_id)
            if paid_clubs:
                logger.info(f"User {user_id} has paid clubs, will only refund portal fees")
            
            return True, None, user
            
        except Exception as e:
            logger.error(f"Error validating refund eligibility: {e}")
            return False, f"Error validating refund eligibility: {str(e)}", None
    
    async def _get_first_trial_join_date(self, user_id: str) -> Optional[datetime]:
        """Get the date when user first joined a club as trial"""
        try:
            # Get trial club access records
            trial_accesses = await self.trial_access_collection.find({
                "user_id": user_id,
                "is_access_active": True
            }).sort("join_date", 1).to_list(None)
            
            if trial_accesses:
                join_date = trial_accesses[0]["join_date"]
                # Ensure timezone awareness
                if join_date.tzinfo is None:
                    join_date = join_date.replace(tzinfo=timezone.utc)
                return join_date
            
            # Fallback: check clubs_joined array in user document
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            clubs_joined = user.get("clubs_joined", [])
            
            for club in clubs_joined:
                if club.get("membership_type") == "trial" and club.get("is_trial"):
                    join_date = club.get("join_date")
                    if join_date:
                        # Ensure timezone awareness
                        if join_date.tzinfo is None:
                            join_date = join_date.replace(tzinfo=timezone.utc)
                        return join_date
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting first trial join date: {e}")
            return None
    
    async def _get_user_paid_clubs(self, user_id: str) -> List[Dict]:
        """Get clubs where user joined as paid member"""
        try:
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            clubs_joined = user.get("clubs_joined", [])
            
            paid_clubs = []
            for club in clubs_joined:
                if (club.get("membership_type") == "paid" or 
                    (club.get("payment_id") and club.get("payment_id") != "null") or
                    club.get("amount_paid", 0) > 0):
                    paid_clubs.append(club)
            
            return paid_clubs
            
        except Exception as e:
            logger.error(f"Error getting user paid clubs: {e}")
            return []
    
    async def _calculate_refund_amount(self, user_id: str, user_data: Dict) -> Tuple[bool, float, float, float, Dict]:
        """
        Calculate refund amount and processing fees
        
        Returns:
            Tuple[bool, float, float, float, Dict]: (success, refund_amount, processing_fee, net_refund, refund_details)
        """
        try:
            # Get original payment record
            payment_record = await self.payments_collection.find_one({
                "user_id": user_id,
                "payment_type": "subscription",
                "membership_type": "trial",
                "status": "succeeded"
            })
            
            if not payment_record:
                return False, 0.0, 0.0, 0.0, {}
            
            original_amount = payment_record.get("amount", PORTAL_FEE_AMOUNT)
            
            # Only refund portal fees, not club fees
            refund_amount = min(original_amount, PORTAL_FEE_AMOUNT)
            
            # Calculate Stripe processing fees
            processing_fee = (refund_amount * STRIPE_PROCESSING_FEE_PERCENTAGE / 100) + STRIPE_FIXED_FEE
            
            # Calculate net refund amount
            net_refund = max(0.0, refund_amount - processing_fee)
            
            # Calculate membership usage details
            refund_details = await self._calculate_membership_usage(user_id, user_data)
            
            logger.info(f"Refund calculation for user {user_id}: "
                       f"Original: ${original_amount}, Refund: ${refund_amount}, "
                       f"Processing Fee: ${processing_fee:.2f}, Net: ${net_refund:.2f}")
            
            return True, refund_amount, processing_fee, net_refund, refund_details
            
        except Exception as e:
            logger.error(f"Error calculating refund amount: {e}")
            return False, 0.0, 0.0, 0.0, {}
    
    async def _calculate_membership_usage(self, user_id: str, user_data: Dict) -> Dict:
        """
        Calculate comprehensive membership usage details for refund tracking
        
        Returns:
            Dict: Usage details including per-club usage, total days, etc.
        """
        try:
            plan_start_date = user_data.get("plan_start_date")
            plan_end_date = user_data.get("plan_end_date")
            now = datetime.now(timezone.utc)
            
            if not plan_start_date or not plan_end_date:
                return {}
            
            # Ensure dates are timezone-aware
            if plan_start_date.tzinfo is None:
                plan_start_date = plan_start_date.replace(tzinfo=timezone.utc)
            if plan_end_date.tzinfo is None:
                plan_end_date = plan_end_date.replace(tzinfo=timezone.utc)
            
            # Calculate total membership period
            total_days = (plan_end_date - plan_start_date).days
            
            # Calculate used days for overall membership
            if now < plan_start_date:
                used_days = 0
            elif now > plan_end_date:
                used_days = total_days
            else:
                used_days = (now - plan_start_date).days
            
            # Calculate remaining days for overall membership
            remaining_days = total_days - used_days
            
            # Get detailed club usage information
            clubs_joined = user_data.get("clubs_joined", [])
            first_trial_join_date = await self._get_first_trial_join_date(user_id)
            
            # Get detailed trial club access information
            trial_club_details = await self._get_trial_club_access_details(user_id, now)
            
            # Count trial vs paid clubs
            paid_clubs = await self._get_user_paid_clubs(user_id)
            trial_clubs_count = len(clubs_joined) - len(paid_clubs)
            
            club_usage_details = {
                "total_clubs_joined": len(clubs_joined),
                "trial_clubs_joined": trial_clubs_count,
                "paid_clubs_joined": len(paid_clubs),
                "first_club_join_date": first_trial_join_date.isoformat() if first_trial_join_date else None,
                "trial_club_details": trial_club_details
            }
            
            return {
                "total_membership_days": total_days,
                "used_days": used_days,
                "remaining_days": remaining_days,
                "membership_start_date": plan_start_date.isoformat(),
                "membership_end_date": plan_end_date.isoformat(),
                "refund_request_date": now.isoformat(),
                "club_usage": club_usage_details
            }
            
        except Exception as e:
            logger.error(f"Error calculating membership usage: {e}")
            return {}
    
    async def _get_trial_club_access_details(self, user_id: str, current_time: datetime) -> List[Dict]:
        """
        Get detailed trial club access information with usage calculations
        
        Returns:
            List[Dict]: Detailed information for each trial club joined
        """
        try:
            self._ensure_collections_initialized()
            
            # Get trial club access records
            trial_access_records = await self.trial_access_collection.find({
                "user_id": user_id,
                "is_access_active": True
            }).to_list(length=None)
            
            trial_club_details = []
            
            for access_record in trial_access_records:
                club_id = access_record.get("club_id")
                club_name = access_record.get("club_name", "Unknown Club")
                join_date = access_record.get("join_date")
                access_expires_date = access_record.get("access_expires_date")
                
                if not join_date or not access_expires_date:
                    continue
                
                # Ensure dates are timezone-aware
                if join_date.tzinfo is None:
                    join_date = join_date.replace(tzinfo=timezone.utc)
                if access_expires_date.tzinfo is None:
                    access_expires_date = access_expires_date.replace(tzinfo=timezone.utc)
                
                # Calculate club-specific usage
                total_club_days = 7  # Each trial club has 7 days access
                
                # Calculate used days for this specific club
                if current_time < join_date:
                    used_days = 0
                elif current_time > access_expires_date:
                    used_days = total_club_days
                else:
                    used_days = (current_time - join_date).days
                
                # Calculate remaining days for this specific club
                remaining_days = total_club_days - used_days
                
                # Check if club access is still active
                is_club_access_active = current_time <= access_expires_date
                
                # Check if club access expires before plan end date
                plan_end_date = None
                user_data = await self.users_collection.find_one({"_id": ObjectId(user_id)})
                if user_data and user_data.get("plan_end_date"):
                    plan_end_date = user_data.get("plan_end_date")
                    if plan_end_date.tzinfo is None:
                        plan_end_date = plan_end_date.replace(tzinfo=timezone.utc)
                
                # Club becomes inactive if plan ends before club access expires
                if plan_end_date and access_expires_date > plan_end_date:
                    is_club_access_active = False
                    # Adjust remaining days based on plan end date
                    if current_time < plan_end_date:
                        remaining_days = (plan_end_date - current_time).days
                    else:
                        remaining_days = 0
                
                club_detail = {
                    "club_id": club_id,
                    "club_name": club_name,
                    "join_date": join_date.isoformat(),
                    "access_expires_date": access_expires_date.isoformat(),
                    "total_days": total_club_days,
                    "used_days": used_days,
                    "remaining_days": remaining_days,
                    "is_access_active": is_club_access_active,
                    "plan_end_date": plan_end_date.isoformat() if plan_end_date else None,
                    "access_affected_by_plan_end": plan_end_date and access_expires_date > plan_end_date if plan_end_date else False
                }
                
                trial_club_details.append(club_detail)
            
            # Sort by join date
            trial_club_details.sort(key=lambda x: x["join_date"])
            
            return trial_club_details
            
        except Exception as e:
            logger.error(f"Error getting trial club access details: {e}")
            return []
    
    async def _process_stripe_refund(self, user_data: Dict, refund_amount: float, reason: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        Process refund through Stripe
        
        Returns:
            Tuple[bool, Optional[str]]: (success, refund_id)
        """
        try:
            subscription_id = user_data.get("subscription_id")
            stripe_customer_id = user_data.get("stripe_customer_id")
            
            if not subscription_id or not stripe_customer_id:
                return False, None
            
            # Get the subscription and find the paid invoice
            subscription = stripe.Subscription.retrieve(subscription_id)
            latest_invoice_id = subscription.latest_invoice
            
            if not latest_invoice_id:
                return False, "No invoice found for subscription"
            
            # Retrieve the latest invoice first
            if isinstance(latest_invoice_id, str):
                latest_invoice = stripe.Invoice.retrieve(latest_invoice_id, expand=['payment_intent', 'charge'])
            else:
                latest_invoice = latest_invoice_id
            
            # Check if latest invoice has amount paid > 0
            # If it's $0 (free trial), we need to find the actual paid invoice
            if latest_invoice.amount_paid == 0:
                logger.info(f"Latest invoice {latest_invoice_id} has $0 amount. Searching for paid invoice...")
                
                # Get all invoices for this subscription
                invoices = stripe.Invoice.list(
                    subscription=subscription_id,
                    limit=20,
                    expand=['data.payment_intent', 'data.charge']
                )
                
                # Find the first invoice with amount > 0
                latest_invoice = None
                for inv in invoices.data:
                    if inv.amount_paid > 0 and inv.status == 'paid':
                        latest_invoice = inv
                        latest_invoice_id = inv.id
                        logger.info(f"Found paid invoice: {latest_invoice_id} with amount ${inv.amount_paid / 100}")
                        break
                
                if not latest_invoice:
                    logger.error(f"No paid invoices found for subscription {subscription_id}")
                    return False, "No paid invoice found. Cannot process refund for free trial."
            
            # Try multiple methods to find the payment
            payment_intent_id = getattr(latest_invoice, 'payment_intent', None)
            charge_id = getattr(latest_invoice, 'charge', None)
            
            # If invoice has payment but no direct reference, try to get from payment field
            if not payment_intent_id and not charge_id and hasattr(latest_invoice, 'payment'):
                payment_id = latest_invoice.payment
                if payment_id:
                    try:
                        payment = stripe.PaymentIntent.retrieve(payment_id)
                        payment_intent_id = payment.id
                        logger.info(f"Found payment intent from payment field: {payment_intent_id}")
                    except:
                        pass
            
            # If still not found, try to get the charge from subscription's latest charge
            if not payment_intent_id and not charge_id:
                try:
                    # Get charges for this customer filtered by this subscription
                    charges = stripe.Charge.list(
                        customer=stripe_customer_id,
                        limit=10
                    )
                    
                    # Find charge associated with this invoice
                    for charge in charges.data:
                        if charge.invoice == latest_invoice_id:
                            charge_id = charge.id
                            logger.info(f"Found charge from customer charges: {charge_id}")
                            break
                except Exception as charge_err:
                    logger.warning(f"Could not retrieve charges: {charge_err}")
            
            # Create refund parameters
            refund_params = {
                "amount": int(refund_amount * 100),  # Convert to cents
                "reason": "requested_by_customer",
                "metadata": {
                    "user_id": str(user_data.get("_id")),
                    "email": user_data.get("email"),
                    "refund_reason": reason or "Trial membership refund"
                }
            }
            
            # Prioritize payment_intent, fall back to charge
            if payment_intent_id:
                # Ensure payment_intent_id is a string
                if hasattr(payment_intent_id, 'id'):
                    payment_intent_id = payment_intent_id.id
                
                logger.info(f"Processing refund for payment intent: {payment_intent_id}")
                refund_params["payment_intent"] = payment_intent_id
                
            elif charge_id:
                # Ensure charge_id is a string
                if hasattr(charge_id, 'id'):
                    charge_id = charge_id.id
                
                logger.info(f"Processing refund for charge: {charge_id}")
                refund_params["charge"] = charge_id
                
            else:
                logger.error(f"No payment intent or charge found in invoice {latest_invoice_id}")
                logger.error(f"Invoice details - ID: {latest_invoice.id}, Status: {latest_invoice.status}, Amount: {latest_invoice.amount_paid}")
                return False, "No valid payment method found for refund"
            
            # Add metadata for webhook tracking (merge with existing metadata)
            existing_metadata = refund_params.get('metadata', {})
            refund_params['metadata'] = {
                **existing_metadata,
                'refund_type': 'member_refund',
                'service': 'auth',
                'user_id': str(user_data.get("_id")),
                'payment_type': 'refund'
            }
            
            # Create refund
            refund = stripe.Refund.create(**refund_params)
            
            logger.info(f"Stripe refund created: {refund.id} for amount ${refund_amount}")
            return True, refund.id
            
        except Exception as e:
            logger.error(f"Error processing Stripe refund: {e}")
            return False, None
    
    async def _update_database_for_refund(
        self, 
        user_id: str, 
        user_data: Dict, 
        refund_amount: float, 
        processing_fee: float, 
        net_refund: float,
        stripe_refund_id: str, 
        reason: Optional[str],
        refund_details: Dict
    ) -> Tuple[bool, Optional[str]]:
        """
        Update database records after successful refund
        
        Returns:
            Tuple[bool, Optional[str]]: (success, error_message)
        """
        try:
            now = datetime.now(timezone.utc)
            
            # Get current refund count and increment it
            current_user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            current_refund_count = current_user.get("refund_count", 0) if current_user else 0
            new_refund_count = current_refund_count + 1
            
            # Update user record
            user_update_result = await self.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "is_refunded": True,
                        "membership_status": "inactive",
                        "status": "inactive",
                        "membership_type": "refunded",
                        "refund_amount": net_refund,
                        "refund_processed_at": now,
                        "refund_reason": reason,
                        "stripe_refund_id": stripe_refund_id,
                        "refund_details": refund_details,
                        "is_reactive": True,  # Default to true - user can reactivate membership
                        "refund_count": new_refund_count,  # Track number of refunds
                        "updated_at": now
                    }
            })
            
            if user_update_result.modified_count == 0:
                return False, "Failed to update user record"
            
            # Update trial club memberships to inactive
            trial_memberships = await self.memberships_collection.find({
                "user_id": user_id,
                "is_trial_membership": True,
                "subscription_status": "active"
            }).to_list(None)
            
            for membership in trial_memberships:
                await self.memberships_collection.update_one(
                    {"_id": membership["_id"]},
                    {
                        "$set": {
                            "subscription_status": "inactive",
                            "refund_processed": True,
                            "refund_amount": net_refund,
                            "updated_at": now
                        }
                    }
                )
            
            # Update trial club access records
            await self.trial_access_collection.update_many(
                {
                    "user_id": user_id,
                    "is_access_active": True
                },
                {
                    "$set": {
                        "is_access_active": False,
                        "refund_processed": True,
                        "updated_at": now
                    }
                }
            )
            
            # Update clubs_joined array in user document
            await self._update_user_clubs_joined_for_refund(user_id)
            
            # Update clubs table - members and paid_members arrays
            await self._update_clubs_table_for_refund(user_id)
            
            # Cancel Stripe subscription
            try:
                subscription_id = user_data.get("subscription_id")
                if subscription_id:
                    stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
                    logger.info(f"Cancelled Stripe subscription: {subscription_id}")
            except Exception as e:
                logger.warning(f"Failed to cancel Stripe subscription: {e}")
            
            logger.info(f"Successfully updated database for refund: user {user_id}")
            return True, None, new_refund_count
            
        except Exception as e:
            logger.error(f"Error updating database for refund: {e}")
            return False, f"Error updating database: {str(e)}", 0
    
    async def _update_user_clubs_joined_for_refund(self, user_id: str):
        """Update clubs_joined array to mark trial clubs as inactive with detailed usage tracking"""
        try:
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return
            
            clubs_joined = user.get("clubs_joined", [])
            updated_clubs = []
            now = datetime.now(timezone.utc)
            
            # Get trial club access details for usage calculation
            trial_club_details = await self._get_trial_club_access_details(user_id, now)
            
            # Create a map of club_id to trial details for quick lookup
            trial_details_map = {detail["club_id"]: detail for detail in trial_club_details}
            
            for club in clubs_joined:
                club_id = club.get("club_id")
                
                # If it's a trial club, mark as inactive and add usage details
                if (club.get("membership_type") == "trial" and 
                    club.get("is_trial") == True):
                    
                    club["membership_status"] = "inactive"
                    club["is_active"] = False
                    club["refund_processed"] = True
                    club["updated_at"] = now.isoformat()
                    
                    # Add detailed usage information if available
                    if club_id in trial_details_map:
                        trial_detail = trial_details_map[club_id]
                        club["refund_usage_details"] = {
                            "total_days": trial_detail["total_days"],
                            "used_days": trial_detail["used_days"],
                            "remaining_days": trial_detail["remaining_days"],
                            "access_expires_date": trial_detail["access_expires_date"],
                            "join_date": trial_detail["join_date"],
                            "was_access_active": trial_detail["is_access_active"],
                            "access_affected_by_plan_end": trial_detail["access_affected_by_plan_end"]
                        }
                
                updated_clubs.append(club)
            
            # Update user document
            await self.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "clubs_joined": updated_clubs,
                        "updated_at": now
                    }
                }
            )
            
            logger.info(f"Updated clubs_joined for user {user_id} with detailed refund usage tracking")
            
        except Exception as e:
            logger.error(f"Error updating user clubs_joined for refund: {e}")
    
    async def _update_clubs_table_for_refund(self, user_id: str):
        """
        Update clubs table - members and paid_members arrays when user refund is processed
        
        This ensures that when a user's membership becomes inactive due to refund,
        their status is also updated in all clubs they joined (both trial and paid).
        """
        try:
            self._ensure_collections_initialized()
            now = datetime.now(timezone.utc)
            
            # Get all clubs where this user is a member (either in members or paid_members array)
            clubs_with_user = await self.clubs_collection.find({
                "$or": [
                    {"members.user_id": user_id},
                    {"paid_members.user_id": user_id}
                ]
            }).to_list(length=None)
            
            logger.info(f"Found {len(clubs_with_user)} clubs to update for refunded user {user_id}")
            
            for club in clubs_with_user:
                club_id = club["_id"]
                club_name = club.get("name", "Unknown Club")
                
                # Update members array (trial users)
                members_updated = await self._update_club_members_array(
                    club_id, user_id, now
                )
                
                # Update paid_members array (paid users)
                paid_members_updated = await self._update_club_paid_members_array(
                    club_id, user_id, now
                )
                
                # Update club member counts if any arrays were modified
                if members_updated or paid_members_updated:
                    await self._update_club_member_counts(club_id)
                    logger.info(f"Updated club {club_name} ({club_id}) for refunded user {user_id}")
            
            logger.info(f"Successfully updated all clubs for refunded user {user_id}")
            
        except Exception as e:
            logger.error(f"Error updating clubs table for refund: {e}")
    
    async def _update_club_members_array(self, club_id: ObjectId, user_id: str, now: datetime) -> bool:
        """Update trial members array in club document"""
        try:
            # Update the specific user's entry in the members array
            result = await self.clubs_collection.update_one(
                {
                    "_id": club_id,
                    "members.user_id": user_id
                },
                {
                    "$set": {
                        "members.$.membership_status": "inactive",
                        "members.$.membership_type": "refunded",
                        "members.$.is_active": False,
                        "members.$.updated_at": now,
                        "members.$.refund_processed": True
                    }
                }
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error updating members array for club {club_id}, user {user_id}: {e}")
            return False
    
    async def _update_club_paid_members_array(self, club_id: ObjectId, user_id: str, now: datetime) -> bool:
        """Update paid members array in club document"""
        try:
            # Update the specific user's entry in the paid_members array
            result = await self.clubs_collection.update_one(
                {
                    "_id": club_id,
                    "paid_members.user_id": user_id
                },
                {
                    "$set": {
                        "paid_members.$.membership_status": "inactive",
                        "paid_members.$.membership_type": "refunded",
                        "paid_members.$.is_active": False,
                        "paid_members.$.updated_at": now,
                        "paid_members.$.refund_processed": True
                    }
                }
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error updating paid_members array for club {club_id}, user {user_id}: {e}")
            return False
    
    async def _update_club_member_counts(self, club_id: ObjectId):
        """Update club member counts after refund processing"""
        try:
            # Get the updated club document to count from actual arrays
            club = await self.clubs_collection.find_one({"_id": club_id})
            if not club:
                logger.error(f"Club {club_id} not found for count update")
                return
            
            # Count members from actual arrays
            paid_members = club.get("paid_members", [])
            members = club.get("members", [])
            
            # Count active members only
            active_paid_members = len([m for m in paid_members if m.get("is_active", False)])
            active_members = len([m for m in members if m.get("is_active", False)])
            total_active_members = active_paid_members + active_members
            
            # Update club member counts
            await self.clubs_collection.update_one(
                {"_id": club_id},
                {
                    "$set": {
                        "member_count": active_members,  # Active trial/free members
                        "paid_member_count": active_paid_members,  # Active paid members
                        "total_members": total_active_members,  # Total active members
                        "updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            logger.info(f"Updated member counts for club {club_id}: active trial={active_members}, active paid={active_paid_members}, total active={total_active_members}")
            
        except Exception as e:
            logger.error(f"Error updating club member counts: {e}")
    
    async def _create_refund_record(
        self, 
        user_id: str, 
        user_data: Dict, 
        refund_amount: float, 
        processing_fee: float, 
        net_refund: float,
        stripe_refund_id: str, 
        reason: Optional[str],
        refund_details: Dict,
        refund_count: int
    ) -> Dict[str, Any]:
        """Create refund record in database"""
        try:
            now = datetime.now(timezone.utc)
            
            refund_record = {
                "user_id": user_id,
                "user_email": user_data.get("email"),
                "user_name": user_data.get("full_name"),
                "refund_type": "portal_fee",
                "original_amount": PORTAL_FEE_AMOUNT,
                "refund_amount": refund_amount,
                "processing_fee": processing_fee,
                "net_refund": net_refund,
                "stripe_refund_id": stripe_refund_id,
                "stripe_customer_id": user_data.get("stripe_customer_id"),
                "subscription_id": user_data.get("subscription_id"),
                "refund_reason": reason,
                "refund_details": refund_details,
                "status": "completed",
                "is_reactive": True,  # Default to true - user can reactivate membership
                "refund_count": refund_count,  # Track which refund this is (1st, 2nd, etc.)
                "processed_at": now,
                "created_at": now,
                "updated_at": now
            }
            
            result = await self.refunds_collection.insert_one(refund_record)
            refund_record["_id"] = str(result.inserted_id)
            
            return refund_record
            
        except Exception as e:
            logger.error(f"Error creating refund record: {e}")
            return {}
    
    async def _reverse_stripe_refund(self, stripe_refund_id: str):
        """Reverse a Stripe refund if database update fails"""
        try:
            # Note: Stripe refunds cannot be reversed, but we can log this for manual review
            logger.warning(f"Database update failed after Stripe refund {stripe_refund_id}. Manual review required.")
        except Exception as e:
            logger.error(f"Error handling failed refund reversal: {e}")
    
    async def get_refund_status(self, user_id: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Get refund status for a user
        
        Returns:
            Tuple[bool, Optional[Dict], Optional[str]]: (success, status_data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False, None, "User not found"
            
            is_refunded = user.get("is_refunded", False)
            membership_status = user.get("membership_status")
            membership_type = user.get("membership_type")
            refund_count = user.get("refund_count", 0)
            
            status_data = {
                "user_id": user_id,
                "is_refunded": is_refunded,
                "membership_status": membership_status,
                "membership_type": membership_type,
                "refund_eligible": False,
                "refund_deadline": None,
                "can_request_refund": False,
                "refund_count": refund_count,
                "is_temporary_deactivate": user.get("is_temporary_deactivate", False),
                "is_permanent_deactivate": user.get("is_permanent_deactivate", False)
            }
            
            if is_refunded:
                # Get refund record to check is_reactive status
                refund_record = await self.refunds_collection.find_one({"user_id": user_id})
                is_reactive = refund_record.get("is_reactive", True) if refund_record else True
                
                status_data.update({
                    "refund_amount": user.get("refund_amount"),
                    "refund_processed_at": user.get("refund_processed_at"),
                    "refund_reason": user.get("refund_reason"),
                    "stripe_refund_id": user.get("stripe_refund_id"),
                    "refund_details": user.get("refund_details"),
                    "is_reactive": is_reactive
                })
            else:
                # Check if user is eligible for refund
                validation_result = await self._validate_refund_eligibility(user_id)
                if validation_result[0]:
                    # Check if user has joined any clubs
                    clubs_joined = user.get("clubs_joined", [])
                    first_trial_join_date = await self._get_first_trial_join_date(user_id)
                    
                    if not clubs_joined or not first_trial_join_date:
                        # Scenario: User hasn't joined any clubs - refund based on membership purchase date
                        plan_start_date = user.get("plan_start_date")
                        if plan_start_date:
                            # Ensure plan_start_date is timezone-aware
                            if plan_start_date.tzinfo is None:
                                plan_start_date = plan_start_date.replace(tzinfo=timezone.utc)
                            
                            refund_deadline = plan_start_date + timedelta(days=TRIAL_REFUND_PERIOD_DAYS)
                            now = datetime.now(timezone.utc)
                            
                        status_data.update({
                            "refund_eligible": True,
                            "refund_deadline": refund_deadline,
                            "can_request_refund": now <= refund_deadline,
                            "first_trial_join_date": None,  # No clubs joined yet
                            "refund_type": "membership_purchase",  # New field to indicate refund type
                            "is_reactive": False  # Default to false, true after successful refund
                        })
                    else:
                        # Scenario: User has joined clubs - refund based on first trial join date
                        # Ensure first_trial_join_date is timezone-aware
                        if first_trial_join_date.tzinfo is None:
                            first_trial_join_date = first_trial_join_date.replace(tzinfo=timezone.utc)
                        
                        refund_deadline = first_trial_join_date + timedelta(days=TRIAL_REFUND_PERIOD_DAYS)
                        now = datetime.now(timezone.utc)
                        
                        status_data.update({
                            "refund_eligible": True,
                            "refund_deadline": refund_deadline,
                            "can_request_refund": now <= refund_deadline,
                            "first_trial_join_date": first_trial_join_date,
                            "refund_type": "trial_club_join",  # New field to indicate refund type
                            "is_reactive": False  # Default to false, true after successful refund
                        })
            
            return True, status_data, None
            
        except Exception as e:
            logger.error(f"Error getting refund status: {e}")
            return False, None, f"Error getting refund status: {str(e)}"
