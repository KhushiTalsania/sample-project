"""
Unified Webhook Routes

Single endpoint to handle ALL Stripe webhook events.
This endpoint routes events to appropriate handlers.
"""

import logging
from fastapi import APIRouter, Request, HTTPException
from typing import Dict, Any

from .webhook_utils import verify_webhook_signature, log_webhook_event, mark_webhook_processed, get_event_context, extract_metadata
from .subscription_webhook_handler import get_subscription_handler
from .refund_webhook_handler import get_refund_handler
from .connect_webhook_handler import get_connect_handler
from .models import WebhookResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def get_webhook_collection():
    """Get webhook events collection"""
    from services.club.db import db
    return db["webhook_events"]


@router.post("/stripe", response_model=WebhookResponse)
async def unified_stripe_webhook(request: Request):
    """
    Unified Stripe Webhook Handler
    
    This single endpoint handles ALL Stripe events:
    - Join-paid subscription renewals (CRITICAL)
    - Trial memberships
    - Club creation payments
    - Moderator payments
    - Refunds
    - Stripe Connect events
    
    **Event Routing:**
    - Subscription events → SubscriptionWebhookHandler
    - Refund events → RefundWebhookHandler
    - Connect events → ConnectWebhookHandler
    
    **Features:**
    - ✅ Signature verification
    - ✅ Event logging (idempotency)
    - ✅ Error handling
    - ✅ Automatic routing
    
    **Configure in Stripe Dashboard:**
    ```
    URL: https://your-domain.com/api/v1/webhooks/stripe
    Events: See WEBHOOK_IMPLEMENTATION_CHECKLIST.md
    ```
    """
    try:
        print(f"🔔 Received webhook with signaturesssssssssssss: {request}")
        print(f"🔍 All headers: {dict(request.headers)}")
        
        # 1. Verify webhook signature
        event = await verify_webhook_signature(request)
        
        # 2. Get event context
        event_type, event_id, data_object = get_event_context(event)
        
        logger.info(f"🔔 Received webhook: {event_type} (ID: {event_id})")
        
        # 3. Log event to database (idempotency check)
        webhook_collection = get_webhook_collection()
        is_new_event = await log_webhook_event(event, webhook_collection)
        
        if not is_new_event:
            logger.info(f"ℹ️ Event {event_id} already processed - skipping")
            return WebhookResponse(
                status="success",
                message="Event already processed",
                event_id=event_id,
                event_type=event_type,
                processed=True
            )
        
        # 4. Route event to appropriate handler
        success, message = await route_webhook_event(event_type, event)
        
        # 5. Mark event as processed
        await mark_webhook_processed(event_id, webhook_collection, success, None if success else message)
        
        # 6. Return response
        if success:
            logger.info(f"✅ Successfully processed webhook {event_type}")
            return WebhookResponse(
                status="success",
                message=message,
                event_id=event_id,
                event_type=event_type,
                processed=True
            )
        else:
            logger.error(f"❌ Failed to process webhook {event_type}: {message}")
            # Still return 200 to Stripe to prevent retries
            return WebhookResponse(
                status="error",
                message=message,
                event_id=event_id,
                event_type=event_type,
                processed=False
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"💥 Unexpected error in webhook handler: {e}")
        import traceback
        traceback.print_exc()
        # Return 200 to prevent Stripe retries
        return WebhookResponse(
            status="error",
            message=f"Internal error: {str(e)}",
            processed=False
        )


async def route_webhook_event(event_type: str, event: Dict[str, Any]) -> tuple[bool, str]:
    """
    Route webhook event to appropriate handler
    
    Args:
        event_type: Stripe event type
        event: Full Stripe event
        
    Returns:
        Tuple of (success, message)
    """
    try:
        # ============================================================
        # SUBSCRIPTION EVENTS (CRITICAL for join-paid memberships)
        # ============================================================
        if event_type == 'invoice.payment_succeeded':
            logger.info("💰 Routing to subscription handler: invoice.payment_succeeded")
            handler = get_subscription_handler()
            return await handler.handle_invoice_payment_succeeded(event)
        
        elif event_type == 'invoice.payment_failed':
            logger.info("💸 Routing to subscription handler: invoice.payment_failed")
            handler = get_subscription_handler()
            return await handler.handle_invoice_payment_failed(event)
        
        elif event_type == 'customer.subscription.deleted':
            logger.info("🗑️ Routing to subscription handler: subscription.deleted")
            handler = get_subscription_handler()
            return await handler.handle_subscription_deleted(event)
        
        elif event_type == 'customer.subscription.updated':
            logger.info("📝 Routing to subscription handler: subscription.updated")
            handler = get_subscription_handler()
            return await handler.handle_subscription_updated(event)
        
        elif event_type == 'customer.subscription.created':
            logger.info("✅ Subscription created (already handled by API)")
            return True, "Subscription created - handled by API"
        
        elif event_type == 'customer.subscription.trial_will_end':
            logger.info("⚠️ Trial will end - notification event")
            # TODO: Send trial ending notification
            return True, "Trial ending notification (TODO: send email)"
        
        # ============================================================
        # REFUND EVENTS
        # ============================================================
        elif event_type == 'charge.refunded':
            logger.info("💰 Routing to refund handler: charge.refunded")
            handler = get_refund_handler()
            return await handler.handle_charge_refunded(event)
        
        elif event_type == 'charge.refund.updated':
            logger.info("📝 Routing to refund handler: refund.updated")
            handler = get_refund_handler()
            return await handler.handle_charge_refund_updated(event)
        
        # ============================================================
        # STRIPE CONNECT EVENTS
        # ============================================================
        elif event_type == 'account.updated':
            logger.info("🏦 Routing to Connect handler: account.updated")
            handler = get_connect_handler()
            return await handler.handle_account_updated(event)
        
        elif event_type == 'payout.paid':
            logger.info("💰 Routing to Connect handler: payout.paid")
            handler = get_connect_handler()
            return await handler.handle_payout_paid(event)
        
        elif event_type == 'payout.failed':
            logger.info("💸 Routing to Connect handler: payout.failed")
            handler = get_connect_handler()
            return await handler.handle_payout_failed(event)
        
        elif event_type == 'transfer.created':
            logger.info("💸 Routing to Connect handler: transfer.created")
            handler = get_connect_handler()
            return await handler.handle_transfer_created(event)
        
        elif event_type == 'transfer.failed':
            logger.info("❌ Routing to Connect handler: transfer.failed")
            handler = get_connect_handler()
            return await handler.handle_transfer_failed(event)
        
        # ============================================================
        # PAYMENT INTENT EVENTS (one-time payments)
        # ============================================================
        elif event_type == 'payment_intent.succeeded':
            # Check metadata to determine payment type
            metadata = extract_metadata(event)
            payment_type = metadata.get('payment_type', '')
            
            if payment_type == 'club_creation':
                # Already handled by existing club webhook
                logger.info("✅ Club creation payment - handled by existing webhook")
                return True, "Club creation payment handled"
            
            elif payment_type == 'connect_payment':
                # Connect payment with revenue split
                logger.info("💰 Routing to Connect handler: payment_intent.succeeded (Connect)")
                handler = get_connect_handler()
                return await handler.handle_payment_intent_succeeded_connect(event)
            
            elif payment_type == 'plan_change':
                # Plan change payment
                logger.info("🔄 Routing to subscription handler: payment_intent.succeeded (Plan Change)")
                handler = get_subscription_handler()
                return await handler.handle_plan_change_payment_succeeded(event)
            
            elif payment_type == 'fallback':
                # Fallback payment (when subscription creation fails)
                logger.info("💰 Routing to subscription handler: payment_intent.succeeded (Fallback)")
                handler = get_subscription_handler()
                return await handler.handle_fallback_payment_succeeded(event)
            
            elif payment_type == 'moderator_upgrade' or payment_type == 'moderator_addition':
                # Moderator payments - logged but already handled synchronously
                logger.info(f"✅ {payment_type} payment succeeded - logged")
                return True, f"{payment_type} payment logged"
            
            else:
                # Other payment intents - logged
                logger.info(f"✅ Payment intent succeeded - logged (type: {payment_type or 'unknown'})")
                return True, "Payment intent logged"
        
        elif event_type == 'payment_intent.payment_failed':
            # Check metadata to determine payment type
            metadata = extract_metadata(event)
            payment_type = metadata.get('payment_type', '')
            
            if payment_type == 'connect_payment':
                # Failed Connect payment
                logger.info("💸 Routing to Connect handler: payment_intent.failed (Connect)")
                handler = get_connect_handler()
                return await handler.handle_payment_intent_failed_connect(event)
            
            elif payment_type == 'plan_change':
                # Failed plan change payment
                logger.info("💸 Routing to subscription handler: payment_intent.failed (Plan Change)")
                handler = get_subscription_handler()
                return await handler.handle_plan_change_payment_failed(event)
            
            else:
                logger.info(f"❌ Payment intent failed - logged (type: {payment_type or 'unknown'})")
                return True, "Payment intent failure logged"
        
        # ============================================================
        # INVOICE EVENTS (informational)
        # ============================================================
        elif event_type == 'invoice.upcoming':
            logger.info("📅 Upcoming invoice - renewal reminder")
            # TODO: Send renewal reminder email
            return True, "Renewal reminder (TODO: send email)"
        
        elif event_type == 'invoice.finalized':
            logger.info("📄 Invoice finalized - logged")
            return True, "Invoice finalized"
        
        # ============================================================
        # PRODUCT/PRICE EVENTS (already handled by existing webhook)
        # ============================================================
        elif event_type in ['product.created', 'product.updated', 'product.deleted', 
                           'price.created', 'price.updated', 'price.deleted']:
            logger.info(f"✅ Product/Price event: {event_type} - handled by existing webhook")
            return True, f"Product/Price event handled by existing webhook"
        
        # ============================================================
        # UNHANDLED EVENTS
        # ============================================================
        else:
            logger.warning(f"⚠️ Unhandled webhook event type: {event_type}")
            return True, f"Event type {event_type} not handled (logged only)"
    
    except Exception as e:
        logger.error(f"Error routing webhook event: {e}")
        import traceback
        traceback.print_exc()
        return False, f"Routing error: {str(e)}"


@router.get("/health")
async def webhook_health_check():
    """
    Health check endpoint for webhook service
    
    Returns webhook service status and configuration info
    """
    import os
    
    return {
        "status": "healthy",
        "service": "Unified Webhook Handler",
        "webhook_secret_configured": bool(os.getenv('STRIPE_WEBHOOK_SECRET')),
        "handlers": {
            "subscription": "active",
            "refund": "active",
            "connect": "active"
        },
        "endpoint": "/api/v1/webhooks/stripe",
        "message": "Configure this endpoint in Stripe Dashboard"
    }


@router.get("/events/recent")
async def get_recent_webhook_events(limit: int = 20):
    """
    Get recent webhook events (for admin dashboard)
    
    Args:
        limit: Number of events to return (max 100)
    """
    try:
        webhook_collection = get_webhook_collection()
        
        # Limit to max 100
        limit = min(limit, 100)
        
        events = await webhook_collection.find().sort("received_at", -1).limit(limit).to_list(limit)
        
        # Convert ObjectId to string for JSON serialization
        for event in events:
            event["_id"] = str(event["_id"])
        
        return {
            "status": "success",
            "count": len(events),
            "events": events
        }
    
    except Exception as e:
        logger.error(f"Error fetching recent webhook events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

