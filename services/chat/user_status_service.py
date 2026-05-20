"""
User Status Service

This service handles user status information in club chat rooms,
including mute status, last visited, DM requests, and member details.
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from bson import ObjectId
import logging

from .db import (
    get_user_access_collection,
    get_users_collection,
    get_dm_requests_collection,
    get_club_collection,
    get_messages_collection,
)
from .models import (
    UserClubStatus,
    ClubMemberStatus,
    DMRequestInfo,
    UserClubStatusResponse,
    ClubMemberStatusResponse,
    ClubCaptainsResponse,
    ClubModeratorsResponse,
    ClubMembersResponse,
)

logger = logging.getLogger(__name__)


class UserStatusService:
    """Service for managing user status in club chat rooms"""

    def __init__(self):
        self.user_access_collection = get_user_access_collection()
        self.users_collection = get_users_collection()
        self.dm_requests_collection = get_dm_requests_collection()
        self.clubs_collection = get_club_collection()
        self.messages_collection = get_messages_collection()

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

    async def get_user_status_in_club(
        self, user_id: str, club_id: str
    ) -> Tuple[bool, Optional[UserClubStatusResponse], Optional[str]]:
        """
        Get the current status of a user in a specific club chat room - ULTRA OPTIMIZED VERSION

        Args:
            user_id: User ID to get status for
            club_id: Club ID to check status in

        Returns:
            Tuple of (success, response, error_message)
        """
        import time

        start_time = time.time()
        print(
            f"🚀 [USER STATUS] Starting optimization for user: {user_id}, club: {club_id}"
        )

        try:
            # Step 1: Get club details - ULTRA OPTIMIZED
            step_start = time.time()
            club = await self.clubs_collection.find_one({"name_based_id": club_id})
            if not club:
                logger.error(f"Club not found with ID: {club_id}")
                return False, None, "Club not found"

            actual_club_id = str(club["_id"])
            club_name_based_id = club_id
            print(
                f"⏱️ [USER STATUS] Club lookup: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 2: Get user data with minimal projection - ULTRA OPTIMIZED
            step_start = time.time()
            user = await self.users_collection.find_one(
                {"_id": ObjectId(user_id)},
                {
                    "_id": 1,
                    "full_name": 1,
                    "email": 1,
                    "phone": 1,
                    "avatar_url": 1,
                    "is_active": 1,
                },
            )

            if not user:
                logger.error(f"User not found with ID: {user_id}")
                return False, None, "User not found"

            print(
                f"⏱️ [USER STATUS] User data fetch: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 3: Get user access info in bulk - ULTRA OPTIMIZED
            step_start = time.time()
            user_access = await self.user_access_collection.find_one(
                {"user_id": user_id, "club_id": club_name_based_id}
            )

            is_muted = user_access.get("is_muted", False) if user_access else False
            last_visited = user_access.get("last_visited") if user_access else None
            print(
                f"⏱️ [USER STATUS] User access fetch: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 4: Get DM requests in bulk - ULTRA OPTIMIZED
            step_start = time.time()
            dm_requests_sent = await self.dm_requests_collection.find(
                {"sender_id": user_id, "club_id": club_name_based_id}
            ).to_list(None)

            dm_requests_received = await self.dm_requests_collection.find(
                {"receiver_id": user_id, "club_id": club_name_based_id}
            ).to_list(None)

            # Process DM requests
            dm_requests_sent_data = []
            for req in dm_requests_sent:
                dm_requests_sent_data.append(
                    {
                        "request_id": str(req["_id"]),
                        "sender_id": req.get("sender_id"),
                        "sender_name": req.get("sender_name"),
                        "receiver_id": req.get("receiver_id"),
                        "receiver_name": req.get("receiver_name"),
                        "status": req.get("status"),
                        "created_at": req.get("created_at"),
                        "updated_at": req.get("updated_at"),
                        "message": req.get("message"),
                    }
                )

            dm_requests_received_data = []
            for req in dm_requests_received:
                dm_requests_received_data.append(
                    {
                        "request_id": str(req["_id"]),
                        "sender_id": req.get("sender_id"),
                        "sender_name": req.get("sender_name"),
                        "receiver_id": req.get("receiver_id"),
                        "receiver_name": req.get("receiver_name"),
                        "status": req.get("status"),
                        "created_at": req.get("created_at"),
                        "updated_at": req.get("updated_at"),
                        "message": req.get("message"),
                    }
                )

            print(
                f"⏱️ [USER STATUS] DM requests fetch: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 5: Determine user role and membership - ULTRA OPTIMIZED
            step_start = time.time()
            role = "Member"
            membership_type = "trial"
            membership_status = "active"
            join_date = datetime.utcnow()

            # Check if user is captain
            if club.get("captain_id") == user_id:
                role = "Captain"
                membership_type = "paid"
            else:
                # Check if user is moderator
                detailed_moderators = club.get("detailed_moderators", [])
                for moderator in detailed_moderators:
                    if (
                        moderator.get("user_id") == user_id
                        and moderator.get("status") == "active"
                    ):
                        role = "Moderator"
                        membership_type = "paid"
                        break

                # Check if user is in paid members
                if role == "Member":
                    paid_members = club.get("paid_members", [])
                    for member in paid_members:
                        member_id = (
                            member.get("user_id")
                            if isinstance(member, dict)
                            else member
                        )
                        if member_id == user_id:
                            membership_type = "paid"
                            break

            print(
                f"⏱️ [USER STATUS] Role determination: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 6: Build response - ULTRA OPTIMIZED
            step_start = time.time()
            user_status = UserClubStatus(
                user_id=user_id,
                full_name=user.get("full_name", ""),
                email=user.get("email", ""),
                phone=user.get("phone", ""),
                avatar_url=user.get("avatar_url"),
                role=role,
                membership_type=membership_type,
                membership_status=membership_status,
                is_muted=is_muted,
                last_visited=last_visited,
                join_date=join_date,
                is_active=user.get("is_active", True),
                dm_requests_sent=dm_requests_sent_data,
                dm_requests_received=dm_requests_received_data,
                total_dm_requests_sent=len(dm_requests_sent_data),
                total_dm_requests_received=len(dm_requests_received_data),
                pending_dm_requests_sent=len(
                    [
                        req
                        for req in dm_requests_sent_data
                        if req.get("status") == "pending"
                    ]
                ),
                pending_dm_requests_received=len(
                    [
                        req
                        for req in dm_requests_received_data
                        if req.get("status") == "pending"
                    ]
                ),
            )

            response_data = {
                "user_status": user_status.dict(),
                "club_info": {
                    "club_id": actual_club_id,
                    "club_name": club.get("name", ""),
                    "name_based_id": club.get("name_based_id", ""),
                    "description": club.get("description", ""),
                    "status": club.get("status", ""),
                },
            }

            print(
                f"⏱️ [USER STATUS] Response building: {(time.time() - step_start)*1000:.2f}ms"
            )

            total_time = (time.time() - start_time) * 1000
            print(f"🚀 [USER STATUS] TOTAL TIME: {total_time:.2f}ms")

            return (
                True,
                UserClubStatusResponse(
                    success=True,
                    message="User status retrieved successfully",
                    data=response_data,
                ),
                None,
            )

        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            print(f"❌ [USER STATUS] Error after {total_time:.2f}ms: {e}")
            logger.error(f"Error getting user status in club: {e}")
            return False, None, f"Error retrieving user status: {str(e)}"

    async def get_all_members_status_in_club(
        self, club_id: str, current_user_id: str
    ) -> Tuple[bool, Optional[ClubMemberStatusResponse], Optional[str]]:
        """
        Get status of all members in a club chat room

        Args:
            club_id: Club ID to get members status for
            current_user_id: Current user ID (for authentication)

        Returns:
            Tuple of (success, response, error_message)
        """
        try:
            # Get club details first - handle both ObjectId and name_based_id
            club = None
            club_name_based_id = None
            try:
                # First try as ObjectId
                club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                if club:
                    club_name_based_id = club.get("name_based_id", club_id)
            except Exception:
                # If ObjectId fails, try as name_based_id
                club = await self.clubs_collection.find_one({"name_based_id": club_id})
                if club:
                    club_name_based_id = club_id

            if not club:
                return False, None, "Club not found"

            # Get the actual club_id (ObjectId) for database operations
            actual_club_id = str(club["_id"])

            # Check if current user has access to this club
            has_access = await self._check_user_membership(
                current_user_id, actual_club_id
            )
            if not has_access:
                return False, None, "You don't have access to this club"

            # Get all members from club document
            all_members = []

            # Add captain
            if club.get("captain_id"):
                captain_status = await self._get_member_status(
                    str(club["captain_id"]), actual_club_id, club_name_based_id
                )
                if captain_status:
                    all_members.append(captain_status)

            # Add moderators from detailed_moderators list
            detailed_moderators = club.get("detailed_moderators", [])
            for moderator in detailed_moderators:
                moderator_user_id = moderator.get("user_id")
                if moderator_user_id:
                    # Check if moderator is active
                    moderator_status = moderator.get("status", "active")
                    if moderator_status == "active":
                        # Fetch moderator user information from users table
                        moderator_user = await self.users_collection.find_one(
                            {"_id": ObjectId(moderator_user_id)}
                        )
                        if moderator_user and moderator_user.get("is_active", True):
                            moderator_status = await self._get_member_status(
                                str(moderator_user_id),
                                actual_club_id,
                                club_name_based_id,
                            )
                            if moderator_status:
                                all_members.append(moderator_status)
                        else:
                            logger.warning(
                                f"Moderator user {moderator_user_id} not found in users table or inactive"
                            )
                    else:
                        logger.warning(
                            f"Moderator {moderator_user_id} found but status is {moderator_status}"
                        )

            # Add members
            for member in club.get("members", []):
                # Handle both cases: member is a user_id string or member is an object with user_id field
                if isinstance(member, dict):
                    member_user_id = member.get("user_id")
                    if member_user_id:
                        member_status = await self._get_member_status(
                            str(member_user_id), actual_club_id, club_name_based_id
                        )
                        if member_status:
                            all_members.append(member_status)
                else:
                    # Direct user_id
                    member_status = await self._get_member_status(
                        str(member), actual_club_id, club_name_based_id
                    )
                    if member_status:
                        all_members.append(member_status)

            # Add paid members
            for paid_member in club.get("paid_members", []):
                # Handle both cases: paid_member is a user_id string or paid_member is an object with user_id field
                if isinstance(paid_member, dict):
                    paid_member_user_id = paid_member.get("user_id")
                    if paid_member_user_id:
                        paid_member_status = await self._get_member_status(
                            str(paid_member_user_id), actual_club_id, club_name_based_id
                        )
                        if paid_member_status:
                            all_members.append(paid_member_status)
                else:
                    # Direct user_id
                    paid_member_status = await self._get_member_status(
                        str(paid_member), actual_club_id, club_name_based_id
                    )
                    if paid_member_status:
                        all_members.append(paid_member_status)
            # Remove duplicates (in case user is in multiple arrays)
            unique_members = {}
            for member in all_members:
                unique_members[member.user_id] = member

            members_list = list(unique_members.values())
            print(f"🔍 Members list: {members_list}")

            # Sort by role (Captain first, then Moderator, then Member)
            role_order = {"Captain": 0, "Moderator": 1, "Member": 2}
            members_list.sort(key=lambda x: role_order.get(x.role, 3))
            print(f"🔍 Members list: {members_list}")

            response_data = {
                "club_info": {
                    "club_id": str(club["_id"]),
                    "club_name": club.get("name", ""),
                    "name_based_id": club.get("name_based_id", ""),
                    "description": club.get("description", ""),
                    "status": club.get("status", ""),
                    "total_members": len(members_list),
                },
                "members": [member.dict() for member in members_list],
                "summary": {
                    "total_members": len(members_list),
                    "captains": len([m for m in members_list if m.role == "Captain"]),
                    "moderators": len(
                        [m for m in members_list if m.role == "Moderator"]
                    ),
                    "members": len([m for m in members_list if m.role == "Member"]),
                    "active_members": len([m for m in members_list if m.is_active]),
                    "muted_members": len([m for m in members_list if m.is_muted]),
                    "trial_members": len(
                        [m for m in members_list if m.membership_type == "trial"]
                    ),
                    "paid_members": len(
                        [m for m in members_list if m.membership_type == "paid"]
                    ),
                },
            }

            return (
                True,
                ClubMemberStatusResponse(
                    success=True,
                    message="Club members status retrieved successfully",
                    data=response_data,
                ),
                None,
            )

        except Exception as e:
            logger.error(f"Error getting all members status in club: {e}")
            return False, None, f"Error retrieving members status: {str(e)}"

    async def _check_user_membership(self, user_id: str, club_id: str) -> bool:
        """Check if user is a member of the club"""
        try:
            club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                logger.error(f"Club not found with ID: {club_id}")
                return False

            logger.info(f"Checking membership for user {user_id} in club {club_id}")
            logger.info(f"Club captain_id: {club.get('captain_id')}")
            logger.info(f"Club moderators: {club.get('moderators', [])}")
            logger.info(f"Club members: {club.get('members', [])}")
            logger.info(f"Club paid_members: {club.get('paid_members', [])}")

            # Check if user is captain (handle both string and ObjectId comparison)
            captain_id = club.get("captain_id")
            if captain_id:
                if str(captain_id) == user_id or str(captain_id) == str(
                    ObjectId(user_id)
                ):
                    logger.info(f"User {user_id} is captain")
                    return True

            # Check if user is in moderators (handle both string and ObjectId comparison)
            moderators = club.get("moderators", [])
            for mod_id in moderators:
                if str(mod_id) == user_id or str(mod_id) == str(ObjectId(user_id)):
                    logger.info(f"User {user_id} is moderator")
                    return True

            # Check if user is in detailed_moderators list
            detailed_moderators = club.get("detailed_moderators", [])
            for moderator in detailed_moderators:
                if str(moderator.get("user_id")) == str(user_id):
                    # Check if moderator is active
                    moderator_status = moderator.get("status", "active")
                    if moderator_status == "active":
                        logger.info(
                            f"User {user_id} is active moderator in detailed_moderators"
                        )
                        return True
                    else:
                        logger.warning(
                            f"User {user_id} found in detailed_moderators but status is {moderator_status}"
                        )
                        return False

            # Check if user is in members (handle both user_id field and direct ID)
            members = club.get("members", [])
            for member in members:
                # Handle both cases: member is a user_id string or member is an object with user_id field
                if isinstance(member, dict):
                    member_user_id = member.get("user_id")
                    if member_user_id and (
                        str(member_user_id) == user_id
                        or str(member_user_id) == str(ObjectId(user_id))
                    ):
                        logger.info(f"User {user_id} is member (from user_id field)")
                        return True
                else:
                    # Direct user_id comparison
                    if str(member) == user_id or str(member) == str(ObjectId(user_id)):
                        logger.info(f"User {user_id} is member (direct ID)")
                        return True

            # Check if user is in paid_members (handle both user_id field and direct ID)
            paid_members = club.get("paid_members", [])
            for paid_member in paid_members:
                # Handle both cases: paid_member is a user_id string or paid_member is an object with user_id field
                if isinstance(paid_member, dict):
                    paid_member_user_id = paid_member.get("user_id")
                    if paid_member_user_id and (
                        str(paid_member_user_id) == user_id
                        or str(paid_member_user_id) == str(ObjectId(user_id))
                    ):
                        logger.info(
                            f"User {user_id} is paid member (from user_id field)"
                        )
                        return True
                else:
                    # Direct user_id comparison
                    if str(paid_member) == user_id or str(paid_member) == str(
                        ObjectId(user_id)
                    ):
                        logger.info(f"User {user_id} is paid member (direct ID)")
                        return True

            logger.warning(f"User {user_id} not found in any membership arrays")
            return False

        except Exception as e:
            logger.error(f"Error checking user membership: {e}")
            return False

    async def _get_member_status(
        self, user_id: str, club_id: str, club_name_based_id: str
    ) -> Optional[ClubMemberStatus]:
        """Get detailed status for a specific member"""
        try:
            # Get user details
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return None

            # Get user access information using club_name_based_id
            user_access = await self.user_access_collection.find_one(
                {"user_id": user_id, "club_id": club_name_based_id}
            )

            # Get DM requests for this user in this club
            dm_requests_sent = await self._get_dm_requests_sent(user_id, club_id)
            dm_requests_received = await self._get_dm_requests_received(
                user_id, club_id
            )

            # Get membership info
            membership_info = await self._get_user_membership_info(user_id, club_id)

            return ClubMemberStatus(
                user_id=user_id,
                full_name=user.get("full_name", ""),
                email=user.get("email", ""),
                phone=user.get("phone", ""),
                avatar_url=user.get("avatar_url"),
                role=membership_info.get("role", "Member"),
                membership_type=membership_info.get("membership_type", "trial"),
                membership_status=membership_info.get("membership_status", "active"),
                is_muted=user_access.get("is_muted", False) if user_access else False,
                last_visited=user_access.get("last_visited") if user_access else None,
                join_date=membership_info.get("join_date", datetime.utcnow()),
                is_active=membership_info.get("is_active", True),
                dm_requests_sent=dm_requests_sent,
                dm_requests_received=dm_requests_received,
                total_dm_requests_sent=len(dm_requests_sent),
                total_dm_requests_received=len(dm_requests_received),
                pending_dm_requests_sent=len(
                    [req for req in dm_requests_sent if req.status == "pending"]
                ),
                pending_dm_requests_received=len(
                    [req for req in dm_requests_received if req.status == "pending"]
                ),
            )

        except Exception as e:
            logger.error(f"Error getting member status: {e}")
            return None

    async def _get_dm_requests_sent(
        self, user_id: str, club_id: str
    ) -> List[DMRequestInfo]:
        """Get DM requests sent by user in this club"""
        try:
            # First try to find by name_based_id (as that's what's stored in dm_requests table)
            club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            name_based_id = club.get("name_based_id") if club else None

            # Try to find by name_based_id first
            requests = await self.dm_requests_collection.find(
                {"sender_id": user_id, "club_id": name_based_id}
            ).to_list(length=None)

            logger.info(
                f"DM requests sent - user_id: {user_id}, name_based_id: {name_based_id}, found: {len(requests)}"
            )

            # If not found by name_based_id, try by actual club_id
            if not requests and name_based_id != club_id:
                requests = await self.dm_requests_collection.find(
                    {"sender_id": user_id, "club_id": club_id}
                ).to_list(length=None)
                logger.info(
                    f"DM requests sent - fallback with club_id: {club_id}, found: {len(requests)}"
                )

            # Debug: Let's also check what DM requests exist in this club for sent requests
            all_dm_requests_sent = await self.dm_requests_collection.find(
                {"club_id": name_based_id}
            ).to_list(length=None)
            logger.info(
                f"All DM requests in club {name_based_id} for sent: {len(all_dm_requests_sent)}"
            )
            for req in all_dm_requests_sent:
                logger.info(
                    f"  DM Request: sender={req.get('sender_id')}, receiver={req.get('receiver_id')}, status={req.get('status')}"
                )

            dm_requests = []
            for req in requests:
                # Get sender and receiver names
                sender_name = await self._get_user_name(req.get("sender_id", ""))
                receiver_name = await self._get_user_name(req.get("receiver_id", ""))

                dm_requests.append(
                    DMRequestInfo(
                        request_id=str(req["_id"]),
                        sender_id=req.get("sender_id", ""),
                        sender_name=sender_name,
                        receiver_id=req.get("receiver_id", ""),
                        receiver_name=receiver_name,
                        status=req.get("status", "pending"),
                        created_at=req.get("created_at", datetime.utcnow()),
                        updated_at=req.get("updated_at"),
                        message=req.get("message"),
                    )
                )

            return dm_requests

        except Exception as e:
            logger.error(f"Error getting DM requests sent: {e}")
            return []

    async def _get_dm_requests_received(
        self, user_id: str, club_id: str
    ) -> List[DMRequestInfo]:
        """Get DM requests received by user in this club"""
        try:
            # First try to find by name_based_id (as that's what's stored in dm_requests table)
            club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            name_based_id = club.get("name_based_id") if club else None
            captain_id = (
                str(club.get("captain_id")) if club and club.get("captain_id") else None
            )

            # Try to find by name_based_id first
            requests = await self.dm_requests_collection.find(
                {"receiver_id": user_id, "club_id": name_based_id}
            ).to_list(length=None)

            logger.info(
                f"DM requests received - user_id: {user_id}, name_based_id: {name_based_id}, captain_id: {captain_id}, found: {len(requests)}"
            )

            # If not found by name_based_id, try by actual club_id
            if not requests and name_based_id != club_id:
                requests = await self.dm_requests_collection.find(
                    {"receiver_id": user_id, "club_id": club_id}
                ).to_list(length=None)
                logger.info(
                    f"DM requests received - fallback with club_id: {club_id}, found: {len(requests)}"
                )

            # Special case: If user is captain and no requests found, check if there are requests to captain_id
            if not requests and captain_id and user_id == captain_id:
                logger.info(
                    f"User is captain, checking for requests to captain_id: {captain_id}"
                )
                requests = await self.dm_requests_collection.find(
                    {"receiver_id": captain_id, "club_id": name_based_id}
                ).to_list(length=None)
                logger.info(f"DM requests to captain_id: {len(requests)}")

            # Additional check: If still no requests and user is captain, look for any DM requests in this club
            # This handles cases where the receiver_id in DM request might be different from captain_id
            if not requests and captain_id and user_id == captain_id:
                logger.info(
                    f"Checking all DM requests in club for potential captain matches..."
                )
                all_club_requests = await self.dm_requests_collection.find(
                    {"club_id": name_based_id}
                ).to_list(length=None)

                # Check if any of these requests are actually for the captain
                # Look for requests where the receiver might be the captain (even with different ID)
                captain_requests = []
                for req in all_club_requests:
                    req_receiver = req.get("receiver_id")
                    # If this is a request to the captain (even with different ID), include it
                    # This handles cases where captain_id might have changed or there are multiple captain records
                    if req_receiver and (
                        req_receiver == captain_id
                        or req_receiver == str(club.get("captain_id"))
                    ):
                        captain_requests.append(req)
                        logger.info(f"  Found DM request for captain: {req_receiver}")

                if captain_requests:
                    requests = captain_requests
                    logger.info(f"Captain found {len(captain_requests)} DM requests")
                else:
                    logger.info(
                        f"No captain-specific DM requests found in {len(all_club_requests)} total requests"
                    )

            # Debug: Let's also check what DM requests exist in this club
            all_dm_requests = await self.dm_requests_collection.find(
                {"club_id": name_based_id}
            ).to_list(length=None)
            logger.info(
                f"All DM requests in club {name_based_id}: {len(all_dm_requests)}"
            )
            for req in all_dm_requests:
                logger.info(
                    f"  DM Request: sender={req.get('sender_id')}, receiver={req.get('receiver_id')}, status={req.get('status')}"
                )

            dm_requests = []
            for req in requests:
                # Get sender and receiver names
                sender_name = await self._get_user_name(req.get("sender_id", ""))
                receiver_name = await self._get_user_name(req.get("receiver_id", ""))

                dm_requests.append(
                    DMRequestInfo(
                        request_id=str(req["_id"]),
                        sender_id=req.get("sender_id", ""),
                        sender_name=sender_name,
                        receiver_id=req.get("receiver_id", ""),
                        receiver_name=receiver_name,
                        status=req.get("status", "pending"),
                        created_at=req.get("created_at", datetime.utcnow()),
                        updated_at=req.get("updated_at"),
                        message=req.get("message"),
                    )
                )

            return dm_requests

        except Exception as e:
            logger.error(f"Error getting DM requests received: {e}")
            return []

    async def _get_user_membership_info(
        self, user_id: str, club_id: str
    ) -> Dict[str, Any]:
        """Get user's membership information in the club"""
        import time

        membership_start_time = time.time()

        try:
            club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                print(
                    f"⏱️ [MEMBERSHIP INFO] Club not found for user {user_id} in {(time.time() - membership_start_time)*1000:.2f}ms"
                )
                return {}

            # Check if user is captain
            if club.get("captain_id") == user_id:
                return {
                    "role": "Captain",
                    "membership_type": "paid",
                    "membership_status": "active",
                    "join_date": club.get("created_at", datetime.utcnow()),
                    "is_active": True,
                }

            # Check moderators
            if user_id in club.get("moderators", []):
                return {
                    "role": "Moderator",
                    "membership_type": "paid",
                    "membership_status": "active",
                    "join_date": club.get("created_at", datetime.utcnow()),
                    "is_active": True,
                }

            # Check detailed_moderators list
            detailed_moderators = club.get("detailed_moderators", [])
            for moderator in detailed_moderators:
                if str(moderator.get("user_id")) == str(user_id):
                    # Check if moderator is active
                    moderator_status = moderator.get("status", "active")
                    if moderator_status == "active":
                        # Fetch moderator user information from users table
                        moderator_user = await self.users_collection.find_one(
                            {"_id": ObjectId(user_id)}
                        )
                        if moderator_user and moderator_user.get("is_active", True):
                            return {
                                "role": "Moderator",
                                "membership_type": "moderator",
                                "membership_status": "active",
                                "join_date": moderator.get(
                                    "join_date",
                                    club.get("created_at", datetime.utcnow()),
                                ),
                                "is_active": True,
                            }
                        else:
                            logger.warning(
                                f"Moderator user {user_id} not found in users table or inactive"
                            )
                            return {
                                "role": "Moderator",
                                "membership_type": "moderator",
                                "membership_status": "inactive",
                                "join_date": moderator.get(
                                    "join_date",
                                    club.get("created_at", datetime.utcnow()),
                                ),
                                "is_active": False,
                            }
                    else:
                        logger.warning(
                            f"Moderator {user_id} found but status is {moderator_status}"
                        )
                        return {
                            "role": "Moderator",
                            "membership_type": "moderator",
                            "membership_status": "inactive",
                            "join_date": moderator.get(
                                "join_date", club.get("created_at", datetime.utcnow())
                            ),
                            "is_active": False,
                        }

            # Check members (handle both user_id field and direct ID)
            members = club.get("members", [])
            for member in members:
                if isinstance(member, dict):
                    member_user_id = member.get("user_id")
                    if member_user_id and (
                        str(member_user_id) == user_id
                        or str(member_user_id) == str(ObjectId(user_id))
                    ):
                        return {
                            "role": "Member",
                            "membership_type": member.get("membership_type", "trial"),
                            "membership_status": member.get(
                                "membership_status", "active"
                            ),
                            "join_date": member.get(
                                "join_date", club.get("created_at", datetime.utcnow())
                            ),
                            "is_active": member.get("is_active", True),
                        }
                else:
                    if str(member) == user_id or str(member) == str(ObjectId(user_id)):
                        return {
                            "role": "Member",
                            "membership_type": "trial",
                            "membership_status": "active",
                            "join_date": club.get("created_at", datetime.utcnow()),
                            "is_active": True,
                        }

            # Check paid members (handle both user_id field and direct ID)
            paid_members = club.get("paid_members", [])
            for paid_member in paid_members:
                if isinstance(paid_member, dict):
                    paid_member_user_id = paid_member.get("user_id")
                    if paid_member_user_id and (
                        str(paid_member_user_id) == user_id
                        or str(paid_member_user_id) == str(ObjectId(user_id))
                    ):
                        return {
                            "role": "Member",
                            "membership_type": paid_member.get(
                                "membership_type", "paid"
                            ),
                            "membership_status": paid_member.get(
                                "membership_status", "active"
                            ),
                            "join_date": paid_member.get(
                                "join_date", club.get("created_at", datetime.utcnow())
                            ),
                            "is_active": paid_member.get("is_active", True),
                        }
                else:
                    if str(paid_member) == user_id or str(paid_member) == str(
                        ObjectId(user_id)
                    ):
                        return {
                            "role": "Member",
                            "membership_type": "paid",
                            "membership_status": "active",
                            "join_date": club.get("created_at", datetime.utcnow()),
                            "is_active": True,
                        }

            return {
                "role": "Member",
                "membership_type": "trial",
                "membership_status": "inactive",
                "join_date": datetime.utcnow(),
                "is_active": False,
            }

        except Exception as e:
            total_membership_time = (time.time() - membership_start_time) * 1000
            print(f"⏱️ [MEMBERSHIP INFO] Error after {total_membership_time:.2f}ms: {e}")
            logger.error(f"Error getting user membership info: {e}")
            return {}

    async def _get_bulk_dm_requests(
        self, user_ids: List[str], club_id: str, club_name_based_id: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get DM requests for multiple users in a single query
        This is optimized to avoid N+1 query problem

        Args:
            user_ids: List of user IDs to get DM requests for
            club_id: Club ObjectId
            club_name_based_id: Club name-based ID

        Returns:
            Dictionary mapping user_id to DM requests data
        """
        import time

        bulk_start_time = time.time()

        try:
            print(
                f"⏱️ [BULK DM REQUESTS] Starting bulk DM requests lookup for {len(user_ids)} users"
            )

            # Get all DM requests for this club in one query
            # Try both name_based_id and club_id as DM requests might be stored with either
            all_dm_requests = []

            # First try with name_based_id (most common case)
            requests_by_name = await self.dm_requests_collection.find(
                {"club_id": club_name_based_id}
            ).to_list(length=None)
            all_dm_requests.extend(requests_by_name)

            # If no requests found and club_id is different, try with club_id as fallback
            if not requests_by_name and club_name_based_id != club_id:
                requests_by_id = await self.dm_requests_collection.find(
                    {"club_id": club_id}
                ).to_list(length=None)
                all_dm_requests.extend(requests_by_id)

            # If still no requests, try with ObjectId format (in case DM requests are stored with ObjectId)
            if not all_dm_requests:
                try:
                    requests_by_object_id = await self.dm_requests_collection.find(
                        {"club_id": ObjectId(club_id)}
                    ).to_list(length=None)
                    all_dm_requests.extend(requests_by_object_id)
                    print(
                        f"⏱️ [BULK DM REQUESTS] Found {len(requests_by_object_id)} requests with ObjectId format"
                    )
                except Exception as e:
                    print(f"⏱️ [BULK DM REQUESTS] ObjectId format failed: {e}")

            print(
                f"⏱️ [BULK DM REQUESTS] Found {len(all_dm_requests)} total DM requests in {(time.time() - bulk_start_time)*1000:.2f}ms"
            )
            print(
                f"⏱️ [BULK DM REQUESTS] Club name_based_id: {club_name_based_id}, club_id: {club_id}"
            )
            if all_dm_requests:
                print(f"⏱️ [BULK DM REQUESTS] Sample DM request: {all_dm_requests[0]}")
            step_start_time = time.time()

            # Initialize result dictionary
            dm_requests_data = {}

            # Process each user
            print(
                f"⏱️ [BULK DM REQUESTS] Processing DM requests for {len(user_ids)} users: {user_ids}"
            )
            for user_id in user_ids:
                # Filter DM requests for this user
                sent_requests = []
                received_requests = []

                for req in all_dm_requests:
                    req_sender_id = req.get("sender_id", "")
                    req_receiver_id = req.get("receiver_id", "")

                    if req_sender_id == user_id:
                        # Get receiver name
                        receiver_name = await self._get_user_name(req_receiver_id)
                        sent_requests.append(
                            {
                                "request_id": str(req["_id"]),
                                "sender_id": req_sender_id,
                                "sender_name": await self._get_user_name(req_sender_id),
                                "receiver_id": req_receiver_id,
                                "receiver_name": receiver_name,
                                "status": req.get("status", "pending"),
                                "created_at": req.get("created_at", datetime.utcnow()),
                                "updated_at": req.get("updated_at"),
                                "message": req.get("message"),
                            }
                        )
                        print(
                            f"⏱️ [BULK DM REQUESTS] Found sent request for user {user_id}: {req_sender_id} -> {req_receiver_id}"
                        )
                    elif req_receiver_id == user_id:
                        # Get sender name
                        sender_name = await self._get_user_name(req_sender_id)
                        received_requests.append(
                            {
                                "request_id": str(req["_id"]),
                                "sender_id": req_sender_id,
                                "sender_name": sender_name,
                                "receiver_id": req_receiver_id,
                                "receiver_name": await self._get_user_name(
                                    req_receiver_id
                                ),
                                "status": req.get("status", "pending"),
                                "created_at": req.get("created_at", datetime.utcnow()),
                                "updated_at": req.get("updated_at"),
                                "message": req.get("message"),
                            }
                        )
                        print(
                            f"⏱️ [BULK DM REQUESTS] Found received request for user {user_id}: {req_sender_id} -> {req_receiver_id}"
                        )

                print(
                    f"⏱️ [BULK DM REQUESTS] User {user_id}: {len(sent_requests)} sent, {len(received_requests)} received"
                )

                # Calculate counts
                total_sent = len(sent_requests)
                total_received = len(received_requests)
                pending_sent = len(
                    [r for r in sent_requests if r["status"] == "pending"]
                )
                pending_received = len(
                    [r for r in received_requests if r["status"] == "pending"]
                )

                dm_requests_data[user_id] = {
                    "dm_requests_sent": sent_requests,
                    "dm_requests_received": received_requests,
                    "total_dm_requests_sent": total_sent,
                    "total_dm_requests_received": total_received,
                    "pending_dm_requests_sent": pending_sent,
                    "pending_dm_requests_received": pending_received,
                }

            print(
                f"⏱️ [BULK DM REQUESTS] DM requests processing completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            total_bulk_time = (time.time() - bulk_start_time) * 1000
            print(
                f"⏱️ [BULK DM REQUESTS] Total bulk DM requests time: {total_bulk_time:.2f}ms"
            )

            return dm_requests_data

        except Exception as e:
            total_bulk_time = (time.time() - bulk_start_time) * 1000
            print(f"⏱️ [BULK DM REQUESTS] Error after {total_bulk_time:.2f}ms: {e}")
            logger.error(f"Error getting bulk DM requests: {e}")
            return {
                user_id: {
                    "dm_requests_sent": [],
                    "dm_requests_received": [],
                    "total_dm_requests_sent": 0,
                    "total_dm_requests_received": 0,
                    "pending_dm_requests_sent": 0,
                    "pending_dm_requests_received": 0,
                }
                for user_id in user_ids
            }

    async def _get_bulk_dm_requests_optimized(
        self, user_ids: List[str], club_id: str, club_name_based_id: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get DM requests for multiple users using optimized bulk method
        Replicates the exact logic from individual methods but in bulk
        """
        import time

        bulk_start_time = time.time()

        try:
            print(f"⏱️ [BULK DM REQUESTS OPTIMIZED] Starting for {len(user_ids)} users")

            # Get club document to get name_based_id (same as individual methods)
            club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            name_based_id = club.get("name_based_id") if club else club_name_based_id

            # Get all DM requests for this club in one query (same logic as individual methods)
            all_dm_requests = []

            # Try with name_based_id first (same as individual methods)
            requests_by_name = await self.dm_requests_collection.find(
                {"club_id": name_based_id}
            ).to_list(length=None)
            all_dm_requests.extend(requests_by_name)

            # If no requests found and club_id is different, try by actual club_id (fallback)
            if not requests_by_name and name_based_id != club_id:
                requests_by_id = await self.dm_requests_collection.find(
                    {"club_id": club_id}
                ).to_list(length=None)
                all_dm_requests.extend(requests_by_id)

            print(
                f"⏱️ [BULK DM REQUESTS OPTIMIZED] Found {len(all_dm_requests)} total requests in {(time.time() - bulk_start_time)*1000:.2f}ms"
            )

            # Get all user names in bulk to avoid N+1
            all_user_ids_in_requests = set(user_ids)
            for req in all_dm_requests:
                all_user_ids_in_requests.add(req.get("sender_id", ""))
                all_user_ids_in_requests.add(req.get("receiver_id", ""))

            # Remove empty strings and get unique user IDs
            all_user_ids_in_requests = [uid for uid in all_user_ids_in_requests if uid]

            # Get all user names in one bulk query
            user_names = await self._get_bulk_user_names(all_user_ids_in_requests)

            print(
                f"⏱️ [BULK DM REQUESTS OPTIMIZED] Got {len(user_names)} user names in {(time.time() - bulk_start_time)*1000:.2f}ms"
            )

            # Process DM requests for each user
            dm_requests_data = {}
            for user_id in user_ids:
                sent_requests = []
                received_requests = []

                for req in all_dm_requests:
                    req_sender_id = req.get("sender_id", "")
                    req_receiver_id = req.get("receiver_id", "")

                    if req_sender_id == user_id:
                        # This is a request sent by this user
                        sent_requests.append(
                            {
                                "request_id": str(req["_id"]),
                                "sender_id": req_sender_id,
                                "sender_name": user_names.get(req_sender_id, "Unknown"),
                                "receiver_id": req_receiver_id,
                                "receiver_name": user_names.get(
                                    req_receiver_id, "Unknown"
                                ),
                                "status": req.get("status", "pending"),
                                "created_at": req.get("created_at", datetime.utcnow()),
                                "updated_at": req.get("updated_at"),
                                "message": req.get("message"),
                            }
                        )
                    elif req_receiver_id == user_id:
                        # This is a request received by this user
                        received_requests.append(
                            {
                                "request_id": str(req["_id"]),
                                "sender_id": req_sender_id,
                                "sender_name": user_names.get(req_sender_id, "Unknown"),
                                "receiver_id": req_receiver_id,
                                "receiver_name": user_names.get(
                                    req_receiver_id, "Unknown"
                                ),
                                "status": req.get("status", "pending"),
                                "created_at": req.get("created_at", datetime.utcnow()),
                                "updated_at": req.get("updated_at"),
                                "message": req.get("message"),
                            }
                        )

                # Calculate counts
                total_sent = len(sent_requests)
                total_received = len(received_requests)
                pending_sent = len(
                    [r for r in sent_requests if r["status"] == "pending"]
                )
                pending_received = len(
                    [r for r in received_requests if r["status"] == "pending"]
                )

                dm_requests_data[user_id] = {
                    "dm_requests_sent": sent_requests,
                    "dm_requests_received": received_requests,
                    "total_dm_requests_sent": total_sent,
                    "total_dm_requests_received": total_received,
                    "pending_dm_requests_sent": pending_sent,
                    "pending_dm_requests_received": pending_received,
                }

            total_time = (time.time() - bulk_start_time) * 1000
            print(f"⏱️ [BULK DM REQUESTS OPTIMIZED] Completed in {total_time:.2f}ms")

            return dm_requests_data

        except Exception as e:
            total_time = (time.time() - bulk_start_time) * 1000
            print(f"⏱️ [BULK DM REQUESTS OPTIMIZED] Error after {total_time:.2f}ms: {e}")
            logger.error(f"Error getting bulk DM requests optimized: {e}")
            return {
                user_id: {
                    "dm_requests_sent": [],
                    "dm_requests_received": [],
                    "total_dm_requests_sent": 0,
                    "total_dm_requests_received": 0,
                    "pending_dm_requests_sent": 0,
                    "pending_dm_requests_received": 0,
                }
                for user_id in user_ids
            }

    async def _get_bulk_user_names(self, user_ids: List[str]) -> Dict[str, str]:
        """
        Get user names for multiple users in a single query to avoid N+1 problem
        """
        try:
            if not user_ids:
                return {}

            # Convert user IDs to ObjectIds
            object_ids = [ObjectId(user_id) for user_id in user_ids]

            # Get all users in one query
            users = await self.users_collection.find(
                {"_id": {"$in": object_ids}}, {"_id": 1, "full_name": 1}
            ).to_list(length=None)

            # Create mapping
            user_names = {}
            for user in users:
                user_id = str(user["_id"])
                user_names[user_id] = user.get("full_name", "Unknown")

            return user_names

        except Exception as e:
            logger.error(f"Error getting bulk user names: {e}")
            return {user_id: "Unknown" for user_id in user_ids}

    async def _get_bulk_membership_info(
        self, user_ids: List[str], club_id: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get membership information for multiple users from club document in a single query
        This is optimized to avoid N+1 query problem

        Args:
            user_ids: List of user IDs to get membership info for
            club_id: Club ObjectId

        Returns:
            Dictionary mapping user_id to membership info
        """
        import time

        bulk_start_time = time.time()

        try:
            print(
                f"⏱️ [BULK MEMBERSHIP] Starting bulk membership lookup for {len(user_ids)} users"
            )

            # Get club document once
            club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                print(
                    f"⏱️ [BULK MEMBERSHIP] Club not found in {(time.time() - bulk_start_time)*1000:.2f}ms"
                )
                return {user_id: {} for user_id in user_ids}

            print(
                f"⏱️ [BULK MEMBERSHIP] Club document fetched in {(time.time() - bulk_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Initialize result dictionary
            membership_data = {}

            # Check captain
            captain_id = club.get("captain_id")
            if captain_id and captain_id in user_ids:
                membership_data[captain_id] = {
                    "role": "Captain",
                    "membership_type": "paid",
                    "membership_status": "active",
                    "join_date": club.get("created_at", datetime.utcnow()),
                    "is_active": True,
                }

            # Check detailed moderators
            detailed_moderators = club.get("detailed_moderators", [])
            for moderator in detailed_moderators:
                moderator_user_id = moderator.get("user_id")
                if moderator_user_id and str(moderator_user_id) in user_ids:
                    membership_data[str(moderator_user_id)] = {
                        "role": "Moderator",
                        "membership_type": "moderator",
                        "membership_status": moderator.get("status", "active"),
                        "join_date": moderator.get(
                            "assigned_at", club.get("created_at", datetime.utcnow())
                        ),
                        "is_active": moderator.get("status", "active") == "active",
                    }

            # Check regular members
            members = club.get("members", [])
            for member in members:
                if isinstance(member, dict):
                    member_user_id = member.get("user_id")
                    if member_user_id and str(member_user_id) in user_ids:
                        membership_data[str(member_user_id)] = {
                            "role": "Member",
                            "membership_type": member.get("membership_type", "trial"),
                            "membership_status": member.get(
                                "membership_status", "active"
                            ),
                            "join_date": member.get(
                                "join_date", club.get("created_at", datetime.utcnow())
                            ),
                            "is_active": member.get("is_active", True),
                        }
                else:
                    if str(member) in user_ids:
                        membership_data[str(member)] = {
                            "role": "Member",
                            "membership_type": "trial",
                            "membership_status": "active",
                            "join_date": club.get("created_at", datetime.utcnow()),
                            "is_active": True,
                        }

            # Check paid members
            paid_members = club.get("paid_members", [])
            for paid_member in paid_members:
                if isinstance(paid_member, dict):
                    paid_member_user_id = paid_member.get("user_id")
                    if paid_member_user_id and str(paid_member_user_id) in user_ids:
                        membership_data[str(paid_member_user_id)] = {
                            "role": "Member",
                            "membership_type": "paid",
                            "membership_status": paid_member.get(
                                "membership_status", "active"
                            ),
                            "join_date": paid_member.get(
                                "join_date", club.get("created_at", datetime.utcnow())
                            ),
                            "is_active": paid_member.get("is_active", True),
                        }
                else:
                    if str(paid_member) in user_ids:
                        membership_data[str(paid_member)] = {
                            "role": "Member",
                            "membership_type": "paid",
                            "membership_status": "active",
                            "join_date": club.get("created_at", datetime.utcnow()),
                            "is_active": True,
                        }

            # Fill in missing users with default inactive status
            for user_id in user_ids:
                if user_id not in membership_data:
                    membership_data[user_id] = {
                        "role": "Unknown",
                        "membership_type": "unknown",
                        "membership_status": "inactive",
                        "join_date": datetime.utcnow(),
                        "is_active": False,
                    }

            print(
                f"⏱️ [BULK MEMBERSHIP] Membership data processing completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            total_bulk_time = (time.time() - bulk_start_time) * 1000
            print(
                f"⏱️ [BULK MEMBERSHIP] Total bulk membership time: {total_bulk_time:.2f}ms"
            )

            return membership_data

        except Exception as e:
            total_bulk_time = (time.time() - bulk_start_time) * 1000
            print(f"⏱️ [BULK MEMBERSHIP] Error after {total_bulk_time:.2f}ms: {e}")
            logger.error(f"Error getting bulk membership info: {e}")
            return {user_id: {} for user_id in user_ids}

    async def _get_pinned_messages(self, club_id: str) -> List[Dict[str, Any]]:
        """Get pinned messages for the club"""
        try:
            # Look for messages that have a 'pinned' object (not just is_pinned boolean)
            pinned_messages = (
                await self.messages_collection.find(
                    {"club_id": club_id, "pinned": {"$exists": True, "$ne": None}}
                )
                .sort("pinned.pinned_at", -1)
                .to_list(length=10)
            )

            logger.info(
                f"Found {len(pinned_messages)} pinned messages for club {club_id}"
            )

            result = []
            for msg in pinned_messages:
                pinned_info = msg.get("pinned", {})
                result.append(
                    {
                        "message_id": str(msg["_id"]),
                        "content": msg.get("content", ""),
                        "sender_id": msg.get("sender_id", ""),
                        "sender_name": msg.get("sender_name", ""),
                        "sender_role": msg.get("sender_role", ""),
                        "message_type": msg.get("message_type", "text"),
                        "created_at": msg.get("created_at"),
                        "pinned_at": pinned_info.get("pinned_at"),
                        "pinned_by": pinned_info.get("pinned_by", ""),
                        "pinned_by_username": pinned_info.get("pinned_by_username", ""),
                        "pinned_reason": pinned_info.get("reason", ""),
                        "reactions": msg.get("reactions", []),
                        "reply_count": msg.get("reply_count", 0),
                        "is_deleted": msg.get("is_deleted", False),
                    }
                )

            logger.info(f"Returning {len(result)} pinned messages")
            return result

        except Exception as e:
            logger.error(f"Error getting pinned messages: {e}")
            return []

    async def _get_recent_messages(
        self, club_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent messages for the club"""
        try:
            recent_messages = (
                await self.messages_collection.find({"club_id": club_id})
                .sort("created_at", -1)
                .limit(limit)
                .to_list(length=limit)
            )

            result = []
            for msg in recent_messages:
                result.append(
                    {
                        "message_id": str(msg["_id"]),
                        "content": msg.get("content", ""),
                        "sender_id": msg.get("sender_id", ""),
                        "sender_name": msg.get("sender_name", ""),
                        "message_type": msg.get("message_type", "text"),
                        "created_at": msg.get("created_at"),
                        "is_pinned": msg.get("is_pinned", False),
                        "reactions": msg.get("reactions", []),
                        "reply_count": msg.get("reply_count", 0),
                        "thread_id": msg.get("thread_id"),
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Error getting recent messages: {e}")
            return []

    async def _get_optimized_member_data(
        self, user_id: str, club_id: str, club_name_based_id: str
    ) -> Optional[dict]:
        """
        Get optimized member data using aggregation pipeline for better performance

        Args:
            user_id: User ID to get data for
            club_id: Club ObjectId
            club_name_based_id: Club name-based ID

        Returns:
            Dictionary with complete member data or None
        """
        try:
            # Create aggregation pipeline to get all member data in one query
            pipeline = [
                # Match the user
                {"$match": {"_id": ObjectId(user_id)}},
                # Lookup user access information
                {
                    "$lookup": {
                        "from": "user_access",
                        "let": {"user_id": "$_id", "club_id": club_name_based_id},
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {
                                                "$eq": [
                                                    "$user_id",
                                                    {"$toString": "$$user_id"},
                                                ]
                                            },
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "user_access",
                    }
                },
                # Lookup DM requests sent
                {
                    "$lookup": {
                        "from": "dm_requests",
                        "let": {
                            "user_id": {"$toString": "$_id"},
                            "club_id": club_name_based_id,
                        },
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$sender_id", "$$user_id"]},
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "dm_requests_sent",
                    }
                },
                # Lookup DM requests received
                {
                    "$lookup": {
                        "from": "dm_requests",
                        "let": {
                            "user_id": {"$toString": "$_id"},
                            "club_id": club_name_based_id,
                        },
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$receiver_id", "$$user_id"]},
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "dm_requests_received",
                    }
                },
                # Project the final result
                {
                    "$project": {
                        "user_id": {"$toString": "$_id"},
                        "full_name": 1,
                        "email": 1,
                        "phone": 1,
                        "avatar_url": 1,
                        "is_active": {"$ifNull": ["$is_active", True]},
                        "is_muted": {
                            "$ifNull": [
                                {"$arrayElemAt": ["$user_access.is_muted", 0]},
                                False,
                            ]
                        },
                        "last_visited": {
                            "$arrayElemAt": ["$user_access.last_visited", 0]
                        },
                        "dm_requests_sent": {
                            "$map": {
                                "input": "$dm_requests_sent",
                                "as": "req",
                                "in": {
                                    "request_id": {"$toString": "$$req._id"},
                                    "sender_id": "$$req.sender_id",
                                    "sender_name": "$$req.sender_name",
                                    "receiver_id": "$$req.receiver_id",
                                    "receiver_name": "$$req.receiver_name",
                                    "status": "$$req.status",
                                    "created_at": "$$req.created_at",
                                    "updated_at": "$$req.updated_at",
                                    "message": "$$req.message",
                                },
                            }
                        },
                        "dm_requests_received": {
                            "$map": {
                                "input": "$dm_requests_received",
                                "as": "req",
                                "in": {
                                    "request_id": {"$toString": "$$req._id"},
                                    "sender_id": "$$req.sender_id",
                                    "sender_name": "$$req.sender_name",
                                    "receiver_id": "$$req.receiver_id",
                                    "receiver_name": "$$req.receiver_name",
                                    "status": "$$req.status",
                                    "created_at": "$$req.created_at",
                                    "updated_at": "$$req.updated_at",
                                    "message": "$$req.message",
                                },
                            }
                        },
                    }
                },
            ]

            # Execute the aggregation pipeline
            result = await self.users_collection.aggregate(pipeline).to_list(length=1)

            if not result:
                return None

            user_data = result[0]

            # Get membership info from club (this is still needed as it's club-specific)
            membership_info = await self._get_user_membership_info(user_id, club_id)

            # Combine all data
            return {
                "user_id": user_data["user_id"],
                "full_name": user_data.get("full_name", ""),
                "email": user_data.get("email", ""),
                "phone": user_data.get("phone", ""),
                "avatar_url": user_data.get("avatar_url"),
                "role": membership_info.get("role", "Member"),
                "membership_type": membership_info.get("membership_type", "trial"),
                "membership_status": membership_info.get("membership_status", "active"),
                "is_muted": user_data.get("is_muted", False),
                "last_visited": user_data.get("last_visited"),
                "join_date": membership_info.get("join_date", datetime.utcnow()),
                "is_active": user_data.get("is_active", True),
                "dm_requests_sent": user_data.get("dm_requests_sent", []),
                "dm_requests_received": user_data.get("dm_requests_received", []),
                "total_dm_requests_sent": len(user_data.get("dm_requests_sent", [])),
                "total_dm_requests_received": len(
                    user_data.get("dm_requests_received", [])
                ),
                "pending_dm_requests_sent": len(
                    [
                        req
                        for req in user_data.get("dm_requests_sent", [])
                        if req.get("status") == "pending"
                    ]
                ),
                "pending_dm_requests_received": len(
                    [
                        req
                        for req in user_data.get("dm_requests_received", [])
                        if req.get("status") == "pending"
                    ]
                ),
            }

        except Exception as e:
            logger.error(f"Error getting optimized member data for {user_id}: {e}")
            return None

    async def _get_optimized_members_data_batch(
        self, user_ids: List[str], club_id: str, club_name_based_id: str
    ) -> List[dict]:
        """
        Get optimized member data for multiple users using batch aggregation pipeline

        Args:
            user_ids: List of user IDs to get data for
            club_id: Club ObjectId
            club_name_based_id: Club name-based ID

        Returns:
            List of dictionaries with complete member data
        """
        try:
            if not user_ids:
                return []

            # Convert user IDs to ObjectIds
            object_ids = [ObjectId(user_id) for user_id in user_ids]

            # Create aggregation pipeline for batch processing
            pipeline = [
                # Match multiple users
                {"$match": {"_id": {"$in": object_ids}}},
                # Lookup user access information
                {
                    "$lookup": {
                        "from": "user_access",
                        "let": {"user_id": "$_id", "club_id": club_name_based_id},
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {
                                                "$eq": [
                                                    "$user_id",
                                                    {"$toString": "$$user_id"},
                                                ]
                                            },
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "user_access",
                    }
                },
                # Lookup DM requests sent
                {
                    "$lookup": {
                        "from": "dm_requests",
                        "let": {
                            "user_id": {"$toString": "$_id"},
                            "club_id": club_name_based_id,
                        },
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$sender_id", "$$user_id"]},
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "dm_requests_sent",
                    }
                },
                # Lookup DM requests received
                {
                    "$lookup": {
                        "from": "dm_requests",
                        "let": {
                            "user_id": {"$toString": "$_id"},
                            "club_id": club_name_based_id,
                        },
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$receiver_id", "$$user_id"]},
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "dm_requests_received",
                    }
                },
                # Project the final result
                {
                    "$project": {
                        "user_id": {"$toString": "$_id"},
                        "full_name": 1,
                        "email": 1,
                        "phone": 1,
                        "avatar_url": 1,
                        "is_active": {"$ifNull": ["$is_active", True]},
                        "is_muted": {
                            "$ifNull": [
                                {"$arrayElemAt": ["$user_access.is_muted", 0]},
                                False,
                            ]
                        },
                        "last_visited": {
                            "$arrayElemAt": ["$user_access.last_visited", 0]
                        },
                        "dm_requests_sent": {
                            "$map": {
                                "input": "$dm_requests_sent",
                                "as": "req",
                                "in": {
                                    "request_id": {"$toString": "$$req._id"},
                                    "sender_id": "$$req.sender_id",
                                    "sender_name": "$$req.sender_name",
                                    "receiver_id": "$$req.receiver_id",
                                    "receiver_name": "$$req.receiver_name",
                                    "status": "$$req.status",
                                    "created_at": "$$req.created_at",
                                    "updated_at": "$$req.updated_at",
                                    "message": "$$req.message",
                                },
                            }
                        },
                        "dm_requests_received": {
                            "$map": {
                                "input": "$dm_requests_received",
                                "as": "req",
                                "in": {
                                    "request_id": {"$toString": "$$req._id"},
                                    "sender_id": "$$req.sender_id",
                                    "sender_name": "$$req.sender_name",
                                    "receiver_id": "$$req.receiver_id",
                                    "receiver_name": "$$req.receiver_name",
                                    "status": "$$req.status",
                                    "created_at": "$$req.created_at",
                                    "updated_at": "$$req.updated_at",
                                    "message": "$$req.message",
                                },
                            }
                        },
                    }
                },
            ]

            # Execute the aggregation pipeline
            results = await self.users_collection.aggregate(pipeline).to_list(
                length=None
            )

            # Get membership info for all users from club using single optimized query
            membership_data = await self._get_bulk_membership_info(user_ids, club_id)

            # Get DM requests for all users using optimized bulk method
            dm_requests_data = await self._get_bulk_dm_requests_optimized(
                user_ids, club_id, club_name_based_id
            )

            # Combine all data
            members_data = []
            for user_data in results:
                user_id = user_data["user_id"]
                membership_info = membership_data.get(user_id, {})
                dm_requests_info = dm_requests_data.get(
                    user_id,
                    {
                        "dm_requests_sent": [],
                        "dm_requests_received": [],
                        "total_dm_requests_sent": 0,
                        "total_dm_requests_received": 0,
                        "pending_dm_requests_sent": 0,
                        "pending_dm_requests_received": 0,
                    },
                )

                members_data.append(
                    {
                        "user_id": user_id,
                        "full_name": user_data.get("full_name", ""),
                        "email": user_data.get("email", ""),
                        "phone": user_data.get("phone", ""),
                        "avatar_url": user_data.get("avatar_url"),
                        "role": membership_info.get("role", "Member"),
                        "membership_type": membership_info.get(
                            "membership_type", "trial"
                        ),
                        "membership_status": membership_info.get(
                            "membership_status", "active"
                        ),
                        "is_muted": user_data.get("is_muted", False),
                        "last_visited": user_data.get("last_visited"),
                        "join_date": membership_info.get(
                            "join_date", datetime.utcnow()
                        ),
                        "is_active": user_data.get("is_active", True),
                        "dm_requests_sent": dm_requests_info.get(
                            "dm_requests_sent", []
                        ),
                        "dm_requests_received": dm_requests_info.get(
                            "dm_requests_received", []
                        ),
                        "total_dm_requests_sent": dm_requests_info.get(
                            "total_dm_requests_sent", 0
                        ),
                        "total_dm_requests_received": dm_requests_info.get(
                            "total_dm_requests_received", 0
                        ),
                        "pending_dm_requests_sent": dm_requests_info.get(
                            "pending_dm_requests_sent", 0
                        ),
                        "pending_dm_requests_received": dm_requests_info.get(
                            "pending_dm_requests_received", 0
                        ),
                    }
                )

            return members_data

        except Exception as e:
            logger.error(f"Error getting optimized members data batch: {e}")
            return []

    async def _get_optimized_moderator_data_batch(
        self, user_ids: List[str], club_id: str, club_name_based_id: str
    ) -> List[dict]:
        """
        Get optimized moderator data for multiple users using batch aggregation pipeline
        Includes is_register field specifically for moderators

        Args:
            user_ids: List of user IDs to get data for
            club_id: Club ObjectId
            club_name_based_id: Club name-based ID

        Returns:
            List of dictionaries with complete moderator data including is_register
        """
        import time

        batch_start_time = time.time()
        step_start_time = time.time()

        try:
            print(
                f"⏱️ [MODERATORS BATCH] Starting batch processing for {len(user_ids)} users"
            )

            if not user_ids:
                print(
                    f"⏱️ [MODERATORS BATCH] No user IDs provided, returning empty list"
                )
                return []

            # Convert user IDs to ObjectIds
            object_ids = [ObjectId(user_id) for user_id in user_ids]
            print(
                f"⏱️ [MODERATORS BATCH] ObjectId conversion completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Create aggregation pipeline for batch processing with is_register field
            pipeline = [
                # Match multiple users
                {"$match": {"_id": {"$in": object_ids}}},
                # Lookup user access information
                {
                    "$lookup": {
                        "from": "user_access",
                        "let": {"user_id": "$_id", "club_id": club_name_based_id},
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {
                                                "$eq": [
                                                    "$user_id",
                                                    {"$toString": "$$user_id"},
                                                ]
                                            },
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "user_access",
                    }
                },
                # Lookup DM requests sent
                {
                    "$lookup": {
                        "from": "dm_requests",
                        "let": {
                            "user_id": {"$toString": "$_id"},
                            "club_id": club_name_based_id,
                        },
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$sender_id", "$$user_id"]},
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "dm_requests_sent",
                    }
                },
                # Lookup DM requests received
                {
                    "$lookup": {
                        "from": "dm_requests",
                        "let": {
                            "user_id": {"$toString": "$_id"},
                            "club_id": club_name_based_id,
                        },
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$receiver_id", "$$user_id"]},
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "dm_requests_received",
                    }
                },
                # Project the final result with is_register field for moderators
                {
                    "$project": {
                        "user_id": {"$toString": "$_id"},
                        "full_name": 1,
                        "email": 1,
                        "phone": 1,
                        "avatar_url": 1,
                        "is_active": {"$ifNull": ["$is_active", True]},
                        "is_register": {"$ifNull": ["$is_register", True]},
                        "is_muted": {
                            "$ifNull": [
                                {"$arrayElemAt": ["$user_access.is_muted", 0]},
                                False,
                            ]
                        },
                        "last_visited": {
                            "$arrayElemAt": ["$user_access.last_visited", 0]
                        },
                        "dm_requests_sent": {
                            "$map": {
                                "input": "$dm_requests_sent",
                                "as": "req",
                                "in": {
                                    "request_id": {"$toString": "$$req._id"},
                                    "sender_id": "$$req.sender_id",
                                    "sender_name": "$$req.sender_name",
                                    "receiver_id": "$$req.receiver_id",
                                    "receiver_name": "$$req.receiver_name",
                                    "status": "$$req.status",
                                    "created_at": "$$req.created_at",
                                    "updated_at": "$$req.updated_at",
                                    "message": "$$req.message",
                                },
                            }
                        },
                        "dm_requests_received": {
                            "$map": {
                                "input": "$dm_requests_received",
                                "as": "req",
                                "in": {
                                    "request_id": {"$toString": "$$req._id"},
                                    "sender_id": "$$req.sender_id",
                                    "sender_name": "$$req.sender_name",
                                    "receiver_id": "$$req.receiver_id",
                                    "receiver_name": "$$req.receiver_name",
                                    "status": "$$req.status",
                                    "created_at": "$$req.created_at",
                                    "updated_at": "$$req.updated_at",
                                    "message": "$$req.message",
                                },
                            }
                        },
                    }
                },
            ]

            # Execute the aggregation pipeline
            print(
                f"⏱️ [MODERATORS BATCH] Executing aggregation pipeline for {len(object_ids)} users"
            )
            results = await self.users_collection.aggregate(pipeline).to_list(
                length=None
            )
            print(
                f"⏱️ [MODERATORS BATCH] Aggregation pipeline completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Get membership info for all users from club using single optimized query
            membership_data = await self._get_bulk_membership_info(user_ids, club_id)

            # Get DM requests for all users using optimized bulk method
            dm_requests_data = await self._get_bulk_dm_requests_optimized(
                user_ids, club_id, club_name_based_id
            )

            print(
                f"⏱️ [MODERATORS BATCH] Membership info fetch completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Combine all data with is_register field for moderators
            moderators_data = []
            for user_data in results:
                user_id = user_data["user_id"]
                membership_info = membership_data.get(user_id, {})
                dm_requests_info = dm_requests_data.get(
                    user_id,
                    {
                        "dm_requests_sent": [],
                        "dm_requests_received": [],
                        "total_dm_requests_sent": 0,
                        "total_dm_requests_received": 0,
                        "pending_dm_requests_sent": 0,
                        "pending_dm_requests_received": 0,
                    },
                )

                moderators_data.append(
                    {
                        "user_id": user_id,
                        "full_name": user_data.get("full_name", ""),
                        "email": user_data.get("email", ""),
                        "phone": user_data.get("phone", ""),
                        "avatar_url": user_data.get("avatar_url"),
                        "role": membership_info.get("role", "Moderator"),
                        "membership_type": membership_info.get(
                            "membership_type", "moderator"
                        ),
                        "membership_status": membership_info.get(
                            "membership_status", "active"
                        ),
                        "is_muted": user_data.get("is_muted", False),
                        "last_visited": user_data.get("last_visited"),
                        "join_date": membership_info.get(
                            "join_date", datetime.utcnow()
                        ),
                        "is_active": user_data.get("is_active", True),
                        "is_register": user_data.get("is_register", True),
                        "dm_requests_sent": dm_requests_info.get(
                            "dm_requests_sent", []
                        ),
                        "dm_requests_received": dm_requests_info.get(
                            "dm_requests_received", []
                        ),
                        "total_dm_requests_sent": dm_requests_info.get(
                            "total_dm_requests_sent", 0
                        ),
                        "total_dm_requests_received": dm_requests_info.get(
                            "total_dm_requests_received", 0
                        ),
                        "pending_dm_requests_sent": dm_requests_info.get(
                            "pending_dm_requests_sent", 0
                        ),
                        "pending_dm_requests_received": dm_requests_info.get(
                            "pending_dm_requests_received", 0
                        ),
                    }
                )

            print(
                f"⏱️ [MODERATORS BATCH] Data processing completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            total_batch_time = (time.time() - batch_start_time) * 1000
            print(
                f"⏱️ [MODERATORS BATCH] Total batch processing time: {total_batch_time:.2f}ms"
            )

            return moderators_data

        except Exception as e:
            total_batch_time = (time.time() - batch_start_time) * 1000
            print(f"⏱️ [MODERATORS BATCH] Error after {total_batch_time:.2f}ms: {e}")
            logger.error(f"Error getting optimized moderators data batch: {e}")
            return []

    async def _get_optimized_captain_data_batch(
        self, user_ids: List[str], club_id: str, club_name_based_id: str
    ) -> List[dict]:
        """
        Get optimized captain data for multiple users using batch aggregation pipeline
        Similar to moderator batch but optimized for captain role

        Args:
            user_ids: List of user IDs to get data for (typically just one captain)
            club_id: Club ObjectId
            club_name_based_id: Club name-based ID

        Returns:
            List of dictionaries with complete captain data
        """
        import time

        batch_start_time = time.time()
        step_start_time = time.time()

        try:
            print(
                f"⏱️ [CAPTAINS BATCH] Starting batch processing for {len(user_ids)} users"
            )

            if not user_ids:
                print(f"⏱️ [CAPTAINS BATCH] No user IDs provided, returning empty list")
                return []

            # Convert user IDs to ObjectIds
            object_ids = [ObjectId(user_id) for user_id in user_ids]
            print(
                f"⏱️ [CAPTAINS BATCH] ObjectId conversion completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Create aggregation pipeline for batch processing (same as moderator but without is_register field)
            pipeline = [
                # Match multiple users
                {"$match": {"_id": {"$in": object_ids}}},
                # Lookup user access information
                {
                    "$lookup": {
                        "from": "user_access",
                        "let": {"user_id": "$_id", "club_id": club_name_based_id},
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {
                                                "$eq": [
                                                    "$user_id",
                                                    {"$toString": "$$user_id"},
                                                ]
                                            },
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "user_access",
                    }
                },
                # Lookup DM requests sent
                {
                    "$lookup": {
                        "from": "dm_requests",
                        "let": {
                            "user_id": {"$toString": "$_id"},
                            "club_id": club_name_based_id,
                        },
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$sender_id", "$$user_id"]},
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "dm_requests_sent",
                    }
                },
                # Lookup DM requests received
                {
                    "$lookup": {
                        "from": "dm_requests",
                        "let": {
                            "user_id": {"$toString": "$_id"},
                            "club_id": club_name_based_id,
                        },
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$receiver_id", "$$user_id"]},
                                            {"$eq": ["$club_id", "$$club_id"]},
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "dm_requests_received",
                    }
                },
                # Project the final result (no is_register field for captains)
                {
                    "$project": {
                        "user_id": {"$toString": "$_id"},
                        "full_name": 1,
                        "email": 1,
                        "phone": 1,
                        "avatar_url": 1,
                        "is_active": {"$ifNull": ["$is_active", True]},
                        "is_muted": {
                            "$ifNull": [
                                {"$arrayElemAt": ["$user_access.is_muted", 0]},
                                False,
                            ]
                        },
                        "last_visited": {
                            "$arrayElemAt": ["$user_access.last_visited", 0]
                        },
                        "dm_requests_sent": {
                            "$map": {
                                "input": "$dm_requests_sent",
                                "as": "req",
                                "in": {
                                    "request_id": {"$toString": "$$req._id"},
                                    "sender_id": "$$req.sender_id",
                                    "sender_name": "$$req.sender_name",
                                    "receiver_id": "$$req.receiver_id",
                                    "receiver_name": "$$req.receiver_name",
                                    "status": "$$req.status",
                                    "created_at": "$$req.created_at",
                                    "updated_at": "$$req.updated_at",
                                    "message": "$$req.message",
                                },
                            }
                        },
                        "dm_requests_received": {
                            "$map": {
                                "input": "$dm_requests_received",
                                "as": "req",
                                "in": {
                                    "request_id": {"$toString": "$$req._id"},
                                    "sender_id": "$$req.sender_id",
                                    "sender_name": "$$req.sender_name",
                                    "receiver_id": "$$req.receiver_id",
                                    "receiver_name": "$$req.receiver_name",
                                    "status": "$$req.status",
                                    "created_at": "$$req.created_at",
                                    "updated_at": "$$req.updated_at",
                                    "message": "$$req.message",
                                },
                            }
                        },
                    }
                },
            ]

            # Execute the aggregation pipeline
            print(
                f"⏱️ [CAPTAINS BATCH] Executing aggregation pipeline for {len(object_ids)} users"
            )
            results = await self.users_collection.aggregate(pipeline).to_list(
                length=None
            )
            print(
                f"⏱️ [CAPTAINS BATCH] Aggregation pipeline completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Get membership info for all users from club using single optimized query
            membership_data = await self._get_bulk_membership_info(user_ids, club_id)

            # Get DM requests for all users using optimized bulk method
            dm_requests_data = await self._get_bulk_dm_requests_optimized(
                user_ids, club_id, club_name_based_id
            )

            print(
                f"⏱️ [CAPTAINS BATCH] Membership info fetch completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Combine all data (no is_register field for captains)
            captains_data = []
            for user_data in results:
                user_id = user_data["user_id"]
                membership_info = membership_data.get(user_id, {})
                dm_requests_info = dm_requests_data.get(
                    user_id,
                    {
                        "dm_requests_sent": [],
                        "dm_requests_received": [],
                        "total_dm_requests_sent": 0,
                        "total_dm_requests_received": 0,
                        "pending_dm_requests_sent": 0,
                        "pending_dm_requests_received": 0,
                    },
                )

                captains_data.append(
                    {
                        "user_id": user_id,
                        "full_name": user_data.get("full_name", ""),
                        "email": user_data.get("email", ""),
                        "phone": user_data.get("phone", ""),
                        "avatar_url": user_data.get("avatar_url"),
                        "role": membership_info.get("role", "Captain"),
                        "membership_type": membership_info.get(
                            "membership_type", "captain"
                        ),
                        "membership_status": membership_info.get(
                            "membership_status", "active"
                        ),
                        "is_muted": user_data.get("is_muted", False),
                        "last_visited": user_data.get("last_visited"),
                        "join_date": membership_info.get(
                            "join_date", datetime.utcnow()
                        ),
                        "is_active": user_data.get("is_active", True),
                        "dm_requests_sent": dm_requests_info.get(
                            "dm_requests_sent", []
                        ),
                        "dm_requests_received": dm_requests_info.get(
                            "dm_requests_received", []
                        ),
                        "total_dm_requests_sent": dm_requests_info.get(
                            "total_dm_requests_sent", 0
                        ),
                        "total_dm_requests_received": dm_requests_info.get(
                            "total_dm_requests_received", 0
                        ),
                        "pending_dm_requests_sent": dm_requests_info.get(
                            "pending_dm_requests_sent", 0
                        ),
                        "pending_dm_requests_received": dm_requests_info.get(
                            "pending_dm_requests_received", 0
                        ),
                    }
                )

            print(
                f"⏱️ [CAPTAINS BATCH] Data processing completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            total_batch_time = (time.time() - batch_start_time) * 1000
            print(
                f"⏱️ [CAPTAINS BATCH] Total batch processing time: {total_batch_time:.2f}ms"
            )

            return captains_data

        except Exception as e:
            total_batch_time = (time.time() - batch_start_time) * 1000
            print(f"⏱️ [CAPTAINS BATCH] Error after {total_batch_time:.2f}ms: {e}")
            logger.error(f"Error getting optimized captain data batch: {e}")
            return []

    async def get_mentionable_users_optimized(self, club_id: str) -> dict:
        """
        Get optimized mentionable users for a club with proper categorization
        Returns captain, moderators, and members in organized structure - OPTIMIZED VERSION

        Args:
            club_id: Club name-based ID

        Returns:
            Dictionary with organized user data
        """
        import time

        start_time = time.time()
        print(f"🚀 [MENTIONABLE USERS] Starting optimization for club: {club_id}")

        try:
            # Step 1: Get club details - OPTIMIZED
            step_start = time.time()
            club = None
            club_name_based_id = None
            try:
                # First try as ObjectId
                club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                if club:
                    club_name_based_id = club.get("name_based_id", club_id)
            except Exception:
                # If ObjectId fails, try as name_based_id
                club = await self.clubs_collection.find_one({"name_based_id": club_id})
                if club:
                    club_name_based_id = club_id

            if not club:
                logger.error(f"Club not found with ID: {club_id}")
                return {"captain": [], "moderators": [], "members": []}

            print(
                f"⏱️ [MENTIONABLE USERS] Club lookup: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Get the actual club_id (ObjectId) for database operations
            actual_club_id = str(club["_id"])

            # Step 2: Collect user IDs efficiently - OPTIMIZED
            step_start = time.time()
            all_user_ids = []
            detailed_moderators = club.get("detailed_moderators", [])

            # Add captain ID
            if club.get("captain_id"):
                all_user_ids.append(str(club["captain_id"]))

            # Add moderator IDs
            for moderator in detailed_moderators:
                mod_user_id = moderator.get("user_id")
                if mod_user_id and moderator.get("status") == "active":
                    all_user_ids.append(str(mod_user_id))

            # Add member IDs from club's members and paid_members arrays (same logic as members API)
            member_user_ids = []

            # Add regular members from club.members array
            for member in club.get("members", []):
                if isinstance(member, dict):
                    member_user_id = member.get("user_id")
                    if member_user_id:
                        member_user_ids.append(str(member_user_id))
                else:
                    # Direct user_id
                    member_user_ids.append(str(member))

            # Add paid members from club.paid_members array
            for paid_member in club.get("paid_members", []):
                if isinstance(paid_member, dict):
                    paid_member_user_id = paid_member.get("user_id")
                    if paid_member_user_id:
                        member_user_ids.append(str(paid_member_user_id))
                else:
                    # Direct user_id
                    member_user_ids.append(str(paid_member))

            # Remove duplicates efficiently
            member_user_ids = list(set(member_user_ids))

            # Add to all_user_ids if not already present
            for user_id in member_user_ids:
                if user_id not in all_user_ids:
                    all_user_ids.append(user_id)

            print(
                f"⏱️ [MENTIONABLE USERS] User ID collection: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 3: Batch user data fetching - OPTIMIZED
            step_start = time.time()
            all_users_data = []

            # Get captain and member data (no is_register field needed)
            captain_and_member_ids = []
            moderator_ids = []

            # Separate captain and member IDs from moderator IDs
            if club.get("captain_id"):
                captain_and_member_ids.append(str(club["captain_id"]))

            # Add member IDs to captain_and_member_ids
            for user_id in member_user_ids:
                if user_id not in captain_and_member_ids:
                    captain_and_member_ids.append(user_id)

            # Get moderator IDs
            for moderator in detailed_moderators:
                mod_user_id = moderator.get("user_id")
                if mod_user_id and moderator.get("status") == "active":
                    mod_user_id_str = str(mod_user_id)
                    if mod_user_id_str in captain_and_member_ids:
                        captain_and_member_ids.remove(
                            mod_user_id_str
                        )  # Remove from regular batch
                    moderator_ids.append(mod_user_id_str)

            # Get captain and member data
            if captain_and_member_ids:
                captain_member_data = await self._get_optimized_members_data_batch(
                    captain_and_member_ids, actual_club_id, club_name_based_id
                )
                all_users_data.extend(captain_member_data)

            # Get moderator data with is_register field
            if moderator_ids:
                moderator_data = await self._get_optimized_moderator_data_batch(
                    moderator_ids, actual_club_id, club_name_based_id
                )
                all_users_data.extend(moderator_data)

            print(
                f"⏱️ [MENTIONABLE USERS] Batch data fetching: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 4: Organize users by role - OPTIMIZED
            step_start = time.time()

            # Create user lookup for easy access
            user_lookup = {user["user_id"]: user for user in all_users_data}

            # Organize users by role
            captain = []
            moderators = []
            members = []

            # Add captain (only if active)
            if club.get("captain_id"):
                captain_id = str(club["captain_id"])
                if captain_id in user_lookup:
                    captain_data = user_lookup[captain_id]
                    # Only include if captain is active
                    if captain_data.get("is_active", True):
                        captain_user = {
                            "id": captain_id,
                            "user_id": captain_id,
                            "username": captain_data.get("full_name", "")
                            .replace(" ", "_")
                            .lower(),
                            "full_name": captain_data["full_name"],
                            "email": captain_data["email"],
                            "avatar_url": captain_data.get("avatar_url", ""),
                            "role": "captain",
                        }
                        captain.append(captain_user)

            # Add moderators (only registered ones)
            for moderator in detailed_moderators:
                mod_user_id = moderator.get("user_id")
                if mod_user_id and moderator.get("status") == "active":
                    mod_user_id_str = str(mod_user_id)
                    if mod_user_id_str in user_lookup:
                        moderator_data = user_lookup[mod_user_id_str]
                        # Only include if user is active AND registered (is_register = True)
                        if moderator_data.get("is_active", True) and moderator_data.get(
                            "is_register", True
                        ):  # Default to True as per requirement
                            moderator_user = {
                                "id": mod_user_id_str,
                                "user_id": mod_user_id_str,
                                "username": moderator_data.get("full_name", "")
                                .replace(" ", "_")
                                .lower(),
                                "full_name": moderator_data["full_name"],
                                "email": moderator_data["email"],
                                "avatar_url": moderator_data.get("avatar_url", ""),
                                "role": "moderator",
                            }
                            moderators.append(moderator_user)

            # Add members (exclude captain and moderators)
            captain_and_moderator_ids = {str(club.get("captain_id", ""))} | {
                str(mod.get("user_id", ""))
                for mod in detailed_moderators
                if mod.get("user_id") and mod.get("status") == "active"
            }

            # Process members using the same logic as members API
            for user_id in member_user_ids:
                if user_id not in captain_and_moderator_ids and user_id in user_lookup:
                    member_data = user_lookup[user_id]
                    # Only include if member is active
                    if member_data.get("is_active", True):
                        member_user = {
                            "id": user_id,
                            "user_id": user_id,
                            "username": member_data.get("full_name", "")
                            .replace(" ", "_")
                            .lower(),
                            "full_name": member_data["full_name"],
                            "email": member_data["email"],
                            "avatar_url": member_data.get("avatar_url", ""),
                            "role": "member",
                        }
                        members.append(member_user)

            print(
                f"⏱️ [MENTIONABLE USERS] User organization: {(time.time() - step_start)*1000:.2f}ms"
            )

            total_time = (time.time() - start_time) * 1000
            print(f"🚀 [MENTIONABLE USERS] TOTAL TIME: {total_time:.2f}ms")
            print(
                f"📊 [MENTIONABLE USERS] Results: {len(captain)} captain, {len(moderators)} moderators, {len(members)} members"
            )

            return {
                "captain": captain,
                "moderators": moderators,
                "members": members,
            }

        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            print(f"❌ [MENTIONABLE USERS] Error after {total_time:.2f}ms: {e}")
            logger.error(f"Error getting optimized mentionable users: {e}")
            return {"captain": [], "moderators": [], "members": []}

    async def get_mentionable_users_ultra_fast(self, club_id: str) -> dict:
        """
        Get mentionable users with ULTRA FAST performance - minimal database queries
        This is specifically optimized for the mentionable-users API
        """
        import time

        start_time = time.time()
        print(f"🚀 [ULTRA FAST MENTIONABLE] Starting for club: {club_id}")

        try:
            # Step 1: Get club with minimal projection
            step_start = time.time()
            club = await self.clubs_collection.find_one(
                {"name_based_id": club_id},
                {
                    "captain_id": 1,
                    "detailed_moderators": 1,
                    "members": 1,
                    "paid_members": 1,
                },
            )
            if not club:
                return {"captain": [], "moderators": [], "members": []}

            print(f"⏱️ [ULTRA FAST] Club fetch: {(time.time() - step_start)*1000:.2f}ms")

            # Step 2: Collect all user IDs
            step_start = time.time()
            all_user_ids = []

            # Add captain
            if club.get("captain_id"):
                all_user_ids.append(str(club["captain_id"]))

            # Add moderators
            for moderator in club.get("detailed_moderators", []):
                if moderator.get("status") == "active" and moderator.get("user_id"):
                    all_user_ids.append(str(moderator["user_id"]))

            # Add members
            for member in club.get("members", []):
                if isinstance(member, dict) and member.get("user_id"):
                    all_user_ids.append(str(member["user_id"]))
                elif isinstance(member, str):
                    all_user_ids.append(member)

            # Add paid members
            for member in club.get("paid_members", []):
                if isinstance(member, dict) and member.get("user_id"):
                    all_user_ids.append(str(member["user_id"]))
                elif isinstance(member, str):
                    all_user_ids.append(member)

            # Remove duplicates
            all_user_ids = list(set(all_user_ids))
            print(
                f"⏱️ [ULTRA FAST] User ID collection: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 3: Single optimized user query
            step_start = time.time()
            if not all_user_ids:
                return {"captain": [], "moderators": [], "members": []}

            # Convert to ObjectIds for query
            user_object_ids = [
                ObjectId(uid) for uid in all_user_ids if ObjectId.is_valid(uid)
            ]

            # Single query with minimal projection
            users_cursor = self.users_collection.find(
                {"_id": {"$in": user_object_ids}},
                {
                    "_id": 1,
                    "full_name": 1,
                    "email": 1,
                    "avatar_url": 1,
                    "is_active": 1,
                    "is_register": 1,
                },
            )

            users_docs = await users_cursor.to_list(None)
            user_lookup = {str(doc["_id"]): doc for doc in users_docs}

            print(
                f"⏱️ [ULTRA FAST] User data fetch: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 4: Build response quickly
            step_start = time.time()
            captain = []
            moderators = []
            members = []

            captain_id = str(club.get("captain_id", ""))
            moderator_ids = {
                str(mod.get("user_id", ""))
                for mod in club.get("detailed_moderators", [])
                if mod.get("status") == "active"
            }

            # Process captain
            if captain_id in user_lookup:
                user_doc = user_lookup[captain_id]
                if user_doc.get("is_active", True):
                    captain.append(
                        {
                            "id": captain_id,
                            "user_id": captain_id,
                            "username": user_doc["full_name"].replace(" ", "_").lower(),
                            "full_name": user_doc["full_name"],
                            "email": user_doc.get("email", ""),
                            "avatar_url": user_doc.get("avatar_url", ""),
                            "role": "captain",
                        }
                    )

            # Process moderators
            for moderator in club.get("detailed_moderators", []):
                if moderator.get("status") == "active" and moderator.get("user_id"):
                    mod_id = str(moderator["user_id"])
                    if mod_id in user_lookup:
                        user_doc = user_lookup[mod_id]
                        if user_doc.get("is_active", True) and user_doc.get(
                            "is_register", True
                        ):
                            moderators.append(
                                {
                                    "id": mod_id,
                                    "user_id": mod_id,
                                    "username": user_doc["full_name"]
                                    .replace(" ", "_")
                                    .lower(),
                                    "full_name": user_doc["full_name"],
                                    "email": user_doc.get("email", ""),
                                    "avatar_url": user_doc.get("avatar_url", ""),
                                    "role": "moderator",
                                }
                            )

            # Process members (exclude captain and moderators)
            for member in club.get("members", []) + club.get("paid_members", []):
                member_id = (
                    str(member.get("user_id", ""))
                    if isinstance(member, dict)
                    else str(member)
                )
                if (
                    member_id
                    and member_id not in moderator_ids
                    and member_id != captain_id
                ):
                    if member_id in user_lookup:
                        user_doc = user_lookup[member_id]
                        if user_doc.get("is_active", True):
                            members.append(
                                {
                                    "id": member_id,
                                    "user_id": member_id,
                                    "username": user_doc["full_name"]
                                    .replace(" ", "_")
                                    .lower(),
                                    "full_name": user_doc["full_name"],
                                    "email": user_doc.get("email", ""),
                                    "avatar_url": user_doc.get("avatar_url", ""),
                                    "role": "member",
                                }
                            )

            print(
                f"⏱️ [ULTRA FAST] Response building: {(time.time() - step_start)*1000:.2f}ms"
            )

            total_time = (time.time() - start_time) * 1000
            print(f"🚀 [ULTRA FAST] TOTAL TIME: {total_time:.2f}ms")
            print(
                f"📊 [ULTRA FAST] Results: {len(captain)} captain, {len(moderators)} moderators, {len(members)} members"
            )

            return {"captain": captain, "moderators": moderators, "members": members}

        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            print(f"❌ [ULTRA FAST] Error after {total_time:.2f}ms: {e}")
            logger.error(f"Error in ultra fast mentionable users: {e}")
            return {"captain": [], "moderators": [], "members": []}

    async def get_club_captains_with_pagination(
        self, club_id: str, current_user_id: str, page: int = 1, page_size: int = 10
    ) -> Tuple[bool, Optional[ClubCaptainsResponse], Optional[str]]:
        """
        Get captains of a club with pagination - OPTIMIZED VERSION

        Args:
            club_id: Club ID to get captains for
            current_user_id: Current user ID (for authentication)
            page: Page number (1-based)
            page_size: Number of items per page

        Returns:
            Tuple of (success, response, error_message)
        """
        import time

        start_time = time.time()
        step_start_time = time.time()

        try:
            print(f"⏱️ [CAPTAINS SERVICE] Starting service for club: {club_id}")

            # Step 1: Get club details first - handle both ObjectId and name_based_id
            club = None
            club_name_based_id = None
            try:
                # First try as ObjectId
                club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                if club:
                    club_name_based_id = club.get("name_based_id", club_id)
            except Exception:
                # If ObjectId fails, try as name_based_id
                club = await self.clubs_collection.find_one({"name_based_id": club_id})
                if club:
                    club_name_based_id = club_id

            if not club:
                print(
                    f"⏱️ [CAPTAINS SERVICE] Club not found in {(time.time() - step_start_time)*1000:.2f}ms"
                )
                return False, None, "Club not found"

            print(
                f"⏱️ [CAPTAINS SERVICE] Club lookup completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Get the actual club_id (ObjectId) for database operations
            actual_club_id = str(club["_id"])

            # Step 2: Check if current user has access to this club
            has_access = await self._check_user_membership(
                current_user_id, actual_club_id
            )
            if not has_access:
                print(
                    f"⏱️ [CAPTAINS SERVICE] Access check failed in {(time.time() - step_start_time)*1000:.2f}ms"
                )
                return False, None, "You don't have access to this club"

            print(
                f"⏱️ [CAPTAINS SERVICE] Access check completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Step 3: Get captain using optimized batch pipeline
            captains = []
            if club.get("captain_id"):
                captain_id = str(club["captain_id"])
                print(
                    f"⏱️ [CAPTAINS SERVICE] Found captain ID: {captain_id} in {(time.time() - step_start_time)*1000:.2f}ms"
                )
                step_start_time = time.time()

                # Use batch optimization even for single captain for consistency
                captains_data = await self._get_optimized_captain_data_batch(
                    [captain_id], actual_club_id, club_name_based_id
                )
                captains.extend(captains_data)

            print(
                f"⏱️ [CAPTAINS SERVICE] Captain data fetch completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Step 4: Apply pagination
            total_count = len(captains)
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_captains = captains[start_index:end_index]

            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1

            print(
                f"⏱️ [CAPTAINS SERVICE] Pagination applied in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Step 5: Build response data
            response_data = {
                "club_info": {
                    "club_id": str(club["_id"]),
                    "club_name": club.get("name", ""),
                    "name_based_id": club.get("name_based_id", ""),
                    "description": club.get("description", ""),
                    "status": club.get("status", ""),
                    "total_captains": total_count,
                },
                "captains": paginated_captains,
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "has_next": has_next,
                    "has_previous": has_previous,
                },
                "summary": {
                    "total_captains": total_count,
                    "active_captains": len(
                        [c for c in captains if c.get("is_active", True)]
                    ),
                    "muted_captains": len(
                        [c for c in captains if c.get("is_muted", False)]
                    ),
                },
            }

            print(
                f"⏱️ [CAPTAINS SERVICE] Response building completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Final step: Create response object
            response_obj = ClubCaptainsResponse(
                success=True,
                message="Club captains retrieved successfully",
                data=response_data,
            )

            print(
                f"⏱️ [CAPTAINS SERVICE] Response object creation completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            total_service_time = (time.time() - start_time) * 1000
            print(
                f"⏱️ [CAPTAINS SERVICE] Total service time: {total_service_time:.2f}ms"
            )

            return (True, response_obj, None)

        except Exception as e:
            total_service_time = (time.time() - start_time) * 1000
            print(f"⏱️ [CAPTAINS SERVICE] Error after {total_service_time:.2f}ms: {e}")
            logger.error(f"Error getting club captains: {e}")
            return False, None, f"Error retrieving captains: {str(e)}"

    async def get_club_moderators_with_pagination(
        self, club_id: str, current_user_id: str, page: int = 1, page_size: int = 10
    ) -> Tuple[bool, Optional[ClubModeratorsResponse], Optional[str]]:
        """
        Get moderators of a club with pagination

        Args:
            club_id: Club ID to get moderators for
            current_user_id: Current user ID (for authentication)
            page: Page number (1-based)
            page_size: Number of items per page

        Returns:
            Tuple of (success, response, error_message)
        """
        import time

        start_time = time.time()
        step_start_time = time.time()

        try:
            print(f"⏱️ [MODERATORS SERVICE] Starting service for club: {club_id}")

            # Step 1: Get club details first - handle both ObjectId and name_based_id
            club = None
            club_name_based_id = None
            try:
                # First try as ObjectId
                club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                if club:
                    club_name_based_id = club.get("name_based_id", club_id)
            except Exception:
                # If ObjectId fails, try as name_based_id
                club = await self.clubs_collection.find_one({"name_based_id": club_id})
                if club:
                    club_name_based_id = club_id

            if not club:
                print(
                    f"⏱️ [MODERATORS SERVICE] Club not found in {(time.time() - step_start_time)*1000:.2f}ms"
                )
                return False, None, "Club not found"

            print(
                f"⏱️ [MODERATORS SERVICE] Club lookup completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Get the actual club_id (ObjectId) for database operations
            actual_club_id = str(club["_id"])

            # Step 2: Check if current user has access to this club
            has_access = await self._check_user_membership(
                current_user_id, actual_club_id
            )
            if not has_access:
                print(
                    f"⏱️ [MODERATORS SERVICE] Access check failed in {(time.time() - step_start_time)*1000:.2f}ms"
                )
                return False, None, "You don't have access to this club"

            print(
                f"⏱️ [MODERATORS SERVICE] Access check completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Step 3: Get moderators from detailed_moderators list using batch optimization
            moderators = []
            detailed_moderators = club.get("detailed_moderators", [])

            # Collect all active moderator user IDs first
            active_moderator_ids = []
            for moderator in detailed_moderators:
                moderator_user_id = moderator.get("user_id")
                if moderator_user_id and moderator.get("status", "active") == "active":
                    active_moderator_ids.append(str(moderator_user_id))

            print(
                f"⏱️ [MODERATORS SERVICE] Found {len(active_moderator_ids)} active moderators in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Step 4: Use batch optimization to get all moderator data at once with is_register field
            if active_moderator_ids:
                moderators_data = await self._get_optimized_moderator_data_batch(
                    active_moderator_ids, actual_club_id, club_name_based_id
                )
                moderators.extend(moderators_data)

            print(
                f"⏱️ [MODERATORS SERVICE] Batch data fetch completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Step 5: Apply pagination
            total_count = len(moderators)
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_moderators = moderators[start_index:end_index]

            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1

            print(
                f"⏱️ [MODERATORS SERVICE] Pagination applied in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Step 6: Build response data
            response_data = {
                "club_info": {
                    "club_id": str(club["_id"]),
                    "club_name": club.get("name", ""),
                    "name_based_id": club.get("name_based_id", ""),
                    "description": club.get("description", ""),
                    "status": club.get("status", ""),
                    "total_moderators": total_count,
                },
                "moderators": paginated_moderators,
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "has_next": has_next,
                    "has_previous": has_previous,
                },
                "summary": {
                    "total_moderators": total_count,
                    "active_moderators": len(
                        [m for m in moderators if m.get("is_active", True)]
                    ),
                    "muted_moderators": len(
                        [m for m in moderators if m.get("is_muted", False)]
                    ),
                },
            }

            print(
                f"⏱️ [MODERATORS SERVICE] Response building completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

            # Final step: Create response object
            response_obj = ClubModeratorsResponse(
                success=True,
                message="Club moderators retrieved successfully",
                data=response_data,
            )

            print(
                f"⏱️ [MODERATORS SERVICE] Response object creation completed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            total_service_time = (time.time() - start_time) * 1000
            print(
                f"⏱️ [MODERATORS SERVICE] Total service time: {total_service_time:.2f}ms"
            )

            return (True, response_obj, None)

        except Exception as e:
            total_service_time = (time.time() - start_time) * 1000
            print(f"⏱️ [MODERATORS SERVICE] Error after {total_service_time:.2f}ms: {e}")
            logger.error(f"Error getting club moderators: {e}")
            return False, None, f"Error retrieving moderators: {str(e)}"

    async def get_club_members_with_pagination(
        self, club_id: str, current_user_id: str, page: int = 1, page_size: int = 10, search: Optional[str] = None
    ) -> Tuple[bool, Optional[ClubMembersResponse], Optional[str]]:
        """
        Get members of a club with pagination and optional search filtering (excludes captains and moderators)

        Args:
            club_id: Club ID to get members for
            current_user_id: Current user ID (for authentication)
            page: Page number (1-based)
            page_size: Number of items per page
            search: Optional search term to filter members by full name

        Returns:
            Tuple of (success, response, error_message)
        """
        try:
            # Get club details first - handle both ObjectId and name_based_id
            club = None
            club_name_based_id = None
            try:
                # First try as ObjectId
                club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                if club:
                    club_name_based_id = club.get("name_based_id", club_id)
            except Exception:
                # If ObjectId fails, try as name_based_id
                club = await self.clubs_collection.find_one({"name_based_id": club_id})
                if club:
                    club_name_based_id = club_id

            if not club:
                return False, None, "Club not found"

            # Get the actual club_id (ObjectId) for database operations
            actual_club_id = str(club["_id"])

            # Check if current user has access to this club
            has_access = await self._check_user_membership(
                current_user_id, actual_club_id
            )
            if not has_access:
                return False, None, "You don't have access to this club"

            # Get members (regular members and paid members) using batch optimization
            members = []
            member_user_ids = []

            # Collect all member user IDs first
            # Add regular members
            for member in club.get("members", []):
                if isinstance(member, dict):
                    member_user_id = member.get("user_id")
                    if member_user_id:
                        member_user_ids.append(str(member_user_id))
                else:
                    # Direct user_id
                    member_user_ids.append(str(member))

            # Add paid members
            for paid_member in club.get("paid_members", []):
                if isinstance(paid_member, dict):
                    paid_member_user_id = paid_member.get("user_id")
                    if paid_member_user_id:
                        member_user_ids.append(str(paid_member_user_id))
                else:
                    # Direct user_id
                    member_user_ids.append(str(paid_member))

            # Remove duplicates
            member_user_ids = list(set(member_user_ids))

            # Use batch optimization to get all member data at once
            if member_user_ids:
                members_data = await self._get_optimized_members_data_batch(
                    member_user_ids, actual_club_id, club_name_based_id
                )
                members.extend(members_data)

            # Apply search filtering if search term is provided
            if search and search.strip():
                search_term = search.strip().lower()
                members = [
                    member for member in members
                    if search_term in member.get("full_name", "").lower()
                ]

            # Apply pagination
            total_count = len(members)
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_members = members[start_index:end_index]

            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1

            response_data = {
                "club_info": {
                    "club_id": str(club["_id"]),
                    "club_name": club.get("name", ""),
                    "name_based_id": club.get("name_based_id", ""),
                    "description": club.get("description", ""),
                    "status": club.get("status", ""),
                    "total_members": total_count,
                },
                "members": paginated_members,
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "has_next": has_next,
                    "has_previous": has_previous,
                },
                "summary": {
                    "total_members": total_count,
                    "active_members": len(
                        [m for m in members if m.get("is_active", True)]
                    ),
                    "muted_members": len(
                        [m for m in members if m.get("is_muted", False)]
                    ),
                    "trial_members": len(
                        [m for m in members if m.get("membership_type") == "trial"]
                    ),
                    "paid_members": len(
                        [m for m in members if m.get("membership_type") == "paid"]
                    ),
                },
            }

            return (
                True,
                ClubMembersResponse(
                    success=True,
                    message="Club members retrieved successfully",
                    data=response_data,
                ),
                None,
            )

        except Exception as e:
            logger.error(f"Error getting club members: {e}")
            return False, None, f"Error retrieving members: {str(e)}"
