from typing import List, Optional
from datetime import datetime, timedelta
from bson import ObjectId

from .db import (
    get_messages_collection,
    get_user_access_collection,
    get_users_collection,
)
from .models import PinnedMessage, ChatMessage, ChatUser, UserRole, MuteUserResponse
from .message_service import message_service
from .auth import mute_user, unmute_user


class ModerationService:
    def __init__(self):
        self.messages_collection = get_messages_collection()
        self.user_access_collection = get_user_access_collection()
        self.users_collection = get_users_collection()

    async def pin_message(
        self, message_id: str, moderator: ChatUser, reason: Optional[str] = None
    ) -> Optional[ChatMessage]:
        """Pin a message (moderator/captain only)"""

        # Check if user has moderator permissions
        if moderator.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
            return None

        # Find the message
        message_doc = await self.messages_collection.find_one(
            {"message_id": message_id, "is_deleted": False}
        )

        if not message_doc:
            return None

        # Check if message is in the same club where user has moderation rights
        if (
            message_doc["club_id"] != moderator.user_id
        ):  # This should be checked against club access
            # TODO: Add proper club access validation
            pass

        # Create pinned info
        now = datetime.utcnow()
        pinned_info = PinnedMessage(
            pinned_by=moderator.user_id,
            pinned_by_username=moderator.username,
            pinned_by_full_name=moderator.full_name,
            pinned_at=now,
            reason=reason,
        )

        # Update message with pin info
        await self.messages_collection.update_one(
            {"message_id": message_id},
            {"$set": {"pinned": pinned_info.dict(), "updated_at": now}},
        )

        # Get updated message
        updated_message = await message_service.get_message_by_id(message_id)
        return updated_message

    async def unpin_message(self, message_id: str, moderator: ChatUser) -> bool:
        """Unpin a message (moderator/captain only)"""

        # Check if user has moderator permissions
        if moderator.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
            return False

        # Find the message
        message_doc = await self.messages_collection.find_one(
            {"message_id": message_id, "is_deleted": False, "pinned": {"$ne": None}}
        )

        if not message_doc:
            return False

        # Remove pin info
        result = await self.messages_collection.update_one(
            {"message_id": message_id},
            {"$unset": {"pinned": ""}, "$set": {"updated_at": datetime.utcnow()}},
        )

        return result.modified_count > 0

    async def get_pinned_messages(self, club_id: str) -> List[ChatMessage]:
        """Get all pinned messages for a club (both moderator and member pinned)"""
        # Get messages that have pinned object (not null)
        cursor = self.messages_collection.find(
            {
                "club_id": club_id,
                "is_deleted": False,
                "pinned": {"$ne": None},  # Messages with pinned object
            }
        ).sort("pinned.pinned_at", -1)

        messages = []
        async for doc in cursor:
            # Convert document to ChatMessage using message service
            chat_message = await message_service.document_to_chat_message(doc)
            if chat_message:
                messages.append(chat_message)

        return messages

    async def mute_user_in_club(
        self,
        target_user_id: str,
        club_id: str,
        moderator: ChatUser,
        reason: Optional[str] = None,
        duration_hours: Optional[int] = None,
    ) -> MuteUserResponse:
        """Mute a user in a specific club"""

        # Check if user has moderator permissions
        if moderator.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
            return MuteUserResponse(
                success=False, message="Only moderators and captains can mute users"
            )

        # Don't allow muting other moderators or captains (unless you're captain)
        if moderator.role == UserRole.MODERATOR:
            target_access = await self.user_access_collection.find_one(
                {"user_id": target_user_id, "club_id": club_id}
            )

            if target_access and target_access.get("role") in ["captain", "moderator"]:
                return MuteUserResponse(
                    success=False,
                    message="Moderators cannot mute other moderators or captains",
                )

        # Calculate mute expiration
        muted_until = None
        if duration_hours:
            muted_until = datetime.utcnow() + timedelta(hours=duration_hours)

        # Mute the user
        success = await mute_user(
            target_user_id, club_id, moderator.user_id, reason, duration_hours
        )
        print(success, "successsuccesssuccess")

        if success:
            duration_text = (
                f" for {duration_hours} hours" if duration_hours else " permanently"
            )
            
            # Send mute notification to the muted user
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                # Get club name for notification
                from .db import get_club_collection
                club_collection = get_club_collection()
                club = await club_collection.find_one({"name_based_id": club_id})
                club_name = club.get("name", "Club") if club else "Club"
                
                # Get target user details
                from .db import get_user_collection
                user_collection = get_user_collection()
                target_user = await user_collection.find_one({"_id": ObjectId(target_user_id)})
                target_user_name = target_user.get("full_name", "User") if target_user else "User"

                # Determine push eligibility
                push_user_ids: List[str] = []
                enabled_user_ids = await filter_users_by_notification_preference(
                    [target_user_id],
                    "mute_alerts"
                )
                if enabled_user_ids:
                    collections = get_collections()
                    user_tokens_collection = collections.get_user_tokens_collection()
                    token_docs = await user_tokens_collection.find(
                        {"user_id": target_user_id, "is_active": True},
                        {"user_id": 1},
                    ).to_list(length=None)
                    if any(doc.get("user_id") for doc in token_docs):
                        push_user_ids = [target_user_id]
                
                title = f"You've Been Muted!"
                body = f"You have been muted in {club_name} by {moderator.full_name}"
                
                notification_data = {
                    "target_user_id": target_user_id,
                    "target_user_name": target_user_name,
                    "club_id": club_id,
                    "club_name": club_name,
                    "moderator_id": moderator.user_id,
                    "moderator_name": moderator.full_name,
                    "reason": reason,
                    "duration_hours": duration_hours,
                    "muted_until": muted_until.isoformat() if muted_until else None,
                    "action": "mute"
                }
                
                notification_result = await send_notification_to_users(
                    user_ids=push_user_ids,
                    title=title,
                    body=body,
                    notification_type="mute_alert",
                    data=notification_data,
                    click_action=f"club/{club_id}",
                    priority="normal",
                    all_user_ids=[target_user_id],
                )
                print(f"✅ Mute notification stored for user {target_user_id}: {notification_result}")
                    
            except Exception as e:
                print(f"⚠️ Failed to send mute notification: {e}")
            
            return MuteUserResponse(
                success=True,
                message=f"User muted successfully{duration_text}",
                muted_until=muted_until,
            )
        else:
            return MuteUserResponse(success=False, message="Failed to mute user")

    async def unmute_user_in_club(
        self, target_user_id: str, club_id: str, moderator: ChatUser
    ) -> MuteUserResponse:
        """Unmute a user in a specific club"""

        # Check if user has moderator permissions
        if moderator.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
            return MuteUserResponse(
                success=False, message="Only moderators and captains can unmute users"
            )

        # Unmute the user
        success = await unmute_user(target_user_id, club_id)

        if success:
            # Send unmute notification to the unmuted user
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                # Get club name for notification
                from .db import get_club_collection
                club_collection = get_club_collection()
                club = await club_collection.find_one({"name_based_id": club_id})
                club_name = club.get("name", "Club") if club else "Club"
                
                # Get target user details
                from .db import get_user_collection
                user_collection = get_user_collection()
                target_user = await user_collection.find_one({"_id": ObjectId(target_user_id)})
                target_user_name = target_user.get("full_name", "User") if target_user else "User"
                
                # Determine push eligibility
                push_user_ids: List[str] = []
                enabled_user_ids = await filter_users_by_notification_preference(
                    [target_user_id],
                    "mute_alerts"
                )
                if enabled_user_ids:
                    collections = get_collections()
                    user_tokens_collection = collections.get_user_tokens_collection()
                    token_docs = await user_tokens_collection.find(
                        {"user_id": target_user_id, "is_active": True},
                        {"user_id": 1},
                    ).to_list(length=None)
                    if any(doc.get("user_id") for doc in token_docs):
                        push_user_ids = [target_user_id]
                
                title = f"You've Been Unmuted!"
                body = f"You have been unmuted in {club_name} by {moderator.full_name}"
                
                notification_data = {
                    "target_user_id": target_user_id,
                    "target_user_name": target_user_name,
                    "club_id": club_id,
                    "club_name": club_name,
                    "moderator_id": moderator.user_id,
                    "moderator_name": moderator.full_name,
                    "action": "unmute"
                }
                
                notification_result = await send_notification_to_users(
                    user_ids=push_user_ids,
                    title=title,
                    body=body,
                    notification_type="mute_alert",
                    data=notification_data,
                    click_action=f"club/{club_id}",
                    priority="normal",
                    all_user_ids=[target_user_id],
                )
                print(f"✅ Unmute notification stored for user {target_user_id}: {notification_result}")
                    
            except Exception as e:
                print(f"⚠️ Failed to send unmute notification: {e}")
            
            return MuteUserResponse(success=True, message="User unmuted successfully")
        else:
            return MuteUserResponse(
                success=False, message="Failed to unmute user or user was not muted"
            )

    async def mute_all_users_in_club(
        self,
        club_id: str,
        moderator: ChatUser,
        reason: Optional[str] = None,
        duration_hours: Optional[int] = None,
    ) -> dict:
        """Mute all members in a club (moderator/captain only) - FIXED VERSION"""

        # Check if user has moderator permissions
        if moderator.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
            return {
                "success": False,
                "message": "Only moderators and captains can mute all users",
            }

        # Get club information
        from .db import get_club_collection

        club_collection = get_club_collection()
        club = await club_collection.find_one({"name_based_id": club_id})
        if not club:
            return {"success": False, "message": "Club not found"}

        # Get all members from club arrays (members, paid_members) - FIXED
        members_to_mute = []

        # Add regular members
        for member in club.get("members", []):
            member_id = member.get("user_id") if isinstance(member, dict) else member
            if member_id:
                members_to_mute.append(str(member_id))

        # Add paid members
        for member in club.get("paid_members", []):
            member_id = member.get("user_id") if isinstance(member, dict) else member
            if member_id:
                members_to_mute.append(str(member_id))

        # Filter out moderators and captains - FIXED
        captain_id = str(club.get("captain_id", ""))
        moderator_ids = set()

        # Get moderator IDs from detailed_moderators field - FIXED
        for moderator_doc in club.get("detailed_moderators", []):
            if moderator_doc.get("status") == "active":
                moderator_ids.add(str(moderator_doc.get("user_id", "")))

        # Remove captain and moderators from members to mute
        members_to_mute = [
            user_id
            for user_id in members_to_mute
            if user_id != captain_id and user_id not in moderator_ids
        ]

        # Mute all filtered members and collect detailed information
        muted_count = 0
        muted_users_details = []
        now = datetime.utcnow()
        muted_until = None
        if duration_hours:
            muted_until = now + timedelta(hours=duration_hours)

        for user_id in members_to_mute:
            success = await mute_user(
                user_id=user_id,
                club_id=club_id,
                muted_by=moderator.user_id,
                reason=reason,
                duration_hours=duration_hours,
            )
            if success:
                muted_count += 1

                # Get user details for the muted user
                try:
                    user_doc = await self.users_collection.find_one(
                        {"_id": ObjectId(user_id)}
                    )
                    if user_doc:
                        # Create detailed muted user object
                        muted_user_detail = {
                            "user_id": str(user_doc.get("_id")),
                            "full_name": user_doc.get("full_name"),
                            "email": user_doc.get("email"),
                            "phone": user_doc.get("phone"),
                            "role": user_doc.get("role"),
                            "status": user_doc.get("status"),
                            "avatar_url": user_doc.get("avatar_url"),
                            "created_at": user_doc.get("created_at"),
                            # Mute details
                            "muted_at": now,
                            "muted_until": muted_until,
                            "muted_by": moderator.user_id,
                            "muted_by_username": moderator.username,
                            "muted_reason": reason,
                            "is_permanently_muted": muted_until is None,
                        }
                        muted_users_details.append(muted_user_detail)
                    else:
                        # If user details can't be fetched, include basic info
                        muted_user_detail = {
                            "user_id": user_id,
                            "full_name": "Unknown User",
                            "email": "N/A",
                            "phone": "N/A",
                            "role": "N/A",
                            "status": "N/A",
                            "avatar_url": None,
                            "created_at": None,
                            # Mute details
                            "muted_at": now,
                            "muted_until": muted_until,
                            "muted_by": moderator.user_id,
                            "muted_by_username": moderator.username,
                            "muted_reason": reason,
                            "is_permanently_muted": muted_until is None,
                        }
                        muted_users_details.append(muted_user_detail)
                except Exception as e:
                    print(f"Error fetching user details for user_id {user_id}: {e}")
                    # If user details can't be fetched, include basic info
                    muted_user_detail = {
                        "user_id": user_id,
                        "full_name": "Unknown User",
                        "email": "N/A",
                        "phone": "N/A",
                        "role": "N/A",
                        "status": "N/A",
                        "avatar_url": None,
                        "created_at": None,
                        # Mute details
                        "muted_at": now,
                        "muted_until": muted_until,
                        "muted_by": moderator.user_id,
                        "muted_by_username": moderator.username,
                        "muted_reason": reason,
                        "is_permanently_muted": muted_until is None,
                    }
                    muted_users_details.append(muted_user_detail)

        duration_text = (
            f" for {duration_hours} hours" if duration_hours else " permanently"
        )
        return {
            "success": True,
            "message": f"Successfully muted {muted_count} members{duration_text}",
            "muted_count": muted_count,
            "muted_users": muted_users_details,
        }

    async def unmute_all_users_in_club(self, club_id: str, moderator: ChatUser) -> dict:
        """Unmute all members in a club (moderator/captain only) - FIXED VERSION"""

        # Check if user has moderator permissions
        if moderator.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
            return {
                "success": False,
                "message": "Only moderators and captains can unmute all users",
            }

        # Get club information
        from .db import get_club_collection

        club_collection = get_club_collection()
        club = await club_collection.find_one({"name_based_id": club_id})
        if not club:
            return {"success": False, "message": "Club not found"}

        # Unmute all users in the club - FIXED: club_id is already the name_based_id
        now = datetime.utcnow()
        result = await self.user_access_collection.update_many(
            {"club_id": club_id, "is_muted": True},  # This is already the name_based_id
            {
                "$set": {
                    "is_muted": False,
                    "muted_until": None,
                    "muted_by": None,
                    "muted_reason": None,
                    "updated_at": now,
                }
            },
        )

        return {
            "success": True,
            "message": f"Successfully unmuted {result.modified_count} members",
            "unmuted_count": result.modified_count,
        }

    async def get_muted_users(self, club_id: str) -> List[dict]:
        """Get list of muted users in a club with user details - FIXED VERSION"""

        now = datetime.utcnow()

        # Find all muted users in the club - FIXED: club_id is already the name_based_id
        muted_users = await self.user_access_collection.find(
            {
                "club_id": club_id,  # This is already the name_based_id
                "is_muted": True,
                "$or": [
                    {"muted_until": None},  # Permanently muted
                    {"muted_until": {"$gt": now}},  # Temporarily muted and not expired
                ],
            }
        ).to_list(None)

        # Get user details for each muted user
        enhanced_muted_users = []

        for muted_user in muted_users:
            user_id = muted_user.get("user_id")
            if user_id:
                try:
                    # Get user details from users collection
                    user_doc = await self.users_collection.find_one(
                        {"_id": ObjectId(user_id)}
                    )
                    if user_doc:
                        # Create enhanced muted user object with user details
                        enhanced_user = {
                            "user_id": str(user_doc.get("_id")),
                            "full_name": user_doc.get("full_name"),
                            "email": user_doc.get("email"),
                            "phone": user_doc.get("phone"),
                            "role": user_doc.get("role"),
                            "status": user_doc.get("status"),
                            "avatar_url": user_doc.get("avatar_url"),
                            "created_at": user_doc.get("created_at"),
                            # Mute details
                            "muted_at": muted_user.get(
                                "updated_at"
                            ),  # When they were muted
                            "muted_until": muted_user.get("muted_until"),
                            "muted_by": muted_user.get("muted_by"),
                            "muted_reason": muted_user.get("muted_reason"),
                            "is_permanently_muted": muted_user.get("muted_until")
                            is None,
                        }
                        enhanced_muted_users.append(enhanced_user)
                except Exception as e:
                    print(f"Error fetching user details for user_id {user_id}: {e}")
                    # If user details can't be fetched, include basic mute info
                    enhanced_user = {
                        "user_id": user_id,
                        "full_name": "Unknown User",
                        "email": "N/A",
                        "phone": "N/A",
                        "role": "N/A",
                        "status": "N/A",
                        "avatar_url": None,
                        "created_at": None,
                        # Mute details
                        "muted_at": muted_user.get("updated_at"),
                        "muted_until": muted_user.get("muted_until"),
                        "muted_by": muted_user.get("muted_by"),
                        "muted_reason": muted_user.get("muted_reason"),
                        "is_permanently_muted": muted_user.get("muted_until") is None,
                    }
                    enhanced_muted_users.append(enhanced_user)

        return enhanced_muted_users

    async def delete_message_as_moderator(
        self, message_id: str, moderator: ChatUser, reason: Optional[str] = None
    ) -> bool:
        """Delete a message as moderator (can delete any message)"""

        # Check if user has moderator permissions
        if moderator.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
            return False

        # Use the message service delete method with moderator privileges
        success = await message_service.delete_message(message_id, moderator)

        if success and reason:
            # Log the moderation action
            await self.log_moderation_action(
                moderator.user_id,
                "message_delete",
                {"message_id": message_id, "reason": reason},
            )

        return success

    async def bulk_delete_messages(
        self, message_ids: List[str], moderator: ChatUser, reason: Optional[str] = None
    ) -> dict:
        """Bulk delete messages (moderator only)"""

        # Check if user has moderator permissions
        if moderator.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
            return {"success": False, "message": "Permission denied"}

        deleted_count = 0
        failed_count = 0

        for message_id in message_ids:
            success = await self.delete_message_as_moderator(
                message_id, moderator, reason
            )
            if success:
                deleted_count += 1
            else:
                failed_count += 1

        return {
            "success": True,
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "total_requested": len(message_ids),
        }

    async def get_recent_moderation_actions(
        self, club_id: str, limit: int = 50
    ) -> List[dict]:
        """Get recent moderation actions for a club"""

        # This would typically be stored in a separate moderation log collection
        # For now, return empty list - implement based on your logging requirements
        return []

    async def log_moderation_action(
        self, moderator_id: str, action_type: str, details: dict
    ):
        """Log moderation action for audit trail"""

        # This would typically save to a moderation_logs collection
        # Implement based on your audit requirements
        log_entry = {
            "moderator_id": moderator_id,
            "action_type": action_type,
            "details": details,
            "timestamp": datetime.utcnow(),
        }

        print(f"Moderation action logged: {log_entry}")
        # TODO: Implement actual logging to database

    async def check_user_permissions(self, user_id: str, club_id: str) -> dict:
        """Check what moderation permissions a user has in a club"""

        access_record = await self.user_access_collection.find_one(
            {"user_id": user_id, "club_id": club_id}
        )

        if not access_record:
            return {
                "can_pin": False,
                "can_mute": False,
                "can_delete_messages": False,
                "can_moderate": False,
                "role": "none",
            }

        role = access_record.get("role", "member")
        is_moderator = role in ["captain", "moderator"]

        return {
            "can_pin": is_moderator,
            "can_mute": is_moderator,
            "can_delete_messages": is_moderator,
            "can_moderate": is_moderator,
            "role": role,
        }

    async def auto_unmute_expired_users(self):
        """Automatically unmute users whose mute period has expired"""

        now = datetime.utcnow()

        # Find users whose mute has expired
        expired_mutes = await self.user_access_collection.find(
            {"is_muted": True, "muted_until": {"$lte": now}}
        ).to_list(None)

        unmuted_count = 0
        for mute_record in expired_mutes:
            success = await unmute_user(mute_record["user_id"], mute_record["club_id"])
            if success:
                unmuted_count += 1

        if unmuted_count > 0:
            print(f"Auto-unmuted {unmuted_count} users whose mute period expired")

        return unmuted_count

    async def get_message_reports(self, club_id: str) -> List[dict]:
        """Get reported messages for a club (if you implement reporting)"""

        # This would typically query a message_reports collection
        # Placeholder for future implementation
        return []

    async def promote_user_to_moderator(
        self, target_user_id: str, club_id: str, captain: ChatUser
    ) -> bool:
        """Promote a user to moderator (captain only)"""

        # Only captains can promote to moderator
        if captain.role != UserRole.CAPTAIN:
            return False

        # Update user role
        result = await self.user_access_collection.update_one(
            {"user_id": target_user_id, "club_id": club_id},
            {"$set": {"role": "moderator", "updated_at": datetime.utcnow()}},
        )

        return result.modified_count > 0

    async def demote_moderator(
        self, target_user_id: str, club_id: str, captain: ChatUser
    ) -> bool:
        """Demote a moderator to regular member (captain only)"""

        # Only captains can demote moderators
        if captain.role != UserRole.CAPTAIN:
            return False

        # Update user role
        result = await self.user_access_collection.update_one(
            {"user_id": target_user_id, "club_id": club_id, "role": "moderator"},
            {"$set": {"role": "member", "updated_at": datetime.utcnow()}},
        )

        return result.modified_count > 0

    async def member_pin_message(
        self, message_id: str, member: ChatUser, reason: Optional[str] = None
    ) -> Optional[ChatMessage]:
        """Pin a message (member only)"""

        # Check if user is a member (not moderator/captain)
        if member.role not in [
            UserRole.MEMBER,
            UserRole.TRIAL_MEMBER,
            UserRole.PAID_MEMBER,
        ]:
            return None

        # Find the message
        message_doc = await self.messages_collection.find_one(
            {"message_id": message_id}
        )

        if not message_doc:
            return None

        # Check if message is already pinned by a member
        if message_doc.get("member_pinned_by"):
            return None  # Already pinned by a member

        # Update message with member pin info
        now = datetime.utcnow()
        update_data = {
            "member_pinned": True,
            "member_pinned_by": member.user_id,
            "member_pinned_by_username": member.username,
            "member_pinned_at": now,
            "member_pin_reason": reason,
            "updated_at": now,
        }

        result = await self.messages_collection.update_one(
            {"message_id": message_id}, {"$set": update_data}
        )

        if result.modified_count == 0:
            return None

        # Convert to ChatMessage object
        updated_doc = await self.messages_collection.find_one(
            {"message_id": message_id}
        )
        return ChatMessage(**updated_doc)

    async def member_unpin_message(self, message_id: str, member: ChatUser) -> bool:
        """Unpin a message (member only)"""

        # Check if user is a member (not moderator/captain)
        if member.role not in [
            UserRole.MEMBER,
            UserRole.TRIAL_MEMBER,
            UserRole.PAID_MEMBER,
        ]:
            return False

        # Find the message
        message_doc = await self.messages_collection.find_one(
            {"message_id": message_id}
        )

        if not message_doc:
            return False

        # Check if message is pinned by a member
        if not message_doc.get("member_pinned") or not message_doc.get(
            "member_pinned_by"
        ):
            return False

        # Check if the member is the one who pinned it (optional - can be removed for any member to unpin)
        # if message_doc.get("member_pinned_by") != member.user_id:
        #     return False

        # Update message to remove member pin info
        now = datetime.utcnow()
        update_data = {
            "member_pinned": False,
            "member_pinned_by": None,
            "member_pinned_by_username": None,
            "member_pinned_at": None,
            "member_pin_reason": None,
            "updated_at": now,
        }

        result = await self.messages_collection.update_one(
            {"message_id": message_id}, {"$set": update_data}
        )

        return result.modified_count > 0


# Global moderation service instance
moderation_service = ModerationService()
