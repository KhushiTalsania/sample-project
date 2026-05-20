from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional
import stripe
import os
from datetime import datetime, timedelta
from bson import ObjectId
from ..models import (
    TrialOfferDetails, 
    TrialMembershipRequest, 
    TrialMembershipResponse,
    TrialRefundRequest,
    TrialRefundResponse,
    TrialStatusResponse,
    CaptainTrialOfferDetails,
    ClubMembershipDetailsResponse,
    ActiveMembershipsResponse,
    ActiveMembershipItem,
    PastMembershipsResponse,
    PastMembershipItem,
    JoinClubRequest,
    JoinClubResponse,
    AddClubMemberRequest,
    AddClubMemberResponse,
    ClubMembershipStatusResponse
)
from ..utils import get_current_user, verify_token
import json

router = APIRouter()

# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')

# Membership configuration - Monthly recurring subscription
MEMBERSHIP_CONFIG = {
    "title": "Trial Membership",
    "subtitle": "Join our community as a Member or Captain",
    "price": 19.95,
    "billing_cycle": "one-time",  # monthly recurring
    "duration": 30,  # days for display
    "features": [
        "Join 1 Club per week (4 total)",
        "Basic community access",
        "Basic community access", 
        # "Email support",
        # "Priority customer support",
        # "Custom club creation"
    ],
    "cta_label": "Pay Now",
    "currency": "usd",
    "product_name": "MVP Sports Membership",
    "product_description": "Unlock the full experience with unlimited access.",
    "price_id": "price_1SFb7PFhr4pAMUPtaqKAFzga",  # Real Stripe price_id from dashboard price_1S2XZTFhr4pAMUPthTXpQVad
    "product_id": "prod_TBz5LZzhixbPWu"  # Real Stripe product_id from dashboard prod_SyUYqpoY8bcEAv
}

# Captain configuration - Monthly recurring subscription
CAPTAIN_CONFIG = {
    "title": "Paid Membership",
    "subtitle": "Join our community as a Member or Captain",
    "price": 99,
    "billing_cycle": "monthly",  # monthly recurring
    "duration": 30,  # days for display
    "features": [
        "Join 1 Club per week (4 total)",
        "Basic community access",
        "Basic community access", 
        "Email support",
        "Priority customer support",
        "Custom club creation"
    ],
    "cta_label": "Pay Now",
    "currency": "usd",
    "product_name": "MVP Sports Membership",
    "product_description": "Unlock the full experience with unlimited access.",
    "price_id": "price_1S2XXiFhr4pAMUPtOn4eloe5",  # Will be updated with actual Stripe price_id
    "product_id": "prod_SyUWAnbVnqACl9"  # Same product as trial, different price
}

# Trial configuration - for trial membership limits and settings
TRIAL_CONFIG = {
    "weekly_limit": 1,        # Maximum clubs user can join per week during trial
    "max_clubs": 4,          # Maximum total clubs user can join during trial
    "refund_days": 7,        # Days within which user can request refund
    "duration": 30,          # Trial duration in days
    "price": 19.95,          # Trial price (same as membership config)
    "club_access_days": 7    # Each club is accessible for 7 days (1 week)
}

# In-memory storage for trial memberships (replace with database in production)
trial_memberships = {}
user_trial_status = {}
import stripe


PRODUCT_ID = "prod_TBz5LZzhixbPWu"  # Your Stripe Product ID
CAPPRODUCT_ID = "prod_SyUWAnbVnqACl9"  # Your Stripe Product ID

@router.get("/api/trial/offer-details")
async def get_membership_offer_details(current_user: dict = Depends(get_current_user)):
    from ..db import get_user_collection
    users_collection = get_user_collection()

    try:
        user_object_id = ObjectId(current_user["user_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    user = await users_collection.find_one({"_id": user_object_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # === Fetch Price ID dynamically from Stripe ===
    try:
        prices = stripe.Price.list(product=PRODUCT_ID, active=True, limit=1)
        if not prices.data:
            raise HTTPException(status_code=500, detail="No active price found for the product.")
        dynamic_price = prices.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

    # === Offer details ===
    offer_details = {
        "title": MEMBERSHIP_CONFIG["title"],
        "subtitle": MEMBERSHIP_CONFIG["subtitle"], 
        "price": (dynamic_price["unit_amount"] / 100.0),  # Convert cents to dollars
        "duration": MEMBERSHIP_CONFIG["duration"],
        "weekly_limit": 1,
        "max_clubs": 4,
        "benefits": MEMBERSHIP_CONFIG["features"],
        "cta_label": MEMBERSHIP_CONFIG["cta_label"],
        "refund_days": 7,
        "price_id": dynamic_price["id"],  # ✅ Dynamic
        "product_id": dynamic_price["product"],
        "currency": dynamic_price["currency"],
        "billing_cycle": dynamic_price["recurring"]["interval"]  # monthly, yearly, etc.
    }

    user_info = {
        "user_id": str(user["_id"]),
        "full_name": user["full_name"],
        "email": user["email"],
        "phone": user["phone"],
        "role": user["role"],
        "membership_status": user.get("membership_status", "none"),
        "wants_membership": user.get("wants_membership", False),
        "terms_accepted": user.get("terms_accepted", False),
        "terms_accepted_at": user.get("terms_accepted_at"),
        "subscription_id": user.get("subscription_id"),
        "stripe_customer_id": user.get("stripe_customer_id"),
        "complete_step": user.get("complete_step", 0),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at")
    }

    return {
        "offer_details": offer_details,
        "user": user_info
    }


@router.get("/api/captain/offer-details")
async def get_captain_offer_details(current_user: dict = Depends(get_current_user)):
    from ..db import get_user_collection
    users_collection = get_user_collection()

    try:
        user_object_id = ObjectId(current_user["user_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    user = await users_collection.find_one({"_id": user_object_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # === Fetch Price ID dynamically from Stripe ===
    try:
        prices = stripe.Price.list(product=CAPPRODUCT_ID, active=True, limit=1)
        if not prices.data:
            raise HTTPException(status_code=500, detail="No active price found for the product.")
        dynamic_price = prices.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

    # === Offer details ===
    offer_details = {
        "title": CAPTAIN_CONFIG["title"],
        "subtitle": CAPTAIN_CONFIG["subtitle"], 
        "price": (dynamic_price["unit_amount"] / 100.0),  # Convert cents to dollars
        "duration": CAPTAIN_CONFIG["duration"],
        "weekly_limit": 1,
        "max_clubs": 4,
        "benefits": CAPTAIN_CONFIG["features"],
        "cta_label": CAPTAIN_CONFIG["cta_label"],
        "refund_days": 7,
        "price_id": dynamic_price["id"],  # ✅ Dynamic
        "product_id": dynamic_price["product"],
        "currency": dynamic_price["currency"],
        "billing_cycle": dynamic_price["recurring"]["interval"]  # monthly, yearly, etc.
    }

    user_info = {
        "user_id": str(user["_id"]),
        "full_name": user["full_name"],
        "email": user["email"],
        "phone": user["phone"],
        "role": user["role"],
        "membership_status": user.get("membership_status", "none"),
        "wants_membership": user.get("wants_membership", False),
        "terms_accepted": user.get("terms_accepted", False),
        "terms_accepted_at": user.get("terms_accepted_at"),
        "subscription_id": user.get("subscription_id"),
        "stripe_customer_id": user.get("stripe_customer_id"),
        "complete_step": user.get("complete_step", 0),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at")
    }

    return {
        "offer_details": offer_details,
        "user": user_info
    }


# ========================================
# Combined offer details without authentication
# ========================================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
STRIPE_DATA_PATH = os.path.join(BASE_DIR, "core", "utils", "stripe_products.json")
print(STRIPE_DATA_PATH,"STRIPE_DATA_PATH")

def load_stripe_products():
    """Load Stripe product/price data from JSON file."""
    if not os.path.exists(STRIPE_DATA_PATH):
        raise HTTPException(status_code=500, detail="Stripe configuration file not found.")
    try:
        with open(STRIPE_DATA_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load Stripe configuration: {str(e)}")

# @router.get("/api/offer-details")
# async def get_public_offer_details(role: str):
#     """
#     Public endpoint (no auth) to fetch offer details by role.
#     role: "member" (or "trial") for member offer, "captain" for captain offer.
#     Returns only offer details (no user context).
#     """
#     role_normalized = (role or "").strip().lower()
#     try:
#         if role_normalized in ("member", "trial"):
#             prices = stripe.Price.list(product=PRODUCT_ID, active=True, limit=1)
#             if not prices.data:
#                 raise HTTPException(status_code=500, detail="No active price found for the product.")
#             dynamic_price = prices.data[0]
#             print(dynamic_price,"dynamic_price")
#             offer_details = {
#                 "title": MEMBERSHIP_CONFIG["title"],
#                 "subtitle": MEMBERSHIP_CONFIG["subtitle"],
#                 "price": (dynamic_price["unit_amount"] / 100.0),
#                 "duration": MEMBERSHIP_CONFIG["duration"],
#                 "weekly_limit": 1,
#                 "max_clubs": 4,
#                 "benefits": MEMBERSHIP_CONFIG["features"],
#                 "cta_label": MEMBERSHIP_CONFIG["cta_label"],
#                 "refund_days": 7,
#                 "price_id": dynamic_price["id"],
#                 "product_id": dynamic_price["product"],
#                 "currency": dynamic_price["currency"],
#                 "billing_cycle": MEMBERSHIP_CONFIG["billing_cycle"],
#                 "role": "member"
#             }
#             print(offer_details,"offer_detailsoffer_details")
#             return {"success": True, "offer_details": offer_details}

#         if role_normalized == "captain":
#             prices = stripe.Price.list(product=CAPPRODUCT_ID, active=True, limit=1)
#             if not prices.data:
#                 raise HTTPException(status_code=500, detail="No active price found for the product.")
#             dynamic_price = prices.data[0]
#             print(dynamic_price,"dynamic_pricedynamic_price")
#             offer_details = {
#                 "title": CAPTAIN_CONFIG["title"],
#                 "subtitle": CAPTAIN_CONFIG["subtitle"],
#                 "price": (dynamic_price["unit_amount"] / 100.0),
#                 "duration": CAPTAIN_CONFIG["duration"],
#                 "weekly_limit": 1,
#                 "max_clubs": 4,
#                 "benefits": CAPTAIN_CONFIG["features"],
#                 "cta_label": CAPTAIN_CONFIG["cta_label"],
#                 "refund_days": 7,
#                 "price_id": dynamic_price["id"],
#                 "product_id": dynamic_price["product"],
#                 "currency": dynamic_price["currency"],
#                 "billing_cycle": dynamic_price["recurring"]["interval"],
#                 "role": "captain"
#             }
#             return {"success": True, "offer_details": offer_details}

#         raise HTTPException(status_code=400, detail="Invalid role. Use 'member' or 'captain'.")
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Failed to load offer details: {str(e)}")


#new code for offer details
@router.get("/api/offer-details")
async def get_public_offer_details(role: str):
    """
    Public endpoint (no auth) to fetch offer details by role.
    role: "member" (or "trial") for member offer, "captain" for captain offer.
    Returns offer details using local JSON (not hitting Stripe API).
    """
    role_normalized = (role or "").strip().lower()
    stripe_data = load_stripe_products()

    try:
        if role_normalized in ("member", "trial"):
            if "member" not in stripe_data:
                raise HTTPException(status_code=500, detail="Member offer not configured in Stripe JSON.")
            data = stripe_data["member"]

            offer_details = {
                "title": MEMBERSHIP_CONFIG["title"],
                "subtitle": MEMBERSHIP_CONFIG["subtitle"],
                "price": data["amount"],
                "duration": MEMBERSHIP_CONFIG["duration"],
                "weekly_limit": 1,
                "max_clubs": 4,
                "benefits": MEMBERSHIP_CONFIG["features"],
                "cta_label": MEMBERSHIP_CONFIG["cta_label"],
                "refund_days": 7,
                "price_id": data["price_id"],
                "product_id": data["product_id"],
                "currency": "usd",
                "billing_cycle": MEMBERSHIP_CONFIG["billing_cycle"],
                "role": "member"
            }
            return {"success": True, "offer_details": offer_details}

        elif role_normalized == "captain":
            if "captain" not in stripe_data:
                raise HTTPException(status_code=500, detail="Captain offer not configured in Stripe JSON.")
            data = stripe_data["captain"]

            offer_details = {
                "title": CAPTAIN_CONFIG["title"],
                "subtitle": CAPTAIN_CONFIG["subtitle"],
                "price": data["amount"],
                "duration": CAPTAIN_CONFIG["duration"],
                "weekly_limit": 1,
                "max_clubs": 4,
                "benefits": CAPTAIN_CONFIG["features"],
                "cta_label": CAPTAIN_CONFIG["cta_label"],
                "refund_days": 7,
                "price_id": data["price_id"],
                "product_id": data["product_id"],
                "currency": "usd",
                "billing_cycle": data.get("interval", "month"),
                "role": "captain"
            }
            return {"success": True, "offer_details": offer_details}

        else:
            raise HTTPException(status_code=400, detail="Invalid role. Use 'member' or 'captain'.")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load offer details: {str(e)}")



async def store_payment_record(
    user_id: str,
    subscription_id: str,
    price_id: str,
    amount: float,
    currency: str,
    status: str,
    payment_method_id: str,
    stripe_customer_id: str,
    payment_intent_id: str = None,
    start_date: datetime = None,
    end_date: datetime = None,
    payment_type: str = "subscription",
    membership_type: str = "trial",
    created_at: datetime = None,
    updated_at: datetime = None,
):
    """
    Store payment record in payments collection for audit and tracking
    """
    try:
        from core.database.collections import get_collections

        collections = get_collections()
        payments_collection = collections.get_payments_collection()

        payment_record = {
            "user_id": user_id,
            "subscription_id": subscription_id,
            "price_id": price_id,
            "amount": amount,
            "currency": currency,
            "status": status,  # succeeded, failed, pending
            "payment_method_id": payment_method_id,
            "stripe_customer_id": stripe_customer_id,
            "payment_intent_id": payment_intent_id,  # Store payment intent ID
            "payment_type": payment_type,
            "membership_type": membership_type,
            "start_date": start_date,  # ✅ New field: Plan start date
            "end_date": end_date,  # ✅ New field: Plan end date
            "created_at": created_at or datetime.now(),
            "updated_at": updated_at or datetime.now(),
        }

        result = await payments_collection.insert_one(payment_record)
        print(f"✅ Payment record stored: {result.inserted_id}")
        if payment_intent_id:
            print(f"✅ Payment intent ID stored: {payment_intent_id}")
        return result.inserted_id

    except Exception as e:
        print(f"❌ Failed to store payment record: {str(e)}")
        # Don't raise exception as payment was successful, just log the error

@router.post("/api/membership/create-subscription")
async def create_subscription_secure(request: dict):
    """
    Create subscription with price validation - secure payment endpoint
    Validates priceId against Stripe before initiating payment
    """
    try:
        # Extract request data
        email = request.get('email')
        payment_method_id = request.get('paymentMethodId')
        price = request.get('price')
        price_id = request.get('priceId')
        
        # Validate required fields
        if not all([email, payment_method_id, price, price_id]):
            raise HTTPException(
                status_code=400, 
                detail="Missing required fields: email, paymentMethodId, price, priceId"
            )
        
        # Auto-determine role based on price
        if price == 19.95 or price == "19.95":
            role = "Member"
        elif price == 99 or price == 99.00 or price == "99" or price == "99.00":
            role = "Captain"
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid price. Must be 19.95 (Member) or 99.00 (Captain)"
            )
        
        # Validate price_id against Stripe
        try:
            stripe_price = stripe.Price.retrieve(price_id)
            print(f"✅ Stripe price retrieved: {stripe_price.id}")
            print(f"✅ Stripe price amount: {stripe_price.unit_amount/100}")
            print(f"✅ Frontend price: {price}")
            
        except stripe.error.InvalidRequestError:
            print(f"❌ Invalid price_id: {price_id}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid price_id: {price_id} not found in Stripe"
            )
        except Exception as e:
            print(f"❌ Stripe price validation error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error validating price with Stripe: {str(e)}"
            )
        
        # Validate price amount matches
        stripe_price_amount = stripe_price.unit_amount / 100  # Convert cents to dollars
        if abs(stripe_price_amount - float(price)) > 0.01:  # Allow small floating point differences
            print(f"❌ Price mismatch - Stripe: ${stripe_price_amount}, Frontend: ${price}")
            raise HTTPException(
                status_code=400,
                detail=f"Price mismatch. Expected: ${stripe_price_amount}, Received: ${price}"
            )
        
        # Generate verify_token for the user
        from ..utils import create_access_token, get_club_count_for_captain, update_user_club_count
        from datetime import timedelta
        
        # Get club count if user is a captain
        club_count = 0
        if role == "Captain":
            try:
                # Check if user exists and get their club count
                if user:
                    club_count = await get_club_count_for_captain(str(user["_id"]))
                    await update_user_club_count(str(user["_id"]), club_count)
                    print(f"👑 Captain {user.get('full_name', 'Unknown')} has {club_count} clubs")
                else:
                    # New captain user, club count will be 0
                    print(f"👑 New Captain user - initial club count: {club_count}")
            except Exception as e:
                print(f"⚠️ Could not get club count for captain: {e}")
                club_count = 0
        
        verify_token_data = {"email": email.lower(), "purpose": "verification", "role": role}
        verify_token = create_access_token(
            data=verify_token_data, 
            expires_delta=timedelta(hours=24),
            club_count=club_count
        )
        print(f"✅ Verify token generated for email: {email}")
        
        # Validate price_id matches our expected price IDs
        # valid_price_ids = [
        #     MEMBERSHIP_CONFIG.get("price_id"),  # Trial membership price
        #     CAPTAIN_CONFIG.get("price_id"),     # Captain membership price
        # ]
        # print(valid_price_ids,"valid_price_ids")
        stripe_data = load_stripe_products()
        role_data = stripe_data.get(role.lower())

        if not role_data:
            raise HTTPException(status_code=400, detail=f"Invalid role: {role}")

        valid_price_ids = [
            stripe_data.get("member", {}).get("price_id"),
            stripe_data.get("captain", {}).get("price_id"),
        ]
        if price_id not in valid_price_ids:
            print(f"❌ Unauthorized price_id: {price_id}")
            print(f"✅ Valid price_ids: {valid_price_ids}")
            raise HTTPException(
                status_code=403,
                detail=f"Unauthorized price_id. This price is not allowed for membership subscriptions."
            )
        
        # Check if price is active
        if not stripe_price.active:
            print(f"❌ Inactive price_id: {price_id}")
            raise HTTPException(
                status_code=400,
                detail=f"Price {price_id} is not active in Stripe"
            )
        
        # Find user by email (case-insensitive) or create if doesn't exist
        from ..db import get_user_collection
        from bson import ObjectId
        from ..utils import hash_password
        import secrets
        import string
        
        users_collection = get_user_collection()
        
        # Use case-insensitive email lookup to match the pattern used in utils.py
        user = await users_collection.find_one({"email": email.lower()})
        print(user,"useruseruseruser")
        
        if not user:
            print(f"⚠️ User not found: {email}, creating new user automatically")
            
            # Generate temporary password for new user
            temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            
            # Create new user document
            user_doc = {
                "full_name": f"User_{email.split('@')[0]}",  # Default name from email
                "email": email.lower(),
                "phone": "",  # Empty phone for now
                "password_hash": hash_password(temp_password),
                "role": role,
                "status": "active",
                "wants_membership": True,
                "terms_accepted": True,  # Assume accepted since they're paying
                "terms_accepted_at": datetime.now(),
                "membership_status": "inactive",  # Will be updated to active after payment
                "subscription_id": None,
                "stripe_customer_id": None,
                "complete_step": 0,  # User just visited, step 0
                "club_count": 0,  # Initialize club_count to 0 for both captains and members
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "is_auto_created": True,  # Flag to identify auto-created users
                "temp_password": temp_password,
                "temp_password_created_at": datetime.now()
            }
            
            # Insert new user
            try:
                result = await users_collection.insert_one(user_doc)
                user_id = str(result.inserted_id)
                user = user_doc
                print(user,"useruseruseruser yahan")
                user["_id"] = result.inserted_id
                
                print(f"✅ New user created automatically: {user_id}")
                print(f"✅ Temporary password generated: {temp_password}")
                print(f"✅ User document: {user_doc}")
            except Exception as create_error:
                print(f"❌ Failed to create user: {str(create_error)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create user account: {str(create_error)}"
                )
        else:
            user_id = str(user["_id"])
            print("pata hai ")
            print(f"✅ Existing user found: {user_id}")
            
            # Ensure existing user has complete_step field initialized
            if "complete_step" not in user:
                await users_collection.update_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "$set": {
                            "complete_step": 0,  # Initialize complete_step for existing users
                            "updated_at": datetime.now()
                        }
                    }
                )
                user["complete_step"] = 0
                print(f"✅ Initialized complete_step for existing user: {user_id}")
            
            # Ensure existing user has temp_password for email sending
            if not user.get("temp_password"):
                temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
                await users_collection.update_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "$set": {
                            "temp_password": temp_password,
                            "temp_password_created_at": datetime.now(),
                            "updated_at": datetime.now()
                        }
                    }
                )
                user["temp_password"] = temp_password
                print(f"✅ Generated temp password for existing user: {temp_password}")
        if user.get("role") == "Captain" or  user.get("role") =="captain":
            current_type = "paid"
        else:
            current_type = "trial"
        # Check if user already has active subscription to prevent duplicates
        current_status = user.get("membership_status")
        # current_type = user.get("membership_type")
        current_plan_end_date = user.get("plan_end_date")
        current_profile_completed = user.get("profile_completed", False)
        print("nahi pata hai ")
        print(f"🔍 Debug - User {user_id} status check:")
        print(f"   - current_status: {current_status}")
        print(f"   - current_type: {current_type}")
        print(f"   - current_plan_end_date: {current_plan_end_date}")
        print(f"   - current_profile_completed: {current_profile_completed}")
        print(f"   - Condition check: {current_status == 'active' and current_type in ['trial', 'paid']}")
         
        # Check if plan is still active (not expired)
        if current_status == "active" and current_type in ["trial", "paid"]:
             print(f"⚠️ User has active membership - checking if plan is expired")
             if current_plan_end_date and current_plan_end_date > datetime.now():
                 # Plan is still active, calculate remaining days
                 remaining_days = (current_plan_end_date - datetime.now()).days
                 
                 # Determine complete_step based on profile completion status
                 # If profile is completed, complete_step = 1, otherwise complete_step = 0
                 current_complete_step = 1 if current_profile_completed else 0
                 
                 print(f"⚠️ Plan is still active for {remaining_days} days")
                 
                 # Return structured response instead of raising exception
                 return JSONResponse(
                     status_code=400,
                     content={
                         "success": False,
                         "subscription_id": user.get("subscription_id", ""),
                         "customer_id": user.get("stripe_customer_id", ""),
                         "price_id": price_id,
                         "validated_price": price,
                         "status": "active",
                         "membership_status": "active",
                         "membership_type": current_type,
                         "role": user.get("role", "Member"),
                         "payment_method_id": payment_method_id,
                         "email": email,
                         "verify_token": user.get("verify_token", ""),
                         "temp_password": user.get("temp_password", ""),
                         "created_at": user.get("created_at", datetime.now()).isoformat() if isinstance(user.get("created_at"), datetime) else str(user.get("created_at", datetime.now())),
                         "complete_step": current_complete_step,
                         "message": f"Plan is still active for {remaining_days} more days. You can make payment again after {current_plan_end_date.strftime('%Y-%m-%d %H:%M:%S')}"
                     }
                 )
             else:
                 # Plan has expired, allow new payment
                 print(f"✅ User's previous plan has expired, allowing new payment")
                 # Update status to inactive to allow new subscription
                 await users_collection.update_one(
                     {"_id": ObjectId(user_id)},
                     {
                         "$set": {
                             "membership_status": "inactive",
                             "membership_type": "expired",
                             "updated_at": datetime.now()
                         }
                     }
                 )
                 print(f"✅ Updated user {user_id} status to inactive (plan expired)")
         
        print(f"✅ User {user_id} passed membership check - proceeding with payment")
         
         # Get or create Stripe customer
        stripe_customer_id = user.get('stripe_customer_id')
        
        if not stripe_customer_id:
            # Create new Stripe customer
            customer = stripe.Customer.create(
                email=user['email'],
                name=user['full_name'],
                metadata={'user_id': user_id}
            )
            stripe_customer_id = customer.id
            print(f"✅ Created Stripe customer: {stripe_customer_id}")
            
            # Update user with Stripe customer ID
            await users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"stripe_customer_id": stripe_customer_id}}
            )
        else:
            print(f"✅ Using existing Stripe customer: {stripe_customer_id}")
        
        # Attach payment method to customer
        try:
            stripe.PaymentMethod.attach(
                payment_method_id,
                customer=stripe_customer_id,
            )
            print(f"✅ Payment method attached: {payment_method_id}")
        except Exception as e:
            print(f"❌ Failed to attach payment method: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid payment method: {str(e)}")
        
        # Determine membership type based on price_id
        membership_type = current_type
        print(membership_type,"membership_type")
        
        # Create subscription with validated price
        try:
            # subscription = stripe.Subscription.create(
            #     customer=stripe_customer_id,
            #     items=[{
            #         'price': price_id,
            #     }],
            #     default_payment_method=payment_method_id,
            #     expand=['latest_invoice.payment_intent'],
            #     metadata={
            #         'user_id': user_id,
            #         'membership_type': membership_type,
            #         'role': role,
            #         'validated_price': str(price)
            #     }
            # )
            # print(f"✅ Subscription created: {subscription.id}")
            subscription = None
            payment_intent = None
            payment_intent_id = None
            subscription_id = None
            subscription_status = None

            if role_data.get("type") == "one_time":
                # --- One-time payment flow ---
                payment_intent = stripe.PaymentIntent.create(
                    amount=int(float(price) * 100),
                    currency="usd",
                    customer=stripe_customer_id,
                    payment_method=payment_method_id,
                    confirm=True,
                    payment_method_types=["card"],
                    metadata={"user_id": user_id, "role": role}
                )
                print(f"✅ One-time payment successful: {payment_intent.id}")
                payment_intent_id = payment_intent.id
                subscription_id = payment_intent.id  # use payment_intent.id as pseudo-subscription
                subscription_status = payment_intent.status

            else:
                # --- Recurring subscription flow ---
                subscription = stripe.Subscription.create(
                    customer=stripe_customer_id,
                    items=[{"price": price_id}],
                    default_payment_method=payment_method_id,
                    expand=["latest_invoice.payment_intent"],
                    metadata={"user_id": user_id, "role": role}
                )
                print(f"✅ Subscription created: {subscription_id}")

                subscription_id = subscription.id
                subscription_status = subscription.status

                if subscription.latest_invoice and subscription.latest_invoice.payment_intent:
                    payment_intent_id = subscription.latest_invoice.payment_intent.id
                    print(f"✅ Payment intent ID extracted: {payment_intent_id}")
                else:
                    print(f"⚠️ No payment intent found in subscription")

            # ✅ Continue using safe IDs downstream
            print(f"🔍 Using subscription_id={subscription_id}, payment_intent_id={payment_intent_id}, status={subscription_status}")
            
            # Check if user is refunded and handle plan dates accordingly
            is_refunded = user.get("is_refunded", False)
            refund_count = user.get("refund_count", 0)
            is_reactive = True  # Default to true
            
            # Convert to proper types for comparison
            is_refunded_bool = bool(is_refunded) if is_refunded is not None else False
            refund_count_int = int(refund_count) if refund_count is not None else 0
            
            # Increment refund_count if user is refunded
            new_refund_count = refund_count_int
            if is_refunded_bool:
                new_refund_count = refund_count_int + 1
                print(f"🔄 REFUNDED USER DETECTED - Incrementing refund_count from {refund_count_int} to {new_refund_count}")
            
            # Debug logging for refund status
            print(f"🔍 DEBUG - User refund status check:")
            print(f"   - is_refunded (raw): {is_refunded} (type: {type(is_refunded)})")
            print(f"   - refund_count (raw): {refund_count} (type: {type(refund_count)})")
            print(f"   - refund_count (int): {refund_count_int}")
            print(f"   - new_refund_count: {new_refund_count}")
            print(f"   - is_refunded (bool): {is_refunded_bool} (type: {type(is_refunded_bool)})")
            print(f"   - Condition (is_refunded_bool and refund_count_int == 1): {is_refunded_bool and refund_count_int == 1}")
            
            # Calculate plan start and end dates
            if is_refunded_bool and refund_count_int == 1:
                # For refunded users (refund_count=1), keep original plan dates
                plan_start_date = user.get("plan_start_date")
                plan_end_date = user.get("plan_end_date")
                is_reactive = False  # User can no longer reactivate
                
                print(f"🔄 REFUNDED USER DETECTED - Setting is_reactive to FALSE")
                print(f"🔄 Refunded user payment: Keeping original plan dates - Start: {plan_start_date}, End: {plan_end_date}")
                print(f"🔄 Setting is_reactive to false for refunded user")
            else:
                # For new users or users without refunds, set new plan dates
                plan_start_date = datetime.now()
                plan_end_date = plan_start_date + timedelta(days=30)
                print(f"✅ NEW USER - Setting is_reactive to TRUE")
                print(f"✅ New user payment: Setting new plan dates - Start: {plan_start_date}, End: {plan_end_date}")
            
            # Update user membership status to active with appropriate membership_type
            try:
                 # Determine complete_step based on profile completion status
                 # If profile is completed, keep complete_step = 1, otherwise set to 0
                 current_profile_completed = user.get("profile_completed", False)
                 complete_step_value = 1 if current_profile_completed else 0
                 
                 # Prepare update data
                 update_data = {
                     "status": "active",  # Update user status from "inactive" to "active"
                     "membership_status": "active",  # Set to "active" for both trial and paid
                     "membership_type": membership_type,     # Track membership type: "trial" or "paid"
                     "subscription_id": subscription_id,
                     "stripe_customer_id": stripe_customer_id,
                     "complete_step": complete_step_value,  # Based on profile completion status
                     "updated_at": datetime.now(),
                     "is_reactive": is_reactive,  # Set based on refund status
                     "refund_count": new_refund_count  # Update refund count
                 }
                 print(update_data,"update_data")
                 
                 # Only update plan dates if they are new (not refunded user)
                 if not (is_refunded_bool and refund_count_int == 1):
                     update_data["plan_start_date"] = plan_start_date
                     update_data["plan_end_date"] = plan_end_date
                 
                 # Debug logging for database update
                 print(f"🔍 DEBUG - Database update data:")
                 print(f"   - User ID: {user_id}")
                 print(f"   - Update data: {update_data}")
                 print(f"   - Is refunded user: {is_refunded_bool and refund_count_int == 1}")
                 
                 update_result = await users_collection.update_one(
                     {"_id": ObjectId(user_id)},
                     {"$set": update_data}
                 )
                 
                 # Debug logging for update result
                 print(f"🔍 DEBUG - Database update result:")
                 print(f"   - matched_count: {update_result.matched_count}")
                 print(f"   - modified_count: {update_result.modified_count}")
                 print(f"   - upserted_id: {update_result.upserted_id}")
                 
                 if update_result.modified_count > 0:
                     if is_refunded_bool and refund_count_int == 1:
                         print(f"🔄 Refunded user status updated from inactive to active: {user_id}")
                         print(f"🔄 Refunded user membership_status updated to active with {membership_type} type: {user_id}")
                         print(f"🔄 Refunded user is_reactive set to false: {user_id}")
                         print(f"🔄 Refunded user refund_count updated from {refund_count_int} to {new_refund_count}: {user_id}")
                         print(f"🔄 Plan dates preserved - Start: {plan_start_date}, End: {plan_end_date}")
                         print(f"🔄 Database update successful - modified_count: {update_result.modified_count}")
                     else:
                         print(f"✅ User status updated to active: {user_id}")
                         print(f"✅ User membership_status updated to active with {membership_type} type: {user_id}")
                         print(f"✅ User complete_step updated to {complete_step_value} (payment successful): {user_id}")
                         print(f"✅ User refund_count set to {new_refund_count}: {user_id}")
                         print(f"✅ Plan start date: {plan_start_date}, Plan end date: {plan_end_date}")
                         print(f"✅ Database update successful - modified_count: {update_result.modified_count}")
                 else:
                     print(f"⚠️ No changes made to user {user_id} - membership status update")
                     print(f"⚠️ Database update failed - modified_count: {update_result.modified_count}")
                     
            except Exception as update_error:
                 print(f"❌ Error updating user membership statusss: {str(update_error)}")
                 # Continue with the process even if this update fails
            
            # Store payment record in database
            await store_payment_record(
                user_id=user_id,
                subscription_id=subscription_id,
                price_id=price_id,
                amount=stripe_price_amount,
                currency=stripe_price.currency,
                status="succeeded",
                payment_method_id=payment_method_id,
                stripe_customer_id=stripe_customer_id,
                payment_intent_id=payment_intent_id,
                start_date=plan_start_date,  # ✅ Pass plan start date
                end_date=plan_end_date        # ✅ Pass plan end date
            )
            # Update membership status and verify_token in database
            try:
                 # Prepare update data for verify_token and final status
                 final_update_data = {
                     "verify_token": verify_token,
                     "status": "active",  # Update user status from "inactive" to "active"
                     "membership_status": "active",
                     "membership_type": membership_type,
                     "subscription_id": subscription_id,
                     "stripe_customer_id": stripe_customer_id,
                     "complete_step": complete_step_value,  # Based on profile completion status
                     "updated_at": datetime.now(),
                     "is_reactive": is_reactive,  # Set based on refund status
                     "refund_count": new_refund_count  # Update refund count
                 }
                 
                 # Only update plan dates if they are new (not refunded user)
                 if not (is_refunded_bool and refund_count_int == 1):
                     final_update_data["plan_start_date"] = plan_start_date
                     final_update_data["plan_end_date"] = plan_end_date
                 
                 # Debug logging for final database update
                 print(f"🔍 DEBUG - Final database update data:")
                 print(f"   - User ID: {user_id}")
                 print(f"   - Final update data: {final_update_data}")
                 print(f"   - Is refunded user: {is_refunded_bool and refund_count_int == 1}")
                 
                 update_result = await users_collection.update_one(
                     {"_id": ObjectId(user_id)},
                     {"$set": final_update_data}
                 )
                 
                 # Debug logging for final update result
                 print(f"🔍 DEBUG - Final database update result:")
                 print(f"   - matched_count: {update_result.matched_count}")
                 print(f"   - modified_count: {update_result.modified_count}")
                 print(f"   - upserted_id: {update_result.upserted_id}")
                 
                 if update_result.modified_count > 0:
                     if is_refunded_bool and refund_count_int == 1:
                         print(f"🔄 Refunded user verify_token and final status updated: {user_id}")
                         print(f"🔄 Refunded user status set to active in final update: {user_id}")
                         print(f"🔄 Refunded user is_reactive set to false in final update: {user_id}")
                         print(f"🔄 Refunded user refund_count updated to {new_refund_count} in final update: {user_id}")
                         print(f"🔄 Final database update successful - modified_count: {update_result.modified_count}")
                     else:
                         print(f"✅ User verify_token and complete_step updated: {user_id}")
                         print(f"✅ User status set to active in final update: {user_id}")
                         print(f"✅ User refund_count set to {new_refund_count} in final update: {user_id}")
                         print(f"✅ Final database update successful - modified_count: {update_result.modified_count}")
                 else:
                     print(f"⚠️ No changes made to user {user_id} - final membership status update")
                     print(f"⚠️ Final database update failed - modified_count: {update_result.modified_count}")
                     
            except Exception as update_error:
                 print(f"❌ Error updating user membership status: {str(update_error)}")
                 # Continue with the process even if this update fails
            
            # Verify database fields were properly updated
            try:
                verification_user = await users_collection.find_one({"_id": ObjectId(user_id)})
                if verification_user:
                    current_status = verification_user.get("status", "NOT_SET")
                    current_membership_status = verification_user.get("membership_status", "NOT_SET")
                    current_is_reactive = verification_user.get("is_reactive", "NOT_SET")
                    current_complete_step = verification_user.get("complete_step", "NOT_SET")
                    current_refund_count = verification_user.get("refund_count", "NOT_SET")
                    
                    print(f"🔍 Verification: User {user_id} database fields after update:")
                    print(f"   - status: {current_status}")
                    print(f"   - membership_status: {current_membership_status}")
                    print(f"   - is_reactive: {current_is_reactive}")
                    print(f"   - complete_step: {current_complete_step}")
                    print(f"   - refund_count: {current_refund_count}")
                    
                    # Verify refunded user specific fields
                    if is_refunded_bool and refund_count_int == 1:
                        if current_status != "active":
                            print(f"❌ ERROR: Refunded user status should be 'active' but is '{current_status}'")
                        if current_membership_status != "active":
                            print(f"❌ ERROR: Refunded user membership_status should be 'active' but is '{current_membership_status}'")
                        if current_is_reactive != False:
                            print(f"❌ ERROR: Refunded user is_reactive should be False but is '{current_is_reactive}'")
                        if current_refund_count != new_refund_count:
                            print(f"❌ ERROR: Refunded user refund_count should be {new_refund_count} but is '{current_refund_count}'")
                        else:
                            print(f"✅ Refunded user verification successful - all fields updated correctly")
                            print(f"✅ Refund count successfully updated from {refund_count_int} to {new_refund_count}")
                    else:
                        if current_refund_count != new_refund_count:
                            print(f"❌ ERROR: User refund_count should be {new_refund_count} but is '{current_refund_count}'")
                        else:
                            print(f"✅ New user verification successful - all fields updated correctly")
                            print(f"✅ Refund count set to {new_refund_count}")
                        
                    # Fix complete_step if needed
                    if current_complete_step != complete_step_value:
                        print(f"⚠️ WARNING: complete_step was not properly set to {complete_step_value} for user {user_id}")
                        # Try to fix it
                        await ensure_complete_step_field(user_id, users_collection)
                else:
                    print(f"❌ Could not verify user {user_id} after updates")
            except Exception as verify_error:
                print(f"❌ Error verifying database fields: {str(verify_error)}")
            
            # Send email with credentials
            try:
                from ..utils import send_email
                
                # Get the temporary password (either from newly created user or existing user)
                temp_password = user.get("temp_password", "Please contact support for password reset")
                
                email_subject = "Welcome to MVP Sports - Your Account Credentials"
                email_body = f"""
                <html>
                <body>
                    <h2>Welcome to MVP Sports!</h2>
                    <p>Your subscription has been created successfully.</p>
                    
                    <h3>Account Details:</h3>
                    <p><strong>Email:</strong> {email}</p>
                    
                    <h3>Next Steps:</h3>
                    <p>1. Use these credentials to sign in to your account</p>
                    <p>2. Complete your profile by providing your first name, last name, and phone number</p>
                    <p>3. Change your password after first login</p>
                    
                    <p><strong>Important:</strong> Please keep your verify token safe for future use.</p>
                    
                    <p>Best regards,<br>MVP Sports Team</p>
                </body>
                </html>
                """
                
                await send_email(
                    to_email=email,
                    subject=email_subject,
                    html_content=email_body
                )
                print(f"✅ Welcome email sent to: {email}")
                
            except Exception as email_error:
                print(f"⚠️ Failed to send welcome email: {str(email_error)}")
                # Don't fail the subscription creation if email fails
            
            # Return success response after all operations are complete
            # Create appropriate message based on refund status
            if is_refunded_bool and refund_count_int == 1:
                message = f"Refunded user subscription reactivated successfully. User role set to {role} based on price ${price}. User membership status updated to active with {membership_type} membership type. Original plan dates preserved. User is_reactive set to false (no further reactivation allowed). Refund count updated from {refund_count_int} to {new_refund_count}. Welcome email sent with credentials."
            else:
                message = f"Subscription created successfully. User role set to {role} based on price ${price}. User membership status updated to active with {membership_type} membership type. User complete_step updated to {complete_step_value} (based on profile completion). Refund count set to {new_refund_count}. Welcome email sent with credentials."
            
            return {
                "success": True,
                "subscription_id": subscription_id,
                "customer_id": stripe_customer_id,
                "price_id": price_id,
                "validated_price": stripe_price_amount,
                "status": subscription_status,
                "membership_status": "active",  # User's new membership status
                "membership_type": membership_type,     # Membership type (trial or paid)
                "role": role,  # Return the auto-determined role in response
                "payment_method_id": payment_method_id,
                "email": email,
                "verify_token": verify_token,  # Return the generated verify_token in response
                "temp_password": user.get("temp_password", "Please contact support for password reset"),  # Return temporary password for frontend reference
                "refund_count": new_refund_count,  # Return the updated refund count
                "is_reactive": is_reactive,  # Return the is_reactive status
                "created_at": datetime.now().isoformat(),  # Return creation timestamp
                "complete_step": complete_step_value,  # Based on profile completion status
                "plan_start_date": plan_start_date.isoformat() if isinstance(plan_start_date, datetime) else str(plan_start_date),  # Return plan start date
                "plan_end_date": plan_end_date.isoformat() if isinstance(plan_end_date, datetime) else str(plan_end_date),  # Return plan end date
                "is_refunded": is_refunded,  # Return refund status
                "message": message
            }
            
        except stripe.error.CardError as e:
            print(f"❌ Card error: {str(e)}")
            
            # Store failed payment record
            try:
                await store_payment_record(
                    user_id=user_id,
                    subscription_id="",
                    price_id=price_id,
                    amount=stripe_price_amount,
                    currency=stripe_price.currency,
                    status="failed",
                    payment_method_id=payment_method_id,
                    stripe_customer_id=stripe_customer_id,
                    payment_intent_id=None,  # No payment intent for failed payments
                    start_date=None,         # ✅ No dates for failed payments
                    end_date=None            # ✅ No dates for failed payments
                )
            except Exception as store_error:
                print(f"❌ Failed to store failed payment record: {str(store_error)}")
            
            raise HTTPException(status_code=400, detail=f"Payment failed: {str(e)}")
        except Exception as e:
            print(f"❌ Subscription creation error: {str(e)}")
            
            # Store failed payment record for general errors
            try:
                await store_payment_record(
                    user_id=user_id,
                    subscription_id="",
                    price_id=price_id,
                    amount=stripe_price_amount,
                    currency=stripe_price.currency,
                    status="failed",
                    payment_method_id=payment_method_id,
                    stripe_customer_id=stripe_customer_id,
                    payment_intent_id=None,  # No payment intent for failed payments
                    start_date=None,         # ✅ No dates for failed payments
                    end_date=None            # ✅ No dates for failed payments
                )
            except Exception as store_error:
                print(f"❌ Failed to store failed payment record: {str(store_error)}")
            
            raise HTTPException(status_code=500, detail=f"Failed to create subscription: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# @router.get("/api/user/membership-status")
# async def get_user_membership_status(
#     email: str,
# ):
#     """
#     Get user's current membership status for testing
#     """
#     try:
#         from ..db import get_user_collection
#         users_collection = get_user_collection()
        
#         user = await users_collection.find_one({"email": email.lower()})
#         if not user:
#             # If user doesn't exist, still respond with membership and status as none/inactive
#             return {
#                 "user_id": None,
#                 "email": email.lower(),
#                 "full_name": None,
#                 "membership_status": "inactive",
#                 "membership_type": "none",
#                 "subscription_id": None,
#                 "stripe_customer_id": None,
#                 "wants_membership": False,
#                 "terms_accepted": False,
#                 "created_at": None,
#                 "updated_at": None,
#                 "status": "suspended",  # default for non-existing user context
#             }
        
#         return {
#             "user_id": str(user["_id"]),
#             "email": user["email"],
#             "full_name": user["full_name"],
#             "membership_status": user.get("membership_status", "inactive"),
#             "membership_type": user.get("membership_type", "none"),
#             "subscription_id": user.get("subscription_id"),
#             "stripe_customer_id": user.get("stripe_customer_id"),
#             "wants_membership": user.get("wants_membership", False),
#             "terms_accepted": user.get("terms_accepted", False),
#             "created_at": user.get("created_at"),
#             "updated_at": user.get("updated_at"),
#             "status": user.get("status", "active"),
#         }
        
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error retrieving user status: {str(e)}")


# ========================================
# Utility Functions
# ========================================

async def fix_user_complete_step(user_id: str):
    """
    Fix complete_step for existing users who have active memberships but missing complete_step field
    """
    try:
        from ..db import get_user_collection
        from bson import ObjectId
        
        users_collection = get_user_collection()
        
        # Find user by ID
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            print(f"❌ User not found: {user_id}")
            return False
        
        # Determine the appropriate complete_step based on user's current state
        complete_step = 0
        
        # If user has active membership, they've completed payment (step 1)
        if user.get("membership_status") == "active":
            complete_step = 1
            
            # If user has completed profile, they're at step 2
            if user.get("profile_completed", False):
                complete_step = 2
                
                # If user has joined clubs (we'd need to check club membership), they're at step 4
                # For now, we'll assume they're at step 3 if profile is completed
        
        # Update the user's complete_step
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "complete_step": complete_step,
                    "updated_at": datetime.now()
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"✅ Fixed user {user_id} complete_step to {complete_step}")
            return True
        else:
            print(f"⚠️ No changes made to user {user_id} complete_step")
            return False
            
    except Exception as e:
        print(f"❌ Error fixing user complete_step: {str(e)}")
        return False

async def ensure_complete_step_field(user_id: str, users_collection):
    """
    Ensure the complete_step field exists and is properly set for a user
    """
    try:
        from bson import ObjectId
        
        # Check if user has complete_step field
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return False
        
        # If complete_step field is missing, initialize it
        if "complete_step" not in user:
            complete_step = 0
            if user.get("membership_status") == "active":
                complete_step = 1
                if user.get("profile_completed", False):
                    complete_step = 2
            
            await users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "complete_step": complete_step,
                        "updated_at": datetime.now()
                    }
                }
            )
            print(f"✅ Initialized missing complete_step field for user {user_id} to {complete_step}")
            return True
        
        return True
        
    except Exception as e:
        print(f"❌ Error ensuring complete_step field: {str(e)}")
        return False

# ========================================
# Membership details by email
# ========================================

@router.get("/api/user/membership-details")
async def get_user_membership_details(
    email: str,
):
    """
    Return full user details by email along with membership_status and account status.
    - If membership_status is active, returns all user details
    - If inactive, still returns all details so frontend can render state
    - Always generates a verify_token for both existing and new users
    """
    try:
        from ..db import get_user_collection
        from ..utils import create_access_token
        from datetime import timedelta
        
        users_collection = get_user_collection()

        user = await users_collection.find_one({"email": email.lower()})
        
        # Generate verify_token for both existing and new users
        # Token expires in 24 hours for verification purposes
        # Get role from user if exists, otherwise use default "Member"
        user_role = user.get("role", "Member") if user else "Member"
        
        # Get club count if user is a captain
        club_count = 0
        if user and user.get("role") == "Captain":
            try:
                from ..utils import get_club_count_for_captain, update_user_club_count
                club_count = await get_club_count_for_captain(str(user["_id"]))
                await update_user_club_count(str(user["_id"]), club_count)
                print(f"👑 Captain {user.get('full_name', 'Unknown')} has {club_count} clubs")
            except Exception as e:
                print(f"⚠️ Could not get club count for captain: {e}")
                club_count = user.get("club_count", 0)
        
        verify_token_data = {"email": email.lower(), "purpose": "verification", "role": user_role}
        verify_token = create_access_token(
            data=verify_token_data, 
            expires_delta=timedelta(hours=24),
            club_count=club_count
        )
        
        # Initialize browser_id variable
        browser_id = ""
        
        if not user:
            # For new users, browser_id should be empty string
            browser_id = ""
            
            # Return default payload for non-existing users for pre-check flows
            return {
                "success": True,
                "isUserExists": False,
                "verify_token": verify_token,
                "browser_id": browser_id,
                "user": {
                    "user_id": None,
                    "full_name": None,
                    "email": email.lower(),
                    "phone": None,
                    "role": None,
                    "status": "suspended",
                    "membership_status": "inactive",
                    "membership_type": "none",
                    "subscription_id": None,
                    "stripe_customer_id": None,
                    "wants_membership": False,
                    "terms_accepted": False,
                    "terms_accepted_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "is_membership_active": False
                }
            }

        created_at = user.get("created_at")
        updated_at = user.get("updated_at")

        user_payload = {
            "user_id": str(user.get("_id")),
            "full_name": user.get("full_name"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "role": user.get("role"),
            "status": user.get("status", "active"),
            "membership_status": user.get("membership_status", "inactive"),
            "membership_type": user.get("membership_type", "none"),
            "subscription_id": user.get("subscription_id"),
            "stripe_customer_id": user.get("stripe_customer_id"),
            "wants_membership": user.get("wants_membership", False),
            "terms_accepted": user.get("terms_accepted", False),
            "terms_accepted_at": user.get("terms_accepted_at"),
            "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
            "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
        }

        user_payload["is_membership_active"] = user_payload["membership_status"] == "active"

        # Get browser_id from database for existing users
        browser_id = user.get("browser_id")
        
        return {
            "success": True,
            "isUserExists": True,
            "verify_token": verify_token,
            "browser_id": browser_id,
            "user": user_payload
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving user details: {str(e)}")


# ========================================
# Complete signup with profile details
# ========================================

# @router.post("/api/membership/complete-signup")
# async def complete_signup_profile(request: dict):
#     """
#     Complete user signup by updating first name, last name, and role.
#     This endpoint is called after successful subscription creation.
#     """
#     try:
#         # Extract request data
#         email = request.get('email')
#         first_name = request.get('first_name')
#         last_name = request.get('last_name')
#         role = request.get('role')
#         browser_id = request.get('browser_id')
        
#         # Validate required fields
#         if not all([email, first_name, last_name, role, browser_id]):
#             raise HTTPException(
#                 status_code=400,
#                 detail="Missing required fields: email, first_name, last_name, role, browser_id"
#             )
        
#         # Validate role
#         valid_roles = ["member", "captain"]
#         if role not in valid_roles:
#             raise HTTPException(
#                 status_code=400,
#                 detail=f"Invalid role. Must be one of: {valid_roles}"
#             )
        
#         # Find user by email and browser_id
#         from ..db import get_user_collection
#         from bson import ObjectId
#         users_collection = get_user_collection()
        
#         user = await users_collection.find_one({
#             "email": email.lower(),
#             "browser_id": browser_id
#         })
        
#         if not user:
#             raise HTTPException(
#                 status_code=404,
#                 detail="User not found with provided email and browser_id"
#             )
        
#         # Check if user already has active membership
#         if user.get("membership_status") != "active":
#             raise HTTPException(
#                 status_code=400,
#                 detail="User does not have active membership. Please complete subscription first."
#             )
        
#         # Update user profile
#         full_name = f"{first_name} {last_name}".strip()
        
#         update_result = await users_collection.update_one(
#             {"_id": user["_id"]},
#             {
#                 "$set": {
#                     "first_name": first_name,
#                     "last_name": last_name,
#                     "full_name": full_name,
#                     "role": role,
#                     "profile_completed": True,
#                     "profile_completed_at": datetime.now(),
#                     "updated_at": datetime.now()
#                 }
#             }
#         )
        
#         if update_result.modified_count == 0:
#             raise HTTPException(
#                 status_code=500,
#                 detail="Failed to update user profile"
#             )
        
#         print(f"✅ User profile completed for: {email}")
        
#         return {
#             "success": True,
#             "message": "Profile completed successfully",
#             "user": {
#                 "user_id": str(user["_id"]),
#                 "email": user["email"],
#                 "first_name": first_name,
#                 "last_name": last_name,
#                 "full_name": full_name,
#                 "role": role,
#                 "membership_status": user.get("membership_status"),
#                 "membership_type": user.get("membership_type"),
#                 "profile_completed": True
#             }
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ Error completing signup: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error completing signup: {str(e)}"
#         )






        

        
#         # Validate password match
#         if password != re_password:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Password and confirm password do not match"
#             )
        
#         # Validate password strength
#         if len(password) < 8:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Password must be at least 8 characters long"
#             )
        
#         # Validate role (convert "user" to "Member" if needed)
#         if role == "user":
#             role = "Member"
        
#         valid_roles = ["Member", "Captain"]
#         if role not in valid_roles:
#             raise HTTPException(
#                 status_code=400,
#                 detail=f"Invalid role. Must be one of: {valid_roles}"
#             )
        
#         # Validate verify_token
#         try:
#             from ..utils import verify_token as verify_jwt_token
#             token_payload = verify_jwt_token(verify_token)
#             if not token_payload:
#                 raise HTTPException(
#                     status_code=401,
#                     detail="Invalid or expired verify_token"
#                 )
            
#             # Validate token email matches request email
#             token_email = token_payload.get('email')
#             if token_email != email.lower():
#                 raise HTTPException(
#                     status_code=401,
#                     detail="Token email does not match request email"
#                 )
            
#             # Validate token purpose
#             token_purpose = token_payload.get('purpose')
#             if token_purpose != 'verification':
#                 raise HTTPException(
#                     status_code=401,
#                     detail="Invalid token purpose"
#                 )
            
#             print(f"✅ Verify token validated for email: {email}")
            
#         except Exception as e:
#             print(f"❌ Token validation error: {str(e)}")
#             raise HTTPException(
#                 status_code=401,
#                 detail=f"Token validation failed: {str(e)}"
#             )
        
#         # Find user by email and browser_id
#         from ..db import get_user_collection
#         from bson import ObjectId
#         from ..utils import hash_password
        
#         users_collection = get_user_collection()
        
#         user = await users_collection.find_one({
#             "email": email.lower(),
#             "browser_id": browser_id
#         })
        
#         if not user:
#             raise HTTPException(
#                 status_code=404,
#                 detail="User not found with provided email and browser_id. Please complete subscription first."
#             )
        
#         # Check if user has active membership
#         if user.get("membership_status") != "active":
#             raise HTTPException(
#                 status_code=400,
#                 detail="User does not have active membership. Please complete subscription first."
#             )
        
#         # Check if profile is already completed
#         if user.get("profile_completed", False):
#             raise HTTPException(
#                 status_code=400,
#                 detail="User profile is already completed"
#             )
        
#         # Update user profile
#         full_name = f"{first_name} {last_name}".strip()
        
#         # Hash the new password
#         hashed_password = hash_password(password)
        
#         update_result = await users_collection.update_one(
#             {"_id": user["_id"]},
#             {
#                 "$set": {
#                     "full_name": full_name,
#                     "first_name": first_name,
#                     "last_name": last_name,
#                     "phone": phone,
#                     "password_hash": hashed_password,
#                     "role": role,
#                     "profile_completed": True,
#                     "profile_completed_at": datetime.now(),
#                     "updated_at": datetime.now(),
#                     "is_auto_created": False  # Mark as manually completed
#                 },
#                 "$unset": {
#                     "temp_password": "",
#                     "temp_password_created_at": ""
#                 }
#             }
#         )
        
#         if update_result.modified_count == 0:
#             raise HTTPException(
#                 status_code=500,
#                 detail="Failed to update user profile"
#             )
        
#         print(f"✅ User profile completed for: {email}")
        
#         # Generate new access token for the updated user
#         from ..utils import create_access_token, create_refresh_token, ACCESS_TOKEN_EXPIRE_MINUTES
        
#         token_data = {
#             "sub": str(user["_id"]),
#             "email": email.lower(),
#             "role": role
#         }
        
#         access_token = create_access_token(data=token_data)
#         refresh_token = create_refresh_token(data=token_data)
        
#         return {
#             "success": True,
#             "message": "Profile completed successfully",
#             "access_token": access_token,
#             "refresh_token": refresh_token,
#             "token_type": "bearer",
#             "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
#             "user": {
#                 "user_id": str(user["_id"]),
#                 "email": email.lower(),
#                 "first_name": first_name,
#                 "last_name": last_name,
#                 "full_name": full_name,
#                 "role": role,
#                 "phone": phone,
#                 "membership_status": user.get("membership_status"),
#                 "membership_type": user.get("membership_type"),
#                 "profile_completed": True,
#                 "subscription_id": user.get("subscription_id"),
#                 "stripe_customer_id": user.get("stripe_customer_id")
#             }
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ Error completing profile: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error completing profile: {str(e)}"
#         )


# # ========================================
# # Admin Endpoints for fixing existing users
# # ========================================

# @router.post("/api/admin/fix-complete-step/{user_id}")
# async def fix_user_complete_step_endpoint(user_id: str):
#     """
#     Admin endpoint to fix complete_step for existing users
#     """
#     try:
#         success = await fix_user_complete_step(user_id)
#         if success:
#             return {
#                 "success": True,
#                 "message": f"User {user_id} complete_step fixed successfully"
#             }
#         else:
#             return {
#                 "success": False,
#                 "message": f"Failed to fix user {user_id} complete_step"
#             }
#     except Exception as e:
#         print(f"❌ Error in fix_user_complete_step_endpoint: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error fixing user complete_step: {str(e)}"
#         )

# @router.post("/api/admin/fix-all-users-complete-step")
# async def fix_all_users_complete_step():
#     """
#     Admin endpoint to fix complete_step for all existing users
#     """
#     try:
#         from ..db import get_user_collection
#         from bson import ObjectId
        
#         users_collection = get_user_collection()
        
#         # Find all users
#         all_users = await users_collection.find({}).to_list(length=None)
        
#         fixed_count = 0
#         total_users = len(all_users)
        
#         for user in all_users:
#             user_id = str(user["_id"])
            
#             # Check if user needs fixing
#             if "complete_step" not in user:
#                 # Determine appropriate complete_step
#                 complete_step = 0
#                 if user.get("membership_status") == "active":
#                     complete_step = 1
#                     if user.get("profile_completed", False):
#                         complete_step = 2
                
#                 # Update user
#                 result = await users_collection.update_one(
#                     {"_id": ObjectId(user_id)},
#                     {
#                         "$set": {
#                             "complete_step": complete_step,
#                             "updated_at": datetime.now()
#                         }
#                     }
#                 )
                
#                 if result.modified_count > 0:
#                     fixed_count += 1
#                     print(f"✅ Fixed user {user_id} complete_step to {complete_step}")
        
#         return {
#             "success": True,
#             "message": f"Fixed {fixed_count} out of {total_users} users",
#             "fixed_count": fixed_count,
#             "total_users": total_users
#         }
        
#     except Exception as e:
#         print(f"❌ Error in fix_all_users_complete_step: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error fixing all users complete_step: {str(e)}"
#         )

# ========================================
# Membership details by email
# ========================================

@router.get("/api/user/membership-details")
async def get_user_membership_details(
    email: str,
):
    """
    Return full user details by email along with membership_status and account status.
    - If membership_status is active, returns all user details
    - If inactive, still returns all details so frontend can render state
    - Always generates a verify_token for both existing and new users
    """
    try:
        from ..db import get_user_collection
        from ..utils import create_access_token
        from datetime import timedelta
        
        users_collection = get_user_collection()

        user = await users_collection.find_one({"email": email.lower()})
        
        # Generate verify_token for both existing and new users
        # Token expires in 24 hours for verification purposes
        # Get role from user if exists, otherwise use default "Member"
        user_role = user.get("role", "Member") if user else "Member"
        verify_token_data = {"email": email.lower(), "purpose": "verification", "role": user_role}
        verify_token = create_access_token(
            data=verify_token_data, 
            expires_delta=timedelta(hours=24)
        )
        
        # Initialize browser_id variable
        browser_id = ""
        
        if not user:
            # For new users, browser_id should be empty string
            browser_id = ""
            
            # Return default payload for non-existing users for pre-check flows
            return {
                "success": True,
                "isUserExists": False,
                "verify_token": verify_token,
                "browser_id": browser_id,
                "user": {
                    "user_id": None,
                    "full_name": None,
                    "email": email.lower(),
                    "phone": None,
                    "role": None,
                    "status": "suspended",
                    "membership_status": "inactive",
                    "membership_type": "none",
                    "subscription_id": None,
                    "stripe_customer_id": None,
                    "wants_membership": False,
                    "terms_accepted": False,
                    "terms_accepted_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "is_membership_active": False
                }
            }

        created_at = user.get("created_at")
        updated_at = user.get("updated_at")

        user_payload = {
            "user_id": str(user.get("_id")),
            "full_name": user.get("full_name"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "role": user.get("role"),
            "status": user.get("status", "active"),
            "membership_status": user.get("membership_status", "inactive"),
            "membership_type": user.get("membership_type", "none"),
            "subscription_id": user.get("subscription_id"),
            "stripe_customer_id": user.get("stripe_customer_id"),
            "wants_membership": user.get("wants_membership", False),
            "terms_accepted": user.get("terms_accepted", False),
            "terms_accepted_at": user.get("terms_accepted_at"),
            "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
            "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
        }

        user_payload["is_membership_active"] = user_payload["membership_status"] == "active"

        # Get browser_id from database for existing users
        browser_id = user.get("browser_id")
        
        return {
            "success": True,
            "isUserExists": True,
            "verify_token": verify_token,
            "browser_id": browser_id,
            "user": user_payload
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving user details: {str(e)}")


# ========================================
# Get user profile completion status
# ========================================

# @router.get("/api/membership/profile-status")
# async def get_profile_completion_status(email: str, browser_id: str):
#     """
#     Check if user profile is completed and get current status.
#     """
#     try:
#         from ..db import get_user_collection
        
#         users_collection = get_user_collection()
        
#         user = await users_collection.find_one({
#             "email": email.lower(),
#             "browser_id": browser_id
#         })
        
#         if not user:
#             raise HTTPException(
#                 status_code=404,
#                 detail="User not found with provided email and browser_id"
#             )
        
#         profile_completed = user.get("profile_completed", False)
#         membership_status = user.get("membership_status", "inactive")
        
#         return {
#             "success": True,
#             "profile_completed": profile_completed,
#             "membership_status": membership_status,
#             "user": {
#                 "user_id": str(user["_id"]),
#                 "email": user["email"],
#                 "first_name": user.get("first_name"),
#                 "last_name": user.get("last_name"),
#                 "full_name": user.get("full_name"),
#                 "role": user.get("role"),
#                 "membership_status": membership_status,
#                 "membership_type": user.get("membership_type"),
#                 "profile_completed": profile_completed,
#                 "subscription_id": user.get("subscription_id"),
#                 "stripe_customer_id": user.get("stripe_customer_id")
#             }
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ Error getting profile status: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error getting profile status: {str(e)}"
#         )

