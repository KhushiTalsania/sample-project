# from fastapi import APIRouter, HTTPException, Depends, Request, status
# from typing import List, Dict, Optional
# import stripe
# import os
# from datetime import datetime
# from bson import ObjectId
# from .models import (
#     ClubPricingPlansRequest, 
#     ClubPricingPlansResponse,
#     ClubMembershipPaymentRequest,
#     ClubMembershipPaymentResponse,
#     StripePricingPlan,
#     WebhookEventData
# )
# from .auth import get_current_captain, get_current_user
# from .db import get_club_collection, get_membership_collection, get_user_collection
# from .stripe_service import StripeService
# from .membership_service import create_club_membership, update_membership_status
# import json
# import hmac
# import hashlib

# router = APIRouter()

# # Stripe webhook secret
# STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

# @router.post("/clubs/{club_id}/pricing-plans", response_model=ClubPricingPlansResponse)
# async def create_club_pricing_plans(
#     club_id: str,
#     pricing_request: ClubPricingPlansRequest,
#     current_captain: dict = Depends(get_current_captain)
# ):
#     """Create dynamic pricing plans for a club with Stripe integration"""
#     try:
#         club_collection = get_club_collection()
        
#         # Validate club exists and belongs to captain
#         try:
#             club_object_id = ObjectId(club_id)
#         except Exception:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Invalid club ID format"
#             )
        
#         club = await club_collection.find_one({
#             "_id": club_object_id,
#             "captain_id": current_captain["user_id"],
#             "is_active": True
#         })
        
#         if not club:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Club not found or you don't have permission to modify it"
#             )
        
#         # Create pricing plans in Stripe
#         updated_plans = await StripeService.create_pricing_plans_for_club(
#             club_id=club_id,
#             club_name=club["name"],
#             captain_id=current_captain["user_id"],
#             pricing_plans=pricing_request.pricing_plans
#         )
        
#         # Update club in database
#         await StripeService.update_club_pricing_plans(club_id, updated_plans)
        
#         return ClubPricingPlansResponse(
#             success=True,
#             message="Pricing plans created successfully",
#             club_id=club_id,
#             pricing_plans=updated_plans
#         )
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ Error creating pricing plans: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to create pricing plans: {str(e)}"
#         )

# @router.get("/clubs/{club_id}/pricing-plans")
# async def get_club_pricing_plans(
#     club_id: str,
#     current_user: Optional[dict] = Depends(get_current_user)
# ):
#     """Get pricing plans for a club"""
#     try:
#         club_collection = get_club_collection()
        
#         try:
#             club_object_id = ObjectId(club_id)
#         except Exception:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Invalid club ID format"
#             )
        
#         club = await club_collection.find_one({
#             "_id": club_object_id,
#             "is_active": True
#         })
        
#         if not club:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Club not found"
#             )
        
#         pricing_plans = club.get("pricing_plans", [])
        
#         return {
#             "success": True,
#             "club_id": club_id,
#             "club_name": club["name"],
#             "pricing_plans": pricing_plans
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ Error getting pricing plans: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to get pricing plans: {str(e)}"
#         )

# @router.post("/clubs/join-membership", response_model=ClubMembershipPaymentResponse)
# async def join_club_membership(
#     membership_request: ClubMembershipPaymentRequest,
#     current_user: dict = Depends(get_current_user)
# ):
#     """Join a club with payment processing"""
#     try:
#         club_id = membership_request.club_id
#         pricing_plan = membership_request.pricing_plan
#         payment_method_id = membership_request.payment_method_id
#         user_id = current_user["user_id"]
        
#         # Get club and validate
#         club_collection = get_club_collection()
#         try:
#             club_object_id = ObjectId(club_id)
#         except Exception:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Invalid club ID format"
#             )
        
#         club = await club_collection.find_one({
#             "_id": club_object_id,
#             "is_active": True
#         })
        
#         if not club:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Club not found"
#             )
        
#         # Find the pricing plan
#         selected_plan = None
#         for plan in club.get("pricing_plans", []):
#             if plan["plan"] == pricing_plan.value:
#                 selected_plan = plan
#                 break
        
#         if not selected_plan:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail=f"Pricing plan {pricing_plan.value} not available for this club"
#             )
        
#         if not selected_plan.get("stripe_price_id"):
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Pricing plan not properly configured with Stripe"
#             )
        
#         # Check if user already has membership
#         membership_collection = get_membership_collection()
#         existing = await membership_collection.find_one({
#             "user_id": user_id,
#             "club_id": club_id,
#             "subscription_status": {"$in": ["active", "pending"]}
#         })
        
#         if existing:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="You already have an active membership for this club"
#             )
        
#         # Get or create Stripe customer
#         customer_id = await StripeService.get_or_create_stripe_customer(
#             user_id=user_id,
#             email=current_user["email"],
#             name=current_user["full_name"]
#         )
        
#         # Create subscription
#         subscription_metadata = {
#             "user_id": user_id,
#             "club_id": club_id,
#             "pricing_plan": pricing_plan.value,
#             "type": "club_membership"
#         }
        
#         subscription = await StripeService.create_subscription(
#             customer_id=customer_id,
#             price_id=selected_plan["stripe_price_id"],
#             payment_method_id=payment_method_id,
#             metadata=subscription_metadata
#         )
        
#         # Create membership record (initially pending)
#         await create_club_membership(
#             user_id=user_id,
#             club_id=club_id,
#             pricing_plan=pricing_plan.value,
#             payment_id=subscription.id
#         )
        
#         return ClubMembershipPaymentResponse(
#             success=True,
#             message="Membership subscription created successfully",
#             subscription_id=subscription.id,
#             customer_id=customer_id,
#             price_id=selected_plan["stripe_price_id"],
#             payment_status=subscription.status
#         )
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ Error creating club membership: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to create membership: {str(e)}"
#         )

# @router.post("/webhooks/stripe")
# async def stripe_webhook(request: Request):
#     """Handle Stripe webhook events for membership payments"""
#     try:
#         payload = await request.body()
#         sig_header = request.headers.get('stripe-signature')
        
#         print(f"🔔 Received webhook with signature: {sig_header}")
#         print(f"🔍 All headers: {dict(request.headers)}")
        
#         # Check if this is a test request from API docs (no signature)
#         if not sig_header or sig_header == "None":
#             print("⚠️ No Stripe signature detected - this might be a test request from API docs")
#             print("💡 For testing from API docs, we'll process without signature verification")
            
#             try:
#                 # Try to parse as JSON for testing
#                 event = json.loads(payload.decode('utf-8'))
#                 print("✅ Processed test payload without signature verification")
#             except json.JSONDecodeError:
#                 print("❌ Invalid JSON payload")
#                 raise HTTPException(status_code=400, detail="Invalid JSON payload")
#         else:
#             # Normal Stripe webhook processing with signature verification
#             if not STRIPE_WEBHOOK_SECRET:
#                 print("⚠️ Stripe webhook secret not configured")
#                 return {"status": "webhook secret not configured"}
            
#             try:
#                 # Verify webhook signature
#                 event = stripe.Webhook.construct_event(
#                     payload, sig_header, STRIPE_WEBHOOK_SECRET
#                 )
#                 print("✅ Webhook signature verified")
#             except ValueError:
#                 print("❌ Invalid payload")
#                 raise HTTPException(status_code=400, detail="Invalid payload")
#             except stripe.error.SignatureVerificationError:
#                 print("❌ Invalid signature")
#                 raise HTTPException(status_code=400, detail="Invalid signature")
        
#         # Handle the event
#         event_data = StripeService.handle_subscription_webhook(event)
        
#         if event.get('type') == 'invoice.payment_succeeded':
#             await handle_payment_success(event_data)
#         elif event.get('type') == 'invoice.payment_failed':
#             await handle_payment_failed(event_data)
#         elif event.get('type') == 'customer.subscription.deleted':
#             await handle_subscription_cancelled(event_data)
#         elif event.get('type') == 'customer.subscription.updated':
#             await handle_subscription_updated(event_data)
        
#         print(f"✅ Handled webhook event: {event.get('type', 'unknown')}")
#         return {"status": "success", "message": "Webhook processed successfully"}
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ Webhook error: {str(e)}")
#         return {"status": "error", "message": str(e)}

# async def handle_payment_success(event_data: Dict):
#     """Handle successful payment webhook"""
#     try:
#         metadata = event_data.get("metadata", {})
#         subscription_id = event_data.get("subscription_id")
        
#         if not subscription_id or not metadata.get("user_id") or not metadata.get("club_id"):
#             print("❌ Missing required metadata in payment success webhook")
#             return
        
#         user_id = metadata["user_id"]
#         club_id = metadata["club_id"]
        
#         # Update membership status to active
#         success = await update_membership_status(user_id, club_id, "active")
        
#         if success:
#             # Update user's club membership status in auth service
#             users_collection = get_user_collection()
#             await users_collection.update_one(
#                 {"_id": ObjectId(user_id)},
#                 {
#                     "$set": {
#                         "last_payment_date": datetime.utcnow(),
#                         "updated_at": datetime.utcnow()
#                     }
#                 }
#             )
            
#             print(f"✅ Activated club membership for user {user_id} in club {club_id}")
#         else:
#             print(f"❌ Failed to activate membership for user {user_id} in club {club_id}")
            
#     except Exception as e:
#         print(f"❌ Error handling payment success: {str(e)}")

# async def handle_payment_failed(event_data: Dict):
#     """Handle failed payment webhook"""
#     try:
#         metadata = event_data.get("metadata", {})
#         subscription_id = event_data.get("subscription_id")
        
#         if not subscription_id or not metadata.get("user_id") or not metadata.get("club_id"):
#             print("❌ Missing required metadata in payment failed webhook")
#             return
        
#         user_id = metadata["user_id"]
#         club_id = metadata["club_id"]
        
#         # Update membership status to failed
#         await update_membership_status(user_id, club_id, "payment_failed")
        
#         print(f"⚠️ Payment failed for user {user_id} club membership {club_id}")
        
#     except Exception as e:
#         print(f"❌ Error handling payment failure: {str(e)}")

# async def handle_subscription_cancelled(event_data: Dict):
#     """Handle subscription cancellation webhook"""
#     try:
#         metadata = event_data.get("metadata", {})
#         subscription_id = event_data.get("subscription_id")
        
#         if not subscription_id or not metadata.get("user_id") or not metadata.get("club_id"):
#             print("❌ Missing required metadata in subscription cancelled webhook")
#             return
        
#         user_id = metadata["user_id"]
#         club_id = metadata["club_id"]
        
#         # Update membership status to cancelled
#         await update_membership_status(user_id, club_id, "cancelled")
        
#         print(f"⚠️ Subscription cancelled for user {user_id} club membership {club_id}")
        
#     except Exception as e:
#         print(f"❌ Error handling subscription cancellation: {str(e)}")

# async def handle_subscription_updated(event_data: Dict):
#     """Handle subscription update webhook"""
#     try:
#         metadata = event_data.get("metadata", {})
#         subscription_id = event_data.get("subscription_id")
#         status = event_data.get("status")
        
#         if not subscription_id or not metadata.get("user_id") or not metadata.get("club_id"):
#             print("❌ Missing required metadata in subscription updated webhook")
#             return
        
#         user_id = metadata["user_id"]
#         club_id = metadata["club_id"]
        
#         # Map Stripe status to our status
#         status_mapping = {
#             "active": "active",
#             "past_due": "past_due",
#             "canceled": "cancelled",
#             "unpaid": "payment_failed"
#         }
        
#         mapped_status = status_mapping.get(status, "unknown")
#         if mapped_status != "unknown":
#             await update_membership_status(user_id, club_id, mapped_status)
#             print(f"✅ Updated membership status to {mapped_status} for user {user_id} in club {club_id}")
        
#     except Exception as e:
#         print(f"❌ Error handling subscription update: {str(e)}") 