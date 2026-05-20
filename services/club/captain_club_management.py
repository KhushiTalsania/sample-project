"""
Captain Club Management Router

This FastAPI router provides captain club management functionality including:
1. DELETE /club/{club_id}/delete - Delete club (permanent/temporary)
2. POST /club/{club_id}/reactivate - Reactivate temporarily deleted club

Supports temporary and permanent deletion with proper Stripe integration.
"""

import os
import stripe
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import jwt
import logging

from core.database.collections import get_collections
from core.utils.response_utils import create_response
from services.club.auth import get_current_captain, get_current_user
from services.club.id_utils import is_valid_name_based_id

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your_super_secret_jwt_key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Initialize router
router = APIRouter(prefix="/club", tags=["Captain Club Management"])

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

logger = logging.getLogger(__name__)

# ========================================
# AUTHENTICATION FUNCTIONS
# ========================================

async def get_current_admin_or_captain(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    """Get current admin or captain from JWT token"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")  # sub contains the user_id
        email = payload.get("email")  # email is directly in the payload
        role = payload.get("role")
        
        logging.info(f"JWT payload decoded - user_id: {user_id}, email: {email}, role: {role}")
        
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token: missing user ID")
        
        # Check if it's an admin session
        # Admin tokens may have email in 'sub' or in 'email' field
        admin_email = email or user_id if '@' in str(user_id) else None
        
        if admin_email:
            try:
                from services.admin.db import sessions_collection
                session = await sessions_collection.find_one({"token": token, "email": admin_email})
                if session:
                    # It's an admin session
                    logging.info(f"✅ Admin session verified for: {admin_email}")
                    return {
                        "user_id": admin_email, 
                        "email": admin_email, 
                        "role": "admin", 
                        "type": "admin",
                        "is_admin": True
                    }
            except Exception as e:
                logging.warning(f"Admin session check failed: {e}")
        
        # Check if it's a captain session (from club service)
        if user_id and role == "Captain":
            # Verify the user exists and is a captain
            from services.club.db import get_user_collection
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            logging.info(f"Captain verification - user found: {user is not None}, user role: {user.get('role') if user else 'N/A'}")
            
            if user and user.get("role") == "Captain":
                return {
                    "user_id": user_id,
                    "email": user.get("email", ""),
                    "role": "Captain",
                    "type": "captain",
                    "is_admin": False
                }
        
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token or insufficient permissions")
        
    except Exception as e:
        logging.error(f"Authentication error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Authentication failed: {str(e)}")

# ========================================
# REQUEST/RESPONSE MODELS
# ========================================

class ClubDeletionRequest(BaseModel):
    """Request model for club deletion"""
    mode: str = Field(..., description="Deletion mode: 'permanent' or 'temporary'")
    reason: Optional[str] = Field(None, description="Reason for deletion")
    captain_notes: Optional[str] = Field(None, description="Captain notes")
    notify_members: bool = Field(True, description="Send notification to members")

class ClubReactivationRequest(BaseModel):
    """Request model for club reactivation"""
    reason: Optional[str] = Field(None, description="Reason for reactivation")
    captain_notes: Optional[str] = Field(None, description="Captain notes")
    notify_members: bool = Field(True, description="Send notification to members")

class StripeAction(BaseModel):
    """Model for Stripe action results"""
    action: str
    subscription_id: Optional[str] = None
    product_id: Optional[str] = None
    club_id: Optional[str] = None
    member_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    success: bool = True
    error: Optional[str] = None

class ClubDeletionResponse(BaseModel):
    """Response model for club deletion"""
    success: bool
    message: str
    club_id: str
    club_name: str
    club_name_based_id: str
    deletion_mode: str
    affected_members_count: int
    stripe_actions: List[StripeAction]
    deleted_at: str
    owner_role: str

class ClubReactivationResponse(BaseModel):
    """Response model for club reactivation"""
    success: bool
    message: str
    club_id: str
    club_name: str
    club_name_based_id: str
    affected_members_count: int
    stripe_actions: List[StripeAction]
    reactivated_at: str
    owner_role: str

# ========================================
# STRIPE INTEGRATION FUNCTIONS
# ========================================

async def pause_stripe_subscription(subscription_id: str) -> StripeAction:
    """Pause a Stripe subscription"""
    try:
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
            success=False,
            error=str(e)
        )

async def resume_stripe_subscription(subscription_id: str, remaining_days: int = 0) -> StripeAction:
    """Resume a Stripe subscription with optional trial period"""
    try:
        if remaining_days > 0:
            # Calculate trial end timestamp
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
            success=False,
            error=str(e)
        )

async def cancel_stripe_subscription(subscription_id: str) -> StripeAction:
    """Cancel a Stripe subscription"""
    try:
        stripe.Subscription.delete(subscription_id)
        
        return StripeAction(
            action="subscription_cancelled",
            subscription_id=subscription_id
        )
    except Exception as e:
        return StripeAction(
            action="subscription_cancel_failed",
            subscription_id=subscription_id,
            success=False,
            error=str(e)
        )

async def archive_stripe_product(product_id: str) -> StripeAction:
    """Archive a Stripe product"""
    try:
        stripe.Product.modify(product_id, active=False)
        
        return StripeAction(
            action="product_archived",
            product_id=product_id
        )
    except Exception as e:
        return StripeAction(
            action="product_archive_failed",
            product_id=product_id,
            success=False,
            error=str(e)
        )

async def reactivate_stripe_product(product_id: str) -> StripeAction:
    """Reactivate a Stripe product"""
    try:
        stripe.Product.modify(product_id, active=True)
        
        return StripeAction(
            action="product_reactivated",
            product_id=product_id
        )
    except Exception as e:
        return StripeAction(
            action="product_reactivate_failed",
            product_id=product_id,
            success=False,
            error=str(e)
        )

# ========================================
# USAGE STATISTICS CALCULATION
# ========================================

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
        
        # Ensure all datetimes are timezone-aware
        if join_date.tzinfo is None:
            join_date = join_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        if deletion_date.tzinfo is None:
            deletion_date = deletion_date.replace(tzinfo=timezone.utc)
        
        # Calculate days
        total_days = (end_date - join_date).days
        used_days = (deletion_date - join_date).days
        remaining_days = max(0, total_days - used_days)
        usage_percentage = (used_days / total_days * 100) if total_days > 0 else 0
        
        return {
            "total_days": total_days,
            "used_days": used_days,
            "remaining_days": remaining_days,
            "usage_percentage": round(usage_percentage, 2),
            "calculated_at": deletion_date.isoformat()
        }
    except Exception as e:
        logger.error(f"Error calculating usage stats: {e}")
        return {
            "total_days": 0,
            "used_days": 0,
            "remaining_days": 0,
            "usage_percentage": 0,
            "calculated_at": deletion_date.isoformat(),
            "error": str(e)
        }

# ========================================
# CLUB MANAGEMENT FUNCTIONS
# ========================================

async def get_club_by_name_based_id(club_name_based_id: str, captain_id: str) -> Optional[Dict[str, Any]]:
    """Get club by name_based_id and verify captain ownership"""
    try:
        club = await clubs_collection.find_one({
            "name_based_id": club_name_based_id,
            "captain_id": captain_id,
            "is_permanently_deleted": {"$ne": True}
        })
        
        if not club:
            logger.warning(f"Club {club_name_based_id} not found or not owned by captain {captain_id}")
            return None
        
        return club
    except Exception as e:
        logger.error(f"Error getting club {club_name_based_id}: {e}")
        return None

async def permanently_delete_club(club_id: str, club_name: str, captain_email: str, owner_role: str = "Captain") -> Tuple[List[str], List[StripeAction]]:
    """Permanently delete a club and all its members"""
    now = datetime.now(timezone.utc)
    affected_members = []
    stripe_actions = []
    
    try:
        # Get club details
        club = await clubs_collection.find_one({"_id": ObjectId(club_id)})
        if not club:
            raise Exception(f"Club {club_id} not found")
        
        # Handle paid members
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
                
                # Mark member as permanently deleted in club
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
                            "paid_members.$.deleted_by": captain_email
                        }
                    }
                )
                
                # Mark member as permanently deleted in user's clubs_joined
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
                            "clubs_joined.$.deleted_by": captain_email
                        }
                    }
                )
        
        # Handle trial members
        members = club.get("members", [])
        for member in members:
            member_id = member.get("user_id")
            if member_id and member_id not in affected_members:
                affected_members.append(member_id)
                
                # Mark member as permanently deleted in club
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
                            "members.$.deleted_by": captain_email
                        }
                    }
                )
                
                # Mark member as permanently deleted in user's clubs_joined
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
                            "clubs_joined.$.deleted_by": captain_email
                        }
                    }
                )
        
        # Handle moderators
        detailed_moderators = club.get("detailed_moderators", [])
        for moderator in detailed_moderators:
            moderator_id = moderator.get("user_id")
            if moderator_id:
                # Mark moderator as permanently deleted in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "detailed_moderators.user_id": moderator_id
                    },
                    {
                        "$set": {
                            "detailed_moderators.$.status": "deleted",
                            "detailed_moderators.$.is_permanently_deleted": True,
                            "detailed_moderators.$.deletion_date": now,
                            "detailed_moderators.$.deleted_by": captain_email
                        }
                    }
                )
        
        # Archive Stripe product if exists
        stripe_product_id = club.get("stripe_product_id")
        if stripe_product_id:
            action = await archive_stripe_product(stripe_product_id)
            action.club_id = club_id
            stripe_actions.append(action)
        
        # Mark club as permanently deleted
        print(f"🔍 Permanently deleting club {club_id} with owner_role: {owner_role}")
        await clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {
                "$set": {
                    "status": "deleted",
                    "is_permanently_deleted": True,
                    "deleted_at": now,
                    "deleted_by": captain_email,
                    "deleted_by_role": owner_role,
                    "deletion_reason": f"{owner_role} permanently deleted"
                }
            }
        )
        print(f"✅ Club {club_id} permanently deleted with owner_role: {owner_role}")
        
        logger.info(f"Permanently deleted club {club_id} with {len(affected_members)} members")
        return affected_members, stripe_actions
        
    except Exception as e:
        logger.error(f"Error permanently deleting club {club_id}: {e}")
        raise e

async def temporarily_delete_club(club_id: str, club_name: str, captain_email: str, owner_role: str = "Captain") -> Tuple[List[str], List[StripeAction]]:
    """Temporarily delete a club and pause all memberships"""
    now = datetime.now(timezone.utc)
    affected_members = []
    stripe_actions = []
    
    try:
        # Get club details
        club = await clubs_collection.find_one({"_id": ObjectId(club_id)})
        if not club:
            raise Exception(f"Club {club_id} not found")
        
        # Handle paid members
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
                            "paid_members.$.paused_by": captain_email
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
                            "clubs_joined.$.usage_stats": usage_stats,
                            "clubs_joined.$.paused_at": now,
                            "clubs_joined.$.paused_by": captain_email
                        }
                    }
                )
        
        # Handle trial members
        members = club.get("members", [])
        for member in members:
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
                            "members.$.paused_by": captain_email
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
                            "clubs_joined.$.usage_stats": usage_stats,
                            "clubs_joined.$.paused_at": now,
                            "clubs_joined.$.paused_by": captain_email
                        }
                    }
                )
        
        # Handle moderators
        detailed_moderators = club.get("detailed_moderators", [])
        for moderator in detailed_moderators:
            moderator_id = moderator.get("user_id")
            if moderator_id:
                # Update moderator status in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "detailed_moderators.user_id": moderator_id
                    },
                    {
                        "$set": {
                            "detailed_moderators.$.status": "inactive",
                            "detailed_moderators.$.is_temporarily_deleted": True,
                            "detailed_moderators.$.deletion_date": now,
                            "detailed_moderators.$.paused_at": now,
                            "detailed_moderators.$.paused_by": captain_email
                        }
                    }
                )
        
        # Mark club as temporarily deleted
        print(f"🔍 Temporarily deleting club {club_id} with owner_role: {owner_role}")
        await clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {
                "$set": {
                    "status": "inactive",
                    "is_temporarily_deleted": True,
                    "deleted_at": now,
                    "deleted_by": captain_email,
                    "deleted_by_role": owner_role,
                    "deletion_reason": f"{owner_role} temporarily deleted"
                }
            }
        )
        print(f"✅ Club {club_id} temporarily deleted with owner_role: {owner_role}")
        
        logger.info(f"Temporarily deleted club {club_id} with {len(affected_members)} members")
        return affected_members, stripe_actions
        
    except Exception as e:
        logger.error(f"Error temporarily deleting club {club_id}: {e}")
        raise e

async def reactivate_club(club_id: str, club_name: str, captain_email: str, owner_role: str = "Captain") -> Tuple[List[str], List[StripeAction]]:
    """Reactivate a temporarily deleted club and resume all memberships"""
    now = datetime.now(timezone.utc)
    affected_members = []
    stripe_actions = []
    
    try:
        # Get club details
        club = await clubs_collection.find_one({"_id": ObjectId(club_id)})
        if not club:
            raise Exception(f"Club {club_id} not found")
        
        # Handle paid members
        paid_members = club.get("paid_members", [])
        for member in paid_members:
            member_id = member.get("user_id")
            if member_id:
                affected_members.append(member_id)
                
                # Get usage stats for remaining days
                usage_stats = member.get("usage_stats", {})
                remaining_days = usage_stats.get("remaining_days", 0)
                
                # Resume subscription if exists
                subscription_id = member.get("subscription_id")
                if subscription_id:
                    action = await resume_stripe_subscription(subscription_id, remaining_days)
                    action.member_id = member_id
                    action.club_id = club_id
                    stripe_actions.append(action)
                
                # Calculate new end date with remaining days
                new_end_date = now + timedelta(days=remaining_days) if remaining_days > 0 else member.get("end_date")
                
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
                            "paid_members.$.reactivated_at": now,
                            "paid_members.$.reactivated_by": captain_email
                        },
                        "$unset": {
                            "paid_members.$.deletion_date": "",
                            "paid_members.$.usage_stats": "",
                            "paid_members.$.paused_at": "",
                            "paid_members.$.paused_by": ""
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
                            "clubs_joined.$.reactivated_at": now,
                            "clubs_joined.$.reactivated_by": captain_email
                        },
                        "$unset": {
                            "clubs_joined.$.deletion_date": "",
                            "clubs_joined.$.usage_stats": "",
                            "clubs_joined.$.paused_at": "",
                            "clubs_joined.$.paused_by": ""
                        }
                    }
                )
        
        # Handle trial members
        members = club.get("members", [])
        for member in members:
            member_id = member.get("user_id")
            if member_id and member_id not in affected_members:
                affected_members.append(member_id)
                
                # Get usage stats for remaining days
                usage_stats = member.get("usage_stats", {})
                remaining_days = usage_stats.get("remaining_days", 0)
                
                # Calculate new end date with remaining days
                new_end_date = now + timedelta(days=remaining_days) if remaining_days > 0 else member.get("end_date")
                
                # Update member status in club
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
                            "members.$.reactivated_at": now,
                            "members.$.reactivated_by": captain_email
                        },
                        "$unset": {
                            "members.$.deletion_date": "",
                            "members.$.usage_stats": "",
                            "members.$.paused_at": "",
                            "members.$.paused_by": ""
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
                            "clubs_joined.$.reactivated_at": now,
                            "clubs_joined.$.reactivated_by": captain_email
                        },
                        "$unset": {
                            "clubs_joined.$.deletion_date": "",
                            "clubs_joined.$.usage_stats": "",
                            "clubs_joined.$.paused_at": "",
                            "clubs_joined.$.paused_by": ""
                        }
                    }
                )
        
        # Handle moderators
        detailed_moderators = club.get("detailed_moderators", [])
        for moderator in detailed_moderators:
            moderator_id = moderator.get("user_id")
            if moderator_id:
                # Update moderator status in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "detailed_moderators.user_id": moderator_id
                    },
                    {
                        "$set": {
                            "detailed_moderators.$.status": "active",
                            "detailed_moderators.$.is_temporarily_deleted": False,
                            "detailed_moderators.$.reactivated_at": now,
                            "detailed_moderators.$.reactivated_by": captain_email
                        },
                        "$unset": {
                            "detailed_moderators.$.deletion_date": "",
                            "detailed_moderators.$.paused_at": "",
                            "detailed_moderators.$.paused_by": ""
                        }
                    }
                )
        
        # Reactivate Stripe product if exists
        stripe_product_id = club.get("stripe_product_id")
        if stripe_product_id:
            action = await reactivate_stripe_product(stripe_product_id)
            action.club_id = club_id
            stripe_actions.append(action)
        
        # Mark club as active
        print(f"🔍 Reactivating club {club_id} with owner_role: {owner_role}")
        await clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {
                "$set": {
                    "status": "approved",
                    "is_temporarily_deleted": False,
                    "reactivated_at": now,
                    "reactivated_by": captain_email,
                    "reactivated_by_role": owner_role
                },
                "$unset": {
                    "deleted_at": "",
                    "deleted_by": "",
                    "deleted_by_role": "",
                    "deletion_reason": ""
                }
            }
        )
        print(f"✅ Club {club_id} reactivated with owner_role: {owner_role}")
        
        logger.info(f"Reactivated club {club_id} with {len(affected_members)} members")
        return affected_members, stripe_actions
        
    except Exception as e:
        logger.error(f"Error reactivating club {club_id}: {e}")
        raise e

# ========================================
# API ENDPOINTS
# ========================================

@router.delete("/{club_id}/delete", response_model=ClubDeletionResponse)
async def delete_club(
    club_id: str,
    request: ClubDeletionRequest,
    current_user: dict = Depends(get_current_admin_or_captain)
):
    """
    Delete a club (permanent or temporary)
    
    **Permanent Deletion:**
    - Club is marked as deleted permanently
    - All members are marked as deleted (no refunds)
    - Stripe subscriptions are cancelled
    - Stripe product is archived
    
    **Temporary Deletion:**
    - Club becomes inactive
    - All memberships are paused
    - Usage stats are calculated and stored
    - Stripe subscriptions are paused
    - Members' remaining days are preserved
    """
    try:
        user_id = current_user["user_id"]
        user_email = current_user["email"]
        is_admin = current_user.get("is_admin", False)
        
        # Validate club_id (support both ObjectId and name_based_id)
        if is_valid_name_based_id(club_id):
            # It's a name_based_id
            if is_admin:
                # Admin can access any club
                club = await clubs_collection.find_one({
                    "name_based_id": club_id,
                    "is_permanently_deleted": {"$ne": True}
                })
            else:
                # Captain can only access their own clubs
                club = await get_club_by_name_based_id(club_id, user_id)
            
            if not club:
                error_msg = f"Club '{club_id}' not found" if is_admin else f"Club '{club_id}' not found or not owned by this captain"
                raise HTTPException(
                    status_code=404,
                    detail=error_msg
                )
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            club_name_based_id = club.get("name_based_id", "")
        else:
            # It's an ObjectId
            if is_admin:
                # Admin can access any club
                club = await clubs_collection.find_one({
                    "_id": ObjectId(club_id),
                    "is_permanently_deleted": {"$ne": True}
                })
            else:
                # Captain can only access their own clubs
                club = await clubs_collection.find_one({
                    "_id": ObjectId(club_id),
                    "captain_id": user_id,
                    "is_permanently_deleted": {"$ne": True}
                })
            
            if not club:
                error_msg = f"Club '{club_id}' not found" if is_admin else f"Club '{club_id}' not found or not owned by this captain"
                raise HTTPException(
                    status_code=404,
                    detail=error_msg
                )
            club_name = club.get("name", "Unknown")
            club_name_based_id = club.get("name_based_id", "")
        
        # Validate deletion mode
        if request.mode not in ["permanent", "temporary"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid deletion mode. Must be 'permanent' or 'temporary'"
            )
        
        # Check if club is already deleted
        if club.get("is_permanently_deleted"):
            raise HTTPException(
                status_code=400,
                detail="Club is already permanently deleted"
            )
        
        if club.get("is_temporarily_deleted") and request.mode == "temporary":
            raise HTTPException(
                status_code=400,
                detail="Club is already temporarily deleted"
            )
        
        # Perform deletion based on mode
        owner_role = "Admin" if is_admin else "Captain"
        print(f"🔍 Delete operation - is_admin: {is_admin}, owner_role: {owner_role}")
        if request.mode == "permanent":
            affected_members, stripe_actions = await permanently_delete_club(
                club_id, club_name, user_email, owner_role
            )
        else:  # temporary
            affected_members, stripe_actions = await temporarily_delete_club(
                club_id, club_name, user_email, owner_role
            )
        
        # Send club status change notification to all club members
        try:
            from services.notifications.notification_service import (
                send_notification_to_users,
                get_club_members,
                filter_users_by_notification_preference,
                get_collections,
            )
            
            if club_name_based_id:
                # Get all club members
                all_club_members = await get_club_members(club_name_based_id)
                
                if all_club_members:
                    # Filter by club status alerts
                    enabled_user_ids = await filter_users_by_notification_preference(
                        all_club_members,
                        "club_status_alerts"
                    )
                    enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]
                    
                    # Look up users with active tokens
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
                    
                    # Build DB and push recipient lists
                    db_user_ids = [uid for uid in all_club_members if uid]
                    push_user_ids = [
                        uid for uid in users_with_tokens if uid in enabled_user_ids
                    ]
                    
                    if db_user_ids:
                        # Prepare notification content
                        deletion_text = "permanently deleted" if request.mode == "permanent" else "temporarily deactivated"
                        title = f"Club {deletion_text.title()}!"
                        body = f"Your club has been {deletion_text} by {owner_role}"
                        
                        notification_data = {
                            "club_id": club_name_based_id,
                            "club_name": club_name,
                            "new_status": "deleted" if request.mode == "permanent" else "inactive",
                            "deletion_mode": request.mode,
                            "changed_by": user_email,
                            "changed_by_role": owner_role,
                            "reason": request.reason
                        }
                        
                        notification_result = await send_notification_to_users(
                            user_ids=push_user_ids,
                            title=title,
                            body=body,
                            notification_type="club_status_change",
                            data=notification_data,
                            click_action=f"club/{club_name_based_id}",
                            priority="high",
                            all_user_ids=db_user_ids,
                        )
                        print(
                            f"✅ Club deletion notification stored for club {club_name_based_id}: {notification_result}"
                        )
                    else:
                        print(f"ℹ️ No eligible club members found for club {club_name_based_id}")
                else:
                    print(f"ℹ️ No club members found for club {club_name_based_id}")
                    
        except Exception as e:
            print(f"⚠️ Failed to send club deletion notification: {e}")
        
        # Log the action
        await audit_logs_collection.insert_one({
            "action": f"club_{request.mode}_deletion",
            "performed_by": user_email,
            "performed_by_type": "admin" if is_admin else "captain",
            "owner_role": "Admin" if is_admin else "Captain",
            "target_id": club_id,
            "target_type": "club",
            "details": {
                "club_name": club_name,
                "club_name_based_id": club_name_based_id,
                "deletion_mode": request.mode,
                "reason": request.reason,
                "captain_notes": request.captain_notes,
                "affected_members_count": len(affected_members),
                "stripe_actions": [action.dict() for action in stripe_actions],
                "owner_role": "Admin" if is_admin else "Captain"
            },
            "timestamp": datetime.now(timezone.utc)
        })
        
        return ClubDeletionResponse(
            success=True,
            message=f"Club '{club_name}' {request.mode}ly deleted successfully",
            club_id=club_id,
            club_name=club_name,
            club_name_based_id=club_name_based_id,
            deletion_mode=request.mode,
            affected_members_count=len(affected_members),
            stripe_actions=stripe_actions,
            deleted_at=datetime.now(timezone.utc).isoformat(),
            owner_role="Admin" if is_admin else "Captain"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting club {club_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting club: {str(e)}"
        )

@router.post("/{club_id}/reactivate", response_model=ClubReactivationResponse)
async def reactivate_club_endpoint(
    club_id: str,
    request: ClubReactivationRequest,
    current_user: dict = Depends(get_current_admin_or_captain)
):
    """
    Reactivate a temporarily deleted club
    
    **Reactivation Process:**
    - Club becomes active again
    - All paused memberships are resumed
    - Remaining days are applied to next billing cycle
    - Stripe subscriptions are unpaused
    - Stripe product is reactivated
    """
    try:
        user_id = current_user["user_id"]
        user_email = current_user["email"]
        is_admin = current_user.get("is_admin", False)
        
        # Validate club_id (support both ObjectId and name_based_id)
        if is_valid_name_based_id(club_id):
            # It's a name_based_id
            if is_admin:
                # Admin can access any club
                club = await clubs_collection.find_one({
                    "name_based_id": club_id,
                    "is_permanently_deleted": {"$ne": True}
                })
            else:
                # Captain can only access their own clubs
                club = await get_club_by_name_based_id(club_id, user_id)
            
            if not club:
                error_msg = f"Club '{club_id}' not found" if is_admin else f"Club '{club_id}' not found or not owned by this captain"
                raise HTTPException(
                    status_code=404,
                    detail=error_msg
                )
            club_id = str(club["_id"])
            club_name = club.get("name", "Unknown")
            club_name_based_id = club.get("name_based_id", "")
        else:
            # It's an ObjectId
            if is_admin:
                # Admin can access any club
                club = await clubs_collection.find_one({
                    "_id": ObjectId(club_id),
                    "is_permanently_deleted": {"$ne": True}
                })
            else:
                # Captain can only access their own clubs
                club = await clubs_collection.find_one({
                    "_id": ObjectId(club_id),
                    "captain_id": user_id,
                    "is_permanently_deleted": {"$ne": True}
                })
            
            if not club:
                error_msg = f"Club '{club_id}' not found" if is_admin else f"Club '{club_id}' not found or not owned by this captain"
                raise HTTPException(
                    status_code=404,
                    detail=error_msg
                )
            club_name = club.get("name", "Unknown")
            club_name_based_id = club.get("name_based_id", "")
        
        # Check if club is temporarily deleted
        if not club.get("is_temporarily_deleted"):
            raise HTTPException(
                status_code=400,
                detail="Club is not temporarily deleted. Only temporarily deleted clubs can be reactivated."
            )
        
        # Perform reactivation
        owner_role = "Admin" if is_admin else "Captain"
        print(f"🔍 Reactivate operation - is_admin: {is_admin}, owner_role: {owner_role}")
        affected_members, stripe_actions = await reactivate_club(
            club_id, club_name, user_email, owner_role
        )
        
        # Send club reactivation notification to all club members
        try:
            from services.notifications.notification_service import (
                send_notification_to_users,
                get_club_members,
                filter_users_by_notification_preference,
                get_collections,
            )
            
            if club_name_based_id:
                # Get all club members
                all_club_members = await get_club_members(club_name_based_id)
                
                if all_club_members:
                    # Filter by club status alerts
                    enabled_user_ids = await filter_users_by_notification_preference(
                        all_club_members,
                        "club_status_alerts"
                    )
                    enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]
                    
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
                    
                    db_user_ids = [uid for uid in all_club_members if uid]
                    push_user_ids = [
                        uid for uid in users_with_tokens if uid in enabled_user_ids
                    ]
                    
                    if db_user_ids:
                        # Prepare notification content
                        title = f"Club Reactivated!"
                        body = f"Your club has been reactivated by {owner_role}"
                        
                        notification_data = {
                            "club_id": club_name_based_id,
                            "club_name": club_name,
                            "new_status": "active",
                            "previous_status": "inactive",
                            "changed_by": user_email,
                            "changed_by_role": owner_role,
                            "reason": request.reason
                        }
                        
                        notification_result = await send_notification_to_users(
                            user_ids=push_user_ids,
                            title=title,
                            body=body,
                            notification_type="club_status_change",
                            data=notification_data,
                            click_action=f"club/{club_name_based_id}",
                            priority="high",
                            all_user_ids=db_user_ids,
                        )
                        print(
                            f"✅ Club reactivation notification stored for club {club_name_based_id}: {notification_result}"
                        )
                    else:
                        print(f"ℹ️ No eligible club members found for club {club_name_based_id}")
                else:
                    print(f"ℹ️ No club members found for club {club_name_based_id}")
                    
        except Exception as e:
            print(f"⚠️ Failed to send club reactivation notification: {e}")
        
        # Log the action
        await audit_logs_collection.insert_one({
            "action": "club_reactivation",
            "performed_by": user_email,
            "performed_by_type": "admin" if is_admin else "captain",
            "owner_role": "Admin" if is_admin else "Captain",
            "target_id": club_id,
            "target_type": "club",
            "details": {
                "club_name": club_name,
                "club_name_based_id": club_name_based_id,
                "reason": request.reason,
                "captain_notes": request.captain_notes,
                "affected_members_count": len(affected_members),
                "stripe_actions": [action.dict() for action in stripe_actions],
                "owner_role": "Admin" if is_admin else "Captain"
            },
            "timestamp": datetime.now(timezone.utc)
        })
        
        return ClubReactivationResponse(
            success=True,
            message=f"Club '{club_name}' reactivated successfully",
            club_id=club_id,
            club_name=club_name,
            club_name_based_id=club_name_based_id,
            affected_members_count=len(affected_members),
            stripe_actions=stripe_actions,
            reactivated_at=datetime.now(timezone.utc).isoformat(),
            owner_role="Admin" if is_admin else "Captain"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reactivating club {club_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error reactivating club: {str(e)}"
        )
