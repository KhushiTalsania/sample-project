"""
Account Deletion API Routes

This module handles account deletion requests with two options:
1. Temporary Delete (Soft Delete): membership_status becomes inactive, can reactivate
2. Permanent Delete: status becomes deleted, no reactivation possible
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import logging
import os
import stripe

from ..models import AccountDeletionRequest, AccountDeletionResponse, AccountDeletionStatusResponse, AccountReactivationResponse
from ..utils import get_current_user
from core.utils.response_utils import create_response
from core.database.collections import get_collections

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Initialize collections
collections = get_collections()
clubs_collection = collections.get_clubs_collection()

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize account deletion service when needed to avoid circular imports
def get_account_deletion_service():
    from ..account_deletion_service import AccountDeletionService
    return AccountDeletionService()

# ========================================
# CAPTAIN-SPECIFIC HELPER FUNCTIONS
# ========================================

async def is_captain(user_id: str) -> bool:
    """Check if user is a captain (has created clubs)"""
    try:
        captain_clubs = await clubs_collection.count_documents({"captain_id": str(user_id)})
        return captain_clubs > 0
    except Exception as e:
        logger.error(f"Error checking if user is captain: {e}")
        return False

async def is_moderator(user_id: str, user_email: str) -> bool:
    """Check if user is a moderator by looking for clubs where they are a moderator"""
    try:
        moderator_clubs = await clubs_collection.count_documents({
            "$or": [
                {"detailed_moderators": {"$elemMatch": {"moderator_user_id": str(user_id)}}},
                {"detailed_moderators": {"$elemMatch": {"moderator_email": user_email}}}
            ]
        })
        return moderator_clubs > 0
    except Exception as e:
        logger.error(f"Error checking if user {user_id} is moderator: {e}")
        return False

async def calculate_usage_stats(member_data: Dict, deletion_date: datetime) -> Dict[str, Any]:
    """Calculate usage statistics for subscription management"""
    try:
        join_date = member_data.get("join_date")
        end_date = member_data.get("end_date")
        
        if not join_date or not end_date:
            return {
                "total_days": 0,
                "used_days": 0,
                "remaining_days": 0,
                "usage_percentage": 0
            }
        
        # Ensure dates are timezone-aware
        if join_date.tzinfo is None:
            join_date = join_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        
        # Calculate total days (inclusive)
        total_days = (end_date - join_date).days + 1
        
        # Calculate used days up to deletion date
        if deletion_date <= join_date:
            used_days = 0
        elif deletion_date >= end_date:
            used_days = total_days
        else:
            used_days = (deletion_date.date() - join_date.date()).days + 1
        
        # Calculate remaining days
        remaining_days = max(0, total_days - used_days)
        
        # Calculate usage percentage
        usage_percentage = (used_days / total_days * 100) if total_days > 0 else 0
        
        return {
            "total_days": total_days,
            "used_days": used_days,
            "remaining_days": remaining_days,
            "usage_percentage": round(usage_percentage, 2)
        }
    except Exception as e:
        logger.error(f"Error calculating usage stats: {e}")
        return {
            "total_days": 0,
            "used_days": 0,
            "remaining_days": 0,
            "usage_percentage": 0
        }

async def archive_stripe_product(stripe_product_id: str) -> Dict[str, Any]:
    """Archive a Stripe product"""
    try:
        product = stripe.Product.modify(stripe_product_id, active=False)
        return {
            "action": "archive_product",
            "product_id": stripe_product_id,
            "success": True,
            "stripe_response": product
        }
    except Exception as e:
        logger.error(f"Error archiving Stripe product {stripe_product_id}: {e}")
        return {
            "action": "archive_product",
            "product_id": stripe_product_id,
            "success": False,
            "error": str(e)
        }

async def reactivate_stripe_product(stripe_product_id: str) -> Dict[str, Any]:
    """Reactivate a Stripe product"""
    try:
        product = stripe.Product.modify(stripe_product_id, active=True)
        return {
            "action": "reactivate_product",
            "product_id": stripe_product_id,
            "success": True,
            "stripe_response": product
        }
    except Exception as e:
        logger.error(f"Error reactivating Stripe product {stripe_product_id}: {e}")
        return {
            "action": "reactivate_product",
            "product_id": stripe_product_id,
            "success": False,
            "error": str(e)
        }

async def pause_stripe_subscription(subscription_id: str) -> Dict[str, Any]:
    """Pause a Stripe subscription"""
    try:
        if not stripe.api_key:
            logger.warning("Stripe API key not configured")
            return {
                "action": "subscription_pause_skipped",
                "subscription_id": subscription_id,
                "success": False,
                "error": "Stripe not configured"
            }
        
        logger.info(f"Pausing Stripe subscription {subscription_id}")
        
        # First, get the current subscription status
        current_subscription = stripe.Subscription.retrieve(subscription_id)
        logger.info(f"Current subscription {subscription_id} status: {current_subscription.status}, pause_collection: {current_subscription.pause_collection}")
        
        # Pause subscription using keep_as_draft behavior
        subscription = stripe.Subscription.modify(
            subscription_id,
            pause_collection={
                "behavior": "keep_as_draft"
            }
        )
        
        logger.info(f"Successfully paused subscription {subscription_id}, status: {subscription.status}, pause_collection: {subscription.pause_collection}")
        
        return {
            "action": "subscription_paused",
            "subscription_id": subscription_id,
            "success": True,
            "stripe_response": {
                "status": subscription.status,
                "pause_collection": subscription.pause_collection
            }
        }
    except Exception as e:
        logger.error(f"Error pausing Stripe subscription {subscription_id}: {e}")
        return {
            "action": "subscription_pause_failed",
            "subscription_id": subscription_id,
            "success": False,
            "error": str(e)
        }

async def resume_stripe_subscription(subscription_id: str, remaining_days: int = 0) -> Dict[str, Any]:
    """Resume a Stripe subscription with trial period for remaining days"""
    try:
        if not stripe.api_key:
            return {
                "action": "subscription_resume_skipped",
                "subscription_id": subscription_id,
                "success": False,
                "error": "Stripe not configured"
            }
        
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
            
            return {
                "action": "subscription_resumed_with_trial",
                "subscription_id": subscription_id,
                "success": True,
                "details": {
                    "remaining_days": remaining_days,
                    "trial_end": datetime.fromtimestamp(trial_end_timestamp, tz=timezone.utc).isoformat()
                }
            }
        else:
            # No remaining days, just clear the pause
            stripe.Subscription.modify(
                subscription_id,
                pause_collection=""  # Clear the pause
            )
            
            return {
                "action": "subscription_resumed",
                "subscription_id": subscription_id,
                "success": True
            }
    except Exception as e:
        return {
            "action": "subscription_resume_failed",
            "subscription_id": subscription_id,
            "success": False,
            "error": str(e)
        }

async def cancel_stripe_subscription(subscription_id: str) -> Dict[str, Any]:
    """Cancel a Stripe subscription"""
    try:
        subscription = stripe.Subscription.cancel(subscription_id)
        return {
            "action": "cancel_subscription",
            "subscription_id": subscription_id,
            "success": True,
            "stripe_response": subscription
        }
    except Exception as e:
        logger.error(f"Error canceling Stripe subscription {subscription_id}: {e}")
        return {
            "action": "cancel_subscription",
            "subscription_id": subscription_id,
            "success": False,
            "error": str(e)
        }


async def handle_captain_temporary_deletion(user_id: str, user: Dict, reason: Optional[str]) -> Dict[str, Any]:
    """Handle temporary deletion for Captain - pause clubs and members"""
    try:
        captain_id = str(user_id)
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
            
            # Update club status to inactive
            await clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {
                    "$set": {
                        "status": "inactive",
                        "is_paused_by_captain": True,
                        "paused_at": now,
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
                        action["member_id"] = member_id
                        action["club_id"] = club_id
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
                                "paid_members.$.status": "inactive",
                                "paid_members.$.is_temporarily_deleted": True,
                                "paid_members.$.deletion_date": now,
                                "paid_members.$.usage_stats": usage_stats,
                                "paid_members.$.paused_at": now,
                                "paid_members.$.paused_by": "captain_deletion"
                            }
                        }
                    )
                    
                    # Update user's clubs_joined array
                    from ..db import get_user_collection
                    users_collection = get_user_collection()
                    await users_collection.update_one(
                        {
                            "_id": ObjectId(member_id),
                            "clubs_joined.club_id": club_id
                        },
                        {
                            "$set": {
                                "clubs_joined.$.membership_status": "inactive",
                                "clubs_joined.$.status": "inactive",
                                "clubs_joined.$.is_temporarily_deleted": True,
                                "clubs_joined.$.deletion_date": now,
                                "clubs_joined.$.usage_stats": usage_stats,
                                "clubs_joined.$.paused_at": now,
                                "clubs_joined.$.paused_by": "captain_deletion"
                            }
                        }
                    )
            
            # Handle trial members - mark as inactive
            trial_members = club.get("members", [])
            for member in trial_members:
                member_id = member.get("user_id")
                if member_id and member_id not in affected_members:
                    affected_members.append(member_id)
                    
                    # Calculate usage stats
                    usage_stats = await calculate_usage_stats(member, now)
                    
                    # Update trial member status in club
                    await clubs_collection.update_one(
                        {
                            "_id": ObjectId(club_id),
                            "members.user_id": member_id
                        },
                        {
                            "$set": {
                                "members.$.membership_status": "inactive",
                                "members.$.status": "inactive",
                                "members.$.is_temporarily_deleted": True,
                                "members.$.deletion_date": now,
                                "members.$.usage_stats": usage_stats,
                                "members.$.paused_at": now,
                                "members.$.paused_by": "captain_deletion"
                            }
                        }
                    )
                    
                    # Update user's clubs_joined array
                    from ..db import get_user_collection
                    users_collection = get_user_collection()
                    await users_collection.update_one(
                        {
                            "_id": ObjectId(member_id),
                            "clubs_joined.club_id": club_id
                        },
                        {
                            "$set": {
                                "clubs_joined.$.membership_status": "inactive",
                                "clubs_joined.$.status": "inactive",
                                "clubs_joined.$.is_temporarily_deleted": True,
                                "clubs_joined.$.deletion_date": now,
                                "clubs_joined.$.usage_stats": usage_stats,
                                "clubs_joined.$.paused_at": now,
                                "clubs_joined.$.paused_by": "captain_deletion"
                            }
                        }
                    )
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error handling captain temporary deletion: {e}")
        return {
            "success": False,
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def handle_captain_permanent_deletion(user_id: str, user: Dict, reason: Optional[str]) -> Dict[str, Any]:
    """Handle permanent deletion for Captain - delete clubs and cancel subscriptions"""
    try:
        captain_id = str(user_id)
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
                        action["member_id"] = member_id
                        action["club_id"] = club_id
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
                                "paid_members.$.deleted_by": "captain_deletion"
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
                                "members.$.deleted_by": "captain_deletion"
                            }
                        }
                    )
            
            # Mark the club as deleted
            await clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {
                    "$set": {
                        "status": "deleted",
                        "is_permanently_deleted": True,
                        "deleted_at": now,
                        "deleted_by": "captain_deletion",
                        "deletion_reason": "Captain permanently deleted"
                    }
                }
            )
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error handling captain permanent deletion: {e}")
        return {
            "success": False,
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def handle_member_temporary_deletion(user_id: str, user: Dict, reason: Optional[str]) -> Dict[str, Any]:
    """Handle temporary deletion for Member - pause all their subscriptions"""
    try:
        member_id = str(user_id)
        affected_clubs = []
        affected_members = [member_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs the member has joined
        clubs_joined = user.get("clubs_joined", [])
        
        # Also check if user has a main subscription ID (from JWT token)
        main_subscription_id = user.get("subscription_id")
        if main_subscription_id:
            logger.info(f"Found main subscription ID for user {user_id}: {main_subscription_id}")
            # Pause the main subscription
            action = await pause_stripe_subscription(main_subscription_id)
            action["member_id"] = member_id
            action["club_id"] = "main_subscription"
            stripe_actions.append(action)
            logger.info(f"Main subscription pause result: {action}")
        
        for club_membership in clubs_joined:
            club_id = club_membership.get("club_id")
            if not club_id:
                continue
            
            affected_clubs.append(club_id)
            
            # Get usage stats and subscription ID
            usage_stats = await calculate_usage_stats(club_membership, now)
            subscription_id = club_membership.get("subscription_id")
            membership_type = club_membership.get("membership_type")
            
            logger.info(f"Processing club {club_id} for member {member_id}, membership_type: {membership_type}, subscription_id: {subscription_id}")
            
            if membership_type == "paid" and subscription_id:
                # Pause Stripe subscription
                logger.info(f"Pausing paid subscription {subscription_id} for member {member_id} in club {club_id}")
                action = await pause_stripe_subscription(subscription_id)
                action["member_id"] = member_id
                action["club_id"] = club_id
                stripe_actions.append(action)
                logger.info(f"Pause result: {action}")
                
                # Update paid member status in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_members.user_id": member_id
                    },
                    {
                        "$set": {
                            "paid_members.$.membership_status": "inactive",
                            "paid_members.$.status": "inactive",
                            "paid_members.$.is_temporarily_deleted": True,
                            "paid_members.$.deletion_date": now,
                            "paid_members.$.usage_stats": usage_stats,
                            "paid_members.$.paused_at": now,
                            "paid_members.$.paused_by": "member_deletion"
                        }
                    }
                )
            else:
                logger.info(f"Skipping Stripe pause for club {club_id} - membership_type: {membership_type}, subscription_id: {subscription_id}")
                
                # Update trial member status in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "inactive",
                            "members.$.status": "inactive",
                            "members.$.is_temporarily_deleted": True,
                            "members.$.deletion_date": now,
                            "members.$.usage_stats": usage_stats,
                            "members.$.paused_at": now,
                            "members.$.paused_by": "member_deletion"
                        }
                    }
                )
            
            # Update user's clubs_joined array
            from ..db import get_user_collection
            users_collection = get_user_collection()
            await users_collection.update_one(
                {
                    "_id": ObjectId(member_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "inactive",
                        "clubs_joined.$.status": "inactive",
                        "clubs_joined.$.is_temporarily_deleted": True,
                        "clubs_joined.$.deletion_date": now,
                        "clubs_joined.$.usage_stats": usage_stats,
                        "clubs_joined.$.paused_at": now,
                        "clubs_joined.$.paused_by": "member_deletion"
                    }
                }
            )
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error in handle_member_temporary_deletion: {e}")
        return {
            "success": False,
            "error": str(e),
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def handle_member_permanent_deletion(user_id: str, user: Dict, reason: Optional[str]) -> Dict[str, Any]:
    """Handle permanent deletion for Member - cancel all their subscriptions"""
    try:
        member_id = str(user_id)
        affected_clubs = []
        affected_members = [member_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs the member has joined
        clubs_joined = user.get("clubs_joined", [])
        
        for club_membership in clubs_joined:
            club_id = club_membership.get("club_id")
            if not club_id:
                continue
            
            affected_clubs.append(club_id)
            
            subscription_id = club_membership.get("subscription_id")
            
            if club_membership.get("membership_type") == "paid" and subscription_id:
                # Cancel Stripe subscription
                action = await cancel_stripe_subscription(subscription_id)
                action["member_id"] = member_id
                action["club_id"] = club_id
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
                            "paid_members.$.status": "deleted",
                            "paid_members.$.is_permanently_deleted": True,
                            "paid_members.$.deletion_date": now,
                            "paid_members.$.deleted_by": "member_deletion"
                        }
                    }
                )
            else:
                # Mark trial member as deleted in club
                await clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "deleted",
                            "members.$.status": "deleted",
                            "members.$.is_permanently_deleted": True,
                            "members.$.deletion_date": now,
                            "members.$.deleted_by": "member_deletion"
                        }
                    }
                )
            
            # Mark as deleted in user's clubs_joined array
            from ..db import get_user_collection
            users_collection = get_user_collection()
            await users_collection.update_one(
                {
                    "_id": ObjectId(member_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "deleted",
                        "clubs_joined.$.status": "deleted",
                        "clubs_joined.$.is_permanently_deleted": True,
                        "clubs_joined.$.deletion_date": now,
                        "clubs_joined.$.deleted_by": "member_deletion"
                    }
                }
            )
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error in handle_member_permanent_deletion: {e}")
        return {
            "success": False,
            "error": str(e),
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def handle_member_reactivation(user_id: str, user: Dict) -> Dict[str, Any]:
    """Handle reactivation for Member - resume all their subscriptions"""
    try:
        member_id = str(user_id)
        affected_clubs = []
        affected_members = [member_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs the member has joined
        clubs_joined = user.get("clubs_joined", [])
        
        # Also check if user has a main subscription ID (from JWT token)
        main_subscription_id = user.get("subscription_id")
        if main_subscription_id:
            logger.info(f"Found main subscription ID for user {user_id}: {main_subscription_id}")
            # Get usage stats from user's main subscription
            main_usage_stats = user.get("usage_stats", {})
            main_unused_days = main_usage_stats.get("remaining_days", 0)
            
            # Resume the main subscription
            action = await resume_stripe_subscription(main_subscription_id, main_unused_days)
            action["member_id"] = member_id
            action["club_id"] = "main_subscription"
            stripe_actions.append(action)
            logger.info(f"Main subscription resume result: {action}")
        
        for club_membership in clubs_joined:
            club_id = club_membership.get("club_id")
            if not club_id:
                continue
            
            affected_clubs.append(club_id)
            
            # Get usage stats and subscription ID
            usage_stats = club_membership.get("usage_stats", {})
            unused_days = usage_stats.get("remaining_days", 0)
            subscription_id = club_membership.get("subscription_id")
            
            if club_membership.get("membership_type") == "paid" and subscription_id:
                # Resume Stripe subscription with trial period for unused days
                action = await resume_stripe_subscription(subscription_id, unused_days)
                action["member_id"] = member_id
                action["club_id"] = club_id
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
                            "paid_members.$.status": "active",
                            "paid_members.$.is_temporarily_deleted": False,
                            "paid_members.$.end_date": new_end_date,
                            "paid_members.$.reactivation_date": now,
                            "paid_members.$.resumed_at": now,
                            "paid_members.$.resumed_by": "member_reactivation"
                        },
                        "$unset": {
                            "paid_members.$.deletion_date": "",
                            "paid_members.$.usage_stats": "",
                            "paid_members.$.paused_at": "",
                            "paid_members.$.paused_by": ""
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
                            "members.$.status": "active",
                            "members.$.is_temporarily_deleted": False,
                            "members.$.end_date": new_end_date,
                            "members.$.reactivation_date": now,
                            "members.$.resumed_at": now,
                            "members.$.resumed_by": "member_reactivation"
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
            from ..db import get_user_collection
            users_collection = get_user_collection()
            await users_collection.update_one(
                {
                    "_id": ObjectId(member_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "active",
                        "clubs_joined.$.status": "active",
                        "clubs_joined.$.is_temporarily_deleted": False,
                        "clubs_joined.$.end_date": new_end_date,
                        "clubs_joined.$.reactivation_date": now
                    },
                    "$unset": {
                        "clubs_joined.$.deletion_date": "",
                        "clubs_joined.$.usage_stats": "",
                        "clubs_joined.$.paused_at": "",
                        "clubs_joined.$.paused_by": ""
                    }
                }
            )
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error in handle_member_reactivation: {e}")
        return {
            "success": False,
            "error": str(e),
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def handle_moderator_temporary_deletion(user_id: str, user: Dict, reason: Optional[str]) -> Dict[str, Any]:
    """Handle temporary deletion for Moderator - mark as inactive in all clubs"""
    try:
        moderator_id = str(user_id)
        affected_clubs = []
        affected_members = [moderator_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs where this user is a moderator
        clubs_cursor = clubs_collection.find({
            "$or": [
                {"detailed_moderators": {"$elemMatch": {"moderator_user_id": moderator_id}}},
                {"detailed_moderators": {"$elemMatch": {"moderator_email": user.get("email")}}}
            ]
        })
        clubs = await clubs_cursor.to_list(None)
        
        for club in clubs:
            club_id = str(club["_id"])
            affected_clubs.append(club_id)
            
            # Mark moderator as inactive in detailed_moderators array
            await clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "detailed_moderators": {
                        "$elemMatch": {
                            "$or": [
                                {"moderator_user_id": moderator_id},
                                {"moderator_email": user.get("email")}
                            ]
                        }
                    }
                },
                {
                    "$set": {
                        "detailed_moderators.$.status": "inactive",
                        "detailed_moderators.$.is_temporarily_deleted": True,
                        "detailed_moderators.$.deletion_date": now,
                        "detailed_moderators.$.deleted_by": "moderator_deletion",
                        "detailed_moderators.$.paused_at": now,
                        "detailed_moderators.$.paused_by": "moderator_deletion"
                    }
                }
            )
            
            logger.info(f"Marked moderator {moderator_id} as inactive in club {club_id}")
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error in handle_moderator_temporary_deletion: {e}")
        return {
            "success": False,
            "error": str(e),
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def handle_moderator_permanent_deletion(user_id: str, user: Dict, reason: Optional[str]) -> Dict[str, Any]:
    """Handle permanent deletion for Moderator - mark as deleted in all clubs"""
    try:
        moderator_id = str(user_id)
        affected_clubs = []
        affected_members = [moderator_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs where this user is a moderator
        clubs_cursor = clubs_collection.find({
            "$or": [
                {"detailed_moderators": {"$elemMatch": {"moderator_user_id": moderator_id}}},
                {"detailed_moderators": {"$elemMatch": {"moderator_email": user.get("email")}}}
            ]
        })
        clubs = await clubs_cursor.to_list(None)
        
        for club in clubs:
            club_id = str(club["_id"])
            affected_clubs.append(club_id)
            
            # Mark moderator as deleted in detailed_moderators array
            await clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "detailed_moderators": {
                        "$elemMatch": {
                            "$or": [
                                {"moderator_user_id": moderator_id},
                                {"moderator_email": user.get("email")}
                            ]
                        }
                    }
                },
                {
                    "$set": {
                        "detailed_moderators.$.status": "deleted",
                        "detailed_moderators.$.is_permanently_deleted": True,
                        "detailed_moderators.$.deletion_date": now,
                        "detailed_moderators.$.deleted_by": "moderator_deletion"
                    }
                }
            )
            
            logger.info(f"Marked moderator {moderator_id} as deleted in club {club_id}")
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error in handle_moderator_permanent_deletion: {e}")
        return {
            "success": False,
            "error": str(e),
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def handle_moderator_reactivation(user_id: str, user: Dict) -> Dict[str, Any]:
    """Handle reactivation for Moderator - mark as active in all clubs"""
    try:
        moderator_id = str(user_id)
        affected_clubs = []
        affected_members = [moderator_id]
        stripe_actions = []
        now = datetime.now(timezone.utc)
        
        # Find all clubs where this user is a moderator
        clubs_cursor = clubs_collection.find({
            "$or": [
                {"detailed_moderators": {"$elemMatch": {"moderator_user_id": moderator_id}}},
                {"detailed_moderators": {"$elemMatch": {"moderator_email": user.get("email")}}}
            ]
        })
        clubs = await clubs_cursor.to_list(None)
        
        for club in clubs:
            club_id = str(club["_id"])
            affected_clubs.append(club_id)
            
            # Mark moderator as active in detailed_moderators array
            await clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "detailed_moderators": {
                        "$elemMatch": {
                            "$or": [
                                {"moderator_user_id": moderator_id},
                                {"moderator_email": user.get("email")}
                            ]
                        }
                    }
                },
                {
                    "$set": {
                        "detailed_moderators.$.status": "active",
                        "detailed_moderators.$.is_temporarily_deleted": False,
                        "detailed_moderators.$.reactivation_date": now,
                        "detailed_moderators.$.reactivated_by": "moderator_reactivation"
                    },
                    "$unset": {
                        "detailed_moderators.$.deletion_date": "",
                        "detailed_moderators.$.paused_at": "",
                        "detailed_moderators.$.paused_by": ""
                    }
                }
            )
            
            logger.info(f"Marked moderator {moderator_id} as active in club {club_id}")
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error in handle_moderator_reactivation: {e}")
        return {
            "success": False,
            "error": str(e),
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

async def handle_captain_reactivation(user_id: str, user: Dict) -> Dict[str, Any]:
    """Handle reactivation for Captain - resume clubs and extend billing cycles"""
    try:
        captain_id = str(user_id)
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
            
            # Update club status to active
            await clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {
                    "$set": {
                        "status": "approved",
                        "is_paused_by_captain": False,
                        "reactivated_at": now,
                        "reactivated_by": "captain_reactivation"
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
                    logger.info(f"Resuming subscription {subscription_id} for member {member_id} with {unused_days} trial days")
                    action = await resume_stripe_subscription(subscription_id, unused_days)
                    action["member_id"] = member_id
                    action["club_id"] = club_id
                    stripe_actions.append(action)
                    
                    if action.get("success", False):
                        # Update subscription status in the database
                        await clubs_collection.update_one(
                            {
                                "_id": ObjectId(club_id),
                                "paid_members.user_id": member_id
                            },
                            {
                                "$set": {
                                    "paid_members.$.subscription_status": "active",
                                    "paid_members.$.stripe_subscription_status": "active",
                                    "paid_members.$.subscription_resumed_at": now
                                }
                            }
                        )
                        logger.info(f"Successfully resumed subscription {subscription_id} for member {member_id}")
                    else:
                        logger.error(f"Failed to resume subscription {subscription_id} for member {member_id}: {action.get('error', 'Unknown error')}")
                
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
                            "paid_members.$.status": "active",
                            "paid_members.$.is_temporarily_deleted": False,
                            "paid_members.$.end_date": new_end_date,
                            "paid_members.$.reactivation_date": now,
                            "paid_members.$.resumed_at": now,
                            "paid_members.$.resumed_by": "captain_reactivation"
                        },
                        "$unset": {
                            "paid_members.$.deletion_date": "",
                            "paid_members.$.usage_stats": ""
                        }
                    }
                )
                
                # Update user's clubs_joined array
                from ..db import get_user_collection
                users_collection = get_user_collection()
                await users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "active",
                            "clubs_joined.$.status": "active",
                            "clubs_joined.$.is_temporarily_deleted": False,
                            "clubs_joined.$.end_date": new_end_date,
                            "clubs_joined.$.reactivation_date": now,
                            "clubs_joined.$.resumed_at": now,
                            "clubs_joined.$.resumed_by": "captain_reactivation"
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
                            "members.$.status": "active",
                            "members.$.is_temporarily_deleted": False,
                            "members.$.end_date": new_end_date,
                            "members.$.reactivation_date": now,
                            "members.$.resumed_at": now,
                            "members.$.resumed_by": "captain_reactivation"
                        },
                        "$unset": {
                            "members.$.deletion_date": "",
                            "members.$.usage_stats": ""
                        }
                    }
                )
                
                # Update user's clubs_joined array
                from ..db import get_user_collection
                users_collection = get_user_collection()
                await users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "active",
                            "clubs_joined.$.status": "active",
                            "clubs_joined.$.is_temporarily_deleted": False,
                            "clubs_joined.$.end_date": new_end_date,
                            "clubs_joined.$.reactivation_date": now,
                            "clubs_joined.$.resumed_at": now,
                            "clubs_joined.$.resumed_by": "captain_reactivation"
                        },
                        "$unset": {
                            "clubs_joined.$.deletion_date": "",
                            "clubs_joined.$.usage_stats": ""
                        }
                    }
                )
        
        return {
            "success": True,
            "affected_clubs": affected_clubs,
            "affected_members": affected_members,
            "stripe_actions": stripe_actions
        }
    except Exception as e:
        logger.error(f"Error handling captain reactivation: {e}")
        return {
            "success": False,
            "affected_clubs": [],
            "affected_members": [],
            "stripe_actions": []
        }

@router.post("/account-deletion/delete", response_model=AccountDeletionResponse)
async def delete_account(
    request: AccountDeletionRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete user account (temporary or permanent)
    
    **Options:**
    1. **Temporary Delete (Soft Delete)**:
       - membership_status becomes inactive
       - All joined clubs become inactive
       - Track usage days and remaining days
       - Can reactivate later if subscription is still valid
    
    2. **Permanent Delete**:
       - status becomes deleted
       - membership_status becomes deleted
       - All joined clubs become deleted
       - No refund provided
       - Cannot reactivate
    
    **Business Rules:**
    - Only the account owner can delete their account
    - Temporary deletion preserves data and allows reactivation
    - Permanent deletion is irreversible
    - Usage statistics are calculated and stored
    - Club memberships are updated accordingly
    
    **Usage Tracking:**
    - Total days: plan_end_date - plan_start_date
    - Used days: current_date - plan_start_date
    - Remaining days: total_days - used_days
    - Usage percentage: (used_days / total_days) * 100
    """
    try:
        user_id = current_user.get("user_id")
        logger.info(f"Account deletion request - User ID from token: {user_id}")
        logger.info(f"Current user data: {current_user}")
        
        if not user_id:
            return create_response(
                status_code=401, status="error",
                message="User ID not found in token",
                error="authentication_error"
            )
        
        # Check if user is a Captain, Moderator, or Member
        is_captain_user = await is_captain(user_id)
        is_moderator_user = await is_moderator(user_id, current_user.get("email", ""))
        
        if is_captain_user:
            # Handle Captain-specific deletion logic
            logger.info(f"Processing Captain deletion for user {user_id}")
            
            # Get user data for Captain-specific processing
            from ..db import get_user_collection
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                return create_response(
                    status_code=400,
                    status="error",
                    message="User not found",
                    error="user_not_found"
                )
            
            # Handle Captain deletion based on type
            if request.deletion_type == "temporary":
                captain_result = await handle_captain_temporary_deletion(user_id, user, request.reason)
            else:
                captain_result = await handle_captain_permanent_deletion(user_id, user, request.reason)
            
            if not captain_result.get("success", False):
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Captain deletion failed: {captain_result.get('error', 'Unknown error')}",
                    error="captain_deletion_failed"
                )
            
            # Update user status using the existing service
            deletion_service = get_account_deletion_service()
            success, error_message, deletion_data = await deletion_service.delete_account(
                user_id=user_id,
                deletion_type=request.deletion_type,
                reason=request.reason
            )
            
            if not success:
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Account deletion failed: {error_message}",
                    error="deletion_failed"
                )
            
            # Add Captain-specific data to response
            deletion_data.update({
                "captain_clubs_affected": captain_result.get("affected_clubs", []),
                "captain_members_affected": captain_result.get("affected_members", []),
                "stripe_actions": captain_result.get("stripe_actions", [])
            })
            
        elif is_moderator_user:
            # Handle Moderator-specific deletion logic
            logger.info(f"Processing Moderator deletion for user {user_id}")
            
            # Get user data for Moderator-specific processing
            from ..db import get_user_collection
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                return create_response(
                    status_code=400,
                    status="error",
                    message="User not found",
                    error="user_not_found"
                )
            
            # Handle Moderator deletion based on type
            if request.deletion_type == "temporary":
                moderator_result = await handle_moderator_temporary_deletion(user_id, user, request.reason)
            else:
                moderator_result = await handle_moderator_permanent_deletion(user_id, user, request.reason)
            
            if not moderator_result.get("success", False):
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Moderator deletion failed: {moderator_result.get('error', 'Unknown error')}",
                    error="moderator_deletion_failed"
                )
            
            # Update user status using the existing service
            deletion_service = get_account_deletion_service()
            success, error_message, deletion_data = await deletion_service.delete_account(
                user_id=user_id,
                deletion_type=request.deletion_type,
                reason=request.reason
            )
            
            if not success:
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Account deletion failed: {error_message}",
                    error="deletion_failed"
                )
            
            # Add Moderator-specific data to response
            deletion_data.update({
                "moderator_clubs_affected": moderator_result.get("affected_clubs", []),
                "moderator_roles_affected": moderator_result.get("affected_members", []),
                "stripe_actions": moderator_result.get("stripe_actions", [])
            })
            
        else:
            # Handle Member-specific deletion logic
            logger.info(f"Processing Member deletion for user {user_id}")
            
            # Get user data for Member-specific processing
            from ..db import get_user_collection
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                return create_response(
                    status_code=400,
                    status="error",
                    message="User not found",
                    error="user_not_found"
                )
            
            # Handle Member deletion based on type
            if request.deletion_type == "temporary":
                member_result = await handle_member_temporary_deletion(user_id, user, request.reason)
            else:
                member_result = await handle_member_permanent_deletion(user_id, user, request.reason)
            
            if not member_result.get("success", False):
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Member deletion failed: {member_result.get('error', 'Unknown error')}",
                    error="member_deletion_failed"
                )
            
            # Update user status using the existing service
            deletion_service = get_account_deletion_service()
            success, error_message, deletion_data = await deletion_service.delete_account(
                user_id=user_id,
                deletion_type=request.deletion_type,
                reason=request.reason
            )
            
            if not success:
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Account deletion failed: {error_message}",
                    error="deletion_failed"
                )
            
            # Add Member-specific data to response
            deletion_data.update({
                "member_clubs_affected": member_result.get("affected_clubs", []),
                "member_subscriptions_affected": member_result.get("affected_members", []),
                "stripe_actions": member_result.get("stripe_actions", [])
            })
        
        if not success:
            return create_response(
                status_code=400,
                status="error",
                message=f"Account deletion failed: {error_message}",
                error="deletion_failed"
            )
        
        # Prepare response message
        if request.deletion_type == "temporary":
            message = f"Account temporarily deactivated successfully. You can reactivate your account until your subscription expires."
        else:
            message = f"Account permanently deleted. This action cannot be undone."
        
        return create_response(
            status_code=200,
            status="success",
            message=message,
            data=deletion_data
        )
        
    except Exception as e:
        logger.error(f"Error in delete_account endpoint: {str(e)}")
        return create_response(
            status_code=500,
            status="error",
            message="Internal server error occurred",
            error="internal_error"
        )

@router.post("/account-deletion/reactivate", response_model=AccountReactivationResponse)
async def reactivate_account(
    current_user: dict = Depends(get_current_user)
):
    """
    Reactivate temporarily deleted account
    
    **Business Rules:**
    - Only temporarily deleted accounts can be reactivated
    - Subscription must still be valid (not expired)
    - All club memberships will be reactivated
    - Usage statistics are preserved
    
    **Conditions:**
    - Account must be temporarily deleted (deletion_type = "temporary")
    - Current date must be before plan_end_date
    - Account status must be inactive
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            return create_response(
                status_code=401, status="error",
                message="User ID not found in token",
                error="authentication_error"
            )
        
        # Check if user is a Captain, Moderator, or Member
        is_captain_user = await is_captain(user_id)
        is_moderator_user = await is_moderator(user_id, current_user.get("email", ""))
        
        if is_captain_user:
            # Handle Captain-specific reactivation logic
            logger.info(f"Processing Captain reactivation for user {user_id}")
            
            # Get user data for Captain-specific processing
            from ..db import get_user_collection
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                return create_response(
                    status_code=400,
                    status="error",
                    message="User not found",
                    error="user_not_found"
                )
            
            # Handle Captain reactivation
            captain_result = await handle_captain_reactivation(user_id, user)
            
            if not captain_result.get("success", False):
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Captain reactivation failed: {captain_result.get('error', 'Unknown error')}",
                    error="captain_reactivation_failed"
                )
            
            # Update user status using the existing service
            deletion_service = get_account_deletion_service()
            success, error_message, reactivation_data = await deletion_service.reactivate_account(
                user_id=user_id
            )
            
            if not success:
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Account reactivation failed: {error_message}",
                    error="reactivation_failed"
                )
            
            # Add Captain-specific data to response
            reactivation_data.update({
                "captain_clubs_reactivated": captain_result.get("affected_clubs", []),
                "captain_members_reactivated": captain_result.get("affected_members", []),
                "stripe_actions": captain_result.get("stripe_actions", [])
            })
            
        elif is_moderator_user:
            # Handle Moderator-specific reactivation logic
            logger.info(f"Processing Moderator reactivation for user {user_id}")
            
            # Get user data for Moderator-specific processing
            from ..db import get_user_collection
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                return create_response(
                    status_code=400,
                    status="error",
                    message="User not found",
                    error="user_not_found"
                )
            
            # Handle Moderator reactivation
            moderator_result = await handle_moderator_reactivation(user_id, user)
            
            if not moderator_result.get("success", False):
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Moderator reactivation failed: {moderator_result.get('error', 'Unknown error')}",
                    error="moderator_reactivation_failed"
                )
            
            # Update user status using the existing service
            deletion_service = get_account_deletion_service()
            success, error_message, reactivation_data = await deletion_service.reactivate_account(
                user_id=user_id
            )
            
            if not success:
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Account reactivation failed: {error_message}",
                    error="reactivation_failed"
                )
            
            # Add Moderator-specific data to response
            reactivation_data.update({
                "moderator_clubs_reactivated": moderator_result.get("affected_clubs", []),
                "moderator_roles_reactivated": moderator_result.get("affected_members", []),
                "stripe_actions": moderator_result.get("stripe_actions", [])
            })
            
        else:
            # Handle Member-specific reactivation logic
            logger.info(f"Processing Member reactivation for user {user_id}")
            
            # Get user data for Member-specific processing
            from ..db import get_user_collection
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                return create_response(
                    status_code=400,
                    status="error",
                    message="User not found",
                    error="user_not_found"
                )
            
            # Handle Member reactivation
            member_result = await handle_member_reactivation(user_id, user)
            
            if not member_result.get("success", False):
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Member reactivation failed: {member_result.get('error', 'Unknown error')}",
                    error="member_reactivation_failed"
                )
            
            # Update user status using the existing service
            deletion_service = get_account_deletion_service()
            success, error_message, reactivation_data = await deletion_service.reactivate_account(
                user_id=user_id
            )
            
            if not success:
                return create_response(
                    status_code=400,
                    status="error",
                    message=f"Account reactivation failed: {error_message}",
                    error="reactivation_failed"
                )
            
            # Add Member-specific data to response
            reactivation_data.update({
                "member_clubs_reactivated": member_result.get("affected_clubs", []),
                "member_subscriptions_reactivated": member_result.get("affected_members", []),
                "stripe_actions": member_result.get("stripe_actions", [])
            })
        
        if not success:
            return create_response(
                status_code=400, status="error",
                message=f"Account reactivation failed: {error_message}",
                error="reactivation_failed"
            )
        
        return create_response(
            status_code=200, status="success",
            message="Account reactivated successfully. Your subscription and club memberships are now active.",
            data=reactivation_data
        )
        
    except Exception as e:
        logger.error(f"Error in reactivate_account endpoint: {str(e)}")
        return create_response(
                status_code=500, status="error",
                message="Internal server error occurred",
                error="internal_error"
        )

@router.get("/account-deletion/status", response_model=AccountDeletionStatusResponse)
async def get_deletion_status(
    current_user: dict = Depends(get_current_user)
):
    """
    Get account deletion status
    
    **Returns:**
    - Current account status and membership_status
    - Deletion type (temporary/permanent/none)
    - Usage statistics (if temporarily deleted)
    - Reactivation eligibility
    - Deletion timestamp and reason
    
    **Usage Statistics Include:**
    - Total days in subscription period
    - Days used since plan start
    - Days remaining until plan end
    - Usage percentage
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            return create_response(
                status_code=401, status="error",
                message="User ID not found in token",
                error="authentication_error"
            )
        
        deletion_service = get_account_deletion_service()
        
        # Get deletion status
        success, error_message, status_data = await deletion_service.get_deletion_status(
            user_id=user_id
        )
        
        if not success:
            return create_response(
                status_code=400, status="error",
                message=f"Failed to get deletion status: {error_message}",
                error="status_check_failed"
            )
        
        return create_response(
            status_code=200, status="success",
            message="Deletion status retrieved successfully",
            data=status_data
        )
        
    except Exception as e:
        logger.error(f"Error in get_deletion_status endpoint: {str(e)}")
        return create_response(
                status_code=500, status="error",
                message="Internal server error occurred",
                error="internal_error"
        )

@router.post("/account-deletion/auto-permanent-delete-captains")
async def auto_permanent_delete_inactive_captains():
    """
    Auto-permanent deletion for Captains who have been inactive for more than 60 days
    
    This endpoint should be called by a cron job or scheduled task.
    It finds all Captains who have been temporarily deleted for more than 60 days
    and permanently deletes them along with their clubs and all members.
    
    **Business Rules:**
    - Only affects Captains with temporary deletion (membership_status = "inactive")
    - Must be inactive for more than 60 days
    - Permanently deletes the Captain's account
    - Permanently deletes all clubs created by the Captain
    - Cancels all subscriptions and removes all members
    - This action is irreversible
    """
    try:
        now = datetime.now(timezone.utc)
        sixty_days_ago = now - timedelta(days=60)
        
        logger.info(f"Starting auto-permanent deletion for Captains inactive since {sixty_days_ago}")
        
        # Find all temporarily deleted Captains inactive for more than 60 days
        from ..db import get_user_collection
        users_collection = get_user_collection()
        
        inactive_captains = await users_collection.find({
            "membership_status": "inactive",
            "deletion_type": "temporary",
            "deleted_at": {"$lt": sixty_days_ago},
            "role": "Captain"
        }).to_list(None)
        
        logger.info(f"Found {len(inactive_captains)} Captains for auto-permanent deletion")
        
        processed_captains = []
        errors = []
        
        for captain in inactive_captains:
            try:
                captain_id = str(captain["_id"])
                captain_email = captain.get("email", "Unknown")
                
                logger.info(f"Processing auto-permanent deletion for Captain {captain_id} ({captain_email})")
                
                # Handle permanent deletion for this Captain
                captain_result = await handle_captain_permanent_deletion(
                    captain_id, 
                    captain, 
                    "Auto-permanent deletion after 60 days of inactivity"
                )
                
                if captain_result.get("success", False):
                    # Update user status to permanently deleted
                    await users_collection.update_one(
                        {"_id": ObjectId(captain_id)},
                        {
                            "$set": {
                                "status": "deleted",
                                "membership_status": "deleted",
                                "deletion_type": "permanent",
                                "is_auto_permanently_deleted": True,
                                "auto_deleted_at": now,
                                "auto_deletion_reason": "60 days of inactivity"
                            }
                        }
                    )
                    
                    processed_captains.append({
                        "captain_id": captain_id,
                        "captain_email": captain_email,
                        "clubs_affected": captain_result.get("affected_clubs", []),
                        "members_affected": captain_result.get("affected_members", []),
                        "stripe_actions": captain_result.get("stripe_actions", [])
                    })
                    
                    logger.info(f"Successfully auto-permanently deleted Captain {captain_id}")
                else:
                    errors.append({
                        "captain_id": captain_id,
                        "captain_email": captain_email,
                        "error": "Failed to process Captain deletion"
                    })
                    
            except Exception as e:
                logger.error(f"Error processing Captain {captain.get('_id', 'Unknown')}: {str(e)}")
                errors.append({
                    "captain_id": str(captain.get("_id", "Unknown")),
                    "captain_email": captain.get("email", "Unknown"),
                    "error": str(e)
                })
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Auto-permanent deletion completed. Processed {len(processed_captains)} Captains.",
            data={
                "processed_captains": processed_captains,
                "total_processed": len(processed_captains),
                "errors": errors,
                "total_errors": len(errors),
                "processed_at": now.isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Error in auto_permanent_delete_inactive_captains endpoint: {str(e)}")
        return create_response(
            status_code=500,
            status="error",
            message="Internal server error occurred during auto-deletion",
            error="internal_error"
        )
