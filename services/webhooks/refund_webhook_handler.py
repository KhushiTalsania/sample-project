"""
Refund Webhook Handler

Handles Stripe refund events to track refund status.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from bson import ObjectId

logger = logging.getLogger(__name__)


class RefundWebhookHandler:
    """Handler for refund-related webhook events"""
    
    def __init__(self):
        from core.database.collections import get_collections
        collections = get_collections()
        # Use existing collections
        self.refunds_collection = collections.get_refunds_collection()  # EXISTING
        self.club_refunds_collection = collections.get_club_refunds_collection()  # EXISTING
        self.clubs_collection = collections.get_clubs_collection()  # EXISTING
        self.users_collection = collections.get_users_collection()  # EXISTING
    
    async def handle_charge_refunded(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle successful refund - works for ALL refund types
        
        Supports refunds from:
        - Club service (member refunds)
        - Auth service (member refunds, account deletion)
        - Admin service (admin-initiated refunds)
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            charge = event['data']['object']
            refunds = charge.get('refunds', {}).get('data', [])
            
            if not refunds:
                logger.warning("No refunds found in charge.refunded event")
                return True, "No refunds in event"
            
            # Get the latest refund
            refund = refunds[0] if refunds else {}
            refund_id = refund.get('id')
            amount_refunded = refund.get('amount', 0) / 100  # Convert from cents
            payment_intent = charge.get('payment_intent')
            metadata = refund.get('metadata', {})
            
            refund_type = metadata.get('refund_type', 'unknown')
            service = metadata.get('service', 'unknown')
            
            logger.info(f"💰 Refund processed: ${amount_refunded} for payment_intent {payment_intent}")
            logger.info(f"📋 Refund type: {refund_type}, Service: {service}")
            
            # Route to appropriate service handler based on metadata
            if service == 'club' or refund_type in ['club_member_refund', 'paid_member_refund']:
                return await self._handle_club_refund(payment_intent, refund_id, amount_refunded, metadata)
            
            elif service == 'auth' or refund_type in ['member_refund', 'account_deletion_refund']:
                return await self._handle_auth_refund(payment_intent, refund_id, amount_refunded, metadata)
            
            elif service == 'admin' or refund_type in ['admin_club_refund', 'admin_payment_refund']:
                return await self._handle_admin_refund(payment_intent, refund_id, amount_refunded, metadata)
            
            else:
                # Generic refund handling (fallback)
                logger.warning(f"Unknown refund type: {refund_type}, service: {service}")
                return await self._handle_generic_refund(payment_intent, refund_id, amount_refunded)
            
        except Exception as e:
            logger.error(f"Error handling charge.refunded: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Error: {str(e)}"
    
    async def _handle_club_refund(self, payment_intent: str, refund_id: str, amount: float, metadata: Dict) -> Tuple[bool, str]:
        """Handle refunds from club service"""
        try:
            # Find refund request by payment_intent in club_refunds collection (EXISTING)
            refund_request = await self.club_refunds_collection.find_one({
                "payment_id": payment_intent
            })
            
            if refund_request:
                # Update refund status to completed
                await self.club_refunds_collection.update_one(
                    {"_id": refund_request["_id"]},
                    {
                        "$set": {
                            "refund_status": "completed",
                            "stripe_refund_id": refund_id,
                            "completed_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                
                logger.info(f"✅ Updated club refund status to completed in club_refunds collection")
                return True, "Club refund completed"
            else:
                logger.warning(f"No club refund found for payment_intent: {payment_intent}")
                return True, "Club refund processed (no record found)"
                
        except Exception as e:
            logger.error(f"Error handling club refund: {e}")
            return False, f"Error: {str(e)}"
    
    async def _handle_auth_refund(self, payment_intent: str, refund_id: str, amount: float, metadata: Dict) -> Tuple[bool, str]:
        """Handle refunds from auth service"""
        try:
            user_id = metadata.get('user_id')
            refund_type = metadata.get('refund_type')
            
            # Find refund request by payment_intent in refunds collection (EXISTING)
            refund_request = await self.refunds_collection.find_one({
                "payment_id": payment_intent
            })
            
            if refund_request:
                # Update refund status to completed
                await self.refunds_collection.update_one(
                    {"_id": refund_request["_id"]},
                    {
                        "$set": {
                            "refund_status": "completed",
                            "stripe_refund_id": refund_id,
                            "completed_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                logger.info(f"✅ Updated auth refund status to completed in refunds collection")
            else:
                logger.info(f"✅ Auth service refund processed: ${amount} for user {user_id} (no record found)")
            
            return True, f"Auth refund completed: {refund_type}"
                
        except Exception as e:
            logger.error(f"Error handling auth refund: {e}")
            return False, f"Error: {str(e)}"
    
    async def _handle_admin_refund(self, payment_intent: str, refund_id: str, amount: float, metadata: Dict) -> Tuple[bool, str]:
        """Handle refunds from admin service"""
        try:
            club_id = metadata.get('club_id')
            admin_id = metadata.get('admin_id')
            refund_type = metadata.get('refund_type')
            
            # Admin refunds might be in club_refunds or refunds collection (EXISTING)
            refund_request = await self.club_refunds_collection.find_one({
                "payment_id": payment_intent
            })
            
            if not refund_request:
                refund_request = await self.refunds_collection.find_one({
                    "payment_id": payment_intent
                })
            
            if refund_request:
                # Update whichever collection it's in
                collection = self.club_refunds_collection if await self.club_refunds_collection.find_one({"_id": refund_request["_id"]}) else self.refunds_collection
                
                await collection.update_one(
                    {"_id": refund_request["_id"]},
                    {
                        "$set": {
                            "refund_status": "completed",
                            "stripe_refund_id": refund_id,
                            "completed_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                logger.info(f"✅ Updated admin refund status to completed")
            else:
                logger.info(f"✅ Admin service refund processed: ${amount} for club {club_id} by admin {admin_id} (no record found)")
            
            return True, f"Admin refund completed: {refund_type}"
                
        except Exception as e:
            logger.error(f"Error handling admin refund: {e}")
            return False, f"Error: {str(e)}"
    
    async def _handle_generic_refund(self, payment_intent: str, refund_id: str, amount: float) -> Tuple[bool, str]:
        """Handle refunds with unknown type (fallback)"""
        try:
            logger.info(f"✅ Generic refund processed: ${amount} for payment_intent {payment_intent}")
            return True, "Generic refund logged"
                
        except Exception as e:
            logger.error(f"Error handling generic refund: {e}")
            return False, f"Error: {str(e)}"
    
    async def handle_charge_refund_updated(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Handle refund status update
        
        Args:
            event: Stripe event
            
        Returns:
            Tuple of (success, message)
        """
        try:
            refund = event['data']['object']
            refund_id = refund.get('id')
            status = refund.get('status')
            
            logger.info(f"📝 Refund updated: {refund_id}, status: {status}")
            
            # Find refund by stripe_refund_id in both collections (EXISTING)
            refund_request = await self.club_refunds_collection.find_one({
                "stripe_refund_id": refund_id
            })
            
            collection = self.club_refunds_collection
            
            if not refund_request:
                refund_request = await self.refunds_collection.find_one({
                    "stripe_refund_id": refund_id
                })
                collection = self.refunds_collection
            
            if refund_request:
                # Map Stripe refund status
                refund_status_mapping = {
                    "succeeded": "completed",
                    "pending": "processing",
                    "failed": "failed",
                    "canceled": "cancelled"
                }
                
                our_status = refund_status_mapping.get(status, status)
                
                await collection.update_one(
                    {"_id": refund_request["_id"]},
                    {
                        "$set": {
                            "refund_status": our_status,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                
                logger.info(f"✅ Updated refund status to {our_status}")
                return True, f"Refund status updated to {our_status}"
            else:
                return True, "Refund not found in our system"
            
        except Exception as e:
            logger.error(f"Error handling charge.refund.updated: {e}")
            return False, f"Error: {str(e)}"


# Global handler instance
_refund_handler: Optional[RefundWebhookHandler] = None

def get_refund_handler() -> RefundWebhookHandler:
    """Get refund webhook handler instance"""
    global _refund_handler
    if _refund_handler is None:
        _refund_handler = RefundWebhookHandler()
    return _refund_handler

