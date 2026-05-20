from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
from bson import ObjectId
from .db import get_club_collection, get_user_collection, db, get_membership_collection
from .models import (
    TrialMembershipStatus, TrialLimits, GroupAccessInfo, 
    TrialMembershipDocument, GroupAccessDocument, ClubResponse
)
import math

# Trial configuration
TRIAL_LIMITS = TrialLimits(
    max_clubs=4,
    trial_duration_days=30,
    refund_period_days=7,
    groups_per_week=1
)

def get_trial_membership_collection():
    """Get trial membership tracking collection"""
    return db["trial_memberships"]

def get_group_access_collection():
    """Get group access tracking collection"""
    return db["group_access"]

def get_refund_requests_collection():
    """Get refund requests collection"""
    return db["refund_requests"]

async def get_week_start_date() -> datetime:
    """Get the start of current week (Monday)"""
    now = datetime.utcnow()
    days_since_monday = now.weekday()
    week_start = now - timedelta(days=days_since_monday)
    return week_start.replace(hour=0, minute=0, second=0, microsecond=0)

async def is_user_trial_member(user_id: str) -> bool:
    """Check if user has trial membership status"""
    user_collection = get_user_collection()
    
    try:
        user_object_id = ObjectId(user_id)
        user = await user_collection.find_one({"_id": user_object_id})
        
        if not user:
            return False
        
        # Check if user has trial membership type and is not permanently deleted
        membership_status = user.get("membership_status")
        membership_type = user.get("membership_type")
        user_status = user.get("status")
        plan_end_date = user.get("plan_end_date")
          # Check if trial has expired
        now = datetime.utcnow()
        if plan_end_date and now > plan_end_date:
            return False
        
        # Allow trial access if:
        # 1. User has trial membership type
        # 2. User is not permanently deleted (status != "deleted")
        # 3. User is either active or inactive (but not deleted)
        return (membership_type == "trial" and 
                user_status != "deleted" and
                membership_status in ["active", "inactive"])
    except Exception:
        return False

async def get_or_create_trial_membership(user_id: str) -> Optional[TrialMembershipDocument]:
    """Get or create trial membership record"""
    trial_collection = get_trial_membership_collection()
    
    # Check if trial membership exists
    trial_membership = await trial_collection.find_one({"user_id": user_id})
    
    if trial_membership:
        return trial_membership
    
    # Create new trial membership if user has trial status
    if not await is_user_trial_member(user_id):
        return None
    
    # Create trial membership record
    now = datetime.utcnow()
    trial_end = now + timedelta(days=TRIAL_LIMITS.trial_duration_days)
    
    trial_doc = {
        "user_id": user_id,
        "trial_start_date": now,
        "trial_end_date": trial_end,
        "clubs_joined": [],
        "refund_requested": False,
        "refund_processed": False,
        "refund_amount": 0.0,
        "refund_date": None,
        "created_at": now,
        "updated_at": now
    }
    
    result = await trial_collection.insert_one(trial_doc)
    if result.inserted_id:
        return await trial_collection.find_one({"_id": result.inserted_id})
    
    return None

async def get_trial_membership_status(user_id: str) -> TrialMembershipStatus:
    """Get comprehensive trial membership status"""
    trial_membership = await get_or_create_trial_membership(user_id)
    
    if not trial_membership:
        return TrialMembershipStatus(is_trial_user=False)
    
    now = datetime.utcnow()
    trial_start = trial_membership["trial_start_date"]
    trial_end = trial_membership["trial_end_date"]
    
    # Calculate remaining days
    days_remaining = max(0, (trial_end - now).days)
    
    # Get user data for trial status and statistics
    user_collection = get_user_collection()
    user = await user_collection.find_one({"_id": ObjectId(user_id)})
    user_status = user.get("status", "active") if user else "active"
    
    # Check if trial is active (not expired, not refunded, and user not permanently deleted)
    is_trial_active = (now <= trial_end and 
                      not trial_membership.get("refund_processed", False) and
                      user_status != "deleted")
    
    if user:
        # Use the updated trial statistics from users table
        clubs_joined_count = user.get("clubs_joined_count", 0)
        clubs_remaining = user.get("clubs_remaining", TRIAL_LIMITS.max_clubs)
        max_clubs = user.get("max_clubs", TRIAL_LIMITS.max_clubs)
    else:
        # Fallback to old method if user not found
        clubs_joined_count = len(trial_membership.get("clubs_joined", []))
        clubs_remaining = max(0, TRIAL_LIMITS.max_clubs - clubs_joined_count)
    
    # Check refund eligibility (within 7 days of trial start)
    refund_deadline = trial_start + timedelta(days=TRIAL_LIMITS.refund_period_days)
    is_refund_eligible = (
        now <= refund_deadline and 
        not trial_membership.get("refund_requested", False) and
        clubs_joined_count > 0
    )
    
    return TrialMembershipStatus(
        is_trial_user=True,
        trial_start_date=trial_start,
        trial_end_date=trial_end,
        clubs_joined_count=clubs_joined_count,
        clubs_remaining=clubs_remaining,
        days_remaining=days_remaining,
        is_trial_active=is_trial_active,
        is_refund_eligible=is_refund_eligible,
        refund_deadline=refund_deadline if is_refund_eligible else None
    )

async def can_join_club_trial(user_id: str, club_id: str) -> Tuple[bool, List[str]]:
    """Check if trial user can join a club"""
    restrictions = []
    
    # Check if user is trial member
    if not await is_user_trial_member(user_id):
        return False, ["User is not a trial member"]
    
    # Get trial status
    trial_status = await get_trial_membership_status(user_id)
    
    if not trial_status.is_trial_active:
        return False, ["Trial period has expired. Please upgrade to a paid membership."]
    
    # Check club limit
    if trial_status.clubs_remaining <= 0:
        restrictions.append(
            f"Trial limit reached. You have joined {trial_status.clubs_joined_count}/{TRIAL_LIMITS.max_clubs} clubs. "
            "To join more clubs, please upgrade to a paid membership."
        )
    
    # Check if already member of this club
    membership_collection = get_membership_collection()
    existing_membership = await membership_collection.find_one({
        "user_id": user_id,
        "club_id": club_id,
        "subscription_status": {"$in": ["active", "pending"]}
    })
    
    if existing_membership:
        restrictions.append("You are already a member of this club")
    
    # Check if club exists and is active
    club_collection = get_club_collection()
    try:
        club_object_id = ObjectId(club_id)
        club = await club_collection.find_one({"_id": club_object_id, "is_active": True})
        
        if not club:
            restrictions.append("Club not found or inactive")
    except Exception:
        restrictions.append("Invalid club ID")
    
    can_join = len(restrictions) == 0
    return can_join, restrictions

async def join_club_trial(user_id: str, club_id: str, pricing_plan: str) -> Tuple[bool, str]:
    """Join a club as trial member"""
    # Validate trial membership
    can_join, restrictions = await can_join_club_trial(user_id, club_id)
    
    if not can_join:
        return False, "; ".join(restrictions)
    
    # Create trial membership
    membership_collection = get_membership_collection()
    trial_collection = get_trial_membership_collection()
    
    now = datetime.utcnow()
    trial_end = now + timedelta(days=TRIAL_LIMITS.trial_duration_days)
    refund_deadline = now + timedelta(days=TRIAL_LIMITS.refund_period_days)
    
    # Create membership document
    membership_doc = {
        "user_id": user_id,
        "club_id": club_id,
        "pricing_plan": pricing_plan,
        "subscription_status": "active",
        "is_trial_membership": True,
        "trial_join_date": now,
        "joined_date": now,
        "expires_date": trial_end,
        "payment_id": None,
        "amount_paid": 0.0,
        "refund_eligible": True,
        "refund_deadline": refund_deadline,
        "created_at": now,
        "updated_at": now
    }
    
    result = await membership_collection.insert_one(membership_doc)
    
    if result.inserted_id:
        # Update trial membership record
        await trial_collection.update_one(
            {"user_id": user_id},
            {
                "$push": {"clubs_joined": club_id},
                "$set": {"updated_at": now}
            }
        )
        
        # Update club member count
        from .membership_service import update_club_member_count, add_member_to_club
        await update_club_member_count(club_id)
        
        # Add detailed member information to club's members array and user's clubs array
        await add_member_to_club(
            user_id=user_id,
            club_id=club_id,
            pricing_plan=pricing_plan,
            is_trial=True,
            membership_status="active",
            payment_id=None,
            amount_paid=0.0,
            end_date=trial_end
        )
        
        # Explicitly update club_count in auth database for members
        # This ensures club_count = 1 when member joins first club, and stays 1 forever
        await _update_member_club_count(user_id)
        
        # Update user complete_step to 3 (joined club)
        await update_user_complete_step(user_id, 3)
        
        return True, "Successfully joined club with trial membership"
    
    return False, "Failed to create membership"

async def _update_member_club_count(user_id: str):
    """Update member's club_count in auth database - ensures it becomes 1 and stays 1"""
    try:
        # Try to import auth service functions first
        try:
            import sys
            import os
            auth_service_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'betting_auth_service', 'auth')
            if auth_service_path not in sys.path:
                sys.path.append(auth_service_path)
            
            from utils import update_user_club_count
            
            # For members, club_count should be 1 if they have joined any clubs
            await update_user_club_count(user_id, 1)
            print(f"👤 Updated member {user_id} club_count to 1 via auth service")
            
        except ImportError as import_error:
            print(f"⚠️ Could not import auth service functions: {import_error}")
            # Fallback: try to update directly in auth database
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                import os
                
                # Get auth database connection
                auth_db_url = os.getenv('AUTH_DATABASE_URL', 'mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main/')
                auth_client = AsyncIOMotorClient(auth_db_url)
                auth_db = auth_client.get_database('betting_main')
                auth_users_collection = auth_db['users']
                
                # Update club_count for member to 1
                now = datetime.utcnow()
                result = await auth_users_collection.update_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "$set": {
                            "club_count": 1,
                            "updated_at": now
                        }
                    }
                )
                
                if result.modified_count > 0:
                    print(f"👤 Updated member {user_id} club_count to 1 (direct database update)")
                else:
                    print(f"⚠️ No document updated for member {user_id} club_count")
                
            except Exception as direct_error:
                print(f"⚠️ Could not update member club_count directly: {direct_error}")
        except Exception as update_error:
            print(f"⚠️ Error updating member club_count via auth service: {update_error}")
            
    except Exception as e:
        print(f"⚠️ Error in _update_member_club_count: {e}")

async def get_group_access_status(user_id: str) -> GroupAccessInfo:
    """Get user's group access status for the current week"""
    group_access_collection = get_group_access_collection()
    week_start = await get_week_start_date()
    next_reset = week_start + timedelta(days=7)
    
    # Find current week's access record
    access_record = await group_access_collection.find_one({
        "user_id": user_id,
        "week_start_date": week_start
    })
    
    if not access_record:
        # Create new week record
        access_doc = {
            "user_id": user_id,
            "week_start_date": week_start,
            "groups_accessed": 0,
            "last_access_date": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await group_access_collection.insert_one(access_doc)
        groups_accessed = 0
    else:
        groups_accessed = access_record.get("groups_accessed", 0)
    
    groups_remaining = max(0, TRIAL_LIMITS.groups_per_week - groups_accessed)
    can_access = groups_remaining > 0
    
    return GroupAccessInfo(
        groups_accessed_this_week=groups_accessed,
        groups_remaining_this_week=groups_remaining,
        next_reset_date=next_reset,
        can_access_groups=can_access
    )

async def access_group(user_id: str) -> Tuple[bool, str]:
    """Record group access for trial user"""
    if not await is_user_trial_member(user_id):
        return False, "Only trial members have group access limitations"
    
    group_access_info = await get_group_access_status(user_id)
    
    if not group_access_info.can_access_groups:
        return False, f"Weekly group access limit reached. Next reset: {group_access_info.next_reset_date.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    
    # Update access count
    group_access_collection = get_group_access_collection()
    week_start = await get_week_start_date()
    now = datetime.utcnow()
    
    await group_access_collection.update_one(
        {"user_id": user_id, "week_start_date": week_start},
        {
            "$inc": {"groups_accessed": 1},
            "$set": {
                "last_access_date": now,
                "updated_at": now
            }
        }
    )
    
    return True, "Group access granted"

async def request_refund(user_id: str, reason: str, club_ids: Optional[List[str]] = None) -> Tuple[bool, str, float]:
    """Request refund for trial memberships"""
    # Check if user is eligible for refund
    trial_status = await get_trial_membership_status(user_id)
    
    if not trial_status.is_trial_user:
        return False, "Only trial members can request refunds", 0.0
    
    if not trial_status.is_refund_eligible:
        return False, f"Refund period expired. Refunds are only available within {TRIAL_LIMITS.refund_period_days} days of joining.", 0.0
    
    # Get memberships to refund
    membership_collection = get_membership_collection()
    trial_collection = get_trial_membership_collection()
    refund_collection = get_refund_requests_collection()
    
    if club_ids:
        # Specific clubs
        memberships = await membership_collection.find({
            "user_id": user_id,
            "club_id": {"$in": club_ids},
            "is_trial_membership": True,
            "refund_eligible": True
        }).to_list(None)
    else:
        # All trial memberships
        memberships = await membership_collection.find({
            "user_id": user_id,
            "is_trial_membership": True,
            "refund_eligible": True
        }).to_list(None)
    
    if not memberships:
        return False, "No eligible memberships found for refund", 0.0
    
    # Calculate refund amount (for trial it's 0, but structure for future paid trials)
    refund_amount = sum(membership.get("amount_paid", 0.0) for membership in memberships)
    club_ids_to_refund = [membership["club_id"] for membership in memberships]
    
    now = datetime.utcnow()
    refund_id = f"refund_{user_id}_{int(now.timestamp())}"
    
    # Create refund request
    refund_doc = {
        "refund_id": refund_id,
        "user_id": user_id,
        "club_ids": club_ids_to_refund,
        "reason": reason,
        "refund_amount": refund_amount,
        "status": "approved",  # Auto-approve trial refunds
        "requested_at": now,
        "processed_at": now,
        "created_at": now,
        "updated_at": now
    }
    
    await refund_collection.insert_one(refund_doc)
    
    # Update memberships to cancelled
    await membership_collection.update_many(
        {"user_id": user_id, "club_id": {"$in": club_ids_to_refund}},
        {
            "$set": {
                "subscription_status": "cancelled",
                "refund_eligible": False,
                "updated_at": now
            }
        }
    )
    
    # Update trial membership record
    await trial_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "refund_requested": True,
                "refund_processed": True,
                "refund_amount": refund_amount,
                "refund_date": now,
                "updated_at": now
            }
        }
    )
    
    # Update club member counts
    from .membership_service import update_club_member_count
    for club_id in club_ids_to_refund:
        await update_club_member_count(club_id)
    
    return True, f"Refund processed successfully for {len(club_ids_to_refund)} memberships", refund_amount

async def get_trial_joined_clubs(user_id: str) -> List[Dict]:
    """Get clubs joined by trial user"""
    membership_collection = get_membership_collection()
    club_collection = get_club_collection()
    
    # Get trial memberships
    memberships = await membership_collection.find({
        "user_id": user_id,
        "is_trial_membership": True,
        "subscription_status": "active"
    }).to_list(None)
    
    clubs = []
    for membership in memberships:
        try:
            club_object_id = ObjectId(membership["club_id"])
            club = await club_collection.find_one({"_id": club_object_id})
            
            if club:
                from .routes import club_document_to_response
                club_response = await club_document_to_response(club)
                clubs.append(club_response)
        except Exception:
            continue
    
    return clubs

async def get_available_trial_actions(user_id: str) -> List[str]:
    """Get available actions for trial user"""
    trial_status = await get_trial_membership_status(user_id)
    group_access = await get_group_access_status(user_id)
    actions = []
    
    if not trial_status.is_trial_user:
        return ["Upgrade to paid membership"]
    
    if trial_status.is_trial_active:
        if trial_status.clubs_remaining > 0:
            actions.append(f"Join {trial_status.clubs_remaining} more clubs")
        
        if group_access.can_access_groups:
            actions.append(f"Access {group_access.groups_remaining_this_week} groups this week")
        
        if trial_status.is_refund_eligible:
            actions.append("Request full refund")
    
    if trial_status.clubs_remaining == 0:
        actions.append("Upgrade to paid membership to join more clubs")
    
    if not trial_status.is_trial_active:
        actions.append("Trial expired - Upgrade to continue")
    
    return actions

async def update_user_complete_step(user_id: str, step: int):
    """Update user's complete_step in the auth service database"""
    try:
        # Import auth service database connection
        from motor.motor_asyncio import AsyncIOMotorClient
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        # Connect to auth service database
        auth_mongo_url = os.getenv("MONGO_URL")
        auth_db_name = os.getenv("AUTH_DATABASE_NAME", "betting_main")
        
        auth_client = AsyncIOMotorClient(
            auth_mongo_url,
            tls=True,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
            maxPoolSize=50,
            minPoolSize=10,
            maxIdleTimeMS=30000,
            waitQueueTimeoutMS=2500,
            retryWrites=True,
            retryReads=True
        )
        
        auth_db = auth_client[auth_db_name]
        users_collection = auth_db["users"]
        
        # Update user's complete_step
        from bson import ObjectId
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"complete_step": step, "updated_at": datetime.utcnow()}}
        )
        
        if result.modified_count > 0:
            print(f"✅ Updated user {user_id} complete_step to {step}")
        else:
            print(f"⚠️ No changes made to user {user_id} complete_step")
            
        # Close the connection
        auth_client.close()
        
    except Exception as e:
        print(f"❌ Error updating user complete_step: {str(e)}")
        # Don't fail the club joining process if this fails 