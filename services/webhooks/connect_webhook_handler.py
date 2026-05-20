"""
Stripe Connect Webhook Handler

Handles Stripe Connect events for captain payouts and revenue tracking.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from bson import ObjectId

logger = logging.getLogger(__name__)


class ConnectWebhookHandler:
    """Handler for Stripe Connect webhook events"""
    
    def __init__(self):
        from core.database.collections import get_collections
        collections = get_collections()
        self.user_collection = collections.get_users_collection()
        # Use existing collections
        self.payments_collection = collections.get_club_payments_collection()  # Existing
        self.webhook_events_collection = collections.get_webhook_events_collection()  # Existing
    
    async def handle_account_updated(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle Stripe Connect account updates
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            account = event['data']['object']
            account_id = account.get('id')
            
            logger.info(f"🏦 Connect account updated: {account_id}")
            
            # Find captain by stripe_connect_account_id
            captain = await self.user_collection.find_one({
                "stripe_connect_account_id": account_id
            })
            
            if captain:
                # Update account status
                charges_enabled = account.get('charges_enabled', False)
                payouts_enabled = account.get('payouts_enabled', False)
                
                await self.user_collection.update_one(
                    {"_id": captain["_id"]},
                    {
                        "$set": {
                            "stripe_connect_status": {
                                "charges_enabled": charges_enabled,
                                "payouts_enabled": payouts_enabled,
                                "updated_at": datetime.utcnow()
                            }
                        }
                    }
                )
                
                logger.info(f"✅ Updated Connect account status for captain {captain.get('full_name')}")
                return True, "Account updated"
            else:
                logger.warning(f"No captain found with account_id: {account_id}")
                return True, "Account not linked to captain"
            
        except Exception as e:
            logger.error(f"Error handling account.updated: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_payout_paid(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle successful payout to captain
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            payout = event['data']['object']
            payout_id = payout.get('id')
            amount = payout.get('amount', 0) / 100  # Convert from cents
            destination_account = payout.get('destination')
            
            logger.info(f"💰 Payout succeeded: ${amount} to account {destination_account}")
            
            # Find captain
            captain = await self.user_collection.find_one({
                "stripe_connect_account_id": destination_account
            })
            
            # Record payout in existing club_payments collection
            payout_record = {
                "payout_id": payout_id,
                "payment_type": "payout",
                "account_id": destination_account,
                "captain_id": str(captain["_id"]) if captain else None,
                "captain_name": captain.get("full_name") if captain else "Unknown",
                "amount": amount,
                "currency": payout.get('currency', 'usd'),
                "payment_status": "paid",
                "arrival_date": datetime.fromtimestamp(payout.get('arrival_date', 0)),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await self.payments_collection.insert_one(payout_record)
            
            logger.info(f"✅ Recorded payout for captain {captain.get('full_name') if captain else 'Unknown'}")
            
            # TODO: Send payout confirmation email to captain
            
            return True, f"Payout recorded: ${amount}"
            
        except Exception as e:
            logger.error(f"Error handling payout.paid: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_payout_failed(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle failed payout
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            payout = event['data']['object']
            payout_id = payout.get('id')
            destination_account = payout.get('destination')
            failure_message = payout.get('failure_message', 'Unknown error')
            
            logger.error(f"💸 Payout failed: {failure_message} for account {destination_account}")
            
            # Find captain
            captain = await self.user_collection.find_one({
                "stripe_connect_account_id": destination_account
            })
            
            # Record failed payout in existing club_payments collection
            payout_record = {
                "payout_id": payout_id,
                "payment_type": "payout",
                "account_id": destination_account,
                "captain_id": str(captain["_id"]) if captain else None,
                "captain_name": captain.get("full_name") if captain else "Unknown",
                "amount": payout.get('amount', 0) / 100,
                "currency": payout.get('currency', 'usd'),
                "payment_status": "failed",
                "failure_message": failure_message,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await self.payments_collection.insert_one(payout_record)
            
            logger.error(f"❌ Recorded failed payout for captain {captain.get('full_name') if captain else 'Unknown'}")
            
            # TODO: Send alert email to captain and admin
            
            return True, f"Failed payout recorded: {failure_message}"
            
        except Exception as e:
            logger.error(f"Error handling payout.failed: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_transfer_created(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle transfer to captain's Connect account
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            transfer = event['data']['object']
            transfer_id = transfer.get('id')
            amount = transfer.get('amount', 0) / 100
            destination_account = transfer.get('destination')
            
            logger.info(f"💸 Transfer created: ${amount} to account {destination_account}")
            
            # Record transfer in existing club_payments collection
            transfer_record = {
                "transfer_id": transfer_id,
                "payment_type": "transfer",
                "destination_account": destination_account,
                "amount": amount,
                "currency": transfer.get('currency', 'usd'),
                "payment_status": "created",
                "created_at": datetime.utcnow()
            }
            
            await self.payments_collection.insert_one(transfer_record)
            
            return True, f"Transfer recorded: ${amount}"
            
        except Exception as e:
            logger.error(f"Error handling transfer.created: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_transfer_failed(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle failed transfer
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            transfer = event['data']['object']
            transfer_id = transfer.get('id')
            
            logger.error(f"💸 Transfer failed: {transfer_id}")
            
            # Update transfer record in existing club_payments collection
            await self.payments_collection.update_one(
                {"transfer_id": transfer_id},
                {
                    "$set": {
                        "payment_status": "failed",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # TODO: Alert admin of failed transfer
            
            return True, "Failed transfer recorded"
            
        except Exception as e:
            logger.error(f"Error handling transfer.failed: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_payment_intent_succeeded_connect(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle successful Connect payment intent
        
        This tracks revenue split between platform and captain
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            payment_intent = event['data']['object']
            payment_intent_id = payment_intent.get('id')
            metadata = payment_intent.get('metadata', {})
            
            # Check if this is a Connect payment
            payment_type = metadata.get('payment_type')
            if payment_type != 'connect_payment':
                return True, "Not a Connect payment - skipping"
            
            logger.info(f"💰 Processing Connect payment: {payment_intent_id}")
            
            # Extract revenue split data from metadata
            club_id = metadata.get('club_id')
            captain_id = metadata.get('captain_id')
            club_name = metadata.get('club_name', 'Unknown')
            customer_name = metadata.get('customer_name', 'Unknown')
            
            # Parse fee amounts from metadata
            try:
                platform_fee = float(metadata.get('platform_fee', 0))
                captain_amount = float(metadata.get('captain_amount', 0))
            except (ValueError, TypeError):
                platform_fee = 0
                captain_amount = 0
            
            total_amount = payment_intent.get('amount', 0) / 100  # Convert from cents
            
            logger.info(f"💵 Revenue Split - Total: ${total_amount}, Platform: ${platform_fee}, Captain: ${captain_amount}")
            
            # Record payment in existing club_payments collection
            payment_record = {
                "payment_intent_id": payment_intent_id,
                "club_id": club_id,
                "captain_id": captain_id,
                "club_name": club_name,
                "customer_name": customer_name,
                "amount": total_amount,
                "platform_fee": platform_fee,
                "captain_amount": captain_amount,
                "currency": payment_intent.get('currency', 'usd'),
                "payment_status": "succeeded",
                "payment_type": "connect_payment",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await self.payments_collection.insert_one(payment_record)
            
            logger.info(f"✅ Recorded Connect payment to club_payments collection for club {club_name}")
            
            # TODO: Send revenue confirmation email to captain
            
            return True, f"Connect payment tracked: ${total_amount} (Platform: ${platform_fee}, Captain: ${captain_amount})"
            
        except Exception as e:
            logger.error(f"Error handling Connect payment_intent.succeeded: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Error: {str(e)}"
    
    async def handle_payment_intent_failed_connect(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle failed Connect payment intent
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            payment_intent = event['data']['object']
            payment_intent_id = payment_intent.get('id')
            metadata = payment_intent.get('metadata', {})
            
            # Check if this is a Connect payment
            if metadata.get('payment_type') != 'connect_payment':
                return True, "Not a Connect payment - skipping"
            
            logger.error(f"💸 Connect payment failed: {payment_intent_id}")
            
            club_name = metadata.get('club_name', 'Unknown')
            failure_message = payment_intent.get('last_payment_error', {}).get('message', 'Unknown error')
            
            # Record failed payment in existing club_payments collection
            failed_payment_record = {
                "payment_intent_id": payment_intent_id,
                "club_id": metadata.get('club_id'),
                "captain_id": metadata.get('captain_id'),
                "club_name": club_name,
                "amount": payment_intent.get('amount', 0) / 100,
                "currency": payment_intent.get('currency', 'usd'),
                "payment_status": "failed",
                "failure_message": failure_message,
                "payment_type": "connect_payment",
                "created_at": datetime.utcnow()
            }
            
            await self.payments_collection.insert_one(failed_payment_record)
            
            logger.error(f"❌ Recorded failed Connect payment for club {club_name}")
            
            # TODO: Send failure alert to admin and captain
            
            return True, f"Failed Connect payment recorded: {failure_message}"
            
        except Exception as e:
            logger.error(f"Error handling Connect payment_intent.failed: {e}")
            return False, f"Error: {str(e)}"


# Global handler instance
_connect_handler: Optional[ConnectWebhookHandler] = None

def get_connect_handler() -> ConnectWebhookHandler:
    """Get Connect webhook handler instance"""
    global _connect_handler
    if _connect_handler is None:
        _connect_handler = ConnectWebhookHandler()
    return _connect_handler

