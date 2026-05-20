"""
Webhook Utilities

Helper functions for webhook processing, signature verification, and logging.
"""

import os
import stripe
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')


async def verify_webhook_signature(request: Request) -> Dict[str, Any]:
    """
    Verify Stripe webhook signature
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Verified Stripe event
        
    Raises:
        HTTPException: If signature verification fails
    """
    try:
        payload = await request.body()
        print(f"🔔 Received webhook with payload: {payload}")
        sig_header = request.headers.get('stripe-signature')
        print(f"🔔 Received webhook with signature: {sig_header}")
        if not sig_header:
            logger.error("Missing Stripe signature header")
            raise HTTPException(status_code=400, detail="Missing Stripe signature")
        
        if not STRIPE_WEBHOOK_SECRET:
            logger.warning("⚠️ STRIPE_WEBHOOK_SECRET not configured - skipping signature verification")
            # For development - allow without verification but log warning
            import json
            event = json.loads(payload.decode('utf-8'))
            logger.warning(f"⚠️ Processing webhook without signature verification: {event.get('type')}")
            return event
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
            logger.info(f"✅ Webhook signature verified for event: {event['type']}")
            return event
            
        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        raise HTTPException(status_code=500, detail="Webhook verification error")


async def log_webhook_event(event: Dict[str, Any], db_collection) -> bool:
    """
    Log webhook event to database
    
    Args:
        event: Stripe event
        db_collection: MongoDB collection for webhook logs
        
    Returns:
        True if logged successfully
    """
    try:
        event_id = event.get('id')
        
        # Check if event already exists (idempotency)
        existing = await db_collection.find_one({"event_id": event_id})
        if existing:
            logger.info(f"ℹ️ Webhook event {event_id} already processed")
            return False
        
        webhook_log = {
            "event_id": event_id,
            "event_type": event.get('type'),
            "livemode": event.get('livemode', False),
            "created": datetime.fromtimestamp(event.get('created', 0)),
            "received_at": datetime.utcnow(),
            "processed": False,
            "processed_at": None,
            "error": None,
            "retry_count": 0,
            "payload": event
        }
        
        await db_collection.insert_one(webhook_log)
        logger.info(f"✅ Logged webhook event: {event_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error logging webhook event: {e}")
        return False


async def mark_webhook_processed(event_id: str, db_collection, success: bool = True, error: str = None):
    """
    Mark webhook event as processed
    
    Args:
        event_id: Stripe event ID
        db_collection: MongoDB collection for webhook logs
        success: Whether processing was successful
        error: Error message if processing failed
    """
    try:
        update_data = {
            "processed": success,
            "processed_at": datetime.utcnow()
        }
        
        if error:
            update_data["error"] = error
        
        await db_collection.update_one(
            {"event_id": event_id},
            {"$set": update_data}
        )
        
        if success:
            logger.info(f"✅ Marked webhook {event_id} as processed")
        else:
            logger.error(f"❌ Marked webhook {event_id} as failed: {error}")
            
    except Exception as e:
        logger.error(f"Error marking webhook processed: {e}")


def extract_metadata(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract metadata from Stripe event
    
    Args:
        event: Stripe event
        
    Returns:
        Metadata dictionary
    """
    try:
        data_object = event.get('data', {}).get('object', {})
        metadata = data_object.get('metadata', {})
        return metadata
    except Exception as e:
        logger.error(f"Error extracting metadata: {e}")
        return {}


def get_event_context(event: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """
    Get event context (type, ID, object)
    
    Args:
        event: Stripe event
        
    Returns:
        Tuple of (event_type, event_id, data_object)
    """
    event_type = event.get('type', 'unknown')
    event_id = event.get('id', 'unknown')
    data_object = event.get('data', {}).get('object', {})
    
    return event_type, event_id, data_object


