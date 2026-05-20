"""
Admin User Control Router

This FastAPI router provides comprehensive admin user control functionality including:
1. DELETE /admin/user/{user_id}/delete - Delete users (permanent/temporary)
2. POST /admin/user/{user_id}/reactivate - Reactivate temporarily deleted users
3. CRON job logic for automatic permanent deletion after 60 days

Supports all user roles: Member, Captain, Moderator
Handles Stripe subscription management and proper database flag management.
"""

import os
import stripe
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import jwt

from core.database.collections import get_collections

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# JWT Configuration (matching admin routes)
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Initialize router
router = APIRouter(prefix="/admin", tags=["Admin User Control"])

# Security scheme
security = HTTPBearer()

# Initialize collections
collections = get_collections()
users_collection = collections.get_users_collection()
clubs_collection = collections.get_clubs_collection()
club_memberships_collection = collections.get_club_memberships_collection()
club_payments_collection = collections.get_club_payments_collection()
payments_collection = collections.get_payments_collection()
audit_logs_collection = collections.get_audit_logs_collection()
admins_collection = collections.get_admins_collection()
sessions_collection = collections.get_admin_sessions_collection()

# ========================================
# ADMIN AUTHENTICATION
# ========================================

async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current admin from JWT token (matching existing admin auth system)"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Verify the session exists
        session = await sessions_collection.find_one({"token": token, "email": email})
        if not session:
            raise HTTPException(status_code=401, detail="Session invalidated or expired")
        
        # Get admin data
        admin = await admins_collection.find_one({"email": email})
        if not admin:
            raise HTTPException(status_code=401, detail="Admin not found")
        
        return {
            "email": admin.get("email"),
            "name": admin.get("name", "Admin"),
            "avatar_url": admin.get("avatar_url"),
            "role": admin.get("role", "Admin")
        }
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        print(f"Error in get_current_admin: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")

# ========================================
# REQUEST/RESPONSE MODELS
# ========================================

class UserDeletionRequest(BaseModel):
    """Request model for user deletion"""
    mode: str = Field(..., description="Deletion mode: 'permanent' or 'temporary'")
    reason: Optional[str] = Field(None, description="Reason for deletion")
    admin_notes: Optional[str] = Field(None, description="Admin notes")
    notify_user: bool = Field(True, description="Send notification email to user")

class UserReactivationRequest(BaseModel):
    """Request model for user reactivation"""
    reason: Optional[str] = Field(None, description="Reason for reactivation")
    admin_notes: Optional[str] = Field(None, description="Admin notes")
    notify_user: bool = Field(True, description="Send notification email to user")

class StripeAction(BaseModel):
    """Model for Stripe actions performed"""
    action: str
    subscription_id: Optional[str] = None
    product_id: Optional[str] = None
    member_id: Optional[str] = None
    club_id: Optional[str] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class UserDeletionResponse(BaseModel):
    """Response model for user deletion"""
    success: bool
    message: str
    user_id: str
    user_role: str
    deletion_type: str
    previous_status: str
    new_status: str
    affected_clubs: List[str] = []
    affected_members: List[str] = []
    stripe_actions: List[StripeAction] = []
    notification_sent: bool = False
    admin_email: str
    timestamp: datetime
    deletion_id: str

class UserReactivationResponse(BaseModel):
    """Response model for user reactivation"""
    success: bool
    message: str
    user_id: str
    user_role: str
    previous_status: str
    new_status: str
    affected_clubs: List[str] = []
    affected_members: List[str] = []
    stripe_actions: List[StripeAction] = []
    notification_sent: bool = False
    admin_email: str
    timestamp: datetime
    reactivation_id: str

# ========================================
# UTILITY FUNCTIONS
# ========================================

async def determine_user_role(user_doc: Dict) -> str:
    """Determine the primary role of a user"""
    try:
        # Check if user is a captain (has created clubs)
        captain_clubs = await clubs_collection.count_documents({"captain_id": str(user_doc["_id"])})
        if captain_clubs > 0:
            return "Captain"
        
        # Check if user is a moderator (is in moderator arrays)
        moderator_clubs = await clubs_collection.count_documents({
            "$or": [
                {"moderators": {"$elemMatch": {"user_id": str(user_doc["_id"])}}},
                {"paid_moderators": {"$elemMatch": {"user_id": str(user_doc["_id"])}}}
            ]
        })
        if moderator_clubs > 0:
            return "Moderator"
        
        # Default to Member
        return "Member"
    except Exception as e:
        print(f"Error determining user role: {e}")
        return "Member"

async def calculate_usage_stats(member_data: Dict, deletion_date: datetime) -> Dict[str, Any]:
    """Calculate usage statistics for subscription management"""
    try:
        # Get subscription dates
        join_date = member_data.get("join_date")
        end_date = member_data.get("end_date")
        
        if not join_date or not end_date:
            return {
                "total_days": 0,
                "used_days": 0,
                "remaining_days": 0,
                "usage_percentage": 0,
                "calculated_at": deletion_date.isoformat()
            }
        
        # Convert to datetime if string
        if isinstance(join_date, str):
            join_date = datetime.fromisoformat(join_date.replace('Z', '+00:00'))
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        # Ensure timezone awareness
        if join_date.tzinfo is None:
            join_date = join_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        if deletion_date.tzinfo is None:
            deletion_date = deletion_date.replace(tzinfo=timezone.utc)
        
        # Calculate days
        total_days = (end_date.date() - join_date.date()).days + 1
        used_days = (deletion_date.date() - join_date.date()).days + 1
        remaining_days = max(0, total_days - used_days)
        usage_percentage = (used_days / total_days) * 100 if total_days > 0 else 0
        
        return {
            "total_days": total_days,
            "used_days": used_days,
            "remaining_days": remaining_days,
            "usage_percentage": round(usage_percentage, 2),
            "calculated_at": deletion_date.isoformat(),
            "subscription_start_date": join_date.isoformat(),
            "subscription_end_date": end_date.isoformat(),
            "deletion_date": deletion_date.isoformat()
        }
    except Exception as e:
        print(f"Error calculating usage stats: {e}")
        return {
            "total_days": 0,
            "used_days": 0,
            "remaining_days": 0,
            "usage_percentage": 0,
            "calculated_at": deletion_date.isoformat()
        }

# ========================================
# STRIPE MANAGEMENT FUNCTIONS
# ========================================

async def pause_stripe_subscription(subscription_id: str) -> StripeAction:
    """Pause a Stripe subscription"""
    try:
        if not stripe.api_key:
            return StripeAction(
                action="subscription_pause_skipped",
                subscription_id=subscription_id,
                error="Stripe not configured"
            )
        
        # Pause subscription using keep_as_draft behavior
        stripe.Subscription.modify(
            subscription_id,
            pause_collection={
                "behavior": "keep_as_draft"
            }
        )
        
        return StripeAction(
            action="subscription_paused",
            subscription_id=subscription_id
        )
    except Exception as e:
        return StripeAction(
            action="subscription_pause_failed",
            subscription_id=subscription_id,
            error=str(e)
        )

async def resume_stripe_subscription(subscription_id: str, remaining_days: int = 0) -> StripeAction:
    """Resume a Stripe subscription with trial period for remaining days"""
    try:
        if not stripe.api_key:
            return StripeAction(
                action="subscription_resume_skipped",
                subscription_id=subscription_id,
                error="Stripe not configured"
            )
        
        if remaining_days > 0:
            # Calculate trial end timestamp (current time + remaining days)
            now = datetime.now(timezone.utc)
            trial_end_timestamp = int(now.timestamp()) + (remaining_days * 86400)
            
            # Resume subscription with trial period for remaining days
            stripe.Subscription.modify(
                subscription_id,
                pause_collection="",  # Clear the pause
                trial_end=trial_end_timestamp,  # Set trial period for remaining days
                proration_behavior="none"  # No proration for trial period
            )
            
            return StripeAction(
                action="subscription_resumed_with_trial",
                subscription_id=subscription_id,
                details={
                    "remaining_days": remaining_days,
                    "trial_end": datetime.fromtimestamp(trial_end_timestamp, tz=timezone.utc).isoformat()
                }
            )
        else:
            # No remaining days, just clear the pause
            stripe.Subscription.modify(
                subscription_id,
                pause_collection=""  # Clear the pause
            )
            
            return StripeAction(
                action="subscription_resumed",
                subscription_id=subscription_id
            )
    except Exception as e:
        return StripeAction(
            action="subscription_resume_failed",
            subscription_id=subscription_id,
            error=str(e)
        )

async def cancel_stripe_subscription(subscription_id: str) -> StripeAction:
    """Cancel a Stripe subscription"""
    try:
        if not stripe.api_key:
            return StripeAction(
                action="subscription_cancel_skipped",
                subscription_id=subscription_id,
                error="Stripe not configured"
            )
        
        # Cancel subscription at period end
        stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True
        )
        
        return StripeAction(
            action="subscription_cancelled",
            subscription_id=subscription_id
        )
    except Exception as e:
        return StripeAction(
            action="subscription_cancel_failed",
            subscription_id=subscription_id,
            error=str(e)
        )

async def archive_stripe_product(product_id: str) -> StripeAction:
    """Archive a Stripe product"""
    try:
        if not stripe.api_key:
            return StripeAction(
                action="product_archive_skipped",
                product_id=product_id,
                error="Stripe not configured"
            )
        
        # Archive the product to make it inactive
        stripe.Product.modify(
            product_id,
            active=False
        )
        
        return StripeAction(
            action="product_archived",
            product_id=product_id
        )
    except Exception as e:
        return StripeAction(
            action="product_archive_failed",
            product_id=product_id,
            error=str(e)
        )

async def reactivate_stripe_product(product_id: str) -> StripeAction:
    """Reactivate a Stripe product"""
    try:
        if not stripe.api_key:
            return StripeAction(
                action="product_reactivate_skipped",
                product_id=product_id,
                error="Stripe not configured"
            )
        
        # Reactivate the product
        stripe.Product.modify(
            product_id,
            active=True
        )
        
        return StripeAction(
            action="product_reactivated",
            product_id=product_id
        )
    except Exception as e:
        return StripeAction(
            action="product_reactivate_failed",
            product_id=product_id,
            error=str(e)
        )

# ========================================
# USER DELETION FUNCTIONS
# ========================================

async def delete_captain(user_doc: Dict, request: UserDeletionRequest, admin_email: str) -> Dict:
    """Delete a captain and handle all associated clubs and members"""
    try:
        captain_id = str(user_doc["_id"])
        affected_clubs = []
        affected_members = []
        stripe_actions = []
        
        # Find all clubs created by this captain
        clubs_cursor = clubs_collection.find({"captain_id": captain_id})
        clubs = await clubs_cursor.to_list(None)
        
        for club in clubs:
            club_id = str(club["_id"])
            affected_clubs.append(club_id)
            
            if request.mode == "permanent":
                # Permanent deletion - delete club and cancel all subscriptions
                result = await permanently_delete_captain_club(club, admin_email)
            else:
                # Temporary deletion - pause club and all subscriptions
                result = await temporarily_delete_captain_club(club, admin_email)
            
            affected_members.extend(result.get("affected_members", []))
            stripe_actions.extend(result.get("stripe_actions", []))
        
        # Update captain status
        now = datetime.now(timezone.utc)
        if request.mode == "permanent":
            await users_collection.update_one(
                {"_id": ObjectId(captain_id)},
                {
                    "$set": {
                        "status": "deleted",
                        "membership_status": "deleted",
                        "is_deleted_per_admin": True,
                        "is_deleted_temp_admin": False,
                        "deleted_at": now,
                        "deleted_by": admin_email,
                        "deletion_reason": request.reason,
                        "admin_notes": request.admin_notes
                    }
                }
            )
        else:
            await users_collection.update_one(
                {"_id": ObjectId(captain_id)},
                {
                    "$set": {
                        "status": "inactive",
                        "membership_status": "inactive",
                        "is_deleted_per_admin": False,
                        "is_deleted_temp_admin": True,
                        "deactivated_at": now,
                        "deactivated_by": admin_email,
                        "deactivation_reason": request.reason,
                        "admin_notes": request.admin_notes
                    }
                }
            )
        
        return {
            "success": True,
            "message": f"Captain {request.mode} deletion completed",
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error deleting captain: {e}")
        return {
            "success": False,
            "message": f"Failed to delete captain: {str(e)}",
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def permanently_delete_captain_club(club: Dict, admin_email: str) -> Dict:
    """Permanently delete a captain's club and cancel all subscriptions"""
    try:
        club_id = str(club["_id"])
        affected_members = []
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Cancel all Stripe products in pricing_plans
        pricing_plans = club.get("pricing_plans", [])
        for plan in pricing_plans:
            stripe_product_id = plan.get("stripe_product_id")
            if stripe_product_id:
                action = await archive_stripe_product(stripe_product_id)
                stripe_actions.append(action)
        
        # Handle paid members - cancel subscriptions and mark as deleted
        paid_members = club.get("paid_members", [])
        for member in paid_members:
            member_id = member.get("user_id")
            if member_id:
                affected_members.append(member_id)
                
                # Cancel subscription if exists
                subscription_id = member.get("subscription_id")
                if subscription_id:
                    action = await cancel_stripe_subscription(subscription_id)
                    action.member_id = member_id
                    action.club_id = club_id
                    stripe_actions.append(action)
                
                # Mark paid member as deleted in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_members.user_id": member_id
                    },
                    {
                        "$set": {
                            "paid_members.$.membership_status": "deleted",
                            "paid_members.$.is_permanently_deleted": True,
                            "paid_members.$.deletion_date": now,
                            "paid_members.$.deleted_by": admin_email
                        }
                    }
                )
                
                # Mark as deleted in user's clubs_joined array
                await users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "deleted",
                            "clubs_joined.$.is_permanently_deleted": True,
                            "clubs_joined.$.deletion_date": now,
                            "clubs_joined.$.deleted_by": admin_email
                        }
                    }
                )
        
        # Handle trial members - mark as deleted
        trial_members = club.get("members", [])
        for member in trial_members:
            member_id = member.get("user_id")
            if member_id and member_id not in affected_members:
                affected_members.append(member_id)
                
                # Mark trial member as deleted in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "deleted",
                            "members.$.is_permanently_deleted": True,
                            "members.$.deletion_date": now,
                            "members.$.deleted_by": admin_email
                        }
                    }
                )
                
                # Mark as deleted in user's clubs_joined array
                await users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "deleted",
                            "clubs_joined.$.is_permanently_deleted": True,
                            "clubs_joined.$.deletion_date": now,
                            "clubs_joined.$.deleted_by": admin_email
                        }
                    }
                )
        
        # Mark the club as deleted instead of removing it
        await clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {
                "$set": {
                    "status": "deleted",
                    "is_permanently_deleted": True,
                    "deleted_at": now,
                    "deleted_by": admin_email,
                    "deletion_reason": "Captain permanently deleted"
                }
            }
        )
        
        return {
            "success": True,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error permanently deleting captain club: {e}")
        return {
            "success": False,
            "affected_members": [],
            "stripe_actions": []
        }

async def temporarily_delete_captain_club(club: Dict, admin_email: str) -> Dict:
    """Temporarily delete a captain's club and pause all subscriptions"""
    try:
        club_id = str(club["_id"])
        affected_members = []
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Update club status to inactive
        await clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {
                "$set": {
                    "status": "inactive",
                    "is_paused_by_admin": True,
                    "paused_at": now,
                    "paused_by": admin_email,
                    "paused_reason": "Captain temporarily deleted"
                }
            }
        )
        
        # Pause all Stripe products in pricing_plans
        pricing_plans = club.get("pricing_plans", [])
        for plan in pricing_plans:
            stripe_product_id = plan.get("stripe_product_id")
            if stripe_product_id:
                action = await archive_stripe_product(stripe_product_id)
                stripe_actions.append(action)
        
        # Handle paid members - pause their subscriptions
        paid_members = club.get("paid_members", [])
        for member in paid_members:
            member_id = member.get("user_id")
            if member_id:
                affected_members.append(member_id)
                
                # Calculate usage stats
                usage_stats = await calculate_usage_stats(member, now)
                
                # Pause subscription if exists
                subscription_id = member.get("subscription_id")
                if subscription_id:
                    action = await pause_stripe_subscription(subscription_id)
                    action.member_id = member_id
                    action.club_id = club_id
                    stripe_actions.append(action)
                
                # Update member status in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_members.user_id": member_id
                    },
                    {
                        "$set": {
                            "paid_members.$.membership_status": "inactive",
                            "paid_members.$.is_temporarily_deleted": True,
                            "paid_members.$.deletion_date": now,
                            "paid_members.$.usage_stats": usage_stats,
                            "paid_members.$.paused_at": now,
                            "paid_members.$.paused_by": admin_email
                        }
                    }
                )
                
                # Update user's clubs_joined array
                await users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "inactive",
                            "clubs_joined.$.is_temporarily_deleted": True,
                            "clubs_joined.$.deletion_date": now,
                            "clubs_joined.$.usage_stats": usage_stats
                        }
                    }
                )
        
        # Handle trial members
        trial_members = club.get("members", [])
        for member in trial_members:
            member_id = member.get("user_id")
            if member_id and member_id not in affected_members:
                affected_members.append(member_id)
                
                # Calculate usage stats
                usage_stats = await calculate_usage_stats(member, now)
                
                # Update member status in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "inactive",
                            "members.$.is_temporarily_deleted": True,
                            "members.$.deletion_date": now,
                            "members.$.usage_stats": usage_stats,
                            "members.$.paused_at": now,
                            "members.$.paused_by": admin_email
                        }
                    }
                )
                
                # Update user's clubs_joined array
                await users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "inactive",
                            "clubs_joined.$.is_temporarily_deleted": True,
                            "clubs_joined.$.deletion_date": now,
                            "clubs_joined.$.usage_stats": usage_stats
                        }
                    }
                )
        
        return {
            "success": True,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error temporarily deleting captain club: {e}")
        return {
            "success": False,
            "affected_members": [],
            "stripe_actions": []
        }

async def delete_member(user_doc: Dict, request: UserDeletionRequest, admin_email: str) -> Dict:
    """Delete a member and handle all club memberships"""
    try:
        member_id = str(user_doc["_id"])
        affected_clubs = []
        affected_members = [member_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs the member has joined
        clubs_joined = user_doc.get("clubs_joined", [])
        
        for club_membership in clubs_joined:
            club_id = club_membership.get("club_id")
            if not club_id:
                continue
            
            affected_clubs.append(club_id)
            
            if request.mode == "permanent":
                # Permanent deletion - mark as deleted in all places (don't remove)
                if club_membership.get("membership_type") == "paid":
                    subscription_id = club_membership.get("subscription_id")
                    if subscription_id:
                        action = await cancel_stripe_subscription(subscription_id)
                        action.member_id = member_id
                        action.club_id = club_id
                        stripe_actions.append(action)
                    
                    # Mark as deleted in paid_members array
                    await clubs_collection.update_one(
                        {
                            "_id": ObjectId(club_id),
                            "paid_members.user_id": member_id
                        },
                        {
                            "$set": {
                                "paid_members.$.membership_status": "deleted",
                                "paid_members.$.is_permanently_deleted": True,
                                "paid_members.$.deletion_date": now,
                                "paid_members.$.deleted_by": admin_email
                            }
                        }
                    )
                else:
                    # Mark as deleted in members array
                    await clubs_collection.update_one(
                        {
                            "_id": ObjectId(club_id),
                            "members.user_id": member_id
                        },
                        {
                            "$set": {
                                "members.$.membership_status": "deleted",
                                "members.$.is_permanently_deleted": True,
                                "members.$.deletion_date": now,
                                "members.$.deleted_by": admin_email
                            }
                        }
                    )
                
                # Mark as deleted in user's clubs_joined array
                await users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "deleted",
                            "clubs_joined.$.is_permanently_deleted": True,
                            "clubs_joined.$.deletion_date": now,
                            "clubs_joined.$.deleted_by": admin_email
                        }
                    }
                )
            else:
                # Temporary deletion - pause membership
                usage_stats = await calculate_usage_stats(club_membership, now)
                
                if club_membership.get("membership_type") == "paid":
                    subscription_id = club_membership.get("subscription_id")
                    if subscription_id:
                        action = await pause_stripe_subscription(subscription_id)
                        action.member_id = member_id
                        action.club_id = club_id
                        stripe_actions.append(action)
                    
                    # Update paid member status
                    await clubs_collection.update_one(
                        {
                            "_id": ObjectId(club_id),
                            "paid_members.user_id": member_id
                        },
                        {
                            "$set": {
                                "paid_members.$.membership_status": "inactive",
                                "paid_members.$.is_temporarily_deleted": True,
                                "paid_members.$.deletion_date": now,
                                "paid_members.$.usage_stats": usage_stats
                            }
                        }
                    )
                else:
                    # Update trial member status
                    await clubs_collection.update_one(
                        {
                            "_id": ObjectId(club_id),
                            "members.user_id": member_id
                        },
                        {
                            "$set": {
                                "members.$.membership_status": "inactive",
                                "members.$.is_temporarily_deleted": True,
                                "members.$.deletion_date": now,
                                "members.$.usage_stats": usage_stats
                            }
                        }
                    )
                
        
        # Update member status
        if request.mode == "permanent":
            await users_collection.update_one(
                {"_id": ObjectId(member_id)},
                {
                    "$set": {
                        "status": "deleted",
                        "membership_status": "deleted",
                        "is_deleted_per_admin": True,
                        "is_deleted_temp_admin": False,
                        "deleted_at": now,
                        "deleted_by": admin_email,
                        "deletion_reason": request.reason,
                        "admin_notes": request.admin_notes
                    }
                }
            )
        else:
            await users_collection.update_one(
                {"_id": ObjectId(member_id)},
                {
                    "$set": {
                        "status": "inactive",
                        "membership_status": "inactive",
                        "is_deleted_per_admin": False,
                        "is_deleted_temp_admin": True,
                        "deactivated_at": now,
                        "deactivated_by": admin_email,
                        "deactivation_reason": request.reason,
                        "admin_notes": request.admin_notes
                    }
                }
            )
        
        return {
            "success": True,
            "message": f"Member {request.mode} deletion completed",
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error deleting member: {e}")
        return {
            "success": False,
            "message": f"Failed to delete member: {str(e)}",
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def delete_moderator(user_doc: Dict, request: UserDeletionRequest, admin_email: str) -> Dict:
    """Delete a moderator and handle all moderator roles"""
    try:
        moderator_id = str(user_doc["_id"])
        affected_clubs = []
        affected_members = [moderator_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs where this user is a moderator
        clubs_cursor = clubs_collection.find({
            "$or": [
                {"moderators": {"$elemMatch": {"user_id": moderator_id}}},
                {"paid_moderators": {"$elemMatch": {"user_id": moderator_id}}}
            ]
        })
        clubs = await clubs_cursor.to_list(None)
        
        for club in clubs:
            club_id = str(club["_id"])
            affected_clubs.append(club_id)
            
            if request.mode == "permanent":
                # Permanent deletion - mark moderator as deleted in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "moderators.user_id": moderator_id
                    },
                    {
                        "$set": {
                            "moderators.$.status": "deleted",
                            "moderators.$.is_permanently_deleted": True,
                            "moderators.$.deletion_date": now,
                            "moderators.$.deleted_by": admin_email
                        }
                    }
                )
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_moderators.user_id": moderator_id
                    },
                    {
                        "$set": {
                            "paid_moderators.$.status": "deleted",
                            "paid_moderators.$.is_permanently_deleted": True,
                            "paid_moderators.$.deletion_date": now,
                            "paid_moderators.$.deleted_by": admin_email
                        }
                    }
                )
            else:
                # Temporary deletion - set moderator as inactive
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "$or": [
                            {"moderators": {"$elemMatch": {"user_id": moderator_id}}},
                            {"paid_moderators": {"$elemMatch": {"user_id": moderator_id}}}
                        ]
                    },
                    {
                        "$set": {
                            "moderators.$.status": "inactive",
                            "moderators.$.deactivated_at": now,
                            "moderators.$.deactivated_by": admin_email,
                            "paid_moderators.$.status": "inactive",
                            "paid_moderators.$.deactivated_at": now,
                            "paid_moderators.$.deactivated_by": admin_email
                        }
                    }
                )
        
        # Update moderator status
        if request.mode == "permanent":
            await users_collection.update_one(
                {"_id": ObjectId(moderator_id)},
                {
                    "$set": {
                        "status": "deleted",
                        "membership_status": "deleted",
                        "is_deleted_per_admin": True,
                        "is_deleted_temp_admin": False,
                        "deleted_at": now,
                        "deleted_by": admin_email,
                        "deletion_reason": request.reason,
                        "admin_notes": request.admin_notes
                    }
                }
            )
        else:
            await users_collection.update_one(
                {"_id": ObjectId(moderator_id)},
                {
                    "$set": {
                        "status": "inactive",
                        "membership_status": "inactive",
                        "is_deleted_per_admin": False,
                        "is_deleted_temp_admin": True,
                        "deactivated_at": now,
                        "deactivated_by": admin_email,
                        "deactivation_reason": request.reason,
                        "admin_notes": request.admin_notes
                    }
                }
            )
        
        return {
            "success": True,
            "message": f"Moderator {request.mode} deletion completed",
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error deleting moderator: {e}")
        return {
            "success": False,
            "message": f"Failed to delete moderator: {str(e)}",
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

# ========================================
# USER REACTIVATION FUNCTIONS
# ========================================

async def reactivate_captain(user_doc: Dict, request: UserReactivationRequest, admin_email: str) -> Dict:
    """Reactivate a captain and resume all clubs and memberships"""
    try:
        captain_id = str(user_doc["_id"])
        affected_clubs = []
        affected_members = []
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs created by this captain
        clubs_cursor = clubs_collection.find({"captain_id": captain_id})
        clubs = await clubs_cursor.to_list(None)
        
        for club in clubs:
            club_id = str(club["_id"])
            affected_clubs.append(club_id)
            
            # Reactivate club
            result = await reactivate_captain_club(club, admin_email)
            affected_members.extend(result.get("affected_members", []))
            stripe_actions.extend(result.get("stripe_actions", []))
        
        # Update captain status
        await users_collection.update_one(
            {"_id": ObjectId(captain_id)},
            {
                "$set": {
                    "status": "active",
                    "membership_status": "active",
                    "is_deleted_per_admin": False,
                    "is_deleted_temp_admin": False,
                    "reactivated_at": now,
                    "reactivated_by": admin_email,
                    "reactivation_reason": request.reason
                }
            }
        )
        
        return {
            "success": True,
            "message": "Captain reactivation completed",
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error reactivating captain: {e}")
        return {
            "success": False,
            "message": f"Failed to reactivate captain: {str(e)}",
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def reactivate_captain_club(club: Dict, admin_email: str) -> Dict:
    """Reactivate a captain's club and resume all memberships"""
    try:
        club_id = str(club["_id"])
        affected_members = []
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Update club status to active
        await clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {
                "$set": {
                    "status": "approved",
                    "is_paused_by_admin": False,
                    "reactivated_at": now,
                    "reactivated_by": admin_email
                }
            }
        )
        
        # Reactivate all Stripe products in pricing_plans
        pricing_plans = club.get("pricing_plans", [])
        for plan in pricing_plans:
            stripe_product_id = plan.get("stripe_product_id")
            if stripe_product_id:
                action = await reactivate_stripe_product(stripe_product_id)
                stripe_actions.append(action)
        
        # Resume paid members' Stripe subscriptions with trial period for unused days
        paid_members = club.get("paid_members", [])
        for member in paid_members:
            member_id = member.get("user_id")
            if not member_id:
                continue
            
            affected_members.append(member_id)
            
            # Get usage stats and subscription ID
            usage_stats = member.get("usage_stats", {})
            unused_days = usage_stats.get("remaining_days", 0)
            subscription_id = member.get("subscription_id")
            
            # Resume Stripe subscription with trial period for unused days
            if subscription_id:
                action = await resume_stripe_subscription(subscription_id, unused_days)
                action.member_id = member_id
                action.club_id = club_id
                stripe_actions.append(action)
            
            # Calculate new end date based on unused days
            new_end_date = None
            if unused_days > 0:
                new_end_date = now + timedelta(days=unused_days)
            
            # Update member status in club
            await clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "paid_members.user_id": member_id
                },
                {
                    "$set": {
                        "paid_members.$.membership_status": "active",
                        "paid_members.$.is_temporarily_deleted": False,
                        "paid_members.$.end_date": new_end_date,
                        "paid_members.$.reactivation_date": now,
                        "paid_members.$.resumed_at": now,
                        "paid_members.$.resumed_by": admin_email
                    },
                    "$unset": {
                        "paid_members.$.deletion_date": "",
                        "paid_members.$.usage_stats": ""
                    }
                }
            )
            
            # Update user's clubs_joined array
            await users_collection.update_one(
                {
                    "_id": ObjectId(member_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "active",
                        "clubs_joined.$.is_temporarily_deleted": False,
                        "clubs_joined.$.end_date": new_end_date,
                        "clubs_joined.$.reactivation_date": now
                    },
                    "$unset": {
                        "clubs_joined.$.deletion_date": "",
                        "clubs_joined.$.usage_stats": ""
                    }
                }
            )
        
        # Resume trial members
        trial_members = club.get("members", [])
        for member in trial_members:
            member_id = member.get("user_id")
            if not member_id:
                continue
            
            if member_id not in affected_members:
                affected_members.append(member_id)
            
            # Get usage stats for trial member
            usage_stats = member.get("usage_stats", {})
            unused_days = usage_stats.get("remaining_days", 0)
            
            # Calculate new end date based on unused days
            new_end_date = None
            if unused_days > 0:
                new_end_date = now + timedelta(days=unused_days)
            
            # Update trial member status in club
            await clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "members.user_id": member_id
                },
                {
                    "$set": {
                        "members.$.membership_status": "active",
                        "members.$.is_temporarily_deleted": False,
                        "members.$.end_date": new_end_date,
                        "members.$.reactivation_date": now,
                        "members.$.resumed_at": now,
                        "members.$.resumed_by": admin_email
                    },
                    "$unset": {
                        "members.$.deletion_date": "",
                        "members.$.usage_stats": ""
                    }
                }
            )
            
            # Update user's clubs_joined array
            await users_collection.update_one(
                {
                    "_id": ObjectId(member_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "active",
                        "clubs_joined.$.is_temporarily_deleted": False,
                        "clubs_joined.$.end_date": new_end_date,
                        "clubs_joined.$.reactivation_date": now
                    },
                    "$unset": {
                        "clubs_joined.$.deletion_date": "",
                        "clubs_joined.$.usage_stats": ""
                    }
                }
            )
        
        return {
            "success": True,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error reactivating captain club: {e}")
        return {
            "success": False,
            "affected_members": [],
            "stripe_actions": []
        }

async def reactivate_member(user_doc: Dict, request: UserReactivationRequest, admin_email: str) -> Dict:
    """Reactivate a member and resume all memberships"""
    try:
        member_id = str(user_doc["_id"])
        affected_clubs = []
        affected_members = [member_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs the member has joined
        clubs_joined = user_doc.get("clubs_joined", [])
        
        for club_membership in clubs_joined:
            club_id = club_membership.get("club_id")
            if not club_id:
                continue
            
            affected_clubs.append(club_id)
            
            # Get usage stats and subscription ID
            usage_stats = club_membership.get("usage_stats", {})
            unused_days = usage_stats.get("remaining_days", 0)
            
            if club_membership.get("membership_type") == "paid":
                subscription_id = club_membership.get("subscription_id")
                if subscription_id:
                    action = await resume_stripe_subscription(subscription_id, unused_days)
                    action.member_id = member_id
                    action.club_id = club_id
                    stripe_actions.append(action)
                
                # Calculate new end date based on unused days
                new_end_date = None
                if unused_days > 0:
                    new_end_date = now + timedelta(days=unused_days)
                
                # Update paid member status in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_members.user_id": member_id
                    },
                    {
                        "$set": {
                            "paid_members.$.membership_status": "active",
                            "paid_members.$.is_temporarily_deleted": False,
                            "paid_members.$.end_date": new_end_date,
                            "paid_members.$.reactivation_date": now,
                            "paid_members.$.resumed_at": now,
                            "paid_members.$.resumed_by": admin_email
                        },
                        "$unset": {
                            "paid_members.$.deletion_date": "",
                            "paid_members.$.usage_stats": ""
                        }
                    }
                )
            else:
                # Calculate new end date based on unused days
                new_end_date = None
                if unused_days > 0:
                    new_end_date = now + timedelta(days=unused_days)
                
                # Update trial member status in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "active",
                            "members.$.is_temporarily_deleted": False,
                            "members.$.end_date": new_end_date,
                            "members.$.reactivation_date": now,
                            "members.$.resumed_at": now,
                            "members.$.resumed_by": admin_email
                        },
                        "$unset": {
                            "members.$.deletion_date": "",
                            "members.$.usage_stats": ""
                        }
                    }
                )
            
            # Update user's clubs_joined array
            new_end_date = None
            if unused_days > 0:
                new_end_date = now + timedelta(days=unused_days)
            
            await users_collection.update_one(
                {
                    "_id": ObjectId(member_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "active",
                        "clubs_joined.$.is_temporarily_deleted": False,
                        "clubs_joined.$.end_date": new_end_date,
                        "clubs_joined.$.reactivation_date": now
                    },
                    "$unset": {
                        "clubs_joined.$.deletion_date": "",
                        "clubs_joined.$.usage_stats": ""
                    }
                }
            )
            
        
        # Update member status
        await users_collection.update_one(
            {"_id": ObjectId(member_id)},
            {
                "$set": {
                    "status": "active",
                    "membership_status": "active",
                    "is_deleted_per_admin": False,
                    "is_deleted_temp_admin": False,
                    "reactivated_at": now,
                    "reactivated_by": admin_email,
                    "reactivation_reason": request.reason
                }
            }
        )
        
        return {
            "success": True,
            "message": "Member reactivation completed",
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error reactivating member: {e}")
        return {
            "success": False,
            "message": f"Failed to reactivate member: {str(e)}",
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def reactivate_moderator(user_doc: Dict, request: UserReactivationRequest, admin_email: str) -> Dict:
    """Reactivate a moderator and resume all moderator roles"""
    try:
        moderator_id = str(user_doc["_id"])
        affected_clubs = []
        affected_members = [moderator_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs where this user is a moderator
        clubs_cursor = clubs_collection.find({
            "$or": [
                {"moderators": {"$elemMatch": {"user_id": moderator_id}}},
                {"paid_moderators": {"$elemMatch": {"user_id": moderator_id}}}
            ]
        })
        clubs = await clubs_cursor.to_list(None)
        
        for club in clubs:
            club_id = str(club["_id"])
            affected_clubs.append(club_id)
            
            # Reactivate moderator role
            await clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "$or": [
                        {"moderators": {"$elemMatch": {"user_id": moderator_id}}},
                        {"paid_moderators": {"$elemMatch": {"user_id": moderator_id}}}
                    ]
                },
                {
                    "$set": {
                        "moderators.$.status": "active",
                        "moderators.$.reactivated_at": now,
                        "moderators.$.reactivated_by": admin_email,
                        "paid_moderators.$.status": "active",
                        "paid_moderators.$.reactivated_at": now,
                        "paid_moderators.$.reactivated_by": admin_email
                    }
                }
            )
        
        # Update moderator status
        await users_collection.update_one(
            {"_id": ObjectId(moderator_id)},
            {
                "$set": {
                    "status": "active",
                    "membership_status": "active",
                    "is_deleted_per_admin": False,
                    "is_deleted_temp_admin": False,
                    "reactivated_at": now,
                    "reactivated_by": admin_email,
                    "reactivation_reason": request.reason
                }
            }
        )
        
        return {
            "success": True,
            "message": "Moderator reactivation completed",
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        print(f"Error reactivating moderator: {e}")
        return {
            "success": False,
            "message": f"Failed to reactivate moderator: {str(e)}",
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

# ========================================
# CRON JOB FUNCTIONS
# ========================================

async def cleanup_inactive_captains():
    """CRON job to permanently delete captains inactive > 60 days"""
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=60)
        
        # Find captains that have been inactive for more than 60 days
        inactive_captains = await users_collection.find({
            "is_deleted_temp_admin": True,
            "deactivated_at": {"$lt": cutoff_date}
        }).to_list(None)
        
        for captain in inactive_captains:
            captain_id = str(captain["_id"])
            
            # Check if this user is actually a captain
            captain_clubs = await clubs_collection.count_documents({"captain_id": captain_id})
            if captain_clubs == 0:
                continue
            
            print(f"Auto-deleting captain {captain_id} after 60 days of inactivity")
            
            # Create permanent deletion request
            deletion_request = UserDeletionRequest(
                mode="permanent",
                reason="Automatic deletion after 60 days of temporary deletion",
                admin_notes="Auto-deleted by CRON job",
                notify_user=True
            )
            
            # Perform permanent deletion
            result = await delete_captain(captain, deletion_request, "system@admin.com")
            
            if result["success"]:
                print(f"Successfully auto-deleted captain {captain_id}")
                
                # Log the action
                await audit_logs_collection.insert_one({
                    "_id": ObjectId(),
                    "action": "AUTO_DELETE_CAPTAIN",
                    "user_id": captain_id,
                    "performed_by": "system@admin.com",
                    "timestamp": datetime.now(timezone.utc),
                    "details": {
                        "reason": "60 days inactive",
                        "affected_clubs": result.get("affected_clubs", []),
                        "affected_members": result.get("affected_members", [])
                    }
                })
            else:
                print(f"Failed to auto-delete captain {captain_id}: {result['message']}")
        
        print(f"CRON job completed. Processed {len(inactive_captains)} inactive captains")
        
    except Exception as e:
        print(f"Error in cleanup_inactive_captains CRON job: {e}")

# ========================================
# API ENDPOINTS
# ========================================

@router.post("/user/{user_id}/delete", response_model=UserDeletionResponse)
async def delete_user(
    user_id: str,
    request: UserDeletionRequest,
    admin: dict = Depends(get_current_admin)
):
    """
    Delete a user (Member, Captain, or Moderator)
    
    - **mode**: "permanent" or "temporary"
    - **permanent**: Removes user completely, cancels subscriptions, no refunds
    - **temporary**: Sets user inactive, pauses subscriptions, saves usage stats
    """
    try:
        # Validate user_id format
        try:
            ObjectId(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid user ID format")
        
        # Validate mode
        if request.mode not in ["permanent", "temporary"]:
            raise HTTPException(status_code=400, detail="Mode must be 'permanent' or 'temporary'")
        
        # Find user
        user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if user is already deleted
        if user_doc.get("is_deleted_per_admin") or user_doc.get("status") == "deleted":
            raise HTTPException(status_code=400, detail="User is already permanently deleted")
        
        # Determine user role
        user_role = await determine_user_role(user_doc)
        previous_status = user_doc.get("status", "active")
        deletion_id = str(ObjectId())
        
        # Process deletion based on user role
        if user_role == "Captain":
            result = await delete_captain(user_doc, request, admin["email"])
        elif user_role == "Member":
            result = await delete_member(user_doc, request, admin["email"])
        elif user_role == "Moderator":
            result = await delete_moderator(user_doc, request, admin["email"])
        else:
            raise HTTPException(status_code=400, detail=f"Invalid user role: {user_role}")
        
        # Extract results
        success = result.get("success", False)
        message = result.get("message", "Deletion completed")
        affected_clubs = result.get("affected_clubs", [])
        affected_members = result.get("affected_members", [])
        stripe_actions = result.get("stripe_actions", [])
        
        if not success:
            raise HTTPException(status_code=500, detail=message)
        
        # Log the deletion action
        await audit_logs_collection.insert_one({
            "_id": ObjectId(),
            "deletion_id": deletion_id,
            "action": "ADMIN_DELETE_USER",
            "user_id": user_id,
            "user_role": user_role,
            "deletion_type": request.mode,
            "previous_status": previous_status,
            "new_status": "deleted" if request.mode == "permanent" else "inactive",
            "reason": request.reason,
            "admin_notes": request.admin_notes,
            "admin_email": admin["email"],
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": [action.dict() for action in stripe_actions],
            "timestamp": datetime.now(timezone.utc)
        })
        
        return UserDeletionResponse(
            success=success,
            message=message,
            user_id=user_id,
            user_role=user_role,
            deletion_type=request.mode,
            previous_status=previous_status,
            new_status="deleted" if request.mode == "permanent" else "inactive",
            affected_clubs=affected_clubs,
            affected_members=affected_members,
            stripe_actions=stripe_actions,
            notification_sent=request.notify_user,
            admin_email=admin["email"],
            timestamp=datetime.now(timezone.utc),
            deletion_id=deletion_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in delete_user: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/user/{user_id}/reactivate", response_model=UserReactivationResponse)
async def reactivate_user(
    user_id: str,
    request: UserReactivationRequest,
    admin: dict = Depends(get_current_admin)
):
    """
    Reactivate a temporarily deleted user
    
    - Resumes Stripe subscriptions with remaining days as trial period
    - Reactivates all club memberships and moderator roles
    - Only works for temporarily deleted users
    """
    try:
        # Validate user_id format
        try:
            ObjectId(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid user ID format")
        
        # Find user
        user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if user is temporarily deleted
        if not user_doc.get("is_deleted_temp_admin"):
            raise HTTPException(status_code=400, detail="User is not temporarily deleted")
        
        # Check if user is permanently deleted
        if user_doc.get("is_deleted_per_admin"):
            raise HTTPException(status_code=400, detail="Cannot reactivate permanently deleted user")
        
        # Determine user role
        user_role = await determine_user_role(user_doc)
        previous_status = user_doc.get("status", "inactive")
        reactivation_id = str(ObjectId())
        
        # Process reactivation based on user role
        if user_role == "Captain":
            result = await reactivate_captain(user_doc, request, admin["email"])
        elif user_role == "Member":
            result = await reactivate_member(user_doc, request, admin["email"])
        elif user_role == "Moderator":
            result = await reactivate_moderator(user_doc, request, admin["email"])
        else:
            raise HTTPException(status_code=400, detail=f"Invalid user role: {user_role}")
        
        # Extract results
        success = result.get("success", False)
        message = result.get("message", "Reactivation completed")
        affected_clubs = result.get("affected_clubs", [])
        affected_members = result.get("affected_members", [])
        stripe_actions = result.get("stripe_actions", [])
        
        if not success:
            raise HTTPException(status_code=500, detail=message)
        
        # Log the reactivation action
        await audit_logs_collection.insert_one({
            "_id": ObjectId(),
            "reactivation_id": reactivation_id,
            "action": "ADMIN_REACTIVATE_USER",
            "user_id": user_id,
            "user_role": user_role,
            "previous_status": previous_status,
            "new_status": "active",
            "reason": request.reason,
            "admin_notes": request.admin_notes,
            "admin_email": admin["email"],
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": [action.dict() for action in stripe_actions],
            "timestamp": datetime.now(timezone.utc)
        })
        
        return UserReactivationResponse(
            success=success,
            message=message,
            user_id=user_id,
            user_role=user_role,
            previous_status=previous_status,
            new_status="active",
            affected_clubs=affected_clubs,
            affected_members=affected_members,
            stripe_actions=stripe_actions,
            notification_sent=request.notify_user,
            admin_email=admin["email"],
            timestamp=datetime.now(timezone.utc),
            reactivation_id=reactivation_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in reactivate_user: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/cron/cleanup-inactive-captains")
async def run_cleanup_cron(admin: dict = Depends(get_current_admin)):
    """
    Manual trigger for CRON job to cleanup inactive captains
    
    - Permanently deletes captains inactive > 60 days
    - Cascades to all their clubs and members
    - Cancels all related Stripe subscriptions
    """
    try:
        await cleanup_inactive_captains()
        return {"success": True, "message": "CRON job completed successfully"}
    except Exception as e:
        print(f"Error running cleanup CRON: {e}")
        raise HTTPException(status_code=500, detail=f"CRON job failed: {str(e)}")
