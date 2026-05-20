"""
Stripe Webhook Service

This service handles Stripe webhook events for subscription management.
It processes subscription updates, billing events, and payment status changes.
"""

import logging
import stripe
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from bson import ObjectId

from core.database.collections import get_collections

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
if not stripe.api_key:
    logger.warning("⚠️ STRIPE_SECRET_KEY not found in environment variables")

class StripeWebhookService:
    """Service for handling Stripe webhook events"""
    
    def __init__(self):
        self._collections = None
        self._users_collection = None
        self._clubs_collection = None
        self._membership_collection = None
    
    def _ensure_collections_initialized(self):
        """Lazy initialization of collections to prevent circular imports"""
        if self._collections is None:
            self._collections = get_collections()
            self._users_collection = self._collections.get_users_collection()
            self._clubs_collection = self._collections.get_clubs_collection()
            self._membership_collection = self._collections.get_membership_collection()
    
    async def handle_subscription_updated(self, subscription: Dict[str, Any]) -> bool:
        """Handle subscription.updated webhook event"""
        try:
            self._ensure_collections_initialized()
            
            subscription_id = subscription.get("id")
            customer_id = subscription.get("customer")
            status = subscription.get("status")
            
            logger.info(f"Processing subscription.updated webhook: {subscription_id}, status: {status}")
            
            # Find user by customer_id
            user = await self._users_collection.find_one({"stripe_customer_id": customer_id})
            if not user:
                logger.warning(f"User not found for customer_id: {customer_id}")
                return False
            
            # Find the subscription in user's clubs_joined
            clubs_joined = user.get("clubs_joined", [])
            for club_membership in clubs_joined:
                if club_membership.get("subscription_id") == subscription_id:
                    await self._update_membership_status(
                        str(user["_id"]), 
                        club_membership.get("club_id"), 
                        subscription, 
                        club_membership
                    )
                    break
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling subscription.updated webhook: {e}")
            return False
    
    async def handle_subscription_deleted(self, subscription: Dict[str, Any]) -> bool:
        """Handle subscription.deleted webhook event"""
        try:
            self._ensure_collections_initialized()
            
            subscription_id = subscription.get("id")
            customer_id = subscription.get("customer")
            
            logger.info(f"Processing subscription.deleted webhook: {subscription_id}")
            
            # Find user by customer_id
            user = await self._users_collection.find_one({"stripe_customer_id": customer_id})
            if not user:
                logger.warning(f"User not found for customer_id: {customer_id}")
                return False
            
            # Update membership status to cancelled
            clubs_joined = user.get("clubs_joined", [])
            for club_membership in clubs_joined:
                if club_membership.get("subscription_id") == subscription_id:
                    await self._update_membership_to_cancelled(
                        str(user["_id"]), 
                        club_membership.get("club_id")
                    )
                    break
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling subscription.deleted webhook: {e}")
            return False
    
    async def handle_invoice_payment_succeeded(self, invoice: Dict[str, Any]) -> bool:
        """Handle invoice.payment_succeeded webhook event"""
        try:
            self._ensure_collections_initialized()
            
            subscription_id = invoice.get("subscription")
            customer_id = invoice.get("customer")
            
            logger.info(f"Processing invoice.payment_succeeded webhook for subscription: {subscription_id}")
            
            # Find user by customer_id
            user = await self._users_collection.find_one({"stripe_customer_id": customer_id})
            if not user:
                logger.warning(f"User not found for customer_id: {customer_id}")
                return False
            
            # Update membership with new billing period
            clubs_joined = user.get("clubs_joined", [])
            for club_membership in clubs_joined:
                if club_membership.get("subscription_id") == subscription_id:
                    await self._update_membership_billing_period(
                        str(user["_id"]), 
                        club_membership.get("club_id"), 
                        invoice
                    )
                    break
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling invoice.payment_succeeded webhook: {e}")
            return False
    
    async def handle_invoice_payment_failed(self, invoice: Dict[str, Any]) -> bool:
        """Handle invoice.payment_failed webhook event"""
        try:
            self._ensure_collections_initialized()
            
            subscription_id = invoice.get("subscription")
            customer_id = invoice.get("customer")
            
            logger.info(f"Processing invoice.payment_failed webhook for subscription: {subscription_id}")
            
            # Find user by customer_id
            user = await self._users_collection.find_one({"stripe_customer_id": customer_id})
            if not user:
                logger.warning(f"User not found for customer_id: {customer_id}")
                return False
            
            # Update membership status to payment_failed
            clubs_joined = user.get("clubs_joined", [])
            for club_membership in clubs_joined:
                if club_membership.get("subscription_id") == subscription_id:
                    await self._update_membership_payment_failed(
                        str(user["_id"]), 
                        club_membership.get("club_id")
                    )
                    break
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling invoice.payment_failed webhook: {e}")
            return False
    
    async def _update_membership_status(
        self, 
        user_id: str, 
        club_id: str, 
        subscription: Dict[str, Any], 
        club_membership: Dict[str, Any]
    ):
        """Update membership status based on subscription status"""
        try:
            status = subscription.get("status")
            current_period_end = subscription.get("current_period_end")
            
            # Calculate new end date
            if current_period_end:
                new_end_date = datetime.fromtimestamp(current_period_end, tz=timezone.utc)
            else:
                # Fallback to existing end_date or 30 days from now
                existing_end_date = club_membership.get("end_date")
                if existing_end_date:
                    new_end_date = existing_end_date
                else:
                    new_end_date = datetime.now(timezone.utc) + timedelta(days=30)
            
            # Map Stripe status to membership status
            if status == "active":
                membership_status = "active"
            elif status == "past_due":
                membership_status = "past_due"
            elif status == "canceled":
                membership_status = "cancelled"
            elif status == "unpaid":
                membership_status = "unpaid"
            else:
                membership_status = "inactive"
            
            # Update user's clubs_joined
            await self._users_collection.update_one(
                {
                    "_id": ObjectId(user_id),
                    "clubs_joined.club_id": club_id,
                    "clubs_joined.subscription_id": subscription.get("id")
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": membership_status,
                        "clubs_joined.$.end_date": new_end_date,
                        "clubs_joined.$.updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            # Update club's members arrays
            await self._clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "paid_members.user_id": user_id,
                    "paid_members.subscription_id": subscription.get("id")
                },
                {
                    "$set": {
                        "paid_members.$.membership_status": membership_status,
                        "paid_members.$.end_date": new_end_date,
                        "paid_members.$.updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            # Update club_memberships collection
            await self._membership_collection.update_one(
                {
                    "user_id": ObjectId(user_id),
                    "club_id": ObjectId(club_id)
                },
                {
                    "$set": {
                        "membership_status": membership_status,
                        "end_date": new_end_date,
                        "updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            logger.info(f"Updated membership status for user {user_id} in club {club_id} to {membership_status}")
            
        except Exception as e:
            logger.error(f"Error updating membership status: {e}")
    
    async def _update_membership_to_cancelled(self, user_id: str, club_id: str):
        """Update membership to cancelled status"""
        try:
            now = datetime.now(timezone.utc)
            
            # Update user's clubs_joined
            await self._users_collection.update_one(
                {
                    "_id": ObjectId(user_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "cancelled",
                        "clubs_joined.$.updated_at": now
                    }
                }
            )
            
            # Update club's members arrays
            await self._clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "paid_members.user_id": user_id
                },
                {
                    "$set": {
                        "paid_members.$.membership_status": "cancelled",
                        "paid_members.$.updated_at": now
                    }
                }
            )
            
            # Update club_memberships collection
            await self._membership_collection.update_one(
                {
                    "user_id": ObjectId(user_id),
                    "club_id": ObjectId(club_id)
                },
                {
                    "$set": {
                        "membership_status": "cancelled",
                        "updated_at": now
                    }
                }
            )
            
            logger.info(f"Updated membership to cancelled for user {user_id} in club {club_id}")
            
        except Exception as e:
            logger.error(f"Error updating membership to cancelled: {e}")
    
    async def _update_membership_billing_period(self, user_id: str, club_id: str, invoice: Dict[str, Any]):
        """Update membership with new billing period"""
        try:
            period_end = invoice.get("period_end")
            if not period_end:
                return
            
            new_end_date = datetime.fromtimestamp(period_end, tz=timezone.utc)
            
            # Update user's clubs_joined
            await self._users_collection.update_one(
                {
                    "_id": ObjectId(user_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.end_date": new_end_date,
                        "clubs_joined.$.updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            # Update club's members arrays
            await self._clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "paid_members.user_id": user_id
                },
                {
                    "$set": {
                        "paid_members.$.end_date": new_end_date,
                        "paid_members.$.updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            # Update club_memberships collection
            await self._membership_collection.update_one(
                {
                    "user_id": ObjectId(user_id),
                    "club_id": ObjectId(club_id)
                },
                {
                    "$set": {
                        "end_date": new_end_date,
                        "updated_at": datetime.now(timezone.utc)
                    }
                }
            )
            
            logger.info(f"Updated billing period for user {user_id} in club {club_id} to {new_end_date}")
            
        except Exception as e:
            logger.error(f"Error updating billing period: {e}")
    
    async def _update_membership_payment_failed(self, user_id: str, club_id: str):
        """Update membership status to payment failed"""
        try:
            now = datetime.now(timezone.utc)
            
            # Update user's clubs_joined
            await self._users_collection.update_one(
                {
                    "_id": ObjectId(user_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "payment_failed",
                        "clubs_joined.$.updated_at": now
                    }
                }
            )
            
            # Update club's members arrays
            await self._clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "paid_members.user_id": user_id
                },
                {
                    "$set": {
                        "paid_members.$.membership_status": "payment_failed",
                        "paid_members.$.updated_at": now
                    }
                }
            )
            
            # Update club_memberships collection
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
            
            logger.info(f"Updated membership to payment_failed for user {user_id} in club {club_id}")
            
        except Exception as e:
            logger.error(f"Error updating membership to payment_failed: {e}")

# Global service instance with lazy initialization
_stripe_webhook_service: Optional[StripeWebhookService] = None

def get_stripe_webhook_service() -> StripeWebhookService:
    """Get the global Stripe webhook service instance"""
    global _stripe_webhook_service
    if _stripe_webhook_service is None:
        _stripe_webhook_service = StripeWebhookService()
    return _stripe_webhook_service

