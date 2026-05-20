from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
import stripe
import os
import json
import hmac
import hashlib
from datetime import datetime
from bson import ObjectId
from ..db import get_user_collection
from ..utils import get_user_collection
import asyncio
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Stripe configuration
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')

STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

def get_webhook_events_collection():
    """Get webhook events collection from main database"""
    from ..db import db
    return db["webhook_events"]

def get_payment_records_collection():
    """Get payment records collection"""
    from ..db import db
    return db["payment_records"]

@router.post("/webhooks/stripe")
async def stripe_webhook_handler(request: Request):
    """
    Handle Stripe webhook events for membership and captain payments
    """
    try:
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        print(f"🔔 Received webhook with signature: {sig_header}")
        print(f"🔍 All headers: {dict(request.headers)}")
        
        # Check if this is a test request from API docs (no signature)
        if not sig_header or sig_header == "None":
            print("⚠️ No Stripe signature detected - this might be a test request from API docs")
            print("💡 For testing from API docs, we'll process without signature verification")
            
            try:
                # Try to parse as JSON for testing
                event = json.loads(payload.decode('utf-8'))
                print("✅ Processed test payload without signature verification")
            except json.JSONDecodeError:
                print("❌ Invalid JSON payload")
                raise HTTPException(status_code=400, detail="Invalid JSON payload")
        else:
            # Normal Stripe webhook processing with signature verification
            if not STRIPE_WEBHOOK_SECRET:
                print("⚠️ No webhook secret configured - processing without verification (LOCAL ONLY)")
                event = json.loads(payload.decode('utf-8'))
            else:
                try:
                    # Verify webhook signature
                    event = stripe.Webhook.construct_event(
                        payload, sig_header, STRIPE_WEBHOOK_SECRET
                    )
                    print("✅ Webhook signature verified")
                except ValueError as e:
                    print(f"❌ Invalid payload: {e}")
                    raise HTTPException(status_code=400, detail="Invalid payload")
                except stripe.error.SignatureVerificationError as e:
                    print(f"❌ Invalid signature: {e}")
                    raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Log the webhook event
        await log_webhook_event(event)
        
        # Handle different event types
        event_type = event.get('type', 'unknown')
        print(f"🔔 Processing webhook event: {event_type}")
        
        if event_type == 'invoice.payment_succeeded':
            await handle_payment_succeeded(event)
        elif event_type == 'invoice.payment_failed':
            await handle_payment_failed(event)
        elif event_type == 'customer.subscription.created':
            await handle_subscription_created(event)
        elif event_type == 'customer.subscription.updated':
            await handle_subscription_updated(event)
        elif event_type == 'customer.subscription.deleted':
            await handle_subscription_deleted(event)
        elif event_type == 'payment_intent.succeeded':
            await handle_payment_intent_succeeded(event)
        elif event_type == 'payment_intent.payment_failed':
            await handle_payment_intent_failed(event)
        else:
            print(f"⚠️ Unhandled event type: {event_type}")
        
        return {"status": "success", "event_type": event_type, "message": "Webhook processed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Webhook processing error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

async def log_webhook_event(event):
    """Log webhook event to database"""
    try:
        webhook_collection = get_webhook_events_collection()
        
        webhook_record = {
            "event_id": event['id'],
            "event_type": event['type'],
            "livemode": event.get('livemode', False),
            "created": datetime.fromtimestamp(event['created']),
            "data": event['data'],
            "processed": False,
            "processed_at": None,
            "error": None,
            "received_at": datetime.utcnow()
        }
        
        # Check if event already exists
        existing = await webhook_collection.find_one({"event_id": event['id']})
        if existing:
            print(f"⚠️ Webhook event {event['id']} already processed")
            return
        
        await webhook_collection.insert_one(webhook_record)
        print(f"✅ Logged webhook event: {event['id']}")
        
    except Exception as e:
        print(f"❌ Error logging webhook event: {str(e)}")

async def handle_payment_succeeded(event):
    """Handle successful payment"""
    try:
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')
        customer_id = invoice.get('customer')
        amount_paid = invoice.get('amount_paid', 0) / 100  # Convert from cents
        
        print(f"💰 Payment succeeded: ${amount_paid} for subscription {subscription_id}")
        
        if subscription_id:
            # Get subscription details to get metadata
            subscription = stripe.Subscription.retrieve(subscription_id)
            metadata = subscription.metadata
            
            user_id = metadata.get('user_id')
            membership_type = metadata.get('membership_type', 'paid')
            
            if user_id:
                # Update user membership status
                await update_user_membership_status(
                    user_id=user_id,
                    status="active",
                    membership_type=membership_type,
                    subscription_id=subscription_id,
                    customer_id=customer_id
                )
                
                # Store payment record
                await store_payment_record(
                    user_id=user_id,
                    subscription_id=subscription_id,
                    customer_id=customer_id,
                    amount=amount_paid,
                    currency=invoice.get('currency', 'usd'),
                    status="succeeded",
                    invoice_id=invoice.get('id'),
                    event_type="payment_succeeded"
                )
                
                print(f"✅ Updated user {user_id} membership to active ({membership_type})")
            else:
                print("⚠️ No user_id found in subscription metadata")
        
        # Mark webhook as processed
        await mark_webhook_processed(event['id'])
        
    except Exception as e:
        print(f"❌ Error handling payment success: {str(e)}")
        await mark_webhook_error(event['id'], str(e))

async def handle_payment_failed(event):
    """Handle failed payment"""
    try:
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')
        customer_id = invoice.get('customer')
        
        print(f"💸 Payment failed for subscription {subscription_id}")
        
        if subscription_id:
            # Get subscription details
            subscription = stripe.Subscription.retrieve(subscription_id)
            metadata = subscription.metadata
            user_id = metadata.get('user_id')
            
            if user_id:
                # Update user membership status to payment_failed
                await update_user_membership_status(
                    user_id=user_id,
                    status="payment_failed",
                    subscription_id=subscription_id,
                    customer_id=customer_id
                )
                
                # Store failed payment record
                await store_payment_record(
                    user_id=user_id,
                    subscription_id=subscription_id,
                    customer_id=customer_id,
                    amount=0,
                    currency=invoice.get('currency', 'usd'),
                    status="failed",
                    invoice_id=invoice.get('id'),
                    event_type="payment_failed"
                )
                
                print(f"⚠️ Updated user {user_id} membership to payment_failed")
        
        await mark_webhook_processed(event['id'])
        
    except Exception as e:
        print(f"❌ Error handling payment failure: {str(e)}")
        await mark_webhook_error(event['id'], str(e))

async def handle_subscription_created(event):
    """Handle subscription creation"""
    try:
        subscription = event['data']['object']
        subscription_id = subscription['id']
        customer_id = subscription['customer']
        metadata = subscription.get('metadata', {})
        
        user_id = metadata.get('user_id')
        print(f"📝 Subscription created: {subscription_id} for user {user_id}")
        
        if user_id:
            # Update user with subscription info
            users_collection = get_user_collection()
            await users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "subscription_id": subscription_id,
                        "stripe_customer_id": customer_id,
                        "subscription_status": subscription['status'],
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            print(f"✅ Updated user {user_id} with subscription info")
        
        await mark_webhook_processed(event['id'])
        
    except Exception as e:
        print(f"❌ Error handling subscription creation: {str(e)}")
        await mark_webhook_error(event['id'], str(e))

async def handle_subscription_updated(event):
    """Handle subscription updates"""
    try:
        subscription = event['data']['object']
        subscription_id = subscription['id']
        status = subscription['status']
        metadata = subscription.get('metadata', {})
        
        user_id = metadata.get('user_id')
        print(f"📝 Subscription updated: {subscription_id} status: {status}")
        
        if user_id:
            # Map Stripe status to our status
            status_mapping = {
                "active": "active",
                "past_due": "past_due",
                "canceled": "cancelled",
                "unpaid": "payment_failed",
                "incomplete": "pending"
            }
            
            mapped_status = status_mapping.get(status, "unknown")
            if mapped_status != "unknown":
                await update_user_membership_status(
                    user_id=user_id,
                    status=mapped_status,
                    subscription_id=subscription_id
                )
                print(f"✅ Updated user {user_id} membership status to {mapped_status}")
        
        await mark_webhook_processed(event['id'])
        
    except Exception as e:
        print(f"❌ Error handling subscription update: {str(e)}")
        await mark_webhook_error(event['id'], str(e))

async def handle_subscription_deleted(event):
    """Handle subscription cancellation"""
    try:
        subscription = event['data']['object']
        subscription_id = subscription['id']
        metadata = subscription.get('metadata', {})
        
        user_id = metadata.get('user_id')
        print(f"🗑️ Subscription cancelled: {subscription_id}")
        
        if user_id:
            await update_user_membership_status(
                user_id=user_id,
                status="cancelled",
                subscription_id=subscription_id
            )
            print(f"✅ Updated user {user_id} membership to cancelled")
        
        await mark_webhook_processed(event['id'])
        
    except Exception as e:
        print(f"❌ Error handling subscription deletion: {str(e)}")
        await mark_webhook_error(event['id'], str(e))

async def handle_payment_intent_succeeded(event):
    """Handle one-time payment success"""
    try:
        payment_intent = event['data']['object']
        metadata = payment_intent.get('metadata', {})
        
        user_id = metadata.get('user_id')
        amount = payment_intent.get('amount', 0) / 100
        
        print(f"💰 One-time payment succeeded: ${amount} for user {user_id}")
        
        if user_id:
            await store_payment_record(
                user_id=user_id,
                payment_intent_id=payment_intent['id'],
                amount=amount,
                currency=payment_intent.get('currency', 'usd'),
                status="succeeded",
                event_type="payment_intent_succeeded"
            )
        
        await mark_webhook_processed(event['id'])
        
    except Exception as e:
        print(f"❌ Error handling payment intent success: {str(e)}")
        await mark_webhook_error(event['id'], str(e))

async def handle_payment_intent_failed(event):
    """Handle one-time payment failure"""
    try:
        payment_intent = event['data']['object']
        metadata = payment_intent.get('metadata', {})
        
        user_id = metadata.get('user_id')
        print(f"💸 One-time payment failed for user {user_id}")
        
        if user_id:
            await store_payment_record(
                user_id=user_id,
                payment_intent_id=payment_intent['id'],
                amount=0,
                currency=payment_intent.get('currency', 'usd'),
                status="failed",
                event_type="payment_intent_failed"
            )
        
        await mark_webhook_processed(event['id'])
        
    except Exception as e:
        print(f"❌ Error handling payment intent failure: {str(e)}")
        await mark_webhook_error(event['id'], str(e))

async def update_user_membership_status(
    user_id: str, 
    status: str, 
    membership_type: str = None,
    subscription_id: str = None,
    customer_id: str = None
):
    """Update user membership status in database"""
    try:
        users_collection = get_user_collection()
        
        update_data = {
            "membership_status": status,
            "updated_at": datetime.utcnow()
        }
        
        if membership_type:
            update_data["membership_type"] = membership_type
        if subscription_id:
            update_data["subscription_id"] = subscription_id
        if customer_id:
            update_data["stripe_customer_id"] = customer_id
        
        # Update complete_step to 1 when payment succeeds
        if status == "active":
            update_data["complete_step"] = 1
        
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )
        
        # If user is a captain and membership is activated, update club count
        if result.modified_count > 0 and status == "active":
            try:
                user = await users_collection.find_one({"_id": ObjectId(user_id)})
                if user and user.get("role") == "Captain":
                    from ..utils import get_club_count_for_captain, update_user_club_count
                    club_count = await get_club_count_for_captain(user_id)
                    await update_user_club_count(user_id, club_count)
                    print(f"👑 Captain {user.get('full_name', 'Unknown')} club count updated to {club_count} after membership activation")
            except Exception as e:
                print(f"⚠️ Could not update club count for captain after membership activation: {e}")
        
        return result.modified_count > 0
        
    except Exception as e:
        print(f"❌ Error updating user membership status: {str(e)}")
        return False

async def store_payment_record(
    user_id: str,
    amount: float,
    currency: str,
    status: str,
    event_type: str,
    subscription_id: str = None,
    customer_id: str = None,
    invoice_id: str = None,
    payment_intent_id: str = None
):
    """Store payment record in database"""
    try:
        payment_collection = get_payment_records_collection()
        
        payment_record = {
            "user_id": user_id,
            "subscription_id": subscription_id,
            "customer_id": customer_id,
            "invoice_id": invoice_id,
            "payment_intent_id": payment_intent_id,
            "amount": amount,
            "currency": currency,
            "status": status,
            "event_type": event_type,
            "created_at": datetime.utcnow()
        }
        
        await payment_collection.insert_one(payment_record)
        print(f"✅ Stored payment record for user {user_id}")
        
    except Exception as e:
        print(f"❌ Error storing payment record: {str(e)}")

async def mark_webhook_processed(event_id: str):
    """Mark webhook event as processed"""
    try:
        webhook_collection = get_webhook_events_collection()
        await webhook_collection.update_one(
            {"event_id": event_id},
            {
                "$set": {
                    "processed": True,
                    "processed_at": datetime.utcnow()
                }
            }
        )
    except Exception as e:
        print(f"❌ Error marking webhook processed: {str(e)}")

async def mark_webhook_error(event_id: str, error: str):
    """Mark webhook event as having an error"""
    try:
        webhook_collection = get_webhook_events_collection()
        await webhook_collection.update_one(
            {"event_id": event_id},
            {
                "$set": {
                    "processed": True,
                    "processed_at": datetime.utcnow(),
                    "error": error
                }
            }
        )
    except Exception as e:
        print(f"❌ Error marking webhook error: {str(e)}")

@router.get("/webhooks/test")
async def test_webhook_endpoint():
    """Test endpoint to verify webhook is working"""
    return {
        "status": "ok",
        "message": "Webhook endpoint is working",
        "webhook_secret_configured": bool(STRIPE_WEBHOOK_SECRET),
        "timestamp": datetime.utcnow().isoformat()
    }

@router.post("/webhooks/test")
async def test_webhook_post(request: Request):
    """Test endpoint for API docs - accepts any JSON payload without signature verification"""
    try:
        payload = await request.body()
        print("🧪 Test webhook endpoint called")
        print(f"📝 Payload: {payload.decode('utf-8')}")
        
        # Parse JSON payload
        event = json.loads(payload.decode('utf-8'))
        
        return {
            "status": "success",
            "message": "Test webhook processed successfully",
            "event_type": event.get('type', 'test'),
            "payload_received": True
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Test webhook error: {str(e)}") 