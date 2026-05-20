"""
Subscription Webhook Handler

Handles Stripe subscription events for join-paid memberships.
This is CRITICAL for recurring subscription renewals.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple, Optional
from bson import ObjectId

from core.database.collections import get_collections

logger = logging.getLogger(__name__)


class SubscriptionWebhookHandler:
    """Handler for subscription-related webhook events"""
    
    def __init__(self):
        self._collections = None
        self._users_collection = None
        self._clubs_collection = None
        self._membership_collection = None
    
    def _ensure_collections_initialized(self):
        """Lazy initialization of collections"""
        if self._collections is None:
            self._collections = get_collections()
            self._users_collection = self._collections.get_users_collection()
            self._clubs_collection = self._collections.get_clubs_collection()
            self._membership_collection = self._collections.get_membership_collection()
    
    async def handle_invoice_payment_succeeded(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle successful subscription renewal payment
        
        This is CRITICAL for join-paid memberships - extends membership when user pays
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            self._ensure_collections_initialized()
            
            invoice = event['data']['object']
            subscription_id = invoice.get('subscription')
            customer_id = invoice.get('customer')
            amount_paid = invoice.get('amount_paid', 0) / 100  # Convert from cents
            
            if not subscription_id:
                logger.warning("No subscription_id in invoice")
                return True, "No subscription_id - skipping"
            
            logger.info(f"💰 Processing successful payment: ${amount_paid} for subscription {subscription_id}")
            
            # Find membership by subscription_id
            user = await self._users_collection.find_one({
                "clubs_joined.subscription_id": subscription_id
            })
            
            if not user:
                logger.warning(f"No user found with subscription_id: {subscription_id}")
                return False, f"User not found for subscription: {subscription_id}"
            
            user_id = str(user["_id"])
            
            # Find the specific club membership
            club_membership = None
            for membership in user.get("clubs_joined", []):
                if membership.get("subscription_id") == subscription_id:
                    club_membership = membership
                    break
            
            if not club_membership:
                logger.error(f"Club membership not found for subscription {subscription_id}")
                return False, "Club membership not found"
            
            club_id = club_membership.get("club_id")
            pricing_plan = club_membership.get("pricing_plan", "monthly")
            
            # Calculate new end date based on pricing plan
            current_period_end = invoice.get('period_end')
            if current_period_end:
                new_end_date = datetime.fromtimestamp(current_period_end, tz=timezone.utc)
            else:
                # Fallback: extend from current end_date
                current_end_date = club_membership.get("end_date")
                if current_end_date:
                    new_end_date = self._calculate_new_end_date(current_end_date, pricing_plan)
                else:
                    new_end_date = self._calculate_new_end_date(datetime.now(timezone.utc), pricing_plan)
            
            logger.info(f"📅 Extending membership to: {new_end_date}")
            
            # Update 3 collections for data consistency
            await self._update_user_membership(user_id, subscription_id, new_end_date)
            await self._update_club_membership(club_id, user_id, subscription_id, new_end_date)
            await self._update_membership_collection(user_id, club_id, subscription_id, new_end_date)
            
            logger.info(f"✅ Successfully extended membership for user {user_id} in club {club_id}")
            
            # TODO: Send renewal confirmation email
            
            return True, f"Membership extended to {new_end_date}"
            
        except Exception as e:
            logger.error(f"Error handling invoice.payment_succeeded: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Error processing payment: {str(e)}"
    
    async def handle_invoice_payment_failed(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle failed subscription renewal payment
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            self._ensure_collections_initialized()
            
            invoice = event['data']['object']
            subscription_id = invoice.get('subscription')
            
            if not subscription_id:
                return True, "No subscription_id - skipping"
            
            logger.warning(f"💸 Payment failed for subscription {subscription_id}")
            
            # Find user
            user = await self._users_collection.find_one({
                "clubs_joined.subscription_id": subscription_id
            })
            
            if not user:
                return False, f"User not found for subscription: {subscription_id}"
            
            user_id = str(user["_id"])
            
            # Find club membership
            club_id = None
            for membership in user.get("clubs_joined", []):
                if membership.get("subscription_id") == subscription_id:
                    club_id = membership.get("club_id")
                    break
            
            if not club_id:
                return False, "Club membership not found"
            
            # Mark membership as payment_failed
            await self._mark_membership_payment_failed(user_id, club_id, subscription_id)
            
            logger.info(f"⚠️ Marked membership as payment_failed for user {user_id}")
            
            # TODO: Send email to update payment method
            
            return True, "Membership marked as payment_failed"
            
        except Exception as e:
            logger.error(f"Error handling invoice.payment_failed: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_subscription_deleted(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle subscription cancellation
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            self._ensure_collections_initialized()
            
            subscription = event['data']['object']
            subscription_id = subscription.get('id')
            
            logger.warning(f"🗑️ Subscription cancelled: {subscription_id}")
            
            # Find user
            user = await self._users_collection.find_one({
                "clubs_joined.subscription_id": subscription_id
            })
            
            if not user:
                return False, f"User not found for subscription: {subscription_id}"
            
            user_id = str(user["_id"])
            
            # Find club membership
            club_id = None
            for membership in user.get("clubs_joined", []):
                if membership.get("subscription_id") == subscription_id:
                    club_id = membership.get("club_id")
                    break
            
            if not club_id:
                return False, "Club membership not found"
            
            # Mark membership as cancelled
            await self._mark_membership_cancelled(user_id, club_id, subscription_id)
            
            logger.info(f"❌ Cancelled membership for user {user_id}")
            
            # TODO: Send cancellation confirmation email
            
            return True, "Membership cancelled"
            
        except Exception as e:
            logger.error(f"Error handling subscription.deleted: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_subscription_updated(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle subscription status updates
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            self._ensure_collections_initialized()
            
            subscription = event['data']['object']
            subscription_id = subscription.get('id')
            status = subscription.get('status')
            
            logger.info(f"📝 Subscription updated: {subscription_id}, status: {status}")
            
            # Find user
            user = await self._users_collection.find_one({
                "clubs_joined.subscription_id": subscription_id
            })
            
            if not user:
                return True, "User not found - may be trial membership"
            
            user_id = str(user["_id"])
            
            # Find club membership
            club_id = None
            for membership in user.get("clubs_joined", []):
                if membership.get("subscription_id") == subscription_id:
                    club_id = membership.get("club_id")
                    break
            
            if not club_id:
                return False, "Club membership not found"
            
            # Map Stripe status to our status
            membership_status = self._map_stripe_status(status)
            
            # Update membership status
            await self._update_membership_status(user_id, club_id, subscription_id, membership_status)
            
            logger.info(f"✅ Updated membership status to: {membership_status}")
            
            return True, f"Status updated to {membership_status}"
            
        except Exception as e:
            logger.error(f"Error handling subscription.updated: {e}")
            return False, f"Error: {str(e)}"
    
    # Helper methods
    
    async def _update_user_membership(self, user_id: str, subscription_id: str, new_end_date: datetime):
        """Update user's clubs_joined array"""
        await self._users_collection.update_one(
            {
                "_id": ObjectId(user_id),
                "clubs_joined.subscription_id": subscription_id
            },
            {
                "$set": {
                    "clubs_joined.$.end_date": new_end_date,
                    "clubs_joined.$.membership_status": "active",
                    "clubs_joined.$.updated_at": datetime.utcnow()
                }
            }
        )
    
    async def _update_club_membership(self, club_id: str, user_id: str, subscription_id: str, new_end_date: datetime):
        """Update club's paid_members array"""
        await self._clubs_collection.update_one(
            {
                "_id": ObjectId(club_id),
                "paid_members.user_id": user_id,
                "paid_members.subscription_id": subscription_id
            },
            {
                "$set": {
                    "paid_members.$.end_date": new_end_date,
                    "paid_members.$.membership_status": "active",
                    "paid_members.$.updated_at": datetime.utcnow()
                }
            }
        )
    
    async def _update_membership_collection(self, user_id: str, club_id: str, subscription_id: str, new_end_date: datetime):
        """Update club_memberships collection"""
        await self._membership_collection.update_one(
            {
                "user_id": ObjectId(user_id),
                "club_id": ObjectId(club_id)
            },
            {
                "$set": {
                    "end_date": new_end_date,
                    "membership_status": "active",
                    "updated_at": datetime.utcnow()
                }
            }
        )
    
    async def _mark_membership_payment_failed(self, user_id: str, club_id: str, subscription_id: str):
        """Mark membership as payment_failed"""
        now = datetime.utcnow()
        
        # Update user
        await self._users_collection.update_one(
            {
                "_id": ObjectId(user_id),
                "clubs_joined.subscription_id": subscription_id
            },
            {
                "$set": {
                    "clubs_joined.$.membership_status": "payment_failed",
                    "clubs_joined.$.updated_at": now
                }
            }
        )
        
        # Update club
        await self._clubs_collection.update_one(
            {
                "_id": ObjectId(club_id),
                "paid_members.subscription_id": subscription_id
            },
            {
                "$set": {
                    "paid_members.$.membership_status": "payment_failed",
                    "paid_members.$.updated_at": now
                }
            }
        )
        
        # Update membership collection
        await self._membership_collection.update_one(
            {
                "user_id": ObjectId(user_id),
                "club_id": ObjectId(club_id)
            },
            {
                "$set": {
                    "membership_status": "payment_failed",
                    "updated_at": now
                }
            }
        )
    
    async def _mark_membership_cancelled(self, user_id: str, club_id: str, subscription_id: str):
        """Mark membership as cancelled"""
        now = datetime.utcnow()
        
        # Update user
        await self._users_collection.update_one(
            {
                "_id": ObjectId(user_id),
                "clubs_joined.subscription_id": subscription_id
            },
            {
                "$set": {
                    "clubs_joined.$.membership_status": "cancelled",
                    "clubs_joined.$.is_active": False,
                    "clubs_joined.$.updated_at": now
                }
            }
        )
        
        # Update club
        await self._clubs_collection.update_one(
            {
                "_id": ObjectId(club_id),
                "paid_members.subscription_id": subscription_id
            },
            {
                "$set": {
                    "paid_members.$.membership_status": "cancelled",
                    "paid_members.$.updated_at": now
                }
            }
        )
        
        # Update membership collection
        await self._membership_collection.update_one(
            {
                "user_id": ObjectId(user_id),
                "club_id": ObjectId(club_id)
            },
            {
                "$set": {
                    "membership_status": "cancelled",
                    "status": "cancelled",
                    "updated_at": now
                }
            }
        )
    
    async def _update_membership_status(self, user_id: str, club_id: str, subscription_id: str, status: str):
        """Update membership status"""
        now = datetime.utcnow()
        
        await self._users_collection.update_one(
            {
                "_id": ObjectId(user_id),
                "clubs_joined.subscription_id": subscription_id
            },
            {
                "$set": {
                    "clubs_joined.$.membership_status": status,
                    "clubs_joined.$.updated_at": now
                }
            }
        )
        
        await self._clubs_collection.update_one(
            {
                "_id": ObjectId(club_id),
                "paid_members.subscription_id": subscription_id
            },
            {
                "$set": {
                    "paid_members.$.membership_status": status,
                    "paid_members.$.updated_at": now
                }
            }
        )
        
        await self._membership_collection.update_one(
            {
                "user_id": ObjectId(user_id),
                "club_id": ObjectId(club_id)
            },
            {
                "$set": {
                    "membership_status": status,
                    "updated_at": now
                }
            }
        )
    
    def _calculate_new_end_date(self, start_date: datetime, pricing_plan: str) -> datetime:
        """Calculate new end date based on pricing plan"""
        if pricing_plan == "daily":
            return start_date + timedelta(days=1)
        elif pricing_plan == "weekly":
            return start_date + timedelta(weeks=1)
        elif pricing_plan == "monthly":
            return start_date + timedelta(days=30)
        elif pricing_plan == "quarterly":
            return start_date + timedelta(days=90)
        elif pricing_plan == "yearly":
            return start_date + timedelta(days=365)
        else:
            return start_date + timedelta(days=30)  # Default to monthly
    
    def _map_stripe_status(self, stripe_status: str) -> str:
        """Map Stripe subscription status to our membership status"""
        status_mapping = {
            "active": "active",
            "past_due": "past_due",
            "canceled": "cancelled",
            "unpaid": "payment_failed",
            "incomplete": "pending",
            "incomplete_expired": "expired",
            "trialing": "active"
        }
        return status_mapping.get(stripe_status, "unknown")
    
    async def handle_plan_change_payment_succeeded(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle successful plan change payment
        
        This activates the scheduled plan change after payment succeeds
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            self._ensure_collections_initialized()
            
            payment_intent = event['data']['object']
            payment_intent_id = payment_intent.get('id')
            metadata = payment_intent.get('metadata', {})
            
            # Check if this is a plan change payment
            payment_type = metadata.get('payment_type')
            if payment_type != 'plan_change':
                return True, "Not a plan change payment - skipping"
            
            logger.info(f"🔄 Processing plan change payment: {payment_intent_id}")
            
            # Extract plan change data from metadata
            user_id = metadata.get('user_id')
            club_id = metadata.get('club_name_based_id')  # Using name_based_id from metadata
            new_pricing_plan = metadata.get('pricing_plan')
            
            if not all([user_id, club_id, new_pricing_plan]):
                logger.error("Missing required metadata for plan change")
                return False, "Missing required metadata"
            
            logger.info(f"🔄 Activating plan change for user {user_id} to {new_pricing_plan}")
            
            # Find the scheduled plan change in user's clubs_joined
            user = await self._users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                return False, f"User not found: {user_id}"
            
            # Look for the upcoming plan change
            clubs_joined = user.get("clubs_joined", [])
            scheduled_change = None
            scheduled_index = None
            
            for idx, membership in enumerate(clubs_joined):
                if (membership.get("club_name_based_id") == club_id and 
                    membership.get("membership_status") == "upcoming" and
                    membership.get("payment_id") == payment_intent_id):
                    scheduled_change = membership
                    scheduled_index = idx
                    break
            
            if not scheduled_change:
                logger.warning(f"No scheduled plan change found for payment {payment_intent_id}")
                return True, "No scheduled plan change found (may already be activated)"
            
            # Activate the plan change by updating status
            now = datetime.utcnow()
            
            # Update the scheduled plan to active
            await self._users_collection.update_one(
                {
                    "_id": ObjectId(user_id),
                    "clubs_joined.payment_id": payment_intent_id,
                    "clubs_joined.membership_status": "upcoming"
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "scheduled",
                        "clubs_joined.$.payment_confirmed": True,
                        "clubs_joined.$.payment_confirmed_at": now,
                        "clubs_joined.$.updated_at": now
                    }
                }
            )
            
            logger.info(f"✅ Plan change confirmed and scheduled for user {user_id}")
            
            # TODO: Send plan change confirmation email
            
            return True, f"Plan change to {new_pricing_plan} scheduled successfully"
            
        except Exception as e:
            logger.error(f"Error handling plan change payment: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Error: {str(e)}"
    
    async def handle_plan_change_payment_failed(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle failed plan change payment
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            self._ensure_collections_initialized()
            
            payment_intent = event['data']['object']
            payment_intent_id = payment_intent.get('id')
            metadata = payment_intent.get('metadata', {})
            
            # Check if this is a plan change payment
            if metadata.get('payment_type') != 'plan_change':
                return True, "Not a plan change payment - skipping"
            
            logger.error(f"💸 Plan change payment failed: {payment_intent_id}")
            
            user_id = metadata.get('user_id')
            club_id = metadata.get('club_name_based_id')
            
            # Remove the failed scheduled plan change
            await self._users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$pull": {
                        "clubs_joined": {
                            "payment_id": payment_intent_id,
                            "membership_status": "upcoming"
                        }
                    }
                }
            )
            
            logger.info(f"❌ Removed failed plan change for user {user_id}")
            
            # TODO: Send plan change failure notification
            
            return True, "Failed plan change removed"
            
        except Exception as e:
            logger.error(f"Error handling plan change payment failure: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_fallback_payment_succeeded(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle successful fallback payment
        
        Fallback payments are used when subscription creation fails
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            self._ensure_collections_initialized()
            
            payment_intent = event['data']['object']
            payment_intent_id = payment_intent.get('id')
            metadata = payment_intent.get('metadata', {})
            
            # Check if this is a fallback payment
            if metadata.get('payment_type') != 'fallback':
                return True, "Not a fallback payment - skipping"
            
            logger.info(f"💰 Processing fallback payment: {payment_intent_id}")
            
            # Log the fallback payment
            # Fallback payments are typically already processed synchronously
            # This webhook provides additional confirmation
            
            logger.info(f"✅ Fallback payment confirmed: {payment_intent_id}")
            
            return True, "Fallback payment confirmed"
            
        except Exception as e:
            logger.error(f"Error handling fallback payment: {e}")
            return False, f"Error: {str(e)}"


# Global handler instance
_subscription_handler: Optional[SubscriptionWebhookHandler] = None

def get_subscription_handler() -> SubscriptionWebhookHandler:
    """Get subscription webhook handler instance"""
    global _subscription_handler
    if _subscription_handler is None:
        _subscription_handler = SubscriptionWebhookHandler()
    return _subscription_handler

