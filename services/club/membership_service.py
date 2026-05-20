from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

from .db import get_club_collection, get_user_collection, get_club_payments_collection, db
from .trial_service import is_user_trial_member, get_trial_membership_status
from .models import (
    MembershipInfo, PricingPlan, ClubMembershipDocument,
    OngoingMembershipDetails, OngoingMembershipCaptain, OngoingMembershipsResponse,
    MembershipSummary, PastMembershipDetails, PastMembershipsResponse, MembershipHistorySummary
)

def get_membership_collection():
    """Get the club memberships collection"""
    return db["club_memberships"]

async def check_user_membership(user_id: str, club_id: str) -> Optional[MembershipInfo]:
    """Check if a user is a member of a specific club"""
    membership_collection = get_membership_collection()
    
    try:
        club_object_id = ObjectId(club_id)
        user_object_id = ObjectId(user_id)
    except Exception:
        return None
    
    # Find active membership
    membership = await membership_collection.find_one({
        "user_id": user_id,
        "club_id": club_id,
        "subscription_status": {"$in": ["active", "pending"]}
    })
    
    if not membership:
        return MembershipInfo(is_member=False)
    
    # Check if membership is expired
    now = datetime.utcnow()
    is_expired = False
    
    if membership.get("expires_date"):
        is_expired = membership["expires_date"] < now
    
    # Determine access level
    can_access_premium = (
        membership["subscription_status"] == "active" and 
        not is_expired
    )
    
    return MembershipInfo(
        is_member=True,
        membership_plan=PricingPlan(membership["pricing_plan"]),
        joined_date=membership["joined_date"],
        expires_date=membership.get("expires_date"),
        subscription_status=membership["subscription_status"],
        can_access_premium=can_access_premium
    )

async def get_user_club_memberships(user_id: str) -> List[Dict]:
    """Get all club memberships for a user"""
    membership_collection = get_membership_collection()
    
    memberships = await membership_collection.find({
        "user_id": user_id,
        "subscription_status": {"$in": ["active", "pending"]}
    }).to_list(None)
    
    return memberships

async def create_club_membership(
    user_id: str, 
    club_id: str, 
    pricing_plan: str,
    payment_id: Optional[str] = None
) -> bool:
    """Create a new club membership"""
    membership_collection = get_membership_collection()
    
    # Check if membership already exists
    existing = await membership_collection.find_one({
        "user_id": user_id,
        "club_id": club_id,
        "subscription_status": {"$in": ["active", "pending"]}
    })
    
    if existing:
        return False  # Already a member
    
    # Calculate expiration date based on plan
    now = datetime.utcnow()
    expires_date = None
    
    if pricing_plan == "daily":
        expires_date = now + timedelta(days=1)
    elif pricing_plan == "weekly":
        expires_date = now + timedelta(weeks=1)  # 7 days
    elif pricing_plan == "monthly":
        expires_date = now + timedelta(days=30)
    elif pricing_plan == "quarterly":
        expires_date = now + timedelta(days=90)
    elif pricing_plan == "yearly":
        expires_date = now + timedelta(days=365)
    
    # Create membership document
    membership_doc = {
        "user_id": user_id,
        "club_id": club_id,
        "pricing_plan": pricing_plan,
        "subscription_status": "pending",  # Will be activated after payment
        "joined_date": now,
        "expires_date": expires_date,
        "payment_id": payment_id,
        "created_at": now,
        "updated_at": now
    }
    
    result = await membership_collection.insert_one(membership_doc)
    
    # Update club member count and add detailed member info
    if result.inserted_id:
        await update_club_member_count(club_id)
        # Add detailed member information to both clubs and users collections
        await add_member_to_club(
            user_id=user_id,
            club_id=club_id,
            pricing_plan=pricing_plan,
            is_trial=False,
            membership_status="pending",
            payment_id=payment_id,
            amount_paid=0.0,
            end_date=expires_date
        )
        return True
    
    return False

async def update_membership_status(
    user_id: str, 
    club_id: str, 
    status: str
) -> bool:
    """Update membership subscription status"""
    membership_collection = get_membership_collection()
    
    result = await membership_collection.update_one(
        {"user_id": user_id, "club_id": club_id},
        {
            "$set": {
                "subscription_status": status,
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    # Update club member count
    await update_club_member_count(club_id)
    
    return result.modified_count > 0

async def update_club_member_count(club_id: str):
    """Update the member count for a club"""
    membership_collection = get_membership_collection()
    club_collection = get_club_collection()
    
    # Count active members
    active_count = await membership_collection.count_documents({
        "club_id": club_id,
        "subscription_status": "active"
    })
    
    # Update club document
    try:
        club_object_id = ObjectId(club_id)
        await club_collection.update_one(
            {"_id": club_object_id},
            {
                "$set": {
                    "member_count": active_count,
                    "updated_at": datetime.utcnow()
                }
            }
        )
    except Exception:
        pass  # Handle gracefully if club doesn't exist

async def add_member_to_club(user_id: str, club_id: str, pricing_plan: str, is_trial: bool = False, 
                           membership_status: str = "active", payment_id: str = None, 
                           amount_paid: float = 0.0, end_date: datetime = None):
    """Add detailed member information to club's members array and user's clubs array"""
    club_collection = get_club_collection()
    user_collection = get_user_collection()
    now = datetime.utcnow()
    
    try:
        # Get user details
        user_object_id = ObjectId(user_id)
        user = await user_collection.find_one({"_id": user_object_id})
        
        if not user:
            print(f"User not found: {user_id}")
            return False
        
        # Get club details
        club_object_id = ObjectId(club_id)
        club = await club_collection.find_one({"_id": club_object_id})
        
        if not club:
            print(f"Club not found: {club_id}")
            return False
        
        # Determine membership type and status
        membership_type = "trial" if is_trial else "paid"
        if not membership_status:
            membership_status = "active"
        
        # Check if user is already a member of the club (in either array)
        existing_member = await club_collection.find_one({
            "_id": club_object_id,
            "$or": [
                {"members.user_id": user_id},
                {"paid_members.user_id": user_id}
            ]
        })
        
        if existing_member:
            print(f"User {user_id} is already a member of club {club_id}")
            return True  # Return True since user is already a member
        
        # Get user's trial period dates for trial memberships
        trial_period_start = None
        trial_period_end = None
        if is_trial:
            trial_period_start = user.get("plan_start_date")
            trial_period_end = user.get("plan_end_date")
        
        # Prepare detailed member info for club
        member_info = {
            "user_id": user_id,
            "full_name": user.get("full_name", "Unknown"),
            "email": user.get("email", ""),
            "phone": user.get("phone", ""),
            "avatar_url": user.get("avatar_url"),
            "membership_type": membership_type,
            "membership_status": membership_status,
            "pricing_plan": pricing_plan,
            "join_date": now,
            "end_date": end_date,
            "is_trial": is_trial,
            "is_active": True,
            "last_seen": now,
            "payment_id": payment_id,
            "amount_paid": amount_paid,
            "trial_period_start": trial_period_start,  # Track trial period
            "trial_period_end": trial_period_end,      # Track trial period
            "created_at": now,
            "updated_at": now
        }
        
        # Add member to appropriate club array based on membership type
        if is_trial:
            # Add to members array for trial/free members
            await club_collection.update_one(
                {"_id": club_object_id},
                {
                    "$addToSet": {
                        "members": member_info
                    },
                    "$set": {
                        "updated_at": now
                    }
                }
            )
        else:
            # Add to paid_members array for paid members
            await club_collection.update_one(
                {"_id": club_object_id},
                {
                    "$addToSet": {
                        "paid_members": member_info
                    },
                    "$set": {
                        "updated_at": now
                    }
                }
            )
        
        # Prepare club info for user
        club_info = {
            "club_id": club_id,
            "club_name": club.get("name", ""),
            "club_name_based_id": club.get("name_based_id", ""),
            "captain_name": club.get("captain_details", {}).get("full_name", "Unknown Captain"),
            "membership_type": membership_type,
            "membership_status": membership_status,
            "pricing_plan": pricing_plan,
            "join_date": now,
            "end_date": end_date,
            "is_trial": is_trial,
            "is_active": True,
            "payment_id": payment_id,
            "amount_paid": amount_paid,
            "trial_period_start": trial_period_start,  # Track trial period
            "trial_period_end": trial_period_end,      # Track trial period
            "created_at": now,
            "updated_at": now
        }
        
        # Check if user already has this club in clubs_joined array
        existing_club = await user_collection.find_one({
            "_id": user_object_id,
            "clubs_joined.club_id": club_id
        })
        
        if not existing_club:
            # Add club to user's clubs array only if not already present
            await user_collection.update_one(
                {"_id": user_object_id},
                {
                    "$addToSet": {
                        "clubs_joined": club_info
                    },
                    "$set": {
                        "updated_at": now
                    }
                }
            )
            
            # Update trial club statistics if this is a trial membership
            if is_trial:
                await update_trial_club_statistics(user_id, user_collection, club_object_id)
        
        # Update user's total clubs joined count - recalculate from clubs_joined array
        updated_user = await user_collection.find_one({"_id": user_object_id})
        if updated_user:
            clubs_joined = updated_user.get("clubs_joined", [])
            clubs_count = len(clubs_joined)
            await user_collection.update_one(
                {"_id": user_object_id},
                {
                    "$set": {
                        "total_clubs_joined": clubs_count,
                        "updated_at": now
                    }
                }
            )
        
        # Update club_count in auth service for members
        # For members: club_count starts at 0, becomes 1 when they join first club, stays 1
        if user.get("role") == "Member":
            try:
                # Import auth service functions to update club_count
                import sys
                import os
                auth_service_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'betting_auth_service', 'auth')
                if auth_service_path not in sys.path:
                    sys.path.append(auth_service_path)
                
                from utils import update_user_club_count
                
                # For members, club_count should be 1 if they have joined any clubs
                member_club_count = 1 if clubs_count > 0 else 0
                await update_user_club_count(user_id, member_club_count)
                print(f"👤 Updated member {user.get('full_name', user_id)} club_count to {member_club_count}")
                
            except ImportError as import_error:
                print(f"⚠️ Could not import auth service functions: {import_error}")
                # Fallback: try to update directly in auth database
                try:
                    from motor.motor_asyncio import AsyncIOMotorClient
                    import os
                    
                    # Get auth database connection
                    auth_db_url = os.getenv('MONGO_URL', 'mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main/')
                    auth_client = AsyncIOMotorClient(auth_db_url)
                    auth_db = auth_client.get_database('betting_main')
                    auth_users_collection = auth_db['users']
                    
                    # Update club_count for member
                    member_club_count = 1 if clubs_count > 0 else 0
                    await auth_users_collection.update_one(
                        {"_id": ObjectId(user_id)},
                        {
                            "$set": {
                                "club_count": member_club_count,
                                "updated_at": now
                            }
                        }
                    )
                    print(f"👤 Updated member {user.get('full_name', user_id)} club_count to {member_club_count} (direct)")
                    
                except Exception as direct_error:
                    print(f"⚠️ Could not update member club_count directly: {direct_error}")
            except Exception as update_error:
                print(f"⚠️ Error updating member club_count: {update_error}")
        
        print(f"✅ Added detailed member info for {user.get('full_name', user_id)} to club {club.get('name', club_id)}")
        
        # Send club join notification to captains and moderators
        try:
            from services.notifications.notification_service import (
                send_notification_to_users,
                get_club_members,
                filter_users_by_notification_preference,
                get_collections,
            )
            
            # Get new member details for notification
            new_member_name = user.get("full_name", "New Member")
            membership_type_text = "trial" if is_trial else "paid"
            
            # Get club members who have club join alerts enabled
            # Note: We need to exclude the new member from the notification recipients
            raw_club_members = await get_club_members(club.get("name_based_id"))
            all_club_members: List[str] = []
            for member in raw_club_members or []:
                if isinstance(member, dict):
                    member_id = (
                        member.get("user_id")
                        or member.get("_id")
                        or member.get("id")
                    )
                else:
                    member_id = member
                if member_id:
                    all_club_members.append(str(member_id))

            # Remove the new member from the list of recipients
            notification_recipients = [
                member_id for member_id in all_club_members if member_id != str(user_id)
            ]
            
            if notification_recipients:
                enabled_user_ids = await filter_users_by_notification_preference(
                    notification_recipients,
                    "club_join_alerts"
                )
                enabled_user_ids = [
                    str(uid) for uid in (enabled_user_ids or []) if uid
                ]
                
                collections = get_collections()
                user_tokens_collection = collections.get_user_tokens_collection()
                
                users_with_tokens: List[str] = []
                if enabled_user_ids:
                    token_cursor = user_tokens_collection.find(
                        {
                            "user_id": {"$in": enabled_user_ids},
                            "is_active": True,
                        },
                        {"user_id": 1},
                    )
                    token_docs = await token_cursor.to_list(length=None)
                    users_with_tokens = list({
                        doc.get("user_id") for doc in token_docs if doc.get("user_id")
                    })
                
                push_user_ids = [
                    uid for uid in users_with_tokens if uid in enabled_user_ids
                ]
                
                if notification_recipients:
                    title = "New Member Joined!"
                    body = f"{new_member_name} has joined the club ({membership_type_text} member)"
                    
                    notification_data = {
                        "club_id": club.get("name_based_id"),
                        "new_member_name": new_member_name,
                        "membership_type": membership_type_text,
                        "new_member_id": user_id
                    }
                    
                    notification_result = await send_notification_to_users(
                        user_ids=push_user_ids,
                        title=title,
                        body=body,
                        notification_type="club_member_join",
                        data=notification_data,
                        click_action=f"club/{club.get('name_based_id')}/members",
                        priority="normal",
                        all_user_ids=notification_recipients,
                    )
                    print(
                        f"✅ Club join notification stored for {new_member_name}: {notification_result}"
                    )
                else:
                    print(f"ℹ️ No users with club join alerts found for club {club.get('name_based_id')}")
            else:
                print(f"ℹ️ No notification recipients found (excluding new member)")
                
        except Exception as e:
            print(f"⚠️ Failed to send club join notification: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error adding detailed member info to club: {e}")
        return False

async def get_club_members_details(club_id: str) -> List[dict]:
    """Get detailed information about all members of a club"""
    club_collection = get_club_collection()
    
    try:
        club_object_id = ObjectId(club_id)
        club = await club_collection.find_one({"_id": club_object_id})
        
        if not club:
            return []
        
        members = club.get("members", [])
        return members
        
    except Exception as e:
        print(f"❌ Error getting club members details: {e}")
        return []

async def get_user_clubs_details(user_id: str) -> List[dict]:
    """Get detailed information about all clubs a user has joined"""
    user_collection = get_user_collection()
    
    try:
        user_object_id = ObjectId(user_id)
        user = await user_collection.find_one({"_id": user_object_id})
        
        if not user:
            return []
        
        clubs_joined = user.get("clubs_joined", [])
        return clubs_joined
        
    except Exception as e:
        print(f"❌ Error getting user clubs details: {e}")
        return []

async def update_member_status_in_club(club_id: str, user_id: str, status: str):
    """Update member status in club's members array"""
    club_collection = get_club_collection()
    now = datetime.utcnow()
    
    try:
        club_object_id = ObjectId(club_id)
        await club_collection.update_one(
            {"_id": club_object_id, "members.user_id": user_id},
            {
                "$set": {
                    "members.$.membership_status": status,
                    "members.$.updated_at": now,
                    "updated_at": now
                }
            }
        )
        
        print(f"✅ Updated member {user_id} status to {status} in club {club_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error updating member status in club: {e}")
        return False

async def update_user_club_status(user_id: str, club_id: str, status: str):
    """Update club status in user's clubs array"""
    user_collection = get_user_collection()
    now = datetime.utcnow()
    
    try:
        user_object_id = ObjectId(user_id)
        await user_collection.update_one(
            {"_id": user_object_id, "clubs_joined.club_id": club_id},
            {
                "$set": {
                    "clubs_joined.$.membership_status": status,
                    "clubs_joined.$.updated_at": now,
                    "updated_at": now
                }
            }
        )
        
        print(f"✅ Updated club {club_id} status to {status} for user {user_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error updating user club status: {e}")
        return False

async def remove_member_from_club(user_id: str, club_id: str):
    """Remove member from club's members array"""
    club_collection = get_club_collection()
    now = datetime.utcnow()
    
    try:
        club_object_id = ObjectId(club_id)
        await club_collection.update_one(
            {"_id": club_object_id},
            {
                "$pull": {
                    "members": {"user_id": user_id}
                },
                "$set": {
                    "updated_at": now
                }
            }
        )
        
        print(f"✅ Removed member {user_id} from club {club_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error removing member from club: {e}")
        return False

async def get_club_members(club_id: str) -> List[dict]:
    """Get all members of a club"""
    club_collection = get_club_collection()
    
    try:
        club_object_id = ObjectId(club_id)
        club = await club_collection.find_one({"_id": club_object_id})
        
        if not club:
            return []
        
        return club.get("members", [])
        
    except Exception as e:
        print(f"❌ Error getting club members: {e}")
        return []

async def cancel_membership(user_id: str, club_id: str) -> bool:
    """Cancel a club membership"""
    membership_collection = get_membership_collection()
    
    result = await membership_collection.update_one(
        {"user_id": user_id, "club_id": club_id},
        {
            "$set": {
                "subscription_status": "cancelled",
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    # Update club member count
    await update_club_member_count(club_id)
    
    return result.modified_count > 0

async def get_captain_total_members(captain_id: str) -> int:
    """Get total members across all captain's clubs"""
    club_collection = get_club_collection()
    
    # Get all captain's clubs
    clubs = await club_collection.find({
        "captain_id": captain_id,
        "is_active": True
    }).to_list(None)
    
    # Calculate total members correctly - use total_members if available, otherwise sum member_count + paid_member_count
    total_members = 0
    for club in clubs:
        if "total_members" in club:
            member_count = club.get("total_members", 0)
        else:
            member_count = club.get("member_count", 0) + club.get("paid_member_count", 0)
        total_members += member_count
    
    return total_members

async def get_captain_stats(captain_id: str) -> Dict:
    """Get aggregated stats for a captain across all clubs"""
    club_collection = get_club_collection()
    
    # Get all captain's clubs
    clubs = await club_collection.find({
        "captain_id": captain_id,
        "is_active": True
    }).to_list(None)
    
    if not clubs:
        return {
            "total_clubs": 0,
            "total_members": 0,
            "average_win_pct": 0.0,
            "total_picks": 0,
            "total_winning_picks": 0
        }
    
    # Calculate total members correctly - use total_members if available, otherwise sum member_count + paid_member_count
    total_members = 0
    for club in clubs:
        if "total_members" in club:
            member_count = club.get("total_members", 0)
        else:
            member_count = club.get("member_count", 0) + club.get("paid_member_count", 0)
        total_members += member_count
    total_picks = sum(club.get("total_bets", 0) for club in clubs)
    total_winning_picks = sum(club.get("winning_bets", 0) for club in clubs)
    
    # Calculate average win percentage (weighted by number of picks)
    total_weighted_win_pct = sum(
        club.get("win_pct", 0) * club.get("total_bets", 0) 
        for club in clubs
    )
    
    average_win_pct = 0.0
    if total_picks > 0:
        average_win_pct = total_weighted_win_pct / total_picks
    
    return {
        "total_clubs": len(clubs),
        "total_members": total_members,
        "average_win_pct": round(average_win_pct, 2),
        "total_picks": total_picks,
        "total_winning_picks": total_winning_picks
    }

async def can_user_join_club(user_id: str, club_id: str) -> Tuple[bool, List[str]]:
    """Check if a user can join a club and return any restrictions"""
    restrictions = []
    
    # Check if already a member
    membership = await check_user_membership(user_id, club_id)
    if membership and membership.is_member:
        return False, ["Already a member of this club"]
    
    # Check if club exists and is active
    club_collection = get_club_collection()
    try:
        club_object_id = ObjectId(club_id)
        club = await club_collection.find_one({"_id": club_object_id})
        
        if not club:
            return False, ["Club not found"]
        
        if not club.get("is_active", True):
            return False, ["Club is not currently accepting new members"]
    except Exception:
        return False, ["Invalid club ID"]
    
    # Check user's membership limit (optional business rule)
    user_memberships = await get_user_club_memberships(user_id)
    if len(user_memberships) >= 10:  # Example limit
        restrictions.append("Maximum number of club memberships reached")
    
    # If user is a captain, check if they're trying to join their own club
    if club["captain_id"] == user_id:
        return False, ["Captains cannot join their own clubs"]
    
    can_join = len(restrictions) == 0
    return can_join, restrictions 

async def calculate_next_renewal_date(start_date: datetime, pricing_plan: str) -> Optional[datetime]:
    """Calculate next renewal date based on pricing plan"""
    if pricing_plan == "trial":
        return None  # Trial doesn't have renewal
    
    if pricing_plan == "daily":
        return start_date + timedelta(days=1)
    elif pricing_plan == "weekly":
        return start_date + timedelta(days=7)
    elif pricing_plan == "monthly":
        return start_date + timedelta(days=30)
    elif pricing_plan == "quarterly":
        return start_date + timedelta(days=90)
    elif pricing_plan == "yearly":
        return start_date + timedelta(days=365)
    elif pricing_plan == "lifetime":
        return None  # Lifetime doesn't have renewal
    
    return None

async def get_ongoing_memberships(user_id: str) -> OngoingMembershipsResponse:
    """Get all ongoing (active) memberships for a user"""
    membership_collection = get_membership_collection()
    club_collection = get_club_collection()
    user_collection = get_user_collection()
    
    # Get all active memberships for the user
    memberships = await membership_collection.find({
        "user_id": user_id,
        "subscription_status": {"$in": ["active", "trial", "pending"]}
    }).to_list(None)
    
    ongoing_memberships = []
    total_monthly_cost = 0.0
    trial_count = 0
    paid_count = 0
    
    now = datetime.utcnow()
    
    for membership in memberships:
        try:
            # Get club details
            club_object_id = ObjectId(membership["club_id"])
            club = await club_collection.find_one({"_id": club_object_id})
            
            if not club or not club.get("is_active", True):
                continue  # Skip inactive clubs
            
            # Get captain details
            captain_object_id = ObjectId(club["captain_id"])
            captain = await user_collection.find_one({"_id": captain_object_id})
            
            captain_info = OngoingMembershipCaptain(
                captain_id=club["captain_id"],
                captain_name=captain.get("full_name", "Unknown Captain") if captain else "Unknown Captain",
                captain_profile_pic=captain.get("avatar_url") if captain else None
            )
            
            # Determine membership type and status
            is_trial = membership.get("is_trial_membership", False)
            membership_type = "Trial" if is_trial else "Paid"
            pricing_plan = membership["pricing_plan"]
            
            # Calculate pricing information
            price = 0.0
            currency = "USD"
            
            if not is_trial:
                # Find the pricing from club's pricing plans
                for plan in club.get("pricing_plans", []):
                    if plan["plan"] == pricing_plan:
                        price = plan["price"]
                        currency = plan.get("currency", "USD")
                        break
            
            # Calculate next renewal date
            start_date = membership["joined_date"]
            next_renewal = await calculate_next_renewal_date(start_date, pricing_plan)
            
            # Calculate days remaining
            days_remaining = None
            if membership.get("expires_date"):
                expires_date = membership["expires_date"]
                days_remaining = max(0, (expires_date - now).days)
            
            # Determine status
            status = "Active"
            if membership["subscription_status"] == "trial":
                status = "Trial"
            elif membership["subscription_status"] == "pending":
                status = "Pending"
            elif membership["subscription_status"] == "cancelled":
                status = "Cancelled"
            elif membership["subscription_status"] == "paused":
                status = "Paused"
            
            # Check if membership is expired
            if membership.get("expires_date") and membership["expires_date"] < now:
                status = "Expired"
                continue  # Skip expired memberships
            
            # Calculate monthly cost for budgeting
            monthly_cost = 0.0
            if not is_trial and price > 0:
                if pricing_plan == "monthly":
                    monthly_cost = price
                elif pricing_plan == "quarterly":
                    monthly_cost = price / 3
                elif pricing_plan == "yearly":
                    monthly_cost = price / 12
                
                total_monthly_cost += monthly_cost
            
            # Determine capabilities
            can_cancel = status in ["Active", "Trial"]
            can_upgrade = is_trial and status == "Trial"
            auto_renewal = not is_trial and status == "Active"
            
            # Count membership types
            if is_trial:
                trial_count += 1
            else:
                paid_count += 1
            
            ongoing_membership = OngoingMembershipDetails(
                club_id=membership["club_id"],
                club_name=club["name"],
                club_logo=club.get("logo_url"),
                captain=captain_info,
                membership_type=membership_type,
                start_date=start_date,
                next_renewal_date=next_renewal,
                price=price,
                pricing_plan=pricing_plan,
                currency=currency,
                status=status,
                days_remaining=days_remaining,
                auto_renewal=auto_renewal,
                can_cancel=can_cancel,
                can_upgrade=can_upgrade
            )
            
            ongoing_memberships.append(ongoing_membership)
            
        except Exception as e:
            print(f"Error processing membership {membership.get('_id')}: {e}")
            continue
    
    return OngoingMembershipsResponse(
        memberships=ongoing_memberships,
        total_count=len(ongoing_memberships),
        active_count=len([m for m in ongoing_memberships if m.status in ["Active", "Trial"]]),
        trial_count=trial_count,
        paid_count=paid_count,
        total_monthly_cost=round(total_monthly_cost, 2)
    )

async def get_membership_summary(user_id: str) -> MembershipSummary:
    """Get summary of user's membership status"""
    memberships_response = await get_ongoing_memberships(user_id)
    is_trial = await is_user_trial_member(user_id)
    
    # Calculate next renewal date
    next_renewal = None
    active_memberships = [m for m in memberships_response.memberships if m.next_renewal_date]
    if active_memberships:
        next_renewal = min(m.next_renewal_date for m in active_memberships)
    
    # Get trial days remaining
    trial_days_remaining = None
    if is_trial:
        trial_status = await get_trial_membership_status(user_id)
        trial_days_remaining = trial_status.days_remaining
    
    return MembershipSummary(
        is_trial_user=is_trial,
        total_memberships=memberships_response.total_count,
        active_memberships=memberships_response.active_count,
        trial_memberships=memberships_response.trial_count,
        paid_memberships=memberships_response.paid_count,
        monthly_cost=memberships_response.total_monthly_cost,
        next_renewal=next_renewal,
        trial_days_remaining=trial_days_remaining
    )

async def cancel_membership_by_id(user_id: str, club_id: str, reason: Optional[str] = None) -> Tuple[bool, str]:
    """Cancel a specific membership"""
    membership_collection = get_membership_collection()
    
    # Find the membership
    membership = await membership_collection.find_one({
        "user_id": user_id,
        "club_id": club_id,
        "subscription_status": {"$in": ["active", "trial", "pending"]}
    })
    
    if not membership:
        return False, "Membership not found or already cancelled"
    
    # Update membership status
    now = datetime.utcnow()
    result = await membership_collection.update_one(
        {"_id": membership["_id"]},
        {
            "$set": {
                "subscription_status": "cancelled",
                "updated_at": now,
                "cancellation_reason": reason,
                "cancelled_at": now
            }
        }
    )
    
    if result.modified_count > 0:
        # Update club member count
        await update_club_member_count(club_id)
        
        # Remove member from club's members array
        await remove_member_from_club(user_id, club_id)
        
        return True, "Membership cancelled successfully"
    
    return False, "Failed to cancel membership"

async def pause_membership_by_id(user_id: str, club_id: str) -> Tuple[bool, str]:
    """Pause a specific membership (for paid memberships only)"""
    membership_collection = get_membership_collection()
    
    # Find the membership
    membership = await membership_collection.find_one({
        "user_id": user_id,
        "club_id": club_id,
        "subscription_status": "active",
        "is_trial_membership": False
    })
    
    if not membership:
        return False, "Active paid membership not found"
    
    # Update membership status
    now = datetime.utcnow()
    result = await membership_collection.update_one(
        {"_id": membership["_id"]},
        {
            "$set": {
                "subscription_status": "paused",
                "updated_at": now,
                "paused_at": now
            }
        }
    )
    
    if result.modified_count > 0:
        return True, "Membership paused successfully"
    
    return False, "Failed to pause membership"

async def resume_membership_by_id(user_id: str, club_id: str) -> Tuple[bool, str]:
    """Resume a paused membership"""
    membership_collection = get_membership_collection()
    
    # Find the paused membership
    membership = await membership_collection.find_one({
        "user_id": user_id,
        "club_id": club_id,
        "subscription_status": "paused"
    })
    
    if not membership:
        return False, "Paused membership not found"
    
    # Update membership status
    now = datetime.utcnow()
    result = await membership_collection.update_one(
        {"_id": membership["_id"]},
        {
            "$set": {
                "subscription_status": "active",
                "updated_at": now,
                "resumed_at": now
            }
        }
    )
    
    if result.modified_count > 0:
        return True, "Membership resumed successfully"
    
    return False, "Failed to resume membership" 

def map_membership_status_to_past_status(membership: dict, now: datetime) -> str:
    """Map database membership status to past membership API status"""
    subscription_status = membership.get("subscription_status", "")
    is_trial = membership.get("is_trial_membership", False)
    expires_date = membership.get("expires_date")
    
    # Check if it's a manually cancelled membership
    if subscription_status == "cancelled":
        if is_trial:
            return "trial_expired"  # Cancelled trials are shown as expired
        else:
            return "canceled"  # Paid memberships that were cancelled
    
    # Check if it's naturally expired
    if expires_date and expires_date < now:
        if is_trial:
            return "trial_expired"
        else:
            return "expired"
    
    # Fallback mapping
    if subscription_status in ["expired"]:
        return "trial_expired" if is_trial else "expired"
    
    # Default for any other past membership
    return "trial_expired" if is_trial else "expired"

def format_membership_price(price: float, pricing_plan: str) -> Optional[str]:
    """Format membership price for display"""
    if price <= 0:
        return None  # Trial memberships
    
    # Format price with currency and period
    if pricing_plan == "daily":
        return f"${price:.2f}/day"
    elif pricing_plan == "weekly":
        return f"${price:.2f}/week"
    elif pricing_plan == "monthly":
        return f"${price:.2f}/month"
    elif pricing_plan == "quarterly":
        return f"${price:.2f}/quarter"
    elif pricing_plan == "yearly":
        return f"${price:.2f}/year"
    elif pricing_plan == "lifetime":
        return f"${price:.2f} (lifetime)"
    else:
        return f"${price:.2f}"

async def get_past_memberships(user_id: str) -> PastMembershipsResponse:
    """Get all past (ended/cancelled) memberships for a user"""
    membership_collection = get_membership_collection()
    club_collection = get_club_collection()
    user_collection = get_user_collection()
    
    now = datetime.utcnow()
    
    # Get all non-active memberships or expired memberships
    past_memberships_query = {
        "user_id": user_id,
        "$or": [
            {"subscription_status": {"$in": ["cancelled", "expired"]}},
            {
                "subscription_status": {"$in": ["active", "trial"]},
                "expires_date": {"$lt": now}
            }
        ]
    }
    
    memberships = await membership_collection.find(past_memberships_query).to_list(None)
    
    past_memberships = []
    trial_count = 0
    paid_count = 0
    canceled_count = 0
    expired_count = 0
    
    for membership in memberships:
        try:
            # Get club details
            club_object_id = ObjectId(membership["club_id"])
            club = await club_collection.find_one({"_id": club_object_id})
            
            if not club:
                continue  # Skip if club no longer exists
            
            # Get captain details
            captain_object_id = ObjectId(club["captain_id"])
            captain = await user_collection.find_one({"_id": captain_object_id})
            
            captain_name = captain.get("full_name", "Unknown Captain") if captain else "Unknown Captain"
            captain_image_url = captain.get("avatar_url") if captain else None
            
            # Determine membership type and status
            is_trial = membership.get("is_trial_membership", False)
            membership_type = "trial" if is_trial else "paid"
            
            # Map status
            status = map_membership_status_to_past_status(membership, now)
            
            # Get pricing information
            price_display = None
            if not is_trial:
                # Find the pricing from club's pricing plans
                pricing_plan = membership["pricing_plan"]
                for plan in club.get("pricing_plans", []):
                    if plan["plan"] == pricing_plan:
                        price_display = format_membership_price(plan["price"], pricing_plan)
                        break
            
            # Determine end date
            end_date = membership.get("cancelled_at") or membership.get("expires_date") or membership.get("updated_at")
            if not end_date:
                end_date = membership.get("created_at")  # Fallback
            
            # Count by type and status
            if is_trial:
                trial_count += 1
            else:
                paid_count += 1
            
            if status == "canceled":
                canceled_count += 1
            else:
                expired_count += 1
            
            past_membership = PastMembershipDetails(
                club_id=membership["club_id"],
                club_name=club["name"],
                club_logo_url=club.get("logo_url"),
                captain_name=captain_name,
                captain_image_url=captain_image_url,
                membership_type=membership_type,
                price=price_display,
                start_date=membership["joined_date"],
                end_date=end_date,
                status=status
            )
            
            past_memberships.append(past_membership)
            
        except Exception as e:
            print(f"Error processing past membership {membership.get('_id')}: {e}")
            continue
    
    # Sort by end date (most recent first)
    past_memberships.sort(key=lambda x: x.end_date, reverse=True)
    
    return PastMembershipsResponse(
        past_memberships=past_memberships,
        total_count=len(past_memberships),
        trial_count=trial_count,
        paid_count=paid_count,
        canceled_count=canceled_count,
        expired_count=expired_count
    )

async def get_membership_history_summary(user_id: str) -> MembershipHistorySummary:
    """Get comprehensive membership history summary"""
    membership_collection = get_membership_collection()
    
    # Get all memberships (past and present)
    all_memberships = await membership_collection.find({"user_id": user_id}).to_list(None)
    
    # Get ongoing memberships
    ongoing_memberships = await get_ongoing_memberships(user_id)
    ongoing_count = ongoing_memberships.total_count
    
    # Calculate statistics
    past_count = 0
    unique_clubs = set()
    total_spent = 0.0
    club_frequency = {}
    most_recent_activity = None
    
    for membership in all_memberships:
        club_id = membership["club_id"]
        unique_clubs.add(club_id)
        
        # Count club frequency for favorite club
        club_frequency[club_id] = club_frequency.get(club_id, 0) + 1
        
        # Track most recent activity
        updated_at = membership.get("updated_at", membership.get("created_at"))
        if not most_recent_activity or updated_at > most_recent_activity:
            most_recent_activity = updated_at
        
        # Calculate spending (only for paid memberships)
        amount_paid = membership.get("amount_paid", 0.0)
        if amount_paid > 0:
            total_spent += amount_paid
        
        # Count past memberships
        now = datetime.utcnow()
        subscription_status = membership.get("subscription_status", "")
        expires_date = membership.get("expires_date")
        
        is_past = (
            subscription_status in ["cancelled", "expired"] or
            (expires_date and expires_date < now)
        )
        
        if is_past:
            past_count += 1
    
    # Determine favorite club (most frequently joined)
    favorite_club = None
    if club_frequency:
        favorite_club_id = max(club_frequency, key=club_frequency.get)
        # Get club name
        try:
            club_collection = get_club_collection()
            club = await club_collection.find_one({"_id": ObjectId(favorite_club_id)})
            favorite_club = club.get("name") if club else None
        except Exception:
            pass
    
    return MembershipHistorySummary(
        total_past_memberships=past_count,
        total_ongoing_memberships=ongoing_count,
        clubs_tried=len(unique_clubs),
        total_spent=round(total_spent, 2),
        favorite_club=favorite_club,
        most_recent_activity=most_recent_activity
    )

async def can_rejoin_club(user_id: str, club_id: str) -> Tuple[bool, str]:
    """Check if user can rejoin a club they previously left"""
    # Check if user currently has an active membership
    membership_collection = get_membership_collection()
    
    active_membership = await membership_collection.find_one({
        "user_id": user_id,
        "club_id": club_id,
        "subscription_status": {"$in": ["active", "trial", "pending"]}
    })
    
    if active_membership:
        return False, "You are already a member of this club"
    
    # Check if club still exists and is active
    club_collection = get_club_collection()
    try:
        club_object_id = ObjectId(club_id)
        club = await club_collection.find_one({"_id": club_object_id})
        
        if not club:
            return False, "Club no longer exists"
        
        if not club.get("is_active", True):
            return False, "Club is no longer accepting new members"
        
        # Check if user is the captain (captains can't join their own clubs)
        if club["captain_id"] == user_id:
            return False, "Captains cannot join their own clubs"
        
        return True, "You can rejoin this club"
        
    except Exception:
        return False, "Invalid club ID"

async def get_rejoinable_clubs(user_id: str) -> List[str]:
    """Get list of club IDs that user can rejoin"""
    past_memberships = await get_past_memberships(user_id)
    rejoinable_clubs = []
    
    for membership in past_memberships.past_memberships:
        can_rejoin, _ = await can_rejoin_club(user_id, membership.club_id)
        if can_rejoin:
            rejoinable_clubs.append(membership.club_id)
    
    return rejoinable_clubs

async def update_trial_club_statistics(user_id: str, user_collection, club_object_id):
    """
    Update trial club statistics in users table
    
    Args:
        user_id: User ID
        user_collection: User collection reference
        club_object_id: Club ObjectId
    """
    try:
        from bson import ObjectId
        from datetime import datetime, timezone
        
        # Get current user data
        user_object_id = ObjectId(user_id)
        user = await user_collection.find_one({"_id": user_object_id})
        
        if not user:
            logger.error(f"User not found for trial statistics update: {user_id}")
            return
        
        # Get user's trial period dates
        plan_start_date = user.get("plan_start_date")
        plan_end_date = user.get("plan_end_date")
        
        if not plan_start_date or not plan_end_date:
            logger.warning(f"User {user_id} has no plan dates for trial statistics")
            return
        
        # Ensure dates are timezone-aware
        if plan_start_date.tzinfo is None:
            plan_start_date = plan_start_date.replace(tzinfo=timezone.utc)
        if plan_end_date.tzinfo is None:
            plan_end_date = plan_end_date.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        
        # Check if user is still in trial period
        if now < plan_start_date or now > plan_end_date:
            logger.info(f"User {user_id} is not in trial period, skipping trial statistics update")
            return
        
        # Get all clubs joined during trial period
        clubs_joined = user.get("clubs_joined", [])
        trial_clubs_joined = []
        
        for club_data in clubs_joined:
            club_join_date = club_data.get("join_date")
            if club_join_date:
                # Ensure join_date is timezone-aware
                if club_join_date.tzinfo is None:
                    club_join_date = club_join_date.replace(tzinfo=timezone.utc)
                
                # Check if club was joined during trial period
                if (club_join_date >= plan_start_date and 
                    club_join_date <= plan_end_date and 
                    club_data.get("membership_type") == "trial"):
                    trial_clubs_joined.append(club_data)
        
        # Calculate trial club statistics
        clubs_joined_count = len(trial_clubs_joined)
        max_clubs = 4  # Maximum trial clubs allowed
        clubs_remaining = max(0, max_clubs - clubs_joined_count)
        
        # Update user with trial club statistics
        update_data = {
            "clubs_joined_count": clubs_joined_count,
            "clubs_remaining": clubs_remaining,
            "max_clubs": max_clubs,
            "updated_at": now
        }
        
        await user_collection.update_one(
            {"_id": user_object_id},
            {"$set": update_data}
        )
        
        logger.info(f"Updated trial club statistics for user {user_id}: "
                   f"joined={clubs_joined_count}, remaining={clubs_remaining}, max={max_clubs}")
        
    except Exception as e:
        logger.error(f"Error updating trial club statistics for user {user_id}: {str(e)}") 