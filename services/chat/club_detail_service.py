"""
Club Detail Service - Handles club detail page functionality
"""

import logging
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
from bson import ObjectId

from .db import get_club_collection, get_user_collection, get_membership_collection, get_user_access_collection, get_dm_requests_collection
from .models import ClubDetailResponse, ClubMember, ClubModerator
from .models import DMRequestInfo

logger = logging.getLogger(__name__)

class ClubDetailService:
    def __init__(self):
        self.clubs_collection = get_club_collection()
        self.users_collection = get_user_collection()
        self.memberships_collection = get_membership_collection()
        self.user_access_collection = get_user_access_collection()
        self.dm_requests_collection = get_dm_requests_collection()
    
    async def get_club_details(self, club_id: str, user_id: str) -> Tuple[bool, Optional[ClubDetailResponse], Optional[str]]:
        """
        Get detailed club information based on user role
        
        Args:
            club_id: name_based_id of the club (e.g., "xyz-abc")
            user_id: ID of the logged-in user
            
        Returns:
            Tuple of (success, ClubDetailResponse, error_message)
        """
        try:
            # Get club information
            club = await self.clubs_collection.find_one({"name_based_id": club_id})
            if not club:
                return False, None, "Club not found"
            
            # Get user information
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False, None, "User not found"
            
            # Determine user's role and relationship with the club
            user_role, user_membership = await self._get_user_club_relationship(user, club)
            
            # Get club members and moderators
            members, moderators, captain = await self._get_club_members_and_moderators(club)
            
            # Calculate statistics
            stats = await self._calculate_club_statistics(club, members)
            
            # Get pricing information
            pricing_info = self._get_pricing_info(club)
            
            # Create response
            response = ClubDetailResponse(
                success=True,
                club_id=str(club["_id"]),
                club_name=club.get("name", "Unknown Club"),
                name_based_id=club.get("name_based_id", ""),
                description=club.get("description"),
                logo_url=club.get("logo_url"),
                banner_url=club.get("banner_url"),
                status=club.get("status", "active"),
                created_at=club.get("created_at", datetime.utcnow()),
                updated_at=club.get("updated_at", datetime.utcnow()),
                
                # User's relationship with the club
                user_role=user_role,
                user_membership_type=user_membership.get("membership_type") if user_membership else None,
                user_membership_status=user_membership.get("membership_status") if user_membership else None,
                user_join_date=user_membership.get("join_date") if user_membership else None,
                user_trial_end_date=user_membership.get("trial_end_date") if user_membership else None,
                user_paid_end_date=user_membership.get("paid_end_date") if user_membership else None,
                user_is_muted=user_membership.get("is_muted", False) if user_membership else False,
                
                # Club statistics
                total_members=stats["total_members"],
                total_moderators=stats["total_moderators"],
                total_paid_members=stats["total_paid_members"],
                total_trial_members=stats["total_trial_members"],
                monthly_revenue=stats["monthly_revenue"],
                
                # Club details
                captain=captain,
                moderators=moderators,
                members=members,
                # paid_members=stats["paid_members"],
                # trial_members=stats["trial_members"],
                
                # Pricing information
                # pricing=pricing_info["pricing"],
                pricing_plans=pricing_info["pricing_plans"],
                
                # Club settings
                # settings=club.get("settings", {}),
                
                message="Club details retrieved successfully"
            )
            
            return True, response, None
            
        except Exception as e:
            logger.error(f"Error getting club details: {e}")
            return False, None, f"Failed to get club details: {str(e)}"
    
    async def _get_user_mute_status(self, user_id: str, club_id: str) -> bool:
        """Get user's mute status from user_access table"""
        try:
            user_access = await self.user_access_collection.find_one({
                "user_id": user_id,
                "club_id": club_id
            })
            return user_access.get("is_muted", False) if user_access else False
        except Exception as e:
            logger.error(f"Error getting mute status for user {user_id} in club {club_id}: {e}")
            return False
    
    async def _get_user_name(self, user_id: str) -> str:
        """Get user's full name by user ID"""
        try:
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if user:
                return user.get("full_name", "Unknown")
            return "Unknown"
        except Exception as e:
            logger.error(f"Error getting user name for {user_id}: {e}")
            return "Unknown"

    async def _get_user_dm_requests(self, user_id: str, club_object_id: str) -> Dict[str, Any]:
        """Get DM request information for a user in a specific club"""
        try:
            # Get DM requests sent by this user
            sent_requests = await self.dm_requests_collection.find({
                "sender_id": user_id,
                "club_id": club_object_id
            }).to_list(length=None)
            
            # Get DM requests received by this user
            received_requests = await self.dm_requests_collection.find({
                "receiver_id": user_id,
                "club_id": club_object_id
            }).to_list(length=None)
            
            # Convert to DMRequestInfo objects
            dm_requests_sent = []
            for req in sent_requests:
                # Ensure status is a valid string value
                status = req.get("status", "pending")
                if status not in ["pending", "accepted", "rejected", "blocked", "cancelled"]:
                    status = "pending"  # Default to pending if invalid status
                
                # Get receiver name
                receiver_name = await self._get_user_name(req.get("receiver_id", ""))
                
                dm_requests_sent.append(DMRequestInfo(
                    request_id=str(req.get("_id", "")),
                    sender_id=req.get("sender_id", ""),
                    sender_name=await self._get_user_name(req.get("sender_id", "")),
                    receiver_id=req.get("receiver_id", ""),
                    receiver_name=receiver_name,
                    status=status,
                    created_at=req.get("created_at", datetime.utcnow()),
                    updated_at=req.get("updated_at"),
                    message=req.get("message")
                ))
            
            dm_requests_received = []
            for req in received_requests:
                # Ensure status is a valid string value
                status = req.get("status", "pending")
                if status not in ["pending", "accepted", "rejected", "blocked", "cancelled"]:
                    status = "pending"  # Default to pending if invalid status
                
                # Get sender name
                sender_name = await self._get_user_name(req.get("sender_id", ""))
                
                dm_requests_received.append(DMRequestInfo(
                    request_id=str(req.get("_id", "")),
                    sender_id=req.get("sender_id", ""),
                    sender_name=sender_name,
                    receiver_id=req.get("receiver_id", ""),
                    receiver_name=await self._get_user_name(req.get("receiver_id", "")),
                    status=status,
                    created_at=req.get("created_at", datetime.utcnow()),
                    updated_at=req.get("updated_at"),
                    message=req.get("message")
                ))
            
            # Calculate counts
            total_sent = len(dm_requests_sent)
            total_received = len(dm_requests_received)
            pending_sent = len([r for r in dm_requests_sent if r.status == "pending"])
            pending_received = len([r for r in dm_requests_received if r.status == "pending"])
            
            return {
                "dm_requests_sent": dm_requests_sent,
                "dm_requests_received": dm_requests_received,
                "total_dm_requests_sent": total_sent,
                "total_dm_requests_received": total_received,
                "pending_dm_requests_sent": pending_sent,
                "pending_dm_requests_received": pending_received
            }
            
        except Exception as e:
            logger.error(f"Error getting DM requests for user {user_id} in club {club_object_id}: {e}")
            return {
                "dm_requests_sent": [],
                "dm_requests_received": [],
                "total_dm_requests_sent": 0,
                "total_dm_requests_received": 0,
                "pending_dm_requests_sent": 0,
                "pending_dm_requests_received": 0
            }
    
    async def _get_user_club_relationship(self, user: dict, club: dict) -> Tuple[str, Optional[dict]]:
        """Determine user's role and membership in the club"""
        user_id = str(user["_id"])
        club_id = str(club["_id"])
        club_name_based_id = club.get("name_based_id", "")
        
        # Check if user is the captain
        if user_id == club.get("captain_id"):
            return "Captain", None
        
        # Check if user is a moderator
        moderators = club.get("moderators", [])
        for moderator in moderators:
            if moderator.get("user_id") == user_id:
                return "Moderator", None
        
        # Check if user is a member (from user's clubs_joined field)
        user_membership = None
        if "clubs_joined" in user and isinstance(user["clubs_joined"], list):
            for club_data in user["clubs_joined"]:
                if club_data.get("club_name_based_id") == club.get("name_based_id"):
                    # Get user's mute status from user_access table
                    user_is_muted = await self._get_user_mute_status(user_id, club_name_based_id)
                    user_membership = club_data.copy()
                    user_membership["is_muted"] = user_is_muted
                    break
        
        # If not found in user document, check memberships collection
        if not user_membership:
            membership_doc = await self.memberships_collection.find_one({
                "user_id": user_id,
                "club_id": club_id,
                "status": "active"
            })
            if membership_doc:
                # Get user's mute status from user_access table
                user_is_muted = await self._get_user_mute_status(user_id, club_name_based_id)
                
                user_membership = {
                    "membership_type": membership_doc.get("membership_type", "trial"),
                    "membership_status": membership_doc.get("status", "active"),
                    "join_date": membership_doc.get("created_at"),
                    "trial_end_date": membership_doc.get("trial_end_date"),
                    "paid_end_date": membership_doc.get("paid_end_date"),
                    "is_muted": user_is_muted
                }
        
        if user_membership:
            return "Member", user_membership
        
        return "None", None
    
    async def _get_club_members_and_moderators(self, club: dict) -> Tuple[List[ClubMember], List[ClubModerator], Optional[ClubMember]]:
        """Get all members, moderators, and captain of the club"""
        members = []
        moderators = []
        captain = None
        
        club_id = str(club["_id"])
        club_name_based_id = club.get("name_based_id", "")
        
        # Use name_based_id for user_access table queries since that's what's stored there
        club_id_for_user_access = club_name_based_id
        
        # Get captain information
        captain_id = club.get("captain_id")
        if captain_id:
            captain_user = await self.users_collection.find_one({"_id": ObjectId(captain_id)})
            if captain_user:
                # Get captain's mute status from user_access table
                captain_is_muted = await self._get_user_mute_status(captain_id, club_id_for_user_access)
                
                # Get captain's DM request information
                captain_dm_info = await self._get_user_dm_requests(captain_id, club_id)
                
                captain = ClubMember(
                    user_id=str(captain_user["_id"]),
                    username=captain_user.get("username", "Unknown"),
                    full_name=captain_user.get("full_name", "Unknown"),
                    email=captain_user.get("email"),
                    avatar_url=captain_user.get("avatar_url"),
                    role="Captain",
                    membership_type="paid",  # Captain always has paid membership
                    membership_status="active",
                    join_date=club.get("created_at"),
                    pricing_plan="monthly",  # Default for captain
                    is_muted=captain_is_muted,
                    # DM Request fields
                    dm_requests_sent=captain_dm_info["dm_requests_sent"],
                    dm_requests_received=captain_dm_info["dm_requests_received"],
                    total_dm_requests_sent=captain_dm_info["total_dm_requests_sent"],
                    total_dm_requests_received=captain_dm_info["total_dm_requests_received"],
                    pending_dm_requests_sent=captain_dm_info["pending_dm_requests_sent"],
                    pending_dm_requests_received=captain_dm_info["pending_dm_requests_received"]
                )
        
        # Get moderators
        club_moderators = club.get("moderators", [])
        for moderator_data in club_moderators:
            moderator_user = await self.users_collection.find_one({"_id": ObjectId(moderator_data.get("user_id"))})
            if moderator_user:
                moderator = ClubModerator(
                    user_id=str(moderator_user["_id"]),
                    username=moderator_user.get("username", "Unknown"),
                    full_name=moderator_user.get("full_name", "Unknown"),
                    email=moderator_user.get("email"),
                    avatar_url=moderator_user.get("avatar_url"),
                    role="Moderator",
                    assigned_by=moderator_data.get("assigned_by", captain_id or ""),
                    assigned_at=moderator_data.get("assigned_at"),
                    permissions=moderator_data.get("permissions", [])
                )
                moderators.append(moderator)
        
        # Get members from club document arrays (members and paid_members)
        club_members = club.get("members", [])
        club_paid_members = club.get("paid_members", [])
        
        # Process regular members
        for member_data in club_members:
            member_user_id = member_data.get("user_id")
            if member_user_id:
                member_user = await self.users_collection.find_one({"_id": ObjectId(member_user_id)})
                if member_user:
                    # Skip if this is the captain (already added)
                    if str(member_user["_id"]) == captain_id:
                        continue
                    
                    # Skip if this is a moderator (already added)
                    is_moderator = any(mod.get("user_id") == str(member_user["_id"]) for mod in club_moderators)
                    if is_moderator:
                        continue
                    
                    # Get member's mute status from user_access table
                    member_is_muted = await self._get_user_mute_status(str(member_user["_id"]), club_id_for_user_access)
                    
                    # Get member's DM request information
                    member_dm_info = await self._get_user_dm_requests(str(member_user["_id"]), club_id)
                    
                    member = ClubMember(
                        user_id=str(member_user["_id"]),
                        username=member_user.get("username", "Unknown"),
                        full_name=member_user.get("full_name", "Unknown"),
                        email=member_user.get("email"),
                        avatar_url=member_user.get("avatar_url"),
                        role="Member",
                        membership_type=member_data.get("membership_type", "trial"),
                        membership_status=member_data.get("membership_status", "active"),
                        join_date=member_data.get("join_date"),
                        trial_end_date=member_data.get("trial_end_date"),
                        paid_end_date=member_data.get("paid_end_date"),
                        pricing_plan=member_data.get("pricing_plan"),
                        is_muted=member_is_muted,
                        # DM Request fields
                        dm_requests_sent=member_dm_info["dm_requests_sent"],
                        dm_requests_received=member_dm_info["dm_requests_received"],
                        total_dm_requests_sent=member_dm_info["total_dm_requests_sent"],
                        total_dm_requests_received=member_dm_info["total_dm_requests_received"],
                        pending_dm_requests_sent=member_dm_info["pending_dm_requests_sent"],
                        pending_dm_requests_received=member_dm_info["pending_dm_requests_received"]
                    )
                    members.append(member)
        
        # Process paid members
        for member_data in club_paid_members:
            member_user_id = member_data.get("user_id")
            if member_user_id:
                member_user = await self.users_collection.find_one({"_id": ObjectId(member_user_id)})
                if member_user:
                    # Skip if this is the captain (already added)
                    if str(member_user["_id"]) == captain_id:
                        continue
                    
                    # Skip if this is a moderator (already added)
                    is_moderator = any(mod.get("user_id") == str(member_user["_id"]) for mod in club_moderators)
                    if is_moderator:
                        continue
                    
                    # Get member's mute status from user_access table
                    member_is_muted = await self._get_user_mute_status(str(member_user["_id"]), club_id_for_user_access)
                    
                    # Get member's DM request information
                    member_dm_info = await self._get_user_dm_requests(str(member_user["_id"]), club_id)
                    
                    member = ClubMember(
                        user_id=str(member_user["_id"]),
                        username=member_user.get("username", "Unknown"),
                        full_name=member_user.get("full_name", "Unknown"),
                        email=member_user.get("email"),
                        avatar_url=member_user.get("avatar_url"),
                        role="Member",
                        membership_type=member_data.get("membership_type", "paid"),
                        membership_status=member_data.get("membership_status", "active"),
                        join_date=member_data.get("join_date"),
                        trial_end_date=member_data.get("trial_end_date"),
                        paid_end_date=member_data.get("paid_end_date"),
                        pricing_plan=member_data.get("pricing_plan"),
                        is_muted=member_is_muted,
                        # DM Request fields
                        dm_requests_sent=member_dm_info["dm_requests_sent"],
                        dm_requests_received=member_dm_info["dm_requests_received"],
                        total_dm_requests_sent=member_dm_info["total_dm_requests_sent"],
                        total_dm_requests_received=member_dm_info["total_dm_requests_received"],
                        pending_dm_requests_sent=member_dm_info["pending_dm_requests_sent"],
                        pending_dm_requests_received=member_dm_info["pending_dm_requests_received"]
                    )
                    members.append(member)
        
        # Also check memberships collection as fallback
        memberships = await self.memberships_collection.find({
            "club_id": club_id,
            "status": "active"
        }).to_list(length=None)
        
        for membership in memberships:
            member_user = await self.users_collection.find_one({"_id": ObjectId(membership["user_id"])})
            if member_user:
                # Skip if this is the captain (already added)
                if str(member_user["_id"]) == captain_id:
                    continue
                
                # Skip if this is a moderator (already added)
                is_moderator = any(mod.get("user_id") == str(member_user["_id"]) for mod in club_moderators)
                if is_moderator:
                    continue
                
                # Skip if already added from club arrays
                already_added = any(m.user_id == str(member_user["_id"]) for m in members)
                if already_added:
                    continue
                
                # Get member's mute status from user_access table
                member_is_muted = await self._get_user_mute_status(str(member_user["_id"]), club_id_for_user_access)
                
                # Get member's DM request information
                member_dm_info = await self._get_user_dm_requests(str(member_user["_id"]), club_id)
                
                member = ClubMember(
                    user_id=str(member_user["_id"]),
                    username=member_user.get("username", "Unknown"),
                    full_name=member_user.get("full_name", "Unknown"),
                    email=member_user.get("email"),
                    avatar_url=member_user.get("avatar_url"),
                    role="Member",
                    membership_type=membership.get("membership_type", "trial"),
                    membership_status=membership.get("status", "active"),
                    join_date=membership.get("created_at"),
                    trial_end_date=membership.get("trial_end_date"),
                    paid_end_date=membership.get("paid_end_date"),
                    pricing_plan=membership.get("pricing_plan"),
                    is_muted=member_is_muted,
                    # DM Request fields
                    dm_requests_sent=member_dm_info["dm_requests_sent"],
                    dm_requests_received=member_dm_info["dm_requests_received"],
                    total_dm_requests_sent=member_dm_info["total_dm_requests_sent"],
                    total_dm_requests_received=member_dm_info["total_dm_requests_received"],
                    pending_dm_requests_sent=member_dm_info["pending_dm_requests_sent"],
                    pending_dm_requests_received=member_dm_info["pending_dm_requests_received"]
                )
                members.append(member)
        
        return members, moderators, captain
    
    async def _calculate_club_statistics(self, club: dict, members: List[ClubMember]) -> Dict[str, Any]:
        """Calculate club statistics"""
        total_members = len(members)
        total_moderators = len(club.get("moderators", []))
        total_paid_members = len([m for m in members if m.membership_type == "paid"])
        total_trial_members = len([m for m in members if m.membership_type == "trial"])
        
        # Calculate monthly revenue (simplified)
        monthly_revenue = 0.0
        for member in members:
            if member.membership_type == "paid":
                # This would need to be calculated based on actual pricing
                monthly_revenue += 10.0  # Placeholder
        
        return {
            "total_members": total_members,
            "total_moderators": total_moderators,
            "total_paid_members": total_paid_members,
            "total_trial_members": total_trial_members,
            "monthly_revenue": monthly_revenue,
            "paid_members": [m for m in members if m.membership_type == "paid"],
            "trial_members": [m for m in members if m.membership_type == "trial"]
        }
    
    def _get_pricing_info(self, club: dict) -> Dict[str, Any]:
        """Get pricing information from club"""
        pricing = club.get("pricing")
        pricing_plans = club.get("pricing_plans", [])
        
        return {
            "pricing": pricing,
            "pricing_plans": pricing_plans
        }

# Global instance
club_detail_service = ClubDetailService()
