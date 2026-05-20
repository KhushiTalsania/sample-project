"""
Stripe Webhooks API Routes

This module provides API endpoints for handling Stripe webhook events.
It processes subscription updates, billing events, and payment status changes.
"""

import logging
import stripe
import os
from fastapi import APIRouter, Request, HTTPException, status
from typing import Dict, Any

from services.auth.stripe_webhook_service import get_stripe_webhook_service

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/stripe-webhooks")
async def handle_stripe_webhook(request: Request):
    """
    Handle Stripe webhook events
    
    **Features:**
    - **Stripe Signature Verification**: Verifies webhook authenticity
    - **Event Processing**: Handles subscription and payment events
    - **Database Updates**: Updates membership status based on Stripe events
    - **Error Handling**: Comprehensive error handling and logging
    
    **Supported Events:**
    - `customer.subscription.updated`: Updates membership status
    - `customer.subscription.deleted`: Cancels membership
    - `invoice.payment_succeeded`: Extends billing period
    - `invoice.payment_failed`: Marks payment as failed
    
    **Security:**
    - Verifies Stripe webhook signature
    - Validates event authenticity
    - Prevents replay attacks
    
    **Example Usage:**
    ```
    POST /auth/stripe-webhooks
    Content-Type: application/json
    Stripe-Signature: t=timestamp,v1=signature
    
    {
      "id": "evt_1234567890",
      "object": "event",
      "type": "customer.subscription.updated",
      "data": {
        "object": {
          "id": "sub_1234567890",
          "customer": "cus_1234567890",
          "status": "active"
        }
      }
    }
    ```
    """
    try:
        # Get the raw body and signature
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        if not sig_header:
            logger.error("Missing Stripe signature header")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe signature header"
            )
        
        # Verify webhook signature
        webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        if not webhook_secret:
            logger.error("Stripe webhook secret not configured")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook secret not configured"
            )
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payload"
            )
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature"
            )
        
        # Get webhook service
        webhook_service = get_stripe_webhook_service()
        
        # Handle different event types
        event_type = event['type']
        event_data = event['data']['object']
        
        logger.info(f"Processing Stripe webhook event: {event_type}")
        
        success = False
        
        if event_type == 'customer.subscription.updated':
            success = await webhook_service.handle_subscription_updated(event_data)
        elif event_type == 'customer.subscription.deleted':
            success = await webhook_service.handle_subscription_deleted(event_data)
        elif event_type == 'invoice.payment_succeeded':
            success = await webhook_service.handle_invoice_payment_succeeded(event_data)
        elif event_type == 'invoice.payment_failed':
            success = await webhook_service.handle_invoice_payment_failed(event_data)
        else:
            logger.info(f"Unhandled event type: {event_type}")
            return {"status": "ignored", "message": f"Event type {event_type} not handled"}
        
        if success:
            logger.info(f"Successfully processed webhook event: {event_type}")
            return {"status": "success", "message": f"Event {event_type} processed successfully"}
        else:
            logger.error(f"Failed to process webhook event: {event_type}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process event {event_type}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in Stripe webhook handler: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )
