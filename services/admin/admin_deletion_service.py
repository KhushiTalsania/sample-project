"""
Admin Deletion Service

This service handles admin deletion and reactivation of users (members, captains, moderators)
with comprehensive Stripe integration and proper flag management.
"""

import stripe
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
from bson import ObjectId
from services.admin.utils.email import send_email
from services.admin.models import (
    AdminDeletionRequest, AdminDeletionResponse, AdminReactivationRequest, AdminReactivationResponse,
    AdminDeletionUserRole, AdminDeletionType
)
from services.admin.db import (
    users_collection, clubs_collection, club_memberships_collection,
    club_payments_collection, club_admin_logs_collection
)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

class AdminDeletionService:
    """Service for handling admin deletion and reactivation of users"""
    
    def __init__(self):
        self.users_collection = users_collection
        self.clubs_collection = clubs_collection
        self.club_memberships_collection = club_memberships_collection
        self.club_payments_collection = club_payments_collection
        self.club_admin_logs_collection = club_admin_logs_collection

    async def delete_user(self, request: AdminDeletionRequest, admin_email: str, ip_address: Optional[str] = None) -> AdminDeletionResponse:
        """
        Delete a user (member/captain/moderator) with comprehensive Stripe integration
        
        Args:
            request: AdminDeletionRequest with deletion details
            admin_email: Admin email performing the action
            ip_address: IP address for audit logging
            
        Returns:
            AdminDeletionResponse with operation results
        """
        try:
            print(f"Processing admin deletion for user {request.user_id} ({request.user_role.value})")
            
            # Validate user exists
            user_doc = await self.users_collection.find_one({"_id": ObjectId(request.user_id)})
            if not user_doc:
                return AdminDeletionResponse(
                    success=False,
                    message="User not found",
                    user_id=request.user_id,
                    user_role=request.user_role,
                    deletion_type=request.deletion_type,
                    previous_status="unknown",
                    new_status="unknown",
                    admin_email=admin_email,
                    timestamp=datetime.utcnow(),
                    deletion_id=""
                )
            
            previous_status = user_doc.get("status", "active")
            deletion_id = str(ObjectId())
            
            # Initialize response data
            affected_clubs = []
            affected_members = []
            stripe_actions = []
            
            # Process deletion based on user role
            if request.user_role == AdminDeletionUserRole.CAPTAIN:
                result = await self._delete_captain(user_doc, request, admin_email)
            elif request.user_role == AdminDeletionUserRole.MEMBER:
                result = await self._delete_member(user_doc, request, admin_email)
            elif request.user_role == AdminDeletionUserRole.MODERATOR:
                result = await self._delete_moderator(user_doc, request, admin_email)
            else:
                return AdminDeletionResponse(
                    success=False,
                    message=f"Invalid user role: {request.user_role}",
                    user_id=request.user_id,
                    user_role=request.user_role,
                    deletion_type=request.deletion_type,
                    previous_status=previous_status,
                    new_status=previous_status,
                    admin_email=admin_email,
                    timestamp=datetime.utcnow(),
                    deletion_id=deletion_id
                )
            
            # Extract results
            success = result.get("success", False)
            message = result.get("message", "Deletion completed")
            affected_clubs = result.get("affected_clubs", [])
            affected_members = result.get("affected_members", [])
            stripe_actions = result.get("stripe_actions", [])
            
            # Send notification if requested
            notification_sent = False
            if request.notify_user and success:
                notification_sent = await self._send_deletion_notification(
                    user_doc, request, admin_email
                )
            
            # Log the deletion action
            await self._log_deletion_action(
                request, admin_email, previous_status, deletion_id, ip_address,
                affected_clubs, affected_members, stripe_actions
            )
            
            return AdminDeletionResponse(
                success=success,
                message=message,
                user_id=request.user_id,
                user_role=request.user_role,
                deletion_type=request.deletion_type,
                previous_status=previous_status,
                new_status="deleted" if request.deletion_type == AdminDeletionType.PERMANENT else "inactive",
                affected_clubs=affected_clubs,
                affected_members=affected_members,
                stripe_actions=stripe_actions,
                notification_sent=notification_sent,
                admin_email=admin_email,
                timestamp=datetime.utcnow(),
                deletion_id=deletion_id
            )
            
        except Exception as e:
            print(f"Error in delete_user: {e}")
            return AdminDeletionResponse(
                success=False,
                message=f"Failed to delete user: {str(e)}",
                user_id=request.user_id,
                user_role=request.user_role,
                deletion_type=request.deletion_type,
                previous_status="unknown",
                new_status="unknown",
                admin_email=admin_email,
                timestamp=datetime.utcnow(),
                deletion_id=""
            )

    async def reactivate_user(self, request: AdminReactivationRequest, admin_email: str, ip_address: Optional[str] = None) -> AdminReactivationResponse:
        """
        Reactivate a temporarily deleted user with proper Stripe integration
        
        Args:
            request: AdminReactivationRequest with reactivation details
            admin_email: Admin email performing the action
            ip_address: IP address for audit logging
            
        Returns:
            AdminReactivationResponse with operation results
        """
        try:
            print(f"Processing admin reactivation for user {request.user_id} ({request.user_role.value})")
            
            # Validate user exists
            user_doc = await self.users_collection.find_one({"_id": ObjectId(request.user_id)})
            if not user_doc:
                return AdminReactivationResponse(
                    success=False,
                    message="User not found",
                    user_id=request.user_id,
                    user_role=request.user_role,
                    previous_status="unknown",
                    new_status="unknown",
                    admin_email=admin_email,
                    timestamp=datetime.utcnow(),
                    reactivation_id=""
                )
            
            previous_status = user_doc.get("status", "inactive")
            reactivation_id = str(ObjectId())
            
            # Initialize response data
            affected_clubs = []
            affected_members = []
            stripe_actions = []
            
            # Process reactivation based on user role
            if request.user_role == AdminDeletionUserRole.CAPTAIN:
                result = await self._reactivate_captain(user_doc, request, admin_email)
            elif request.user_role == AdminDeletionUserRole.MEMBER:
                result = await self._reactivate_member(user_doc, request, admin_email)
            elif request.user_role == AdminDeletionUserRole.MODERATOR:
                result = await self._reactivate_moderator(user_doc, request, admin_email)
            else:
                return AdminReactivationResponse(
                    success=False,
                    message=f"Invalid user role: {request.user_role}",
                    user_id=request.user_id,
                    user_role=request.user_role,
                    previous_status=previous_status,
                    new_status=previous_status,
                    admin_email=admin_email,
                    timestamp=datetime.utcnow(),
                    reactivation_id=reactivation_id
                )
            
            # Extract results
            success = result.get("success", False)
            message = result.get("message", "Reactivation completed")
            affected_clubs = result.get("affected_clubs", [])
            affected_members = result.get("affected_members", [])
            stripe_actions = result.get("stripe_actions", [])
            
            # Send notification if requested
            notification_sent = False
            if request.notify_user and success:
                notification_sent = await self._send_reactivation_notification(
                    user_doc, request, admin_email
                )
            
            # Log the reactivation action
            await self._log_reactivation_action(
                request, admin_email, previous_status, reactivation_id, ip_address,
                affected_clubs, affected_members, stripe_actions
            )
            
            return AdminReactivationResponse(
                success=success,
                message=message,
                user_id=request.user_id,
                user_role=request.user_role,
                previous_status=previous_status,
                new_status="active",
                affected_clubs=affected_clubs,
                affected_members=affected_members,
                stripe_actions=stripe_actions,
                notification_sent=notification_sent,
                admin_email=admin_email,
                timestamp=datetime.utcnow(),
                reactivation_id=reactivation_id
            )
            
        except Exception as e:
            print(f"Error in reactivate_user: {e}")
            return AdminReactivationResponse(
                success=False,
                message=f"Failed to reactivate user: {str(e)}",
                user_id=request.user_id,
                user_role=request.user_role,
                previous_status="unknown",
                new_status="unknown",
                admin_email=admin_email,
                timestamp=datetime.utcnow(),
                reactivation_id=""
            )

    async def _delete_captain(self, user_doc: Dict, request: AdminDeletionRequest, admin_email: str) -> Dict:
        """Delete a captain and handle all associated clubs and members"""
        try:
            captain_id = str(user_doc["_id"])
            affected_clubs = []
            affected_members = []
            stripe_actions = []
            
            # Find all clubs created by this captain
            clubs_cursor = self.clubs_collection.find({"captain_id": captain_id})
            clubs = await clubs_cursor.to_list(None)
            
            print(f"Found {len(clubs)} clubs for captain {captain_id}")
            
            for club in clubs:
                club_id = str(club["_id"])
                affected_clubs.append(club_id)
                
                if request.deletion_type == AdminDeletionType.PERMANENT:
                    # Permanent deletion - delete club and all members
                    result = await self._permanently_delete_captain_club(club, admin_email)
                else:
                    # Temporary deletion - pause club and all members
                    result = await self._temporarily_delete_captain_club(club, admin_email)
                
                affected_members.extend(result.get("affected_members", []))
                stripe_actions.extend(result.get("stripe_actions", []))
            
            # Update captain status
            if request.deletion_type == AdminDeletionType.PERMANENT:
                await self.users_collection.update_one(
                    {"_id": ObjectId(captain_id)},
                    {
                        "$set": {
                            "status": "deleted",
                            "membership_status": "deleted",
                            "is_deleted_per_admin": True,
                            "is_deleted_temp_admin": False,
                            "deleted_at": datetime.utcnow(),
                            "deleted_by": admin_email,
                            "deletion_reason": request.reason,
                            "admin_notes": request.admin_notes
                        }
                    }
                )
            else:
                await self.users_collection.update_one(
                    {"_id": ObjectId(captain_id)},
                    {
                        "$set": {
                            "status": "inactive",
                            "membership_status": "inactive",
                            "is_deleted_per_admin": False,
                            "is_deleted_temp_admin": True,
                            "deactivated_at": datetime.utcnow(),
                            "deactivated_by": admin_email,
                            "deactivation_reason": request.reason,
                            "admin_notes": request.admin_notes
                        }
                    }
                )
            
            return {
                "success": True,
                "message": f"Captain {request.deletion_type.value} deletion completed",
                "affected_clubs": affected_clubs,
                "affected_members": affected_members,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _delete_captain: {e}")
            return {
                "success": False,
                "message": f"Failed to delete captain: {str(e)}",
                "affected_clubs": [],
                "affected_members": [],
                "stripe_actions": []
            }

    async def _delete_member(self, user_doc: Dict, request: AdminDeletionRequest, admin_email: str) -> Dict:
        """Delete a member and handle all club memberships"""
        try:
            member_id = str(user_doc["_id"])
            affected_clubs = []
            affected_members = [member_id]
            stripe_actions = []
            
            # Find all clubs the member has joined
            clubs_joined = user_doc.get("clubs_joined", [])
            
            print(f"Found {len(clubs_joined)} clubs for member {member_id}")
            
            for club_membership in clubs_joined:
                club_id = club_membership.get("club_id")
                if not club_id:
                    continue
                
                affected_clubs.append(club_id)
                
                # Get club details
                club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                if not club_doc:
                    continue
                
                if request.deletion_type == AdminDeletionType.PERMANENT:
                    # Permanent deletion - remove from all clubs
                    result = await self._permanently_delete_member_from_club(
                        member_id, club_doc, club_membership, admin_email
                    )
                else:
                    # Temporary deletion - pause membership
                    result = await self._temporarily_delete_member_from_club(
                        member_id, club_doc, club_membership, admin_email
                    )
                
                stripe_actions.extend(result.get("stripe_actions", []))
            
            # Update member status
            if request.deletion_type == AdminDeletionType.PERMANENT:
                await self.users_collection.update_one(
                    {"_id": ObjectId(member_id)},
                    {
                        "$set": {
                            "status": "deleted",
                            "membership_status": "deleted",
                            "is_deleted_per_admin": True,
                            "is_deleted_temp_admin": False,
                            "deleted_at": datetime.utcnow(),
                            "deleted_by": admin_email,
                            "deletion_reason": request.reason,
                            "admin_notes": request.admin_notes
                        }
                    }
                )
            else:
                await self.users_collection.update_one(
                    {"_id": ObjectId(member_id)},
                    {
                        "$set": {
                            "status": "inactive",
                            "membership_status": "inactive",
                            "is_deleted_per_admin": False,
                            "is_deleted_temp_admin": True,
                            "deactivated_at": datetime.utcnow(),
                            "deactivated_by": admin_email,
                            "deactivation_reason": request.reason,
                            "admin_notes": request.admin_notes
                        }
                    }
                )
            
            return {
                "success": True,
                "message": f"Member {request.deletion_type.value} deletion completed",
                "affected_clubs": affected_clubs,
                "affected_members": affected_members,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _delete_member: {e}")
            return {
                "success": False,
                "message": f"Failed to delete member: {str(e)}",
                "affected_clubs": [],
                "affected_members": [],
                "stripe_actions": []
            }

    async def _delete_moderator(self, user_doc: Dict, request: AdminDeletionRequest, admin_email: str) -> Dict:
        """Delete a moderator and handle all moderator roles"""
        try:
            moderator_id = str(user_doc["_id"])
            affected_clubs = []
            affected_members = [moderator_id]
            stripe_actions = []
            
            # Find all clubs where this user is a moderator
            clubs_cursor = self.clubs_collection.find({
                "$or": [
                    {"moderators": {"$elemMatch": {"user_id": moderator_id}}},
                    {"paid_moderators": {"$elemMatch": {"user_id": moderator_id}}}
                ]
            })
            clubs = await clubs_cursor.to_list(None)
            
            print(f"Found {len(clubs)} clubs for moderator {moderator_id}")
            
            for club in clubs:
                club_id = str(club["_id"])
                affected_clubs.append(club_id)
                
                if request.deletion_type == AdminDeletionType.PERMANENT:
                    # Permanent deletion - remove moderator from club
                    await self._permanently_delete_moderator_from_club(moderator_id, club_id, admin_email)
                else:
                    # Temporary deletion - set moderator as inactive
                    await self._temporarily_delete_moderator_from_club(moderator_id, club_id, admin_email)
            
            # Update moderator status
            if request.deletion_type == AdminDeletionType.PERMANENT:
                await self.users_collection.update_one(
                    {"_id": ObjectId(moderator_id)},
                    {
                        "$set": {
                            "status": "deleted",
                            "membership_status": "deleted",
                            "is_deleted_per_admin": True,
                            "is_deleted_temp_admin": False,
                            "deleted_at": datetime.utcnow(),
                            "deleted_by": admin_email,
                            "deletion_reason": request.reason,
                            "admin_notes": request.admin_notes
                        }
                    }
                )
            else:
                await self.users_collection.update_one(
                    {"_id": ObjectId(moderator_id)},
                    {
                        "$set": {
                            "status": "inactive",
                            "membership_status": "inactive",
                            "is_deleted_per_admin": False,
                            "is_deleted_temp_admin": True,
                            "deactivated_at": datetime.utcnow(),
                            "deactivated_by": admin_email,
                            "deactivation_reason": request.reason,
                            "admin_notes": request.admin_notes
                        }
                    }
                )
            
            return {
                "success": True,
                "message": f"Moderator {request.deletion_type.value} deletion completed",
                "affected_clubs": affected_clubs,
                "affected_members": affected_members,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _delete_moderator: {e}")
            return {
                "success": False,
                "message": f"Failed to delete moderator: {str(e)}",
                "affected_clubs": [],
                "affected_members": [],
                "stripe_actions": []
            }

    async def _temporarily_delete_captain_club(self, club: Dict, admin_email: str) -> Dict:
        """Temporarily delete a captain's club and pause all memberships"""
        try:
            club_id = str(club["_id"])
            affected_members = []
            stripe_actions = []
            
            print(f"Temporarily deleting club {club_id}")
            
            # Update club status to inactive
            await self.clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {
                    "$set": {
                        "status": "inactive",
                        "is_paused_by_admin": True,
                        "paused_at": datetime.utcnow(),
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
                    try:
                        # Archive the product to make it inactive
                        stripe.Product.modify(
                            stripe_product_id,
                            active=False
                        )
                        
                        stripe_actions.append({
                            "action": "product_archived",
                            "product_id": stripe_product_id,
                            "club_id": club_id,
                            "plan_frequency": plan.get("frequency")
                        })
                        
                    except Exception as e:
                        print(f"Error archiving Stripe product {stripe_product_id}: {e}")
                        stripe_actions.append({
                            "action": "product_archive_failed",
                            "product_id": stripe_product_id,
                            "club_id": club_id,
                            "error": str(e)
                        })
            
            # Handle paid members - pause their Stripe subscriptions with usage calculation
            paid_members = club.get("paid_members", [])
            for member in paid_members:
                member_id = member.get("user_id")
                if not member_id:
                    continue
                    
                affected_members.append(member_id)
                
                # Calculate usage stats for this member
                usage_stats = await self._calculate_member_usage_stats(member, datetime.now(timezone.utc))
                
                # Pause Stripe subscription if exists
                subscription_id = await self._get_member_subscription_id(member)
                if subscription_id:
                    try:
                        # Pause subscription with keep_as_draft behavior
                        stripe.Subscription.modify(
                            subscription_id,
                            pause_collection={
                                "behavior": "keep_as_draft"  # Invoices stay in draft, not chargeable
                            }
                        )
                        
                        stripe_actions.append({
                            "action": "subscription_paused",
                            "subscription_id": subscription_id,
                            "member_id": member_id,
                            "club_id": club_id,
                            "pause_type": "permanent"
                        })
                        
                    except Exception as e:
                        print(f"Error pausing Stripe subscription for member {member_id}: {e}")
                        stripe_actions.append({
                            "action": "subscription_pause_failed",
                            "member_id": member_id,
                            "club_id": club_id,
                            "error": str(e)
                        })
                
                # Update member status in club with usage stats
                await self.clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_members.user_id": member_id
                    },
                    {
                        "$set": {
                            "paid_members.$.membership_status": "inactive",
                            "paid_members.$.is_temporarily_deleted": True,
                            "paid_members.$.deletion_date": datetime.now(timezone.utc),
                            "paid_members.$.usage_stats": usage_stats,
                            "paid_members.$.paused_at": datetime.now(timezone.utc),
                            "paid_members.$.paused_by": admin_email,
                            "paid_members.$.paused_reason": "Captain temporarily deleted",
                            "paid_members.$.subscription_id": subscription_id
                        }
                    }
                )
                
                # Update user's clubs_joined array
                await self.users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "inactive",
                            "clubs_joined.$.is_temporarily_deleted": True,
                            "clubs_joined.$.deletion_date": datetime.now(timezone.utc),
                            "clubs_joined.$.usage_stats": usage_stats,
                            "clubs_joined.$.subscription_id": subscription_id
                        }
                    }
                )
            
            # Handle trial members - pause their trial memberships
            trial_members = club.get("members", [])
            for member in trial_members:
                member_id = member.get("user_id")
                if not member_id:
                    continue
                    
                if member_id not in affected_members:
                    affected_members.append(member_id)
                
                # Calculate usage stats for trial member
                usage_stats = await self._calculate_trial_member_usage_stats(member, datetime.now(timezone.utc))
                
                # Update trial member status in club
                await self.clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "inactive",
                            "members.$.is_temporarily_deleted": True,
                            "members.$.deletion_date": datetime.now(timezone.utc),
                            "members.$.usage_stats": usage_stats,
                            "members.$.paused_at": datetime.now(timezone.utc),
                            "members.$.paused_by": admin_email,
                            "members.$.paused_reason": "Captain temporarily deleted"
                        }
                    }
                )
                
                # Update user's clubs_joined array
                await self.users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "inactive",
                            "clubs_joined.$.is_temporarily_deleted": True,
                            "clubs_joined.$.deletion_date": datetime.now(timezone.utc),
                            "clubs_joined.$.usage_stats": usage_stats
                        }
                    }
                )
                
                # Update user's trial membership status
                await self.users_collection.update_one(
                    {"_id": ObjectId(member_id)},
                    {
                        "$set": {
                            "trial_membership_paused": True,
                            "trial_paused_at": datetime.now(timezone.utc),
                            "trial_paused_by": admin_email,
                            "trial_paused_reason": "Captain temporarily deleted"
                        }
                    }
                )
            
            return {
                "success": True,
                "affected_members": affected_members,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _temporarily_delete_captain_club: {e}")
            return {
                "success": False,
                "affected_members": [],
                "stripe_actions": []
            }

    async def _permanently_delete_captain_club(self, club: Dict, admin_email: str) -> Dict:
        """Permanently delete a captain's club and all memberships"""
        try:
            club_id = str(club["_id"])
            affected_members = []
            stripe_actions = []
            
            print(f"Permanently deleting club {club_id}")
            
            # Cancel all Stripe subscriptions for paid members
            paid_members = club.get("paid_members", [])
            for member in paid_members:
                member_id = member.get("user_id")
                if not member_id:
                    continue
                    
                affected_members.append(member_id)
                
                # Cancel Stripe subscription if exists
                payment_id = member.get("payment_id")
                if payment_id:
                    try:
                        # Get subscription from Stripe
                        subscription = stripe.Subscription.list(
                            customer=member.get("stripe_customer_id"),
                            status="active",
                            limit=1
                        )
                        
                        if subscription.data:
                            sub_id = subscription.data[0].id
                            
                            # Cancel subscription
                            stripe.Subscription.modify(
                                sub_id,
                                cancel_at_period_end=True
                            )
                            
                            stripe_actions.append({
                                "action": "subscription_cancelled",
                                "subscription_id": sub_id,
                                "member_id": member_id,
                                "club_id": club_id
                            })
                            
                    except Exception as e:
                        print(f"Error cancelling Stripe subscription for member {member_id}: {e}")
                        stripe_actions.append({
                            "action": "subscription_cancel_failed",
                            "member_id": member_id,
                            "club_id": club_id,
                            "error": str(e)
                        })
            
            # Add trial members to affected list
            trial_members = club.get("members", [])
            for member in trial_members:
                member_id = member.get("user_id")
                if member_id and member_id not in affected_members:
                    affected_members.append(member_id)
            
            # Delete the club
            await self.clubs_collection.delete_one({"_id": ObjectId(club_id)})
            
            return {
                "success": True,
                "affected_members": affected_members,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _permanently_delete_captain_club: {e}")
            return {
                "success": False,
                "affected_members": [],
                "stripe_actions": []
            }

    async def _temporarily_delete_member_from_club(self, member_id: str, club_doc: Dict, 
                                                   club_membership: Dict, admin_email: str) -> Dict:
        """Temporarily delete a member from a club and pause their subscription"""
        try:
            club_id = str(club_doc["_id"])
            stripe_actions = []
            
            print(f"Temporarily deleting member {member_id} from club {club_id}")
            
            # Check if it's a paid membership
            if club_membership.get("membership_type") == "paid":
                payment_id = club_membership.get("payment_id")
                if payment_id:
                    try:
                        # Get payment intent to find subscription
                        payment_intent = stripe.PaymentIntent.retrieve(payment_id)
                        subscription_id = payment_intent.get("subscription")
                        
                        if subscription_id:
                            # Pause subscription
                            stripe.Subscription.modify(
                                subscription_id,
                                pause_collection={
                                    "behavior": "mark_uncollectible",
                                    "resumes_at": None
                                }
                            )
                            
                            stripe_actions.append({
                                "action": "subscription_paused",
                                "subscription_id": subscription_id,
                                "member_id": member_id,
                                "club_id": club_id
                            })
                        else:
                            # If no subscription, try to find by customer
                            customer_id = club_membership.get("stripe_customer_id")
                            if customer_id:
                                subscriptions = stripe.Subscription.list(
                                    customer=customer_id,
                                    status="active",
                                    limit=1
                                )
                                
                                if subscriptions.data:
                                    sub_id = subscriptions.data[0].id
                                    stripe.Subscription.modify(
                                        sub_id,
                                        pause_collection={
                                            "behavior": "mark_uncollectible",
                                            "resumes_at": None
                                        }
                                    )
                                    
                                    stripe_actions.append({
                                        "action": "subscription_paused",
                                        "subscription_id": sub_id,
                                        "member_id": member_id,
                                        "club_id": club_id
                                    })
                            
                    except Exception as e:
                        print(f"Error pausing Stripe subscription for member {member_id}: {e}")
                        stripe_actions.append({
                            "action": "subscription_pause_failed",
                            "member_id": member_id,
                            "club_id": club_id,
                            "error": str(e)
                        })
                
                # Update paid member status in club
                await self.clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_members.user_id": member_id
                    },
                    {
                        "$set": {
                            "paid_members.$.membership_status": "paused",
                            "paid_members.$.paused_at": datetime.utcnow(),
                            "paid_members.$.paused_by": admin_email,
                            "paid_members.$.paused_reason": "Member temporarily deleted"
                        }
                    }
                )
            else:
                # Trial membership - update status
                await self.clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "paused",
                            "members.$.paused_at": datetime.utcnow(),
                            "members.$.paused_by": admin_email,
                            "members.$.paused_reason": "Member temporarily deleted"
                        }
                    }
                )
            
            return {
                "success": True,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _temporarily_delete_member_from_club: {e}")
            return {
                "success": False,
                "stripe_actions": []
            }

    async def _permanently_delete_member_from_club(self, member_id: str, club_doc: Dict, 
                                                   club_membership: Dict, admin_email: str) -> Dict:
        """Permanently delete a member from a club and cancel their subscription"""
        try:
            club_id = str(club_doc["_id"])
            stripe_actions = []
            
            print(f"Permanently deleting member {member_id} from club {club_id}")
            
            # Check if it's a paid membership
            if club_membership.get("membership_type") == "paid":
                payment_id = club_membership.get("payment_id")
                if payment_id:
                    try:
                        # Get subscription from Stripe
                        subscription = stripe.Subscription.list(
                            customer=club_membership.get("stripe_customer_id"),
                            status="active",
                            limit=1
                        )
                        
                        if subscription.data:
                            sub_id = subscription.data[0].id
                            
                            # Cancel subscription
                            stripe.Subscription.modify(
                                sub_id,
                                cancel_at_period_end=True
                            )
                            
                            stripe_actions.append({
                                "action": "subscription_cancelled",
                                "subscription_id": sub_id,
                                "member_id": member_id,
                                "club_id": club_id
                            })
                            
                    except Exception as e:
                        print(f"Error cancelling Stripe subscription for member {member_id}: {e}")
                        stripe_actions.append({
                            "action": "subscription_cancel_failed",
                            "member_id": member_id,
                            "club_id": club_id,
                            "error": str(e)
                        })
                
                # Remove from paid members
                await self.clubs_collection.update_one(
                    {"_id": ObjectId(club_id)},
                    {"$pull": {"paid_members": {"user_id": member_id}}}
                )
            else:
                # Remove from trial members
                await self.clubs_collection.update_one(
                    {"_id": ObjectId(club_id)},
                    {"$pull": {"members": {"user_id": member_id}}}
                )
            
            # Update member count
            await self.clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {"$inc": {"total_members": -1}}
            )
            
            return {
                "success": True,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _permanently_delete_member_from_club: {e}")
            return {
                "success": False,
                "stripe_actions": []
            }

    async def _temporarily_delete_moderator_from_club(self, moderator_id: str, club_id: str, admin_email: str):
        """Temporarily delete a moderator from a club"""
        try:
            await self.clubs_collection.update_one(
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
                        "moderators.$.deactivated_at": datetime.utcnow(),
                        "moderators.$.deactivated_by": admin_email,
                        "paid_moderators.$.status": "inactive",
                        "paid_moderators.$.deactivated_at": datetime.utcnow(),
                        "paid_moderators.$.deactivated_by": admin_email
                    }
                }
            )
        except Exception as e:
            print(f"Error in _temporarily_delete_moderator_from_club: {e}")

    async def _permanently_delete_moderator_from_club(self, moderator_id: str, club_id: str, admin_email: str):
        """Permanently delete a moderator from a club"""
        try:
            # Remove from moderators array
            await self.clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {"$pull": {"moderators": {"user_id": moderator_id}}}
            )
            
            # Remove from paid_moderators array
            await self.clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {"$pull": {"paid_moderators": {"user_id": moderator_id}}}
            )
        except Exception as e:
            print(f"Error in _permanently_delete_moderator_from_club: {e}")

    async def _calculate_member_usage_stats(self, member: Dict, deletion_date: datetime) -> Dict[str, Any]:
        """Calculate usage statistics for paid member using Stripe subscription dates"""
        try:
            # Get subscription ID
            subscription_id = await self._get_member_subscription_id(member)
            
            # First try to get dates from Stripe subscription
            stripe_start_date = None
            stripe_end_date = None
            
            if subscription_id and stripe.api_key:
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    stripe_start_date = datetime.fromtimestamp(subscription.current_period_start, tz=timezone.utc)
                    stripe_end_date = datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc)
                except Exception as e:
                    print(f"Error fetching Stripe subscription: {e}")
            
            # Fallback to database dates if Stripe fetch fails
            if not stripe_start_date or not stripe_end_date:
                join_date = member.get("join_date")
                end_date = member.get("end_date")
                
                if not join_date or not end_date:
                    return {
                        "total_days": 0,
                        "used_days": 0,
                        "remaining_days": 0,
                        "usage_percentage": 0,
                        "calculated_at": deletion_date.isoformat(),
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
                        print(f"Error parsing database join_date {join_date}: {e}")
                        return {
                            "total_days": 0,
                            "used_days": 0,
                            "remaining_days": 0,
                            "usage_percentage": 0,
                            "calculated_at": deletion_date.isoformat(),
                            "data_source": "error"
                        }
                
                if isinstance(end_date, str):
                    try:
                        if 'T' in end_date and '+' in end_date:
                            stripe_end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                        else:
                            stripe_end_date = datetime.fromisoformat(end_date)
                    except Exception as e:
                        print(f"Error parsing database end_date {end_date}: {e}")
                        return {
                            "total_days": 0,
                            "used_days": 0,
                            "remaining_days": 0,
                            "usage_percentage": 0,
                            "calculated_at": deletion_date.isoformat(),
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
            
            return {
                "total_days": total_days,
                "used_days": used_days,
                "remaining_days": remaining_days,
                "usage_percentage": round(usage_percentage, 2),
                "calculated_at": deletion_date.isoformat(),
                "data_source": data_source,
                "subscription_start_date": stripe_start_date.isoformat(),
                "subscription_end_date": stripe_end_date.isoformat(),
                "deletion_date": deletion_date.isoformat()
            }
            
        except Exception as e:
            print(f"Error calculating usage stats: {e}")
            return {
                "total_days": 0,
                "used_days": 0,
                "remaining_days": 0,
                "usage_percentage": 0,
                "calculated_at": deletion_date.isoformat(),
                "data_source": "error"
            }

    async def _calculate_trial_member_usage_stats(self, member: Dict, deletion_date: datetime) -> Dict[str, Any]:
        """Calculate usage statistics for trial member"""
        try:
            join_date = member.get("join_date")
            end_date = member.get("end_date")
            
            if not join_date or not end_date:
                return {
                    "total_days": 0,
                    "used_days": 0,
                    "remaining_days": 0,
                    "usage_percentage": 0,
                    "calculated_at": deletion_date.isoformat(),
                    "data_source": "none"
                }
            
            # Convert database dates to datetime
            if isinstance(join_date, str):
                try:
                    if 'T' in join_date and '+' in join_date:
                        start_date = datetime.fromisoformat(join_date.replace('Z', '+00:00'))
                    else:
                        start_date = datetime.fromisoformat(join_date)
                except Exception as e:
                    print(f"Error parsing trial join_date {join_date}: {e}")
                    return {
                        "total_days": 0,
                        "used_days": 0,
                        "remaining_days": 0,
                        "usage_percentage": 0,
                        "calculated_at": deletion_date.isoformat(),
                        "data_source": "error"
                    }
            
            if isinstance(end_date, str):
                try:
                    if 'T' in end_date and '+' in end_date:
                        end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    else:
                        end_date = datetime.fromisoformat(end_date)
                except Exception as e:
                    print(f"Error parsing trial end_date {end_date}: {e}")
                    return {
                        "total_days": 0,
                        "used_days": 0,
                        "remaining_days": 0,
                        "usage_percentage": 0,
                        "calculated_at": deletion_date.isoformat(),
                        "data_source": "error"
                    }
            
            # Ensure all dates are timezone-aware
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            if deletion_date.tzinfo is None:
                deletion_date = deletion_date.replace(tzinfo=timezone.utc)
            
            # Calculate days (inclusive)
            total_days = (end_date.date() - start_date.date()).days + 1
            used_days = (deletion_date.date() - start_date.date()).days + 1
            remaining_days = max(0, total_days - used_days)
            usage_percentage = (used_days / total_days) * 100 if total_days > 0 else 0
            
            return {
                "total_days": total_days,
                "used_days": used_days,
                "remaining_days": remaining_days,
                "usage_percentage": round(usage_percentage, 2),
                "calculated_at": deletion_date.isoformat(),
                "data_source": "database",
                "trial_start_date": start_date.isoformat(),
                "trial_end_date": end_date.isoformat(),
                "deletion_date": deletion_date.isoformat()
            }
            
        except Exception as e:
            print(f"Error calculating trial usage stats: {e}")
            return {
                "total_days": 0,
                "used_days": 0,
                "remaining_days": 0,
                "usage_percentage": 0,
                "calculated_at": deletion_date.isoformat(),
                "data_source": "error"
            }

    async def _get_member_subscription_id(self, member: Dict) -> Optional[str]:
        """Get subscription ID from Stripe for a paid member"""
        try:
            # Check if we already have subscription_id in the member data
            if member.get("subscription_id"):
                return member["subscription_id"]
            
            # Get payment_id from member
            payment_id = member.get("payment_id")
            if not payment_id:
                return None
            
            # Try to get subscription from Stripe using payment intent
            try:
                payment_intent = stripe.PaymentIntent.retrieve(payment_id)
                subscription_id = payment_intent.get("subscription")
                
                if subscription_id:
                    return subscription_id
                
            except Exception as e:
                print(f"Could not retrieve payment intent {payment_id}: {e}")
            
            return None
            
        except Exception as e:
            print(f"Error getting subscription ID for member: {e}")
            return None

    async def _send_deletion_notification(self, user_doc: Dict, request: AdminDeletionRequest, admin_email: str) -> bool:
        """Send email notification about deletion"""
        try:
            user_email = user_doc.get("email")
            if not user_email:
                return False
            
            subject = f"Account {request.deletion_type.value.title()} Deletion Notice"
            body = f"""
Dear {user_doc.get('full_name', 'User')},

Your account has been {request.deletion_type.value}ly deleted by an administrator.

Reason: {request.reason}

If you have any questions, please contact our support team.

Best regards,
Admin Team
            """
            
            await send_email(user_email, subject, body)
            return True
            
        except Exception as e:
            print(f"Error sending deletion notification: {e}")
            return False

    async def _send_reactivation_notification(self, user_doc: Dict, request: AdminReactivationRequest, admin_email: str) -> bool:
        """Send email notification about reactivation"""
        try:
            user_email = user_doc.get("email")
            if not user_email:
                return False
            
            subject = "Account Reactivation Notice"
            body = f"""
Dear {user_doc.get('full_name', 'User')},

Your account has been reactivated by an administrator.

Reason: {request.reason}

You can now access all your previous clubs and memberships.

Best regards,
Admin Team
            """
            
            await send_email(user_email, subject, body)
            return True
            
        except Exception as e:
            print(f"Error sending reactivation notification: {e}")
            return False

    async def _log_deletion_action(self, request: AdminDeletionRequest, admin_email: str, 
                                 previous_status: str, deletion_id: str, ip_address: Optional[str],
                                 affected_clubs: List[str], affected_members: List[str], 
                                 stripe_actions: List[Dict]):
        """Log deletion action for audit purposes"""
        try:
            log_entry = {
                "_id": ObjectId(),
                "deletion_id": deletion_id,
                "action": "ADMIN_DELETE_USER",
                "user_id": request.user_id,
                "user_role": request.user_role.value,
                "deletion_type": request.deletion_type.value,
                "previous_status": previous_status,
                "new_status": "deleted" if request.deletion_type == AdminDeletionType.PERMANENT else "inactive",
                "reason": request.reason,
                "admin_notes": request.admin_notes,
                "admin_email": admin_email,
                "ip_address": ip_address,
                "affected_clubs": affected_clubs,
                "affected_members": affected_members,
                "stripe_actions": stripe_actions,
                "timestamp": datetime.utcnow()
            }
            
            await self.club_admin_logs_collection.insert_one(log_entry)
            
        except Exception as e:
            print(f"Error logging deletion action: {e}")

    async def _log_reactivation_action(self, request: AdminReactivationRequest, admin_email: str,
                                     previous_status: str, reactivation_id: str, ip_address: Optional[str],
                                     affected_clubs: List[str], affected_members: List[str],
                                     stripe_actions: List[Dict]):
        """Log reactivation action for audit purposes"""
        try:
            log_entry = {
                "_id": ObjectId(),
                "reactivation_id": reactivation_id,
                "action": "ADMIN_REACTIVATE_USER",
                "user_id": request.user_id,
                "user_role": request.user_role.value,
                "previous_status": previous_status,
                "new_status": "active",
                "reason": request.reason,
                "admin_notes": request.admin_notes,
                "admin_email": admin_email,
                "ip_address": ip_address,
                "affected_clubs": affected_clubs,
                "affected_members": affected_members,
                "stripe_actions": stripe_actions,
                "timestamp": datetime.utcnow()
            }
            
            await self.club_admin_logs_collection.insert_one(log_entry)
            
        except Exception as e:
            print(f"Error logging reactivation action: {e}")


    # Reactivation methods
    async def _reactivate_captain(self, user_doc: Dict, request: AdminReactivationRequest, admin_email: str) -> Dict:
        """Reactivate a captain and resume all clubs and memberships"""
        try:
            captain_id = str(user_doc["_id"])
            affected_clubs = []
            affected_members = []
            stripe_actions = []
            
            # Find all clubs created by this captain
            clubs_cursor = self.clubs_collection.find({"captain_id": captain_id})
            clubs = await clubs_cursor.to_list(None)
            
            print(f"Reactivating {len(clubs)} clubs for captain {captain_id}")
            
            for club in clubs:
                club_id = str(club["_id"])
                affected_clubs.append(club_id)
                
                # Reactivate club
                result = await self._reactivate_captain_club(club, admin_email)
                affected_members.extend(result.get("affected_members", []))
                stripe_actions.extend(result.get("stripe_actions", []))
            
            # Update captain status
            await self.users_collection.update_one(
                {"_id": ObjectId(captain_id)},
                {
                    "$set": {
                        "status": "active",
                        "membership_status": "active",
                        "is_deleted_per_admin": False,
                        "is_deleted_temp_admin": False,
                        "reactivated_at": datetime.utcnow(),
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
            print(f"Error in _reactivate_captain: {e}")
            return {
                "success": False,
                "message": f"Failed to reactivate captain: {str(e)}",
                "affected_clubs": [],
                "affected_members": [],
                "stripe_actions": []
            }

    async def _reactivate_captain_club(self, club: Dict, admin_email: str) -> Dict:
        """Reactivate a captain's club and resume all memberships"""
        try:
            club_id = str(club["_id"])
            affected_members = []
            stripe_actions = []
            
            print(f"Reactivating club {club_id}")
            
            # Update club status to active
            await self.clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {
                    "$set": {
                        "status": "approved",
                        "is_paused_by_admin": False,
                        "reactivated_at": datetime.utcnow(),
                        "reactivated_by": admin_email
                    }
                }
            )
            
            # Reactivate all Stripe products in pricing_plans
            pricing_plans = club.get("pricing_plans", [])
            for plan in pricing_plans:
                stripe_product_id = plan.get("stripe_product_id")
                if stripe_product_id:
                    try:
                        # Reactivate the product
                        stripe.Product.modify(
                            stripe_product_id,
                            active=True
                        )
                        
                        stripe_actions.append({
                            "action": "product_reactivated",
                            "product_id": stripe_product_id,
                            "club_id": club_id,
                            "plan_frequency": plan.get("frequency")
                        })
                        
                    except Exception as e:
                        print(f"Error reactivating Stripe product {stripe_product_id}: {e}")
                        stripe_actions.append({
                            "action": "product_reactivate_failed",
                            "product_id": stripe_product_id,
                            "club_id": club_id,
                            "error": str(e)
                        })
            
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
                    try:
                        if unused_days > 0:
                            # Calculate trial end timestamp (current time + unused days in seconds)
                            now = datetime.now(timezone.utc)
                            trial_end_timestamp = int(now.timestamp()) + (unused_days * 86400)
                            
                            # Resume subscription with trial period for unused days
                            stripe.Subscription.modify(
                                subscription_id,
                                pause_collection="",  # Clear the pause
                                trial_end=trial_end_timestamp,  # Set trial period for unused days
                                proration_behavior="none"  # No proration for trial period
                            )
                            
                            stripe_actions.append({
                                "action": "subscription_resumed_with_trial",
                                "subscription_id": subscription_id,
                                "member_id": member_id,
                                "club_id": club_id,
                                "unused_days": unused_days,
                                "trial_end": datetime.fromtimestamp(trial_end_timestamp, tz=timezone.utc).isoformat()
                            })
                        else:
                            # No unused days, just clear the pause
                            stripe.Subscription.modify(
                                subscription_id,
                                pause_collection=""  # Clear the pause
                            )
                            
                            stripe_actions.append({
                                "action": "subscription_resumed",
                                "subscription_id": subscription_id,
                                "member_id": member_id,
                                "club_id": club_id
                            })
                            
                    except Exception as e:
                        print(f"Error resuming Stripe subscription for member {member_id}: {e}")
                        stripe_actions.append({
                            "action": "subscription_resume_failed",
                            "member_id": member_id,
                            "club_id": club_id,
                            "error": str(e)
                        })
                
                # Calculate new end date based on unused days
                new_end_date = None
                if unused_days > 0:
                    new_end_date = datetime.now(timezone.utc) + timedelta(days=unused_days)
                
                # Update member status in club
                await self.clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_members.user_id": member_id
                    },
                    {
                        "$set": {
                            "paid_members.$.membership_status": "active",
                            "paid_members.$.is_temporarily_deleted": False,
                            "paid_members.$.end_date": new_end_date,
                            "paid_members.$.reactivation_date": datetime.now(timezone.utc),
                            "paid_members.$.resumed_at": datetime.now(timezone.utc),
                            "paid_members.$.resumed_by": admin_email
                        },
                        "$unset": {
                            "paid_members.$.deletion_date": "",
                            "paid_members.$.usage_stats": ""
                        }
                    }
                )
                
                # Update user's clubs_joined array
                await self.users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "active",
                            "clubs_joined.$.is_temporarily_deleted": False,
                            "clubs_joined.$.end_date": new_end_date,
                            "clubs_joined.$.reactivation_date": datetime.now(timezone.utc)
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
                    new_end_date = datetime.now(timezone.utc) + timedelta(days=unused_days)
                
                # Update trial member status in club
                await self.clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "active",
                            "members.$.is_temporarily_deleted": False,
                            "members.$.end_date": new_end_date,
                            "members.$.reactivation_date": datetime.now(timezone.utc),
                            "members.$.resumed_at": datetime.now(timezone.utc),
                            "members.$.resumed_by": admin_email
                        },
                        "$unset": {
                            "members.$.deletion_date": "",
                            "members.$.usage_stats": ""
                        }
                    }
                )
                
                # Update user's clubs_joined array
                await self.users_collection.update_one(
                    {
                        "_id": ObjectId(member_id),
                        "clubs_joined.club_id": club_id
                    },
                    {
                        "$set": {
                            "clubs_joined.$.membership_status": "active",
                            "clubs_joined.$.is_temporarily_deleted": False,
                            "clubs_joined.$.end_date": new_end_date,
                            "clubs_joined.$.reactivation_date": datetime.now(timezone.utc)
                        },
                        "$unset": {
                            "clubs_joined.$.deletion_date": "",
                            "clubs_joined.$.usage_stats": ""
                        }
                    }
                )
                
                # Update user's trial membership status
                await self.users_collection.update_one(
                    {"_id": ObjectId(member_id)},
                    {
                        "$set": {
                            "trial_membership_paused": False,
                            "trial_resumed_at": datetime.now(timezone.utc),
                            "trial_resumed_by": admin_email
                        }
                    }
                )
            
            return {
                "success": True,
                "affected_members": affected_members,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _reactivate_captain_club: {e}")
            return {
                "success": False,
                "affected_members": [],
                "stripe_actions": []
            }

    async def _reactivate_member(self, user_doc: Dict, request: AdminReactivationRequest, admin_email: str) -> Dict:
        """Reactivate a member and resume all memberships"""
        try:
            member_id = str(user_doc["_id"])
            affected_clubs = []
            affected_members = [member_id]
            stripe_actions = []
            
            # Find all clubs the member has joined
            clubs_joined = user_doc.get("clubs_joined", [])
            
            print(f"Reactivating {len(clubs_joined)} memberships for member {member_id}")
            
            for club_membership in clubs_joined:
                club_id = club_membership.get("club_id")
                if not club_id:
                    continue
                
                affected_clubs.append(club_id)
                
                # Get club details
                club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                if not club_doc:
                    continue
                
                # Reactivate membership
                result = await self._reactivate_member_from_club(
                    member_id, club_doc, club_membership, admin_email
                )
                stripe_actions.extend(result.get("stripe_actions", []))
            
            # Update member status
            await self.users_collection.update_one(
                {"_id": ObjectId(member_id)},
                {
                    "$set": {
                        "status": "active",
                        "membership_status": "active",
                        "is_deleted_per_admin": False,
                        "is_deleted_temp_admin": False,
                        "reactivated_at": datetime.utcnow(),
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
            print(f"Error in _reactivate_member: {e}")
            return {
                "success": False,
                "message": f"Failed to reactivate member: {str(e)}",
                "affected_clubs": [],
                "affected_members": [],
                "stripe_actions": []
            }

    async def _reactivate_member_from_club(self, member_id: str, club_doc: Dict, 
                                          club_membership: Dict, admin_email: str) -> Dict:
        """Reactivate a member's membership in a club"""
        try:
            club_id = str(club_doc["_id"])
            stripe_actions = []
            
            print(f"Reactivating member {member_id} in club {club_id}")
            
            # Check if it's a paid membership
            if club_membership.get("membership_type") == "paid":
                payment_id = club_membership.get("payment_id")
                if payment_id:
                    try:
                        # Get payment intent to find subscription
                        payment_intent = stripe.PaymentIntent.retrieve(payment_id)
                        subscription_id = payment_intent.get("subscription")
                        
                        if subscription_id:
                            # Resume subscription
                            stripe.Subscription.modify(
                                subscription_id,
                                pause_collection=None
                            )
                            
                            stripe_actions.append({
                                "action": "subscription_resumed",
                                "subscription_id": subscription_id,
                                "member_id": member_id,
                                "club_id": club_id
                            })
                            
                    except Exception as e:
                        print(f"Error resuming Stripe subscription for member {member_id}: {e}")
                        stripe_actions.append({
                            "action": "subscription_resume_failed",
                            "member_id": member_id,
                            "club_id": club_id,
                            "error": str(e)
                        })
                
                # Update paid member status in club
                await self.clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "paid_members.user_id": member_id
                    },
                    {
                        "$set": {
                            "paid_members.$.membership_status": "active",
                            "paid_members.$.resumed_at": datetime.utcnow(),
                            "paid_members.$.resumed_by": admin_email
                        }
                    }
                )
            else:
                # Trial membership - update status
                await self.clubs_collection.update_one(
                    {
                        "_id": ObjectId(club_id),
                        "members.user_id": member_id
                    },
                    {
                        "$set": {
                            "members.$.membership_status": "active",
                            "members.$.resumed_at": datetime.utcnow(),
                            "members.$.resumed_by": admin_email
                        }
                    }
                )
            
            return {
                "success": True,
                "stripe_actions": stripe_actions
            }
            
        except Exception as e:
            print(f"Error in _reactivate_member_from_club: {e}")
            return {
                "success": False,
                "stripe_actions": []
            }

    async def _reactivate_moderator(self, user_doc: Dict, request: AdminReactivationRequest, admin_email: str) -> Dict:
        """Reactivate a moderator and resume all moderator roles"""
        try:
            moderator_id = str(user_doc["_id"])
            affected_clubs = []
            affected_members = [moderator_id]
            stripe_actions = []
            
            # Find all clubs where this user is a moderator
            clubs_cursor = self.clubs_collection.find({
                "$or": [
                    {"moderators": {"$elemMatch": {"user_id": moderator_id}}},
                    {"paid_moderators": {"$elemMatch": {"user_id": moderator_id}}}
                ]
            })
            clubs = await clubs_cursor.to_list(None)
            
            print(f"Reactivating {len(clubs)} moderator roles for moderator {moderator_id}")
            
            for club in clubs:
                club_id = str(club["_id"])
                affected_clubs.append(club_id)
                
                # Reactivate moderator role
                await self._reactivate_moderator_from_club(moderator_id, club_id, admin_email)
            
            # Update moderator status
            await self.users_collection.update_one(
                {"_id": ObjectId(moderator_id)},
                {
                    "$set": {
                        "status": "active",
                        "membership_status": "active",
                        "is_deleted_per_admin": False,
                        "is_deleted_temp_admin": False,
                        "reactivated_at": datetime.utcnow(),
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
            print(f"Error in _reactivate_moderator: {e}")
            return {
                "success": False,
                "message": f"Failed to reactivate moderator: {str(e)}",
                "affected_clubs": [],
                "affected_members": [],
                "stripe_actions": []
            }

    async def _reactivate_moderator_from_club(self, moderator_id: str, club_id: str, admin_email: str):
        """Reactivate a moderator's role in a club"""
        try:
            await self.clubs_collection.update_one(
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
                        "moderators.$.reactivated_at": datetime.utcnow(),
                        "moderators.$.reactivated_by": admin_email,
                        "paid_moderators.$.status": "active",
                        "paid_moderators.$.reactivated_at": datetime.utcnow(),
                        "paid_moderators.$.reactivated_by": admin_email
                    }
                }
            )
        except Exception as e:
            print(f"Error in _reactivate_moderator_from_club: {e}")


# Create service instance
admin_deletion_service = AdminDeletionService()
