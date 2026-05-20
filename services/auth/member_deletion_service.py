"""
Member Deletion Service

This service handles deleting members from clubs with temporary and permanent options.
It manages database updates, Stripe subscription handling, and billing management.
"""

import logging
import os
import stripe
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from core.database.collections import get_collections
from core.utils.email_service import send_email

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
if not stripe.api_key:
    logger.warning("⚠️ STRIPE_SECRET_KEY not found in environment variables")

def _safe_isoformat(value):
    """Safely convert datetime to ISO format string"""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)

def _serialize_dict_datetimes(obj):
    """Recursively serialize datetime objects in a dictionary"""
    if isinstance(obj, dict):
        return {key: _serialize_dict_datetimes(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_dict_datetimes(item) for item in obj]
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        return obj

class MemberDeletionService:
    """Service for managing member deletion from clubs"""
    
    def __init__(self):
        self._collections = None
        self._users_collection = None
        self._clubs_collection = None
        self._membership_collection = None
    
    def _ensure_collections_initialized(self):
        """Lazy initialization of collections to prevent circular imports"""
        if self._collections is None:
            self._collections = get_collections()
            self._users_collection = self._collections.get_users_collection()
            self._clubs_collection = self._collections.get_clubs_collection()
            self._membership_collection = self._collections.get_membership_collection()
    
    async def delete_member_from_club(
        self, 
        captain_id: str,
        club_id: str,
        member_id: str,
        deletion_type: str,
        reason: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Delete a member from a club with temporary or permanent deletion
        
        Args:
            captain_id: The captain ID requesting the deletion
            club_id: The club ID
            member_id: The member ID to delete
            deletion_type: "temporary" or "permanent"
            reason: Optional reason for deletion
        
        Returns:
            Tuple of (success, data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            
            # Validate inputs
            try:
                captain_object_id = ObjectId(captain_id)
                club_object_id = ObjectId(club_id)
                member_object_id = ObjectId(member_id)
            except Exception:
                return False, None, "Invalid ID format"
            
            # Get member data
            member = await self._users_collection.find_one({"_id": member_object_id})
            if not member:
                return False, None, "Member not found"
            
            # Get club data
            club = await self._clubs_collection.find_one({"_id": club_object_id})
            if not club:
                return False, None, "Club not found"
            
            # Verify captain owns the club
            if not self._is_captain_owner(club, captain_id):
                return False, None, "Captain is not the owner of this club"
            
            # Find member's membership in this club
            member_membership = await self._find_member_membership(member, club_id)
            logger.info(f"Member membership found: {member_membership.get('membership_type', 'unknown')} - {member_membership.get('subscription_id', 'no_subscription')}")
            if not member_membership:
                return False, None, "Member is not part of this club"
            
            # Check if member is paid member
            is_paid_member = member_membership.get("membership_type") == "paid"
            
            if deletion_type == "temporary":
                return await self._temporary_delete_member(
                    member, club, member_membership, is_paid_member, reason
                )
            elif deletion_type == "permanent":
                return await self._permanent_delete_member(
                    member, club, member_membership, is_paid_member, reason
                )
            else:
                return False, None, "Invalid deletion type. Must be 'temporary' or 'permanent'"
                
        except Exception as e:
            logger.error(f"Error deleting member from club: {e}")
            return False, None, f"Internal server error: {str(e)}"
    
    async def _temporary_delete_member(
        self, 
        member: Dict, 
        club: Dict, 
        member_membership: Dict,
        is_paid_member: bool,
        reason: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """Handle temporary deletion of member"""
        try:
            member_id = str(member["_id"])
            club_id = str(club["_id"])
            now = datetime.now(timezone.utc)
            
            # Calculate usage stats using Stripe subscription dates
            subscription_id = member_membership.get("subscription_id") if is_paid_member else None
            usage_stats = await self._calculate_usage_stats(member_membership, now, subscription_id)
            
            # Update user's clubs_joined array
            await self._update_user_clubs_joined_temporary(member_id, club_id, usage_stats, now)
            
            # Update club's members arrays
            await self._update_club_members_temporary(club_id, member_id, usage_stats, now)
            
            # Update club_memberships collection
            await self._update_membership_temporary(club_id, member_id, usage_stats, now)
            
            # Handle Stripe for paid members
            stripe_subscription_id = None
            billing_paused = False
            next_billing_date = None
            
            if is_paid_member:
                subscription_id = member_membership.get("subscription_id")
                if subscription_id:
                    remaining_days = usage_stats.get("remaining_days", 0)
                    # Use permanent pause by default for temporary deletion
                    stripe_result = await self._pause_stripe_subscription(subscription_id, remaining_days, permanent_pause=True)
                    if stripe_result[0]:
                        stripe_subscription_id = subscription_id
                        billing_paused = True
                        next_billing_date = stripe_result[1]  # Will be None for permanent pause
                        pause_details = stripe_result[2]  # Get pause details
                        
                        # Store pause details in usage stats for future reference
                        usage_stats["pause_details"] = pause_details
            
            # Send notification email
            await self._send_temporary_deletion_email(member, club, reason)
            
            # Ensure all datetime objects in usage_stats are serialized
            serialized_usage_stats = self._serialize_usage_stats(usage_stats)
            
            response_data = {
                "success": True,
                "message": f"Member {member.get('full_name', 'Unknown')} temporarily deleted from club with permanent subscription pause",
                "deletion_type": "temporary",
                "member_id": member_id,
                "club_id": club_id,
                "club_name": club.get("name", "Unknown"),
                "member_name": member.get("full_name", "Unknown"),
                "member_email": member.get("email", ""),
                "deletion_date": _safe_isoformat(now),
                "reason": reason,
                "reactivation_available": True,
                "usage_stats": serialized_usage_stats,
                "stripe_subscription_id": stripe_subscription_id,
                "billing_paused": billing_paused,
                "next_billing_date": next_billing_date,  # Will be None for permanent pause
                "pause_type": "permanent",
                "unused_days": usage_stats.get("remaining_days", 0),
                "admin_unpause_required": True
            }
            
            logger.info(f"Successfully temporarily deleted member {member_id} from club {club_id}")
            
            # Send member deletion notification to all club members
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    get_club_members,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                club_name_based_id = club.get("name_based_id")
                if club_name_based_id:
                    # Get all club members
                    all_club_members = await get_club_members(club_name_based_id)
                    
                    if all_club_members:
                        # Determine exclusion list (captain performing action and removed member)
                        exclude_user_ids = {member_id}
                        captain_id = club.get("captain_id")
                        if captain_id:
                            exclude_user_ids.add(str(captain_id))

                        # Filter by club status alerts preference
                        enabled_user_ids = await filter_users_by_notification_preference(
                            all_club_members,
                            "club_status_alerts"
                        )
                        enabled_user_ids = [
                            uid for uid in (enabled_user_ids or [])
                            if uid and uid not in exclude_user_ids
                        ]

                        # Look up users with active tokens
                        collections = get_collections()
                        user_tokens_collection = collections.get_user_tokens_collection()

                        users_with_tokens = []
                        if enabled_user_ids:
                            token_cursor = user_tokens_collection.find(
                                {
                                    "user_id": {"$in": enabled_user_ids},
                                    "is_active": True,
                                },
                                {"user_id": 1},
                            )
                            token_docs = await token_cursor.to_list(length=None)
                            users_with_tokens = list(
                                {doc.get("user_id") for doc in token_docs if doc.get("user_id")}
                            )

                        # Build DB and push recipient lists
                        db_user_ids = [
                            uid for uid in all_club_members
                            if uid and uid not in exclude_user_ids
                        ]
                        push_user_ids = [
                            uid for uid in users_with_tokens if uid in enabled_user_ids
                        ]

                        if db_user_ids:
                            # Prepare notification content
                            member_name = member.get("full_name", "A member")
                            title = f"Member Removed!"
                            body = f"{member_name} has been temporarily removed from the club by Captain"

                            notification_data = {
                                "club_id": club_name_based_id,
                                "club_name": club.get("name", "Club"),
                                "member_name": member_name,
                                "member_id": member_id,
                                "deletion_type": "temporary",
                                "reason": reason,
                                "changed_by": "Captain"
                            }

                            notification_result = await send_notification_to_users(
                                user_ids=push_user_ids,
                                title=title,
                                body=body,
                                notification_type="club_status_change",
                                data=notification_data,
                                click_action=f"club/{club_name_based_id}/members",
                                priority="normal",
                                all_user_ids=db_user_ids,
                            )
                            logger.info(f"✅ Member deletion notification sent for club {club_name_based_id}: {notification_result}")
                        else:
                            logger.info(f"ℹ️ No eligible club members found for club {club_name_based_id}")
                    else:
                        logger.info(f"ℹ️ No club members found for club {club_name_based_id}")
                        
            except Exception as e:
                logger.error(f"⚠️ Failed to send member deletion notification: {e}")
            
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error in temporary deletion: {e}")
            return False, None, f"Temporary deletion failed: {str(e)}"
    
    async def _permanent_delete_member(
        self, 
        member: Dict, 
        club: Dict, 
        member_membership: Dict,
        is_paid_member: bool,
        reason: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """Handle permanent deletion of member"""
        try:
            member_id = str(member["_id"])
            club_id = str(club["_id"])
            now = datetime.now(timezone.utc)
            
            # Update user's clubs_joined array
            await self._update_user_clubs_joined_permanent(member_id, club_id, now)
            
            # Update club's members arrays
            await self._update_club_members_permanent(club_id, member_id, now)
            
            # Update club_memberships collection
            await self._update_membership_permanent(club_id, member_id, now)
            
            # Handle Stripe for paid members
            refund_processed = False
            refund_amount = None
            stripe_subscription_cancelled = False
            
            if is_paid_member:
                subscription_id = member_membership.get("subscription_id")
                if subscription_id:
                    # Cancel subscription and process refund
                    refund_result = await self._cancel_stripe_subscription_and_refund(subscription_id, member_id)
                    if refund_result[0]:
                        stripe_subscription_cancelled = True
                        refund_processed = refund_result[1]
                        refund_amount = refund_result[2]
            
            # Send notification email
            await self._send_permanent_deletion_email(member, club, reason, refund_amount)
            
            response_data = {
                "success": True,
                "message": f"Member {member.get('full_name', 'Unknown')} permanently deleted from club",
                "deletion_type": "permanent",
                "member_id": member_id,
                "club_id": club_id,
                "club_name": club.get("name", "Unknown"),
                "member_name": member.get("full_name", "Unknown"),
                "member_email": member.get("email", ""),
                "deletion_date": _safe_isoformat(now),
                "reason": reason,
                "refund_processed": refund_processed,
                "refund_amount": refund_amount,
                "stripe_subscription_cancelled": stripe_subscription_cancelled
            }
            
            logger.info(f"Successfully permanently deleted member {member_id} from club {club_id}")
            
            # Send member deletion notification to all club members
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    get_club_members,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                club_name_based_id = club.get("name_based_id")
                if club_name_based_id:
                    # Get all club members
                    all_club_members = await get_club_members(club_name_based_id)
                    
                    if all_club_members:
                        exclude_user_ids = {member_id}
                        captain_id = club.get("captain_id")
                        if captain_id:
                            exclude_user_ids.add(str(captain_id))

                        enabled_user_ids = await filter_users_by_notification_preference(
                            all_club_members,
                            "club_status_alerts"
                        )
                        enabled_user_ids = [
                            uid for uid in (enabled_user_ids or [])
                            if uid and uid not in exclude_user_ids
                        ]

                        collections = get_collections()
                        user_tokens_collection = collections.get_user_tokens_collection()

                        users_with_tokens = []
                        if enabled_user_ids:
                            token_cursor = user_tokens_collection.find(
                                {
                                    "user_id": {"$in": enabled_user_ids},
                                    "is_active": True,
                                },
                                {"user_id": 1},
                            )
                            token_docs = await token_cursor.to_list(length=None)
                            users_with_tokens = list(
                                {doc.get("user_id") for doc in token_docs if doc.get("user_id")}
                            )

                        db_user_ids = [
                            uid for uid in all_club_members
                            if uid and uid not in exclude_user_ids
                        ]
                        push_user_ids = [
                            uid for uid in users_with_tokens if uid in enabled_user_ids
                        ]

                        if db_user_ids:
                            member_name = member.get("full_name", "A member")
                            title = f"Member Removed!"
                            body = f"{member_name} has been permanently removed from the club by Captain"

                            notification_data = {
                                "club_id": club_name_based_id,
                                "club_name": club.get("name", "Club"),
                                "member_name": member_name,
                                "member_id": member_id,
                                "deletion_type": "permanent",
                                "reason": reason,
                                "changed_by": "Captain"
                            }

                            notification_result = await send_notification_to_users(
                                user_ids=push_user_ids,
                                title=title,
                                body=body,
                                notification_type="club_status_change",
                                data=notification_data,
                                click_action=f"club/{club_name_based_id}/members",
                                priority="normal",
                                all_user_ids=db_user_ids,
                            )
                            logger.info(f"✅ Member deletion notification sent for club {club_name_based_id}: {notification_result}")
                        else:
                            logger.info(f"ℹ️ No eligible club members found for club {club_name_based_id}")
                    else:
                        logger.info(f"ℹ️ No club members found for club {club_name_based_id}")
                        
            except Exception as e:
                logger.error(f"⚠️ Failed to send member deletion notification: {e}")
            
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error in permanent deletion: {e}")
            return False, None, f"Permanent deletion failed: {str(e)}"
    
    async def reactivate_member(
        self,
        captain_id: str,
        club_id: str,
        member_id: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Reactivate a temporarily deleted member
        
        Args:
            captain_id: The captain ID requesting reactivation
            club_id: The club ID
            member_id: The member ID to reactivate
        
        Returns:
            Tuple of (success, data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            
            # Validate inputs
            try:
                captain_object_id = ObjectId(captain_id)
                club_object_id = ObjectId(club_id)
                member_object_id = ObjectId(member_id)
            except Exception:
                return False, None, "Invalid ID format"
            
            # Get member data
            member = await self._users_collection.find_one({"_id": member_object_id})
            if not member:
                return False, None, "Member not found"
            
            # Get club data
            club = await self._clubs_collection.find_one({"_id": club_object_id})
            if not club:
                return False, None, "Club not found"
            
            # Verify captain owns the club
            if not self._is_captain_owner(club, captain_id):
                return False, None, "Captain is not the owner of this club"
            
            # Find member's inactive membership in this club
            member_membership = await self._find_inactive_member_membership(member, club_id)
            print(f"Member membership found: {member_membership}")
            if not member_membership:
                return False, None, "Member is not temporarily deleted from this club"
            
            # Check if member is paid member
            is_paid_member = member_membership.get("membership_type") == "paid"
            
            # Calculate new billing date based on unused days from Stripe
            unused_days = member_membership.get("usage_stats", {}).get("remaining_days", 0)
            now = datetime.now(timezone.utc)
            subscription_id = member_membership.get("subscription_id") if is_paid_member else None
            
            # Get new billing date based on Stripe subscription and unused days
            new_end_date = await self._calculate_new_billing_date(subscription_id, unused_days, now)
            
            # Update user's clubs_joined array
            await self._reactivate_user_clubs_joined(member_id, club_id, new_end_date, now)
            
            # Update club's members arrays
            await self._reactivate_club_members(club_id, member_id, new_end_date, now)
            
            # Update club_memberships collection
            await self._reactivate_membership(club_id, member_id, new_end_date, now)
            
            # Handle Stripe for paid members
            billing_resumed = False
            next_billing_date = None
            
            if is_paid_member:
                subscription_id = member_membership.get("subscription_id")
                if subscription_id:
                    stripe_result = await self._resume_stripe_subscription(subscription_id, new_end_date)
                    if stripe_result[0]:
                        billing_resumed = True
                        next_billing_date = stripe_result[1]
            
            # Send notification email
            await self._send_reactivation_email(member, club, unused_days)
            
            response_data = {
                "success": True,
                "message": f"Member {member.get('full_name', 'Unknown')} reactivated successfully",
                "member_id": member_id,
                "club_id": club_id,
                "club_name": club.get("name", "Unknown"),
                "member_name": member.get("full_name", "Unknown"),
                "reactivation_date": _safe_isoformat(now),
                "billing_resumed": billing_resumed,
                "next_billing_date": next_billing_date,
                "unused_days_applied": unused_days
            }
            
            logger.info(f"Successfully reactivated member {member_id} from club {club_id}")
            
            # Send member reactivation notification to all club members
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    get_club_members,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                club_name_based_id = club.get("name_based_id")
                if club_name_based_id:
                    # Get all club members
                    all_club_members = await get_club_members(club_name_based_id)
                    
                    if all_club_members:
                        exclude_user_ids = {member_id}
                        captain_id = club.get("captain_id")
                        if captain_id:
                            exclude_user_ids.add(str(captain_id))

                        enabled_user_ids = await filter_users_by_notification_preference(
                            all_club_members,
                            "club_status_alerts"
                        )
                        enabled_user_ids = [
                            uid for uid in (enabled_user_ids or [])
                            if uid and uid not in exclude_user_ids
                        ]

                        collections = get_collections()
                        user_tokens_collection = collections.get_user_tokens_collection()

                        users_with_tokens = []
                        if enabled_user_ids:
                            token_cursor = user_tokens_collection.find(
                                {
                                    "user_id": {"$in": enabled_user_ids},
                                    "is_active": True,
                                },
                                {"user_id": 1},
                            )
                            token_docs = await token_cursor.to_list(length=None)
                            users_with_tokens = list(
                                {doc.get("user_id") for doc in token_docs if doc.get("user_id")}
                            )

                        db_user_ids = [
                            uid for uid in all_club_members
                            if uid and uid not in exclude_user_ids
                        ]
                        push_user_ids = [
                            uid for uid in users_with_tokens if uid in enabled_user_ids
                        ]

                        if db_user_ids:
                            member_name = member.get("full_name", "A member")
                            title = f"Member Rejoined!"
                            body = f"{member_name} has been reactivated in the club by Captain"

                            notification_data = {
                                "club_id": club_name_based_id,
                                "club_name": club.get("name", "Club"),
                                "member_name": member_name,
                                "member_id": member_id,
                                "action_type": "reactivation",
                                "changed_by": "Captain"
                            }

                            notification_result = await send_notification_to_users(
                                user_ids=push_user_ids,
                                title=title,
                                body=body,
                                notification_type="club_status_change",
                                data=notification_data,
                                click_action=f"club/{club_name_based_id}/members",
                                priority="normal",
                                all_user_ids=db_user_ids,
                            )
                            logger.info(f"✅ Member reactivation notification sent for club {club_name_based_id}: {notification_result}")
                        else:
                            logger.info(f"ℹ️ No eligible club members found for club {club_name_based_id}")
                    else:
                        logger.info(f"ℹ️ No club members found for club {club_name_based_id}")
                        
            except Exception as e:
                logger.error(f"⚠️ Failed to send member reactivation notification: {e}")
            
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error reactivating member: {e}")
            return False, None, f"Reactivation failed: {str(e)}"
    
    async def _calculate_usage_stats(self, membership: Dict, deletion_date: datetime, subscription_id: str = None) -> Dict[str, Any]:
        """Calculate usage statistics for temporary deletion using Stripe subscription dates"""
        try:
            # First try to get dates from Stripe subscription
            stripe_start_date = None
            stripe_end_date = None
            
            if subscription_id and stripe.api_key:
                try:
                    logger.info(f"Fetching subscription details from Stripe: {subscription_id}")
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    
                    # Get subscription period dates
                    stripe_start_date = datetime.fromtimestamp(subscription.current_period_start, tz=timezone.utc)
                    stripe_end_date = datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc)
                    
                    logger.info(f"Stripe subscription dates: start={stripe_start_date}, end={stripe_end_date}")
                    
                except Exception as e:
                    logger.error(f"Error fetching Stripe subscription: {e}")
            
            # Fallback to database dates if Stripe fetch fails
            if not stripe_start_date or not stripe_end_date:
                logger.info("Falling back to database dates")
                join_date = membership.get("join_date")
                end_date = membership.get("end_date")
                
                if not join_date or not end_date:
                    logger.warning("Missing dates in both Stripe and database")
                    return {
                        "total_days": 0,
                        "used_days": 0,
                        "remaining_days": 0,
                        "usage_percentage": 0,
                        "calculated_at": _safe_isoformat(deletion_date),
                        "data_source": "none"
                    }
                
                # Convert database dates to datetime
                if isinstance(join_date, str):
                    try:
                        if 'T' in join_date and '+' in join_date:
                            stripe_start_date = datetime.fromisoformat(join_date.replace('Z', '+00:00'))
                        else:
                            stripe_start_date = datetime.fromisoformat(join_date)
                    except Exception as e:
                        logger.error(f"Error parsing database join_date {join_date}: {e}")
                        return {
                            "total_days": 0,
                            "used_days": 0,
                            "remaining_days": 0,
                            "usage_percentage": 0,
                            "calculated_at": _safe_isoformat(deletion_date),
                            "data_source": "error"
                        }
                
                if isinstance(end_date, str):
                    try:
                        if 'T' in end_date and '+' in end_date:
                            stripe_end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                        else:
                            stripe_end_date = datetime.fromisoformat(end_date)
                    except Exception as e:
                        logger.error(f"Error parsing database end_date {end_date}: {e}")
                        return {
                            "total_days": 0,
                            "used_days": 0,
                            "remaining_days": 0,
                            "usage_percentage": 0,
                            "calculated_at": _safe_isoformat(deletion_date),
                            "data_source": "error"
                        }
                
                data_source = "database"
            else:
                data_source = "stripe"
            
            # Ensure all dates are timezone-aware
            if stripe_start_date.tzinfo is None:
                stripe_start_date = stripe_start_date.replace(tzinfo=timezone.utc)
            if stripe_end_date.tzinfo is None:
                stripe_end_date = stripe_end_date.replace(tzinfo=timezone.utc)
            if deletion_date.tzinfo is None:
                deletion_date = deletion_date.replace(tzinfo=timezone.utc)
            
            # Calculate days (inclusive)
            total_days = (stripe_end_date.date() - stripe_start_date.date()).days + 1
            used_days = (deletion_date.date() - stripe_start_date.date()).days + 1
            remaining_days = max(0, total_days - used_days)
            usage_percentage = (used_days / total_days) * 100 if total_days > 0 else 0
            
            logger.info(f"Usage calculation from {data_source}: total_days={total_days}, used_days={used_days}, remaining_days={remaining_days}")
            logger.info(f"Date range: {stripe_start_date.date()} to {stripe_end_date.date()}, deletion: {deletion_date.date()}")
            
            return {
                "total_days": total_days,
                "used_days": used_days,
                "remaining_days": remaining_days,
                "usage_percentage": round(usage_percentage, 2),
                "calculated_at": _safe_isoformat(deletion_date),
                "data_source": data_source,
                "subscription_start_date": _safe_isoformat(stripe_start_date),
                "subscription_end_date": _safe_isoformat(stripe_end_date),
                "deletion_date": _safe_isoformat(deletion_date)
            }
            
        except Exception as e:
            logger.error(f"Error calculating usage stats: {e}")
            import traceback
            traceback.print_exc()
            return {
                "total_days": 0,
                "used_days": 0,
                "remaining_days": 0,
                "usage_percentage": 0,
                "calculated_at": _safe_isoformat(deletion_date),
                "data_source": "error"
            }
    
    async def _calculate_new_billing_date(self, subscription_id: str, unused_days: int, current_date: datetime) -> datetime:
        """Calculate new billing date based on Stripe subscription and unused days"""
        try:
            # If no unused days, return current date + 30 days
            if unused_days <= 0:
                return current_date + timedelta(days=30)
            
            # If no subscription ID, just add unused days
            if not subscription_id or not stripe.api_key:
                return current_date + timedelta(days=unused_days)
            
            try:
                # Get current subscription details from Stripe
                subscription = stripe.Subscription.retrieve(subscription_id)
                
                # Get the original period end date from Stripe
                original_period_end = datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc)
                
                # Calculate new billing date based on unused days
                # If reactivation is after original period ended, add unused days from current date
                if current_date > original_period_end:
                    new_billing_date = current_date + timedelta(days=unused_days)
                    logger.info(f"Reactivation after original period: new billing date = {new_billing_date}")
                else:
                    # If reactivation is before original period ended, use original end date + unused days
                    new_billing_date = original_period_end + timedelta(days=unused_days)
                    logger.info(f"Reactivation before original period: new billing date = {new_billing_date}")
                
                return new_billing_date
                
            except Exception as e:
                logger.error(f"Error fetching Stripe subscription for billing date calculation: {e}")
                # Fallback to simple calculation
                return current_date + timedelta(days=unused_days)
                
        except Exception as e:
            logger.error(f"Error calculating new billing date: {e}")
            # Fallback to simple calculation
            return current_date + timedelta(days=unused_days if unused_days > 0 else 30)
    
    def _serialize_usage_stats(self, usage_stats: Dict) -> Dict:
        """Serialize datetime objects in usage_stats for JSON response"""
        try:
            return _serialize_dict_datetimes(usage_stats)
        except Exception as e:
            logger.error(f"Error serializing usage stats: {e}")
            # Return a safe version without datetime objects
            return {
                "total_days": usage_stats.get("total_days", 0),
                "used_days": usage_stats.get("used_days", 0),
                "remaining_days": usage_stats.get("remaining_days", 0),
                "usage_percentage": usage_stats.get("usage_percentage", 0),
                "calculated_at": _safe_isoformat(usage_stats.get("calculated_at")),
                "status": usage_stats.get("status", "inactive")
            }
    
    def _is_captain_owner(self, club: Dict, captain_id: str) -> bool:
        """Check if captain is the owner of the club"""
        try:
            # Try different possible field names for captain identification
            captain_fields = ["captain_id", "created_by", "owner_id", "user_id"]
            
            for field in captain_fields:
                if field in club:
                    club_captain = club[field]
                    if str(club_captain) == captain_id:
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking captain ownership: {e}")
            return False
    
    async def _find_member_membership(self, member: Dict, club_id: str) -> Optional[Dict]:
        """Find member's active membership in a club and enrich with Stripe subscription data"""
        try:
            clubs_joined = member.get("clubs_joined", [])
            for club_joined in clubs_joined:
                if str(club_joined.get("club_id", "")) == club_id:
                    membership = club_joined.copy()
                    
                    # For paid members, try to get subscription_id from Stripe
                    if membership.get("membership_type") == "paid":
                        subscription_id = await self._get_subscription_id_for_member(member, membership)
                        if subscription_id:
                            membership["subscription_id"] = subscription_id
                            logger.info(f"Found subscription_id for member: {subscription_id}")
                        else:
                            logger.warning(f"No subscription_id found for paid member in club {club_id}")
                    
                    return membership
            return None
            
        except Exception as e:
            logger.error(f"Error finding member membership: {e}")
            return None
    
    async def _get_subscription_id_for_member(self, member: Dict, membership: Dict) -> Optional[str]:
        """Get subscription ID from Stripe for a paid member"""
        try:
            # Check if we already have subscription_id in the membership
            if membership.get("subscription_id"):
                return membership["subscription_id"]
            
            # Get customer ID from user
            stripe_customer_id = member.get("stripe_customer_id")
            if not stripe_customer_id:
                logger.warning("No stripe_customer_id found for member")
                return None
            
            # Get payment_id from membership
            payment_id = membership.get("payment_id")
            if not payment_id:
                logger.warning("No payment_id found in membership")
                return None
            
            # Try to get subscription from Stripe using payment intent
            try:
                payment_intent = stripe.PaymentIntent.retrieve(payment_id)
                subscription_id = payment_intent.get("subscription")
                
                if subscription_id:
                    logger.info(f"Found subscription_id from payment intent: {subscription_id}")
                    return subscription_id
                
            except Exception as e:
                logger.warning(f"Could not retrieve payment intent {payment_id}: {e}")
            
            # Alternative: Get all subscriptions for customer and find matching one
            try:
                subscriptions = stripe.Subscription.list(
                    customer=stripe_customer_id,
                    status="active",
                    limit=100
                )
                
                # Find subscription that matches the club/membership
                for subscription in subscriptions.data:
                    logger.info(f"Checking subscription {subscription.id} for customer {stripe_customer_id}")
                    
                    # Check if subscription matches the membership criteria
                    if subscription.status == "active":
                        # Try to match by checking if the subscription was created around the same time
                        subscription_created = datetime.fromtimestamp(subscription.created, tz=timezone.utc)
                        membership_created = membership.get("created_at")
                        
                        if isinstance(membership_created, str):
                            try:
                                membership_created = datetime.fromisoformat(membership_created.replace('Z', '+00:00'))
                            except:
                                membership_created = None
                        
                        # If created within 24 hours, likely the same subscription
                        if membership_created:
                            time_diff = abs((subscription_created - membership_created).total_seconds())
                            if time_diff < 86400:  # 24 hours
                                logger.info(f"Found matching subscription {subscription.id} based on creation time")
                                return subscription.id
                        
                        # If no time match, return the first active subscription as fallback
                        logger.info(f"Using first active subscription {subscription.id} for member")
                        return subscription.id
                
            except Exception as e:
                logger.error(f"Error fetching subscriptions from Stripe: {e}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting subscription ID for member: {e}")
            return None
    
    async def _find_inactive_member_membership(self, member: Dict, club_id: str) -> Optional[Dict]:
        """Find member's inactive membership in a club and enrich with Stripe subscription data"""
        try:
            clubs_joined = member.get("clubs_joined", [])
            for club_joined in clubs_joined:
                if (str(club_joined.get("club_id", "")) == club_id and 
                    club_joined.get("membership_status") == "inactive"):
                    membership = club_joined.copy()
                    
                    # For paid members, try to get subscription_id from Stripe
                    if membership.get("membership_type") == "paid":
                        subscription_id = await self._get_subscription_id_for_member(member, membership)
                        if subscription_id:
                            membership["subscription_id"] = subscription_id
                            logger.info(f"Found subscription_id for inactive member: {subscription_id}")
                        else:
                            logger.warning(f"No subscription_id found for inactive paid member in club {club_id}")
                    
                    return membership
            return None
            
        except Exception as e:
            logger.error(f"Error finding inactive member membership: {e}")
            return None
    
    # Database update methods
    async def _update_user_clubs_joined_temporary(self, member_id: str, club_id: str, usage_stats: Dict, now: datetime):
        """Update user's clubs_joined array for temporary deletion"""
        try:
            await self._users_collection.update_one(
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
                        "clubs_joined.$.updated_at": now
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error updating user clubs_joined temporary: {e}")
            raise
    
    async def _update_user_clubs_joined_permanent(self, member_id: str, club_id: str, now: datetime):
        """Update user's clubs_joined array for permanent deletion"""
        try:
            await self._users_collection.update_one(
                {
                    "_id": ObjectId(member_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "deleted",
                        "clubs_joined.$.is_permanently_deleted": True,
                        "clubs_joined.$.deletion_date": now,
                        "clubs_joined.$.updated_at": now
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error updating user clubs_joined permanent: {e}")
            raise
    
    async def _reactivate_user_clubs_joined(self, member_id: str, club_id: str, new_end_date: datetime, now: datetime):
        """Reactivate user's clubs_joined array"""
        try:
            logger.info(f"Reactivating user clubs_joined for member_id: {member_id}, club_id: {club_id}")
            result = await self._users_collection.update_one(
                {
                    "_id": ObjectId(member_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.membership_status": "active",
                        "clubs_joined.$.is_temporarily_deleted": False,
                        "clubs_joined.$.end_date": new_end_date,
                        "clubs_joined.$.reactivation_date": now,
                        "clubs_joined.$.updated_at": now
                    },
                    "$unset": {
                        "clubs_joined.$.deletion_date": "",
                        "clubs_joined.$.usage_stats": ""
                    }
                }
            )
            logger.info(f"User clubs_joined update result: {result.modified_count} documents modified")
        except Exception as e:
            logger.error(f"Error reactivating user clubs_joined: {e}")
            raise
    
    async def _update_club_members_temporary(self, club_id: str, member_id: str, usage_stats: Dict, now: datetime):
        """Update club's members arrays for temporary deletion"""
        try:
            # Update trial members
            await self._clubs_collection.update_one(
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
                        "members.$.updated_at": now
                    }
                }
            )
            
            # Update paid members
            await self._clubs_collection.update_one(
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
                        "paid_members.$.updated_at": now
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error updating club members temporary: {e}")
            raise
    
    async def _update_club_members_permanent(self, club_id: str, member_id: str, now: datetime):
        """Update club's members arrays for permanent deletion"""
        try:
            # Update trial members
            await self._clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "members.user_id": member_id
                },
                {
                    "$set": {
                        "members.$.membership_status": "deleted",
                        "members.$.is_permanently_deleted": True,
                        "members.$.deletion_date": now,
                        "members.$.updated_at": now
                    }
                }
            )
            
            # Update paid members
            await self._clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "paid_members.user_id": member_id
                },
                {
                    "$set": {
                        "paid_members.$.membership_status": "deleted",
                        "paid_members.$.is_permanently_deleted": True,
                        "paid_members.$.deletion_date": now,
                        "paid_members.$.updated_at": now
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error updating club members permanent: {e}")
            raise
    
    async def _reactivate_club_members(self, club_id: str, member_id: str, new_end_date: datetime, now: datetime):
        """Reactivate club's members arrays"""
        try:
            logger.info(f"Reactivating club members for club_id: {club_id}, member_id: {member_id}")
            
            # Update trial members
            result_members = await self._clubs_collection.update_one(
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
                        "members.$.updated_at": now
                    },
                    "$unset": {
                        "members.$.deletion_date": "",
                        "members.$.usage_stats": ""
                    }
                }
            )
            
            # Update paid members
            result_paid_members = await self._clubs_collection.update_one(
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
                        "paid_members.$.updated_at": now
                    },
                    "$unset": {
                        "paid_members.$.deletion_date": "",
                        "paid_members.$.usage_stats": ""
                    }
                }
            )
            
            logger.info(f"Update results - members: {result_members.modified_count}, paid_members: {result_paid_members.modified_count}")
        except Exception as e:
            logger.error(f"Error reactivating club members: {e}")
            raise
    
    async def _update_membership_temporary(self, club_id: str, member_id: str, usage_stats: Dict, now: datetime):
        """Update club_memberships collection for temporary deletion"""
        try:
            await self._membership_collection.update_one(
                {
                    "club_id": ObjectId(club_id),
                    "user_id": ObjectId(member_id)
                },
                {
                    "$set": {
                        "membership_status": "inactive",
                        "is_temporarily_deleted": True,
                        "deletion_date": now,
                        "usage_stats": usage_stats,
                        "updated_at": now
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error updating membership temporary: {e}")
            raise
    
    async def _update_membership_permanent(self, club_id: str, member_id: str, now: datetime):
        """Update club_memberships collection for permanent deletion"""
        try:
            await self._membership_collection.update_one(
                {
                    "club_id": ObjectId(club_id),
                    "user_id": ObjectId(member_id)
                },
                {
                    "$set": {
                        "membership_status": "deleted",
                        "is_permanently_deleted": True,
                        "deletion_date": now,
                        "updated_at": now
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error updating membership permanent: {e}")
            raise
    
    async def _reactivate_membership(self, club_id: str, member_id: str, new_end_date: datetime, now: datetime):
        """Reactivate club_memberships collection"""
        try:
            await self._membership_collection.update_one(
                {
                    "club_id": ObjectId(club_id),
                    "user_id": ObjectId(member_id)
                },
                {
                    "$set": {
                        "membership_status": "active",
                        "is_temporarily_deleted": False,
                        "end_date": new_end_date,
                        "reactivation_date": now,
                        "updated_at": now
                    },
                    "$unset": {
                        "deletion_date": "",
                        "usage_stats": ""
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error reactivating membership: {e}")
            raise
    
    async def reactivate_member(self, captain_id: str, club_id: str, member_id: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """Reactivate a temporarily deleted member with improved Stripe trial period approach"""
        try:
            logger.info(f"Reactivating member {member_id} in club {club_id} by captain {captain_id}")
            
            # Ensure collections are initialized
            self._ensure_collections_initialized()
            
            # Get member details
            member = await self._users_collection.find_one({"_id": ObjectId(member_id)})
            if not member:
                return False, None, "Member not found"
            
            # Get club details
            club = await self._clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                return False, None, "Club not found"
            
            # Check if captain owns this club
            if not self._is_captain_owner(club, captain_id):
                return False, None, "You are not authorized to reactivate members in this club"
            
            # Find the inactive membership
            member_membership = await self._find_inactive_member_membership(member, club_id)
            if not member_membership:
                return False, None, "No inactive membership found for this member in this club"
            
            # Check if it's a paid membership
            is_paid_member = member_membership.get("membership_type") == "paid"
            
            # Get usage stats for unused days calculation
            usage_stats = member_membership.get("usage_stats", {})
            unused_days = usage_stats.get("remaining_days", 0)
            
            # Handle Stripe for paid members
            stripe_subscription_id = None
            billing_resumed = False
            new_billing_date = None
            
            if is_paid_member:
                subscription_id = member_membership.get("subscription_id")
                if subscription_id:
                    # Resume subscription with trial period for unused days
                    stripe_result = await self._resume_stripe_subscription_with_trial(subscription_id, unused_days)
                    if stripe_result[0]:
                        stripe_subscription_id = subscription_id
                        billing_resumed = True
                        new_billing_date = stripe_result[1]
            
            # Update member status back to active
            now = datetime.utcnow()
            
            # Calculate new end date based on unused days
            new_end_date = None
            if unused_days > 0:
                new_end_date = now + timedelta(days=unused_days)
            
            # Update user status
            await self._users_collection.update_one(
                {"_id": ObjectId(member_id)},
                {
                    "$set": {
                        "status": "active",
                        "membership_status": "active",
                        "updated_at": now
                    }
                }
            )
            
            # Update user's clubs_joined array
            await self._reactivate_user_clubs_joined(member_id, club_id, new_end_date, now)
            
            # Update club membership status
            await self._reactivate_club_members(club_id, member_id, new_end_date, now)
            
            # Update club_memberships collection
            await self._reactivate_membership(club_id, member_id, new_end_date, now)
            
            # Send notification email
            await self._send_reactivation_email(member, club, unused_days)
            
            response_data = {
                "success": True,
                "message": f"Member {member.get('full_name', 'Unknown')} reactivated successfully",
                "member_id": member_id,
                "club_id": club_id,
                "club_name": club.get("name", "Unknown"),
                "member_name": member.get("full_name", "Unknown"),
                "member_email": member.get("email", ""),
                "reactivation_date": _safe_isoformat(now),
                "unused_days_applied": unused_days,
                "new_end_date": _safe_isoformat(new_end_date),
                "stripe_subscription_id": stripe_subscription_id,
                "billing_resumed": billing_resumed,
                "new_billing_date": new_billing_date
            }
            
            logger.info(f"Successfully reactivated member {member_id} in club {club_id}")
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error reactivating member: {e}")
            return False, None, f"Internal error: {str(e)}"
    
    # Stripe management methods
    async def _pause_stripe_subscription(self, subscription_id: str, remaining_days: int = 0, permanent_pause: bool = False) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Pause Stripe subscription with permanent pause option"""
        try:
            if not stripe.api_key:
                logger.warning("Stripe not configured - skipping subscription pause")
                return True, None, None
            
            logger.info(f"Pausing Stripe subscription {subscription_id} - Permanent: {permanent_pause}, Remaining days: {remaining_days}")
            
            # Get current subscription details
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            if permanent_pause:
                # For permanent pause, just pause without resume date
                logger.info(f"Implementing permanent pause for subscription {subscription_id}")
                
                # Store subscription details for future unpause
                pause_details = {
                    "subscription_id": subscription_id,
                    "original_period_end": subscription.current_period_end,
                    "remaining_days": remaining_days,
                    "paused_at": datetime.now(timezone.utc),
                    "pause_type": "permanent"
                }
                
                # Pause the subscription permanently using keep_as_draft
                paused_subscription = stripe.Subscription.modify(
                    subscription_id,
                    pause_collection={
                        "behavior": "keep_as_draft"  # Invoices stay in draft, not chargeable
                    }
                )
                
                logger.info(f"Successfully paused subscription {subscription_id} permanently")
                return True, None, pause_details
                
            else:
                # For temporary pause, calculate resume date based on remaining days
                now = datetime.now(timezone.utc)
                pause_until = now + timedelta(days=remaining_days) if remaining_days > 0 else now + timedelta(days=30)
                
                pause_details = {
                    "subscription_id": subscription_id,
                    "remaining_days": remaining_days,
                    "paused_at": now,
                    "pause_type": "temporary",
                    "resumes_at": pause_until
                }
                
                # Pause the subscription with specific resume date using keep_as_draft
                paused_subscription = stripe.Subscription.modify(
                    subscription_id,
                    pause_collection={
                        "behavior": "keep_as_draft",  # Invoices stay in draft, not chargeable
                        "resumes_at": int(pause_until.timestamp())
                    }
                )
                
                logger.info(f"Successfully paused subscription {subscription_id} until {pause_until}")
                return True, _safe_isoformat(pause_until), pause_details
            
        except Exception as e:
            logger.error(f"Error pausing Stripe subscription: {e}")
            return False, None, None
    
    async def _resume_stripe_subscription(self, subscription_id: str, new_end_date: datetime) -> Tuple[bool, Optional[str]]:
        """Resume Stripe subscription with new billing date"""
        try:
            if not stripe.api_key:
                logger.warning("Stripe not configured - skipping subscription resume")
                return True, None
            
            # Resume the subscription
            subscription = stripe.Subscription.modify(
                subscription_id,
                pause_collection=None,
                current_period_end=int(new_end_date.timestamp())
            )
            
            logger.info(f"Successfully resumed Stripe subscription {subscription_id}")
            return True, _safe_isoformat(new_end_date)
            
        except Exception as e:
            logger.error(f"Error resuming Stripe subscription: {e}")
            return False, None
    
    async def _cancel_stripe_subscription_and_refund(self, subscription_id: str, user_id: str = None) -> Tuple[bool, bool, Optional[float]]:
        """Cancel Stripe subscription and process refund"""
        try:
            if not stripe.api_key:
                logger.warning("Stripe not configured - skipping subscription cancellation")
                return True, False, None
            
            # Get subscription details
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            # Cancel the subscription
            stripe.Subscription.cancel(subscription_id)
            
            # Process refund for unused period
            refund_amount = None
            refund_processed = False
            
            try:
                # Calculate unused amount (simplified - you might need more complex logic)
                # This is a basic example - adjust based on your pricing model
                refund_amount = 10.0  # Example amount
                
                # Create refund
                refund = stripe.Refund.create(
                    payment_intent=subscription.latest_invoice,
                    amount=int(refund_amount * 100),  # Convert to cents
                    metadata={
                        'refund_type': 'account_deletion_refund',
                        'service': 'auth',
                        'user_id': user_id,
                        'reason': 'account_deletion',
                        'payment_type': 'refund'
                    }
                )
                
                refund_processed = True
                logger.info(f"Successfully processed refund of ${refund_amount}")
                
            except Exception as refund_error:
                logger.error(f"Error processing refund: {refund_error}")
                refund_processed = False
            
            logger.info(f"Successfully cancelled Stripe subscription {subscription_id}")
            return True, refund_processed, refund_amount
            
        except Exception as e:
            logger.error(f"Error cancelling Stripe subscription: {e}")
            return False, False, None
    
    # Email notification methods
    async def _send_temporary_deletion_email(self, member: Dict, club: Dict, reason: Optional[str]):
        """Send email notification for temporary deletion"""
        try:
            subject = f"Membership Temporarily Suspended - {club.get('name', 'Club')}"
            body = f"""
Dear {member.get('full_name', 'Member')},

Your membership in {club.get('name', 'the club')} has been temporarily suspended.

{f'Reason: {reason}' if reason else ''}

Your membership can be reactivated by the club captain. You will retain any unused days from your subscription period.

If you have any questions, please contact the club captain.

Best regards,
The Club Team
            """
            
            await send_email(member.get('email', ''), subject, body)
            logger.info(f"Temporary deletion email sent to {member.get('email', '')}")
            
        except Exception as e:
            logger.error(f"Error sending temporary deletion email: {e}")
    
    async def _send_permanent_deletion_email(self, member: Dict, club: Dict, reason: Optional[str], refund_amount: Optional[float]):
        """Send email notification for permanent deletion"""
        try:
            subject = f"Membership Cancelled - {club.get('name', 'Club')}"
            body = f"""
Dear {member.get('full_name', 'Member')},

Your membership in {club.get('name', 'the club')} has been permanently cancelled.

{f'Reason: {reason}' if reason else ''}

{f'Refund Amount: ${refund_amount:.2f}' if refund_amount else 'No refund applicable.'}

Thank you for being part of our community.

Best regards,
The Club Team
            """
            
            await send_email(member.get('email', ''), subject, body)
            logger.info(f"Permanent deletion email sent to {member.get('email', '')}")
            
        except Exception as e:
            logger.error(f"Error sending permanent deletion email: {e}")
    
    async def _send_reactivation_email(self, member: Dict, club: Dict, unused_days: int):
        """Send email notification for reactivation"""
        try:
            subject = f"Membership Reactivated - {club.get('name', 'Club')}"
            body = f"""
Dear {member.get('full_name', 'Member')},

Your membership in {club.get('name', 'the club')} has been reactivated.

{f'Unused Days Applied: {unused_days} days' if unused_days > 0 else ''}

Your billing has been resumed and will continue according to your subscription plan.

Welcome back!

Best regards,
The Club Team
            """
            
            await send_email(member.get('email', ''), subject, body)
            logger.info(f"Reactivation email sent to {member.get('email', '')}")
            
        except Exception as e:
            logger.error(f"Error sending reactivation email: {e}")
    
    async def _unpause_subscription_with_free_extension(self, subscription_id: str, pause_details: Dict) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Unpause subscription and apply unused days as free extension"""
        try:
            if not stripe.api_key:
                logger.warning("Stripe not configured - skipping subscription unpause")
                return True, None, None
            
            logger.info(f"Unpausing subscription {subscription_id} with free extension")
            
            # Get current subscription details
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            # Calculate the free extension period
            unused_days = pause_details.get("remaining_days", 0)
            now = datetime.now(timezone.utc)
            
            if unused_days > 0:
                # Calculate trial end date (current time + unused days)
                trial_end_timestamp = int(now.timestamp()) + (unused_days * 86400)
                
                logger.info(f"Applying {unused_days} unused days as trial extension until {datetime.fromtimestamp(trial_end_timestamp, tz=timezone.utc)}")
                
                # Clear pause and set trial period for free extension
                updated_subscription = stripe.Subscription.modify(
                    subscription_id,
                    pause_collection="",  # Clear the pause
                    trial_end=trial_end_timestamp,  # Set trial period for unused days
                    proration_behavior="none"  # No proration for trial period
                )
                
                free_extension_end = datetime.fromtimestamp(trial_end_timestamp, tz=timezone.utc)
                logger.info(f"Successfully unpaused subscription with {unused_days} days trial extension")
                
                return True, _safe_isoformat(free_extension_end), {
                    "subscription_id": subscription_id,
                    "free_extension_days": unused_days,
                    "free_extension_until": free_extension_end,
                    "next_billing_date": free_extension_end,
                    "unpause_date": now,
                    "trial_end_timestamp": trial_end_timestamp
                }
            else:
                # No unused days, just clear the pause
                updated_subscription = stripe.Subscription.modify(
                    subscription_id,
                    pause_collection=""  # Clear the pause
                )
                
                logger.info(f"Successfully unpaused subscription (no unused days)")
                
                return True, None, {
                    "subscription_id": subscription_id,
                    "free_extension_days": 0,
                    "unpause_date": now
                }
            
        except Exception as e:
            logger.error(f"Error unpausing subscription with free extension: {e}")
            return False, None, None
    
    async def admin_unpause_subscription(self, member_id: str, club_id: str, admin_user: Dict) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """Admin endpoint to unpause a permanently paused subscription with free extension"""
        try:
            logger.info(f"Admin unpause request for member {member_id} in club {club_id}")
            
            # Ensure collections are initialized
            self._ensure_collections_initialized()
            
            # Check if user is admin
            if admin_user.get("role") != "Admin":
                return False, None, "Only admins can unpause subscriptions"
            
            # Get member details
            member = await self._users_collection.find_one({"_id": ObjectId(member_id)})
            if not member:
                return False, None, "Member not found"
            
            # Get club details
            club = await self._clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                return False, None, "Club not found"
            
            # Find the inactive membership
            member_membership = await self._find_inactive_member_membership(member, club_id)
            if not member_membership:
                return False, None, "No inactive membership found for this member in this club"
            
            # Check if it's a paid membership with pause details
            if member_membership.get("membership_type") != "paid":
                return False, None, "Only paid memberships can be unpaused"
            
            # Get pause details from usage stats
            usage_stats = member_membership.get("usage_stats", {})
            pause_details = usage_stats.get("pause_details", {})
            
            if pause_details.get("pause_type") != "permanent":
                return False, None, "Only permanently paused subscriptions can be unpaused by admin"
            
            subscription_id = pause_details.get("subscription_id")
            if not subscription_id:
                return False, None, "No subscription ID found for this membership"
            
            # Unpause subscription with free extension
            unpause_success, next_billing_date, unpause_details = await self._unpause_subscription_with_free_extension(
                subscription_id, pause_details
            )
            
            if not unpause_success:
                return False, None, "Failed to unpause subscription in Stripe"
            
            # Update member status back to active
            now = datetime.utcnow()
            
            # Update user status
            await self._users_collection.update_one(
                {"_id": ObjectId(member_id)},
                {
                    "$set": {
                        "status": "active",
                        "membership_status": "active",
                        "updated_at": now
                    }
                }
            )
            
            # Update club membership status
            await self._clubs_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "members.user_id": ObjectId(member_id)
                },
                {
                    "$set": {
                        "members.$.membership_status": "active",
                        "members.$.status": "active",
                        "members.$.updated_at": now,
                        "members.$.unpause_details": unpause_details
                    }
                }
            )
            
            # Update club_memberships collection
            await self._membership_collection.update_one(
                {
                    "user_id": ObjectId(member_id),
                    "club_id": ObjectId(club_id)
                },
                {
                    "$set": {
                        "status": "active",
                        "membership_status": "active",
                        "updated_at": now,
                        "unpause_details": unpause_details
                    }
                }
            )
            
            # Send notification email
            await self._send_admin_unpause_email(member, club, unpause_details)
            
            # Serialize unpause_details to ensure no datetime objects
            serialized_unpause_details = _serialize_dict_datetimes(unpause_details)
            
            response_data = {
                "success": True,
                "message": f"Subscription unpaused with {unpause_details.get('free_extension_days', 0)} days free extension",
                "member_id": member_id,
                "club_id": club_id,
                "club_name": club.get("name", "Unknown"),
                "member_name": member.get("full_name", "Unknown"),
                "member_email": member.get("email", ""),
                "subscription_id": subscription_id,
                "free_extension_days": unpause_details.get("free_extension_days", 0),
                "free_extension_until": _safe_isoformat(unpause_details.get("free_extension_until")),
                "next_billing_date": _safe_isoformat(unpause_details.get("next_billing_date")),
                "unpause_date": _safe_isoformat(unpause_details.get("unpause_date")),
                "unpause_details": serialized_unpause_details
            }
            
            logger.info(f"Successfully unpaused subscription for member {member_id} with free extension")
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error in admin_unpause_subscription: {e}")
            return False, None, f"Internal error: {str(e)}"
    
    async def _send_admin_unpause_email(self, member: Dict, club: Dict, unpause_details: Dict):
        """Send email notification for admin unpause"""
        try:
            free_extension_days = unpause_details.get("free_extension_days", 0)
            next_billing_date = unpause_details.get("next_billing_date")
            
            subject = f"Subscription Unpaused - {club.get('name', 'Club')}"
            body = f"""
Dear {member.get('full_name', 'Member')},

Your subscription in {club.get('name', 'the club')} has been unpaused by an administrator.

{f'Free Extension: You have received {free_extension_days} days as a free extension.' if free_extension_days > 0 else ''}

{f'Next billing date: {next_billing_date}' if next_billing_date else ''}

Your membership is now active and you can enjoy all club benefits.

Welcome back!

Best regards,
The Club Team
            """
            
            await send_email(member.get('email', ''), subject, body)
            logger.info(f"Admin unpause email sent to {member.get('email', '')}")
            
        except Exception as e:
            logger.error(f"Error sending admin unpause email: {e}")
    
    async def _resume_stripe_subscription_with_trial(self, subscription_id: str, unused_days: int) -> Tuple[bool, Optional[str]]:
        """Resume Stripe subscription with trial period for unused days (Captain reactivation)"""
        try:
            if not stripe.api_key:
                logger.warning("Stripe not configured - skipping subscription resume")
                return True, None
            
            logger.info(f"Resuming Stripe subscription {subscription_id} with {unused_days} unused days as trial")
            
            if unused_days > 0:
                # Calculate trial end timestamp (current time + unused days in seconds)
                now = datetime.now(timezone.utc)
                trial_end_timestamp = int(now.timestamp()) + (unused_days * 86400)
                
                logger.info(f"Applying {unused_days} unused days as trial period until {datetime.fromtimestamp(trial_end_timestamp, tz=timezone.utc)}")
                
                # Resume subscription with trial period for unused days
                updated_subscription = stripe.Subscription.modify(
                    subscription_id,
                    pause_collection="",  # Clear the pause
                    trial_end=trial_end_timestamp,  # Set trial period for unused days
                    proration_behavior="none"  # No proration for trial period
                )
                
                trial_end_date = datetime.fromtimestamp(trial_end_timestamp, tz=timezone.utc)
                logger.info(f"Successfully resumed subscription with {unused_days} days trial period")
                
                return True, _safe_isoformat(trial_end_date)
            else:
                # No unused days, just clear the pause
                updated_subscription = stripe.Subscription.modify(
                    subscription_id,
                    pause_collection=""  # Clear the pause
                )
                
                logger.info(f"Successfully resumed subscription (no unused days)")
                
                return True, None
            
        except Exception as e:
            logger.error(f"Error resuming Stripe subscription with trial: {e}")
            return False, None

# Global service instance with lazy initialization
_member_deletion_service: MemberDeletionService = None

def get_member_deletion_service() -> MemberDeletionService:
    """Get the global member deletion service instance"""
    global _member_deletion_service
    if _member_deletion_service is None:
        _member_deletion_service = MemberDeletionService()
    return _member_deletion_service
