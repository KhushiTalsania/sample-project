from fastapi import APIRouter, HTTPException, Depends, Request, status, Query
from typing import List, Dict, Optional
import stripe
import os
from datetime import datetime
from bson import ObjectId
from .models import (
    WebhookEventData
)
from .auth import get_current_captain, get_current_user
from .db import get_club_collection, get_webhook_events_collection
from .stripe_service import StripeService
from services.admin.db import get_admin_collection
import json
import hmac
import hashlib

def create_response(status_code: int, status: str, message: str, data=None):
    """Create a common response body with status code"""
    print(f"Creating API response - Status: {status_code}, Type: {status}, Message: {message}")
    
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": status, "message": message, "data": data},
    )

async def get_admin_id_for_tj() -> Optional[str]:
    """Get admin_id for tj@mailinator.com"""
    try:
        admin_collection = get_admin_collection()
        admin = await admin_collection.find_one({"email": "tj@mailinator.com"})
        if admin:
            return str(admin["_id"])
        else:
            print("Admin tj@mailinator.com not found in database")
            return None
    except Exception as e:
        print(f"Error getting admin_id for tj@mailinator.com: {e}")
        return None

router = APIRouter()

# Stripe webhook secret
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

@router.get("/clubs/{club_id}/check-stripe-status")
async def check_club_stripe_status(
    club_id: str,
    current_captain: dict = Depends(get_current_captain)
):
    """
    Check the current Stripe integration status for a club
    
    This endpoint returns:
    - Whether the club has a Stripe product
    - Which pricing plans already exist in Stripe
    - What needs to be created
    """
    try:
        club_collection = get_club_collection()
        
        # First try to find club by name_based_id (string)
        club = await club_collection.find_one({
            "name_based_id": club_id,
            "captain_id": current_captain["user_id"]
        })
        
        # If not found by name_based_id, try ObjectId
        if not club:
            try:
                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({
                    "_id": club_object_id,
                    "captain_id": current_captain["user_id"]
                })
            except Exception:
                pass
        
        if not club:
            return create_response(
                status_code=404,
                status="error",
                message="Club not found or you don't have permission to view it",
                data=None
            )
        
        # Check Stripe status
        pricing_plans = club.get("pricing_plans", [])
        stripe_status = {
            "club_id": club_id,
            "club_name": club.get("name"),
            "has_stripe_product": False,
            "stripe_product_id": None,
            "plans_status": [],
            "total_plans": len(pricing_plans),
            "plans_with_stripe": 0,
            "plans_needing_stripe": 0
        }
        
        if pricing_plans:
            # Check if any plan has a Stripe product ID
            product_id = None
            for plan in pricing_plans:
                if plan.get("stripe_product_id"):
                    product_id = plan["stripe_product_id"]
                    stripe_status["has_stripe_product"] = True
                    stripe_status["stripe_product_id"] = product_id
                    break
            
            # Check each plan's Stripe status
            for plan in pricing_plans:
                plan_status = {
                    "frequency": plan.get("plan"),
                    "price": plan.get("price"),
                    "currency": plan.get("currency"),
                    "has_stripe_product": bool(plan.get("stripe_product_id")),
                    "has_stripe_price": bool(plan.get("stripe_price_id")),
                    "stripe_product_id": plan.get("stripe_product_id"),
                    "stripe_price_id": plan.get("stripe_price_id"),
                    "status": "complete" if plan.get("stripe_product_id") and plan.get("stripe_price_id") else "incomplete"
                }
                
                stripe_status["plans_status"].append(plan_status)
                
                if plan_status["status"] == "complete":
                    stripe_status["plans_with_stripe"] += 1
                else:
                    stripe_status["plans_needing_stripe"] += 1
        
        return create_response(
            status_code=200,
            status="success",
            message="Stripe status retrieved successfully",
            data=stripe_status
        )
        
    except Exception as e:
        print(f"❌ Error checking Stripe status: {str(e)}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to check Stripe status: {str(e)}",
            data=None
        )

@router.post("/clubs/{club_id}/pricing-plans")
async def create_club_pricing_plans(
    club_id: str,
    pricing_request: dict,
    current_captain: dict = Depends(get_current_captain)
):
    """
    Create dynamic pricing plans for a club with Stripe integration
    
    This endpoint allows captains to create pricing plans that will be automatically
    created in Stripe dashboard. The system will:
    1. Create a Stripe product for the club
    2. Create individual prices for each pricing plan
    3. Store the Stripe IDs (product_id, price_id) in the database
    4. Return the complete pricing plan details with Stripe IDs
    
    Request structure:
    {
        "club_id": "football-group",
        "pricing_plans": [
            {
                "frequency": "monthly",
                "price": 19.99,
                "currency": "USD"
            },
            {
                "frequency": "quarterly", 
                "price": 49.99,
                "currency": "USD"
            },
            {
                "frequency": "yearly",
                "price": 179.99,
                "currency": "USD"
            }
        ]
    }
    """
    try:
        club_collection = get_club_collection()
        print(f"club_collection: {club_collection}")
        print(f"current_captain: {current_captain['user_id']} {club_id}")
        
        # First try to find club by name_based_id (string) - exact match
        club = await club_collection.find_one({
            "name_based_id": club_id,
            "captain_id": current_captain["user_id"]
        })
        print(f"club: {club}")
        
        # If not found by exact name_based_id, try case-insensitive search
        if not club:
            print(f"🔍 Debug: Trying case-insensitive search for: {club_id}")
            # Use regex for case-insensitive search
            import re
            club = await club_collection.find_one({
                "name_based_id": {"$regex": f"^{re.escape(club_id)}$", "$options": "i"},
                "captain_id": current_captain["user_id"]
            })
            if club:
                print(f"🔍 Debug: Found club with case-insensitive search: {club.get('name_based_id')}")
        
        # If not found by name_based_id, try ObjectId
        if not club:
            try:
                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({
                    "_id": club_object_id,
                    "captain_id": current_captain["user_id"]
                })
            except Exception:
                pass
        
        # Debug: Let's also check what clubs exist for this captain
        if not club:
            print(f"🔍 Debug: No club found with name_based_id: {club_id}")
            print(f"🔍 Debug: Captain ID: {current_captain['user_id']}")
            
            # Check what clubs exist for this captain
            captain_clubs = await club_collection.find({
                "captain_id": current_captain["user_id"]
            }).to_list(length=5)
            print(f"🔍 Debug: Captain has {len(captain_clubs)} clubs:")
            for c in captain_clubs:
                print(f"   - {c.get('name', 'No name')} (name_based_id: {c.get('name_based_id', 'No name_based_id')})")
            
            # Also check if the club exists but with different captain
            club_exists = await club_collection.find_one({"name_based_id": club_id})
            if club_exists:
                print(f"🔍 Debug: Club {club_id} exists but belongs to captain: {club_exists.get('captain_id')}")
                print(f"🔍 Debug: Current captain: {current_captain['user_id']}")
        
        if not club:
            return create_response(
                status_code=404,
                status="error",
                message="Club not found or you don't have permission to modify it",
                data=None
            )
        
        # Validate pricing request structure
        if not pricing_request.get("pricing_plans"):
            return create_response(
                status_code=400,
                status="error",
                message="pricing_plans field is required",
                data=None
            )
        
        # Convert frequency to plan type for Stripe service
        frequency_to_plan_mapping = {
            "monthly": "monthly",
            "quarterly": "quarterly", 
            "yearly": "yearly"
        }
        
        # Transform pricing plans to match Stripe service expectations
        transformed_plans = []
        plans_to_create = []
        
        for plan in pricing_request["pricing_plans"]:
            frequency = plan.get("frequency")
            if frequency not in frequency_to_plan_mapping:
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Invalid frequency: {frequency}. Must be monthly, quarterly, or yearly",
                    data=None
                )
            
            transformed_plan = {
                "plan": frequency_to_plan_mapping[frequency],
                "price": plan.get("price"),
                "currency": plan.get("currency", "USD")
            }
            
            # Check if this plan already exists in database with Stripe IDs
            existing_plan = None
            if club.get("pricing_plans"):
                for existing in club["pricing_plans"]:
                    if (existing.get("plan") == transformed_plan["plan"] and
                        existing.get("price") == transformed_plan["price"] and
                        existing.get("currency") == transformed_plan["currency"] and
                        existing.get("stripe_product_id") and
                        existing.get("stripe_price_id")):
                        existing_plan = existing
                        break
            
            if existing_plan:
                # Plan already exists with Stripe IDs, use existing data
                transformed_plan.update({
                    "stripe_product_id": existing_plan["stripe_product_id"],
                    "stripe_price_id": existing_plan["stripe_price_id"],
                    "created_at": existing_plan.get("created_at"),
                    "updated_at": existing_plan.get("updated_at")
                })
                print(f"✅ Plan {frequency} already exists with Stripe IDs, skipping creation")
            else:
                # Plan needs to be created in Stripe
                plans_to_create.append(transformed_plan)
                print(f"🆕 Plan {frequency} needs to be created in Stripe")
            
            transformed_plans.append(transformed_plan)
        
        # Only create plans in Stripe if there are new ones
        if plans_to_create:
            print(f"🔄 Creating {len(plans_to_create)} new plans in Stripe...")
            
            # Get admin_id for tj@mailinator.com
            admin_id = await get_admin_id_for_tj()
            print(f"Retrieved admin_id for tj@mailinator.com: {admin_id}")
            
            # Create pricing plans in Stripe
            updated_plans = await StripeService.create_pricing_plans_for_club(
                club_id=str(club["_id"]),  # Use ObjectId for Stripe service
                club_name=club["name"],
                captain_id=current_captain["user_id"],
                pricing_plans=plans_to_create,
                admin_id=admin_id
            )
            
            # Update the transformed plans with Stripe IDs
            for i, updated_plan in enumerate(updated_plans):
                # Find the corresponding plan in transformed_plans
                for j, plan in enumerate(transformed_plans):
                    if (plan["plan"] == updated_plan["plan"] and
                        plan["price"] == updated_plan["price"] and
                        plan["currency"] == updated_plan["currency"]):
                        transformed_plans[j].update({
                            "stripe_product_id": updated_plan["stripe_product_id"],
                            "stripe_price_id": updated_plan["stripe_price_id"],
                            "created_at": updated_plan["created_at"],
                            "updated_at": updated_plan["updated_at"]
                        })
                        break
        else:
            print("✅ All plans already exist in Stripe, no need to create new ones")
        
        # Update club in database with all pricing plans (including existing and new ones)
        await StripeService.update_club_pricing_plans(str(club["_id"]), transformed_plans)
        
        # Transform response back to match original structure
        response_plans = []
        for plan in transformed_plans:
            response_plan = {
                "frequency": plan.get("plan"),
                "price": plan.get("price"),
                "currency": plan.get("currency"),
                "stripe_product_id": plan.get("stripe_product_id"),
                "stripe_price_id": plan.get("stripe_price_id"),
                "is_active": plan.get("is_active", True),
                "created_at": plan.get("created_at").isoformat() if plan.get("created_at") else None,
                "updated_at": plan.get("updated_at").isoformat() if plan.get("updated_at") else None
            }
            response_plans.append(response_plan)
        
        return create_response(
            status_code=200,
            status="success",
            message="Pricing plans created successfully in Stripe and database",
            data={
                "club_id": club_id,
                "club_name": club.get("name"),
                "pricing_plans": response_plans
            }
        )
        
    except Exception as e:
        print(f"❌ Error creating pricing plans: {str(e)}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to create pricing plans: {str(e)}",
            data=None
        )

@router.get("/clubs/{club_id}/stripe-pricing-details")
async def get_club_stripe_pricing_details(
    club_id: str,
    current_captain: Optional[dict] = Depends(get_current_captain)
):
    """
    Get detailed Stripe pricing information for a club's pricing plans
    
    This endpoint returns all the Stripe-specific details including:
    - product_id: The Stripe product ID for the club
    - price_id: Individual price IDs for each plan
    - plan details: pricing, frequency, currency
    - Stripe metadata and status
    
    This is useful for:
    - Frontend integration with Stripe
    - Payment processing
    - Subscription management
    - Webhook handling
    """
    try:
        club_collection = get_club_collection()
        
        # First try to find club by name_based_id (string)
        club = await club_collection.find_one({
            "name_based_id": club_id
        })
        
        # If not found by name_based_id, try ObjectId
        if not club:
            try:
                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({
                    "_id": club_object_id
                })
            except Exception:
                pass
        
        if not club:
            return create_response(
                status_code=404,
                status="error",
                message="Club not found",
                data=None
            )
        
        # Check if captain has permission (if captain is authenticated)
        if current_captain:
            if club.get("captain_id") != current_captain["user_id"]:
                return create_response(
                    status_code=403,
                    status="error",
                    message="You don't have permission to view this club's pricing details",
                    data=None
                )
        
        # Get pricing plans
        pricing_plans = club.get("pricing_plans", [])
        
        if not pricing_plans:
            return create_response(
                status_code=404,
                status="error",
                message="No pricing plans found for this club",
                data=None
            )
        
        # Verify Stripe IDs exist
        plans_with_stripe = []
        for plan in pricing_plans:
            if plan.get("stripe_product_id") and plan.get("stripe_price_id"):
                plans_with_stripe.append(plan)
        
        if not plans_with_stripe:
            return create_response(
                status_code=400,
                status="error",
                message="Pricing plans exist but Stripe integration is not complete",
                data=None
            )
        
        # Get additional Stripe details for each plan
        detailed_plans = []
        for plan in plans_with_stripe:
            try:
                # Get Stripe price details
                stripe_price = stripe.Price.retrieve(plan["stripe_price_id"])
                
                # Get Stripe product details
                stripe_product = stripe.Product.retrieve(plan["stripe_product_id"])
                
                # Convert Stripe timestamps to ISO format strings for JSON serialization
                def convert_stripe_timestamp(timestamp):
                    """Convert Stripe timestamp to ISO format string"""
                    if timestamp:
                        # Stripe timestamps are Unix timestamps
                        from datetime import datetime
                        return datetime.fromtimestamp(timestamp).isoformat()
                    return None
                
                # Comprehensive function to convert any datetime objects to ISO strings
                def convert_datetime_to_iso(obj):
                    """Recursively convert datetime objects to ISO format strings"""
                    if isinstance(obj, dict):
                        return {key: convert_datetime_to_iso(value) for key, value in obj.items()}
                    elif isinstance(obj, list):
                        return [convert_datetime_to_iso(item) for item in obj]
                    elif hasattr(obj, 'isoformat'):  # datetime objects
                        return obj.isoformat()
                    else:
                        return obj
                
                # Convert the plan object datetime fields first
                converted_plan = convert_datetime_to_iso(plan)
                
                detailed_plan = {
                    **converted_plan,
                    "stripe_price_details": {
                        "price_id": stripe_price.id,
                        "unit_amount": stripe_price.unit_amount,
                        "currency": stripe_price.currency,
                        "recurring": convert_datetime_to_iso(stripe_price.recurring),
                        "active": stripe_price.active,
                        "created": convert_stripe_timestamp(stripe_price.created),
                        "metadata": convert_datetime_to_iso(stripe_price.metadata)
                    },
                    "stripe_product_details": {
                        "product_id": stripe_product.id,
                        "name": stripe_product.name,
                        "description": stripe_product.description,
                        "active": stripe_product.active,
                        "created": convert_stripe_timestamp(stripe_product.created),
                        "metadata": convert_datetime_to_iso(stripe_product.metadata)
                    }
                }
                detailed_plans.append(detailed_plan)
                
            except stripe.error.StripeError as e:
                print(f"❌ Error fetching Stripe details for plan {plan.get('plan')}: {str(e)}")
                # Continue with basic plan info if Stripe fetch fails
                # Convert datetime fields to ensure JSON serialization
                converted_plan = convert_datetime_to_iso(plan)
                detailed_plans.append(converted_plan)
        
        # Convert club datetime fields
        converted_club = convert_datetime_to_iso(club)
        
        return create_response(
            status_code=200,
            status="success",
            message="Stripe pricing details retrieved successfully",
            data={
                "club_id": club_id,
                "club_name": converted_club.get("name"),
                "captain_id": converted_club.get("captain_id"),
                "total_plans": len(detailed_plans),
                "pricing_plans": detailed_plans,
                "stripe_integration_status": "active" if plans_with_stripe else "inactive"
            }
        )
        
    except Exception as e:
        print(f"❌ Error retrieving Stripe pricing details: {str(e)}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to retrieve Stripe pricing details: {str(e)}",
            data=None
        )

@router.get("/captains/{captain_id}/stripe-pricing-summary")
async def get_captain_stripe_pricing_summary(
    captain_id: str,
    current_captain: dict = Depends(get_current_captain)
):
    """
    Get a summary of all Stripe pricing plans created by a captain
    
    This endpoint returns:
    - All clubs owned by the captain
    - Pricing plans for each club with Stripe IDs
    - Stripe integration status
    - Total active plans and revenue potential
    
    Useful for:
    - Captain dashboard overview
    - Revenue tracking
    - Plan management
    """
    try:
        # Verify captain is requesting their own data
        if current_captain["user_id"] != captain_id:
            return create_response(
                status_code=403,
                status="error",
                message="You can only view your own pricing summary",
                data=None
            )
        
        club_collection = get_club_collection()
        
        # Get all clubs owned by this captain
        clubs = await club_collection.find({
            "captain_id": captain_id
        }).to_list(length=None)
        
        if not clubs:
            return create_response(
                status_code=200,
                status="success",
                message="No clubs found for this captain",
                data={
                    "captain_id": captain_id,
                    "total_clubs": 0,
                    "total_pricing_plans": 0,
                    "clubs": []
                }
            )
        
        # Process each club's pricing plans
        clubs_with_pricing = []
        total_plans = 0
        total_revenue_potential = 0
        
        for club in clubs:
            pricing_plans = club.get("pricing_plans", [])
            plans_with_stripe = [
                plan for plan in pricing_plans 
                if plan.get("stripe_product_id") and plan.get("stripe_price_id")
            ]
            
            if plans_with_stripe:
                club_revenue = sum(plan.get("price", 0) for plan in plans_with_stripe)
                total_revenue_potential += club_revenue
                
                clubs_with_pricing.append({
                    "club_id": str(club["_id"]),
                    "club_name": club.get("name"),
                    "club_status": club.get("status"),
                    "total_plans": len(plans_with_stripe),
                    "active_plans": len([p for p in plans_with_stripe if p.get("is_active", True)]),
                    "revenue_potential": club_revenue,
                    "stripe_integration": "active",
                    "pricing_plans": plans_with_stripe
                })
                total_plans += len(plans_with_stripe)
        
        return create_response(
            status_code=200,
            status="success",
            message="Captain pricing summary retrieved successfully",
            data={
                "captain_id": captain_id,
                "total_clubs": len(clubs),
                "clubs_with_pricing": len(clubs_with_pricing),
                "total_pricing_plans": total_plans,
                "total_revenue_potential": total_revenue_potential,
                "clubs": clubs_with_pricing
            }
        )
        
    except Exception as e:
        print(f"❌ Error retrieving captain pricing summary: {str(e)}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to retrieve captain pricing summary: {str(e)}",
            data=None
        )

@router.post("/webhooks/stripe")
async def handle_stripe_webhook(request: Request):
    """
    Handle Stripe webhook events for pricing plan updates
    
    This endpoint receives webhooks from Stripe when:
    - Products are created/updated
    - Prices are created/updated
    - Subscriptions are created/modified
    - Payment events occur
    
    The webhook data is stored for audit and processing purposes.
    """
    try:
        # Get the raw body
        body = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        if not sig_header:
            return create_response(
                status_code=400,
                status="error",
                message="Missing Stripe signature",
                data=None
            )
        
        # Verify webhook signature
        try:
            event = stripe.Webhook.construct_event(
                body, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            return create_response(
                status_code=400,
                status="error",
                message="Invalid payload",
                data=None
            )
        except stripe.error.SignatureVerificationError as e:
            return create_response(
                status_code=400,
                status="error",
                message="Invalid signature",
                data=None
            )
        
        # Process the webhook event
        event_type = event['type']
        data = event['data']['object']
        
        # Store webhook event for audit
        webhook_collection = get_webhook_events_collection()
        await webhook_collection.insert_one({
            "stripe_event_id": event['id'],
            "event_type": event_type,
            "event_data": data,
            "received_at": datetime.utcnow(),
            "processed": False
        })
        
        # Handle specific event types
        print(f"🔔 Processing webhook event: {event_type}")
        
        if event_type in ['product.created', 'product.updated']:
            # Handle product events
            print(f"🏭 Handling product webhook: {event_type}")
            await handle_product_webhook(data, event_type)
        elif event_type in ['price.created', 'price.updated']:
            # Handle price events
            print(f"💰 Handling price webhook: {event_type}")
            await handle_price_webhook(data, event_type)
        elif event_type in ['invoice.payment_succeeded', 'invoice.payment_failed']:
            # Handle payment events
            print(f"💳 Handling payment webhook: {event_type}")
            await handle_payment_webhook(data, event_type)
        else:
            print(f"ℹ️ Unhandled webhook event type: {event_type}")
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Webhook {event_type} processed successfully",
            data={
                "event_id": event['id'],
                "event_type": event_type
            }
        )
        
    except Exception as e:
        print(f"❌ Error processing Stripe webhook: {str(e)}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to process webhook: {str(e)}",
            data=None
        )

async def handle_product_webhook(data: dict, event_type: str):
    """Handle Stripe product webhook events"""
    try:
        product_id = data.get('id')
        metadata = data.get('metadata', {})
        club_id = metadata.get('club_id')
        captain_id = metadata.get('captain_id')
        
        if club_id:
            print(f"✅ {event_type} for club {club_id}: {product_id}")
            
            # Update club with Stripe product ID if not already present
            club_collection = get_club_collection()
            
            # Try to find club by ObjectId first
            try:
                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({"_id": club_object_id})
            except Exception:
                club = None
            
            # If not found by ObjectId, try name_based_id
            if not club:
                club = await club_collection.find_one({"name_based_id": club_id})
            
            if club:
                # Check if pricing_plans exist and need Stripe product ID
                pricing_plans = club.get("pricing_plans", [])
                if pricing_plans:
                    # Update all plans with the product ID if not present
                    updated_plans = []
                    for plan in pricing_plans:
                        if not plan.get("stripe_product_id"):
                            plan["stripe_product_id"] = product_id
                        updated_plans.append(plan)
                    
                    # Update the club with Stripe product ID and flags
                    await club_collection.update_one(
                        {"_id": club["_id"]},
                        {
                            "$set": {
                                "pricing_plans": updated_plans,
                                "stripe_product_id": product_id,
                                "has_stripe_product": True,
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    print(f"✅ Updated club {club_id} with Stripe product ID: {product_id}")
            
    except Exception as e:
        print(f"❌ Error handling product webhook: {str(e)}")

async def handle_price_webhook(data: dict, event_type: str):
    """Handle Stripe price webhook events"""
    try:
        price_id = data.get('id')
        metadata = data.get('metadata', {})
        club_id = metadata.get('club_id')
        pricing_plan = metadata.get('pricing_plan')
        
        if club_id and pricing_plan:
            print(f"✅ {event_type} for club {club_id}, plan {pricing_plan}: {price_id}")
            
            # Update club with Stripe price ID for the specific plan
            club_collection = get_club_collection()
            
            # Try to find club by ObjectId first
            try:
                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({"_id": club_object_id})
            except Exception:
                club = None
            
            # If not found by ObjectId, try name_based_id
            if not club:
                club = await club_collection.find_one({"name_based_id": club_id})
            
            if club:
                # Find and update the specific pricing plan
                pricing_plans = club.get("pricing_plans", [])
                updated_plans = []
                plan_updated = False
                
                for plan in pricing_plans:
                    if plan.get("frequency") == pricing_plan and not plan.get("stripe_price_id"):
                        plan["stripe_price_id"] = price_id
                        plan_updated = True
                        print(f"✅ Updated plan {pricing_plan} with Stripe price ID: {price_id}")
                    updated_plans.append(plan)
                
                if plan_updated:
                    # Update the club with Stripe price flags
                    await club_collection.update_one(
                        {"_id": club["_id"]},
                        {
                            "$set": {
                                "pricing_plans": updated_plans,
                                "has_stripe_price": True,
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    print(f"✅ Updated club {club_id} with Stripe price ID for plan {pricing_plan}")
            
    except Exception as e:
        print(f"❌ Error handling price webhook: {str(e)}")

async def handle_payment_webhook(data: dict, event_type: str):
    """Handle Stripe payment webhook events"""
    try:
        invoice_id = data.get('id')
        subscription_id = data.get('subscription')
        amount = data.get('amount_paid', 0) / 100  # Convert from cents
        currency = data.get('currency')
        
        print(f"✅ {event_type}: Invoice {invoice_id}, Amount: {amount} {currency}")
        # You can add additional logic here for payment processing
        
    except Exception as e:
        print(f"❌ Error handling payment webhook: {str(e)}")

@router.get("/stripe/health-check")
async def stripe_health_check():
    """
    Health check endpoint for Stripe integration
    
    This endpoint verifies:
    - Stripe API connectivity
    - API key validity
    - Basic Stripe operations
    """
    try:
        # Test Stripe API connectivity
        account = stripe.Account.retrieve()
        
        return create_response(
            status_code=200,
            status="success",
            message="Stripe integration is healthy",
            data={
                "stripe_account_id": account.id,
                "stripe_account_type": account.type,
                "stripe_environment": "test" if "test" in stripe.api_key else "live",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
    except stripe.error.AuthenticationError:
        return create_response(
            status_code=401,
            status="error",
            message="Invalid Stripe API key",
            data=None
        )
    except stripe.error.APIConnectionError:
        return create_response(
            status_code=503,
            status="error",
            message="Cannot connect to Stripe API",
            data=None
        )
    except Exception as e:
        return create_response(
            status_code=500,
            status="error",
            message=f"Stripe health check failed: {str(e)}",
            data=None
        )
