from typing import Optional, Tuple, List, Dict
from datetime import datetime, timezone
from bson import ObjectId
import uuid
import logging
import re
import time

from .db import (
    get_dm_requests_collection,
    get_dm_messages_collection,
    get_dm_blocks_collection,
    get_user_collection,
    get_club_collection,
)
from .models import (
    DMRequest,
    DMRequestStatus,
    CreateDMRequestRequest,
    CreateDMRequestResponse,
    RespondToDMRequestRequest,
    RespondToDMRequestResponse,
    GetDMRequestsRequest,
    GetDMRequestsResponse,
    BlockUserRequest,
    BlockUserResponse,
    UnblockUserRequest,
    UnblockUserResponse,
    GetBlockedUsersResponse,
    DMMessage,
    SendDMMessageRequest,
    SendDMMessageResponse,
    GetDMMessagesRequest,
    GetDMMessagesResponse,
    GetDMConversationsRequest,
    GetDMConversationsResponse,
    DMConversation,
    MessageContent,
    MessageType,
    UserMention,
    GetDMPinnedMessagesResponse,
    EditDMMessageRequest,
    EditDMMessageResponse,
    DeleteDMMessageRequest,
    DeleteDMMessageResponse,
    ConnectedDMUser,
    GetConnectedDMUsersRequest,
    GetConnectedDMUsersResponse,
    SendDMThreadMessageRequest,
    SendDMThreadMessageResponse,
    GetDMThreadMessagesRequest,
    GetDMThreadMessagesResponse,
    is_html_content,
)
from .auth import check_club_access

logger = logging.getLogger(__name__)


class DMService:
    def __init__(self):
        self.dm_requests_collection = get_dm_requests_collection()
        self.dm_messages_collection = get_dm_messages_collection()
        self.dm_blocks_collection = get_dm_blocks_collection()
        self.users_collection = get_user_collection()
        self.clubs_collection = get_club_collection()

    async def can_users_dm(
        self, user1_id: str, user2_id: str, club_id: str
    ) -> Tuple[bool, str]:
        """Check if two users can DM each other (have accepted request)"""
        try:
            # Get club information
            club = await self.clubs_collection.find_one({"name_based_id": club_id})
            if not club:
                return False, "Club not found"

            # Check if there's an accepted DM request between the users
            dm_request = await self.dm_requests_collection.find_one(
                {
                    "$or": [
                        {
                            "sender_id": user1_id,
                            "receiver_id": user2_id,
                            "club_id": str(club["_id"]),
                        },
                        {
                            "sender_id": user2_id,
                            "receiver_id": user1_id,
                            "club_id": str(club["_id"]),
                        },
                    ],
                    "status": DMRequestStatus.ACCEPTED,
                }
            )

            if not dm_request:
                return False, "No accepted DM request found. Send a DM request first."

            # Check if either user is blocked by the other
            is_blocked = await self.dm_blocks_collection.find_one(
                {
                    "$or": [
                        {
                            "blocker_id": user1_id,
                            "blocked_id": user2_id,
                            "club_id": str(club["_id"]),
                        },
                        {
                            "blocker_id": user2_id,
                            "blocked_id": user1_id,
                            "club_id": str(club["_id"]),
                        },
                    ]
                }
            )

            if is_blocked:
                return False, "One of the users is blocked by the other"

            return True, "Users can DM each other"

        except Exception as e:
            logger.error(f"Error checking if users can DM: {e}")
            return False, f"Error checking DM permissions: {str(e)}"

    async def edit_dm_message(
        self, request: "EditDMMessageRequest", current_user: dict
    ) -> Tuple[bool, Optional["EditDMMessageResponse"], Optional[str]]:
        """Edit a DM message (only by sender)"""
        try:
            sender_id = current_user["user_id"]

            # Find the message
            dm_message_doc = await self.dm_messages_collection.find_one(
                {"dm_message_id": request.dm_message_id}
            )

            if not dm_message_doc:
                return False, None, "DM message not found"

            # Check if the current user is the sender
            if dm_message_doc["sender_id"] != sender_id:
                return False, None, "You can only edit your own messages"

            # Update the message
            now = datetime.now(timezone.utc)
            update_data = {
                "content.text": request.new_content,
                "content.is_html": is_html_content(request.new_content),
                "updated_at": now,
            }

            await self.dm_messages_collection.update_one(
                {"dm_message_id": request.dm_message_id}, {"$set": update_data}
            )

            # Get updated message
            updated_doc = await self.dm_messages_collection.find_one(
                {"dm_message_id": request.dm_message_id}
            )

            # Create response
            dm_message = DMMessage(**updated_doc)
            response = EditDMMessageResponse(
                success=True,
                dm_message=dm_message,
                message="DM message edited successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error editing DM message: {e}")
            return False, None, f"Failed to edit DM message: {str(e)}"

    async def delete_dm_message(
        self, request: "DeleteDMMessageRequest", current_user: dict
    ) -> Tuple[bool, Optional["DeleteDMMessageResponse"], Optional[str]]:
        """Delete a DM message (only by sender)"""
        try:
            sender_id = current_user["user_id"]

            # Find the message
            dm_message_doc = await self.dm_messages_collection.find_one(
                {"dm_message_id": request.dm_message_id}
            )

            if not dm_message_doc:
                return False, None, "DM message not found"

            # Check if the current user is the sender
            if dm_message_doc["sender_id"] != sender_id:
                return False, None, "You can only delete your own messages"

            # Delete the message
            await self.dm_messages_collection.delete_one(
                {"dm_message_id": request.dm_message_id}
            )

            # Create response
            response = DeleteDMMessageResponse(
                success=True, message="DM message deleted successfully"
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error deleting DM message: {e}")
            return False, None, f"Failed to delete DM message: {str(e)}"

    async def create_dm_request(
        self, request: CreateDMRequestRequest, current_user: dict
    ) -> Tuple[bool, Optional[CreateDMRequestResponse], Optional[str]]:
        """Create a DM request to another user"""
        try:
            sender_id = current_user["user_id"]
            logger.info(
                f"Creating DM request from {sender_id} to {request.receiver_id} in club {request.club_id}"
            )

            # Check if sender has access to the club
            has_access, access_details = await check_club_access(
                sender_id, request.club_id
            )
            if not has_access:
                logger.info("Sender does not have access to club")
                return (
                    False,
                    None,
                    "You must be a member of this club to send DM requests",
                )

            # Get club information by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                logger.info("Club not found")
                return False, None, "Club not found"

            logger.info(f"Found club: {club.get('name')} with ID: {club.get('_id')}")

            # Check if receiver exists
            receiver = await self.users_collection.find_one(
                {"_id": ObjectId(request.receiver_id)}
            )
            if not receiver:
                logger.info("Receiver not found")
                return False, None, "Receiver user not found"

            # Check if users are the same
            if sender_id == request.receiver_id:
                logger.info("Cannot send DM request to yourself")
                return False, None, "Cannot send DM request to yourself"

            # Check if receiver has access to the club
            receiver_has_access, receiver_access_details = await check_club_access(
                request.receiver_id, request.club_id
            )

            # Both users must be club members to send DM requests
            if not receiver_has_access:
                logger.info("Receiver does not have access to club")
                return (
                    False,
                    None,
                    "Receiver must be a member of this club to receive DM requests",
                )

            # Check if there's already a pending or accepted request (sender to receiver)
            existing_request = await self.dm_requests_collection.find_one(
                {
                    "sender_id": sender_id,
                    "receiver_id": request.receiver_id,
                    "club_id": str(club["_id"]),
                    "status": {"$in": ["pending", "accepted"]},
                }
            )

            if existing_request:
                status = existing_request.get("status", "UNKNOWN")
                logger.info(f"Found existing request with status: {status}")
                if status == "pending":
                    return (
                        False,
                        None,
                        "A pending DM request already exists. Please wait for the receiver to respond.",
                    )
                elif status == "accepted":
                    return (
                        False,
                        None,
                        "DM request has already been accepted. You can now send messages directly.",
                    )
                else:
                    return (
                        False,
                        None,
                        f"DM request already exists with status: {status}",
                    )

            # Also check if there's a reverse request (receiver to sender)
            reverse_request = await self.dm_requests_collection.find_one(
                {
                    "sender_id": request.receiver_id,
                    "receiver_id": sender_id,
                    "club_id": str(club["_id"]),
                    "status": {"$in": ["pending", "accepted"]},
                }
            )

            if reverse_request:
                status = reverse_request.get("status", "UNKNOWN")
                logger.info(f"Found reverse request with status: {status}")
                if status == "pending":
                    return (
                        False,
                        None,
                        "This user has already sent you a DM request. Please check your received requests and respond to it.",
                    )
                elif status == "accepted":
                    return (
                        False,
                        None,
                        "DM request has already been accepted. You can now send messages directly.",
                    )
                else:
                    return (
                        False,
                        None,
                        f"A DM request from this user already exists with status: {status}",
                    )

            # Check if sender is blocked by receiver
            is_blocked = await self.dm_blocks_collection.find_one(
                {
                    "blocker_id": request.receiver_id,
                    "blocked_id": sender_id,
                    "club_id": str(club["_id"]),
                }
            )
            if is_blocked:
                logger.info("Sender is blocked by receiver")
                return False, None, "You are blocked by this user"

            # Create DM request
            request_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            dm_request_data = {
                "request_id": request_id,
                "sender_id": sender_id,
                "sender_username": current_user.get("username", "Unknown"),
                "sender_full_name": current_user.get("full_name", "Unknown"),
                "sender_avatar": current_user.get("avatar_url"),
                "receiver_id": request.receiver_id,
                "receiver_username": receiver.get("username", "Unknown"),
                "receiver_full_name": receiver.get("full_name", "Unknown"),
                "receiver_avatar": receiver.get("avatar_url"),
                "club_id": str(club["_id"]),
                "club_name": club.get("name", "Unknown Club"),
                "status": "pending",
                "message": request.message,
                "created_at": now,
                "updated_at": now,
                "responded_at": None,
            }

            logger.info("Inserting DM request into database")
            await self.dm_requests_collection.insert_one(dm_request_data)

            # Create response
            dm_request = DMRequest(**dm_request_data)
            response = CreateDMRequestResponse(
                success=True,
                request_id=request_id,
                dm_request=dm_request,
                message="DM request sent successfully",
            )

            logger.info("DM request created successfully")
            
            # Send friend request notification to the receiver
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )

                # Determine recipient lists
                db_user_ids = [uid for uid in [request.receiver_id] if uid and uid != sender_id]

                if db_user_ids:
                    # Filter by friend request alerts preference (push candidates)
                    enabled_user_ids = await filter_users_by_notification_preference(
                        db_user_ids,
                        "friend_request_alerts"
                    )
                    enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]

                    # Identify users with active device tokens
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

                    push_user_ids = [
                        uid for uid in users_with_tokens if uid in enabled_user_ids
                    ]

                    # Get sender details
                    sender_name = current_user.get("full_name", "Someone")

                    title = f"New Friend Request!"
                    body = f"{sender_name} sent you a friend request in {club.get('name', 'Club')}"

                    notification_data = {
                        "request_id": request_id,
                        "sender_id": sender_id,
                        "sender_name": sender_name,
                        "receiver_id": request.receiver_id,
                        "receiver_name": receiver.get("full_name", "User"),
                        "club_id": club.get("name_based_id", "Club"),
                        "message": request.message,
                        "action": "friend_request_sent"
                    }

                    notification_result = await send_notification_to_users(
                        user_ids=push_user_ids,
                        title=title,
                        body=body,
                        notification_type="friend_request",
                        data=notification_data,
                        click_action=f"club/{request.club_id}/dm-requests",
                        priority="normal",
                        all_user_ids=db_user_ids,
                    )
                    logger.info(f"✅ Friend request notification stored for user {request.receiver_id}: {notification_result}")

                    if not push_user_ids:
                        logger.info(f"ℹ️ User {request.receiver_id} has friend request alerts disabled or no active tokens")
                else:
                    logger.info("ℹ️ No valid recipients found for friend request notification")

            except Exception as e:
                logger.error(f"⚠️ Failed to send friend request notification: {e}")
            
            return True, response, None

        except Exception as e:
            logger.error(f"Error creating DM request: {e}")
            logger.error(f"Exception type: {type(e)}")
            logger.error(f"Exception args: {e.args}")
            return False, None, f"Failed to create DM request: {str(e)}"

    async def respond_to_dm_request(
        self, request: RespondToDMRequestRequest, current_user: dict
    ) -> Tuple[bool, Optional[RespondToDMRequestResponse], Optional[str]]:
        """Respond to a DM request (accept/reject/block)"""
        try:
            receiver_id = current_user["user_id"]
            logger.info(
                f"DM Request Debug - Current user ID: {receiver_id}, Request ID: {request.request_id}, Action: {request.action}"
            )

            # Find the DM request
            # For block/unblock actions, we need to be more flexible with the query
            if request.action in ["block", "unblock"]:
                # For block/unblock, find request where current user is either sender or receiver
                query = {
                    "request_id": request.request_id,
                    "$or": [{"receiver_id": receiver_id}, {"sender_id": receiver_id}],
                }
                logger.info(f"DM Request Debug - Block/Unblock query: {query}")
                dm_request_doc = await self.dm_requests_collection.find_one(query)
            else:
                # For accept/reject, current user must be the receiver
                query = {"request_id": request.request_id, "receiver_id": receiver_id}
                logger.info(f"DM Request Debug - Accept/Reject query: {query}")
                dm_request_doc = await self.dm_requests_collection.find_one(query)

            if not dm_request_doc:
                # Debug: Check if request exists at all (regardless of user)
                debug_doc = await self.dm_requests_collection.find_one(
                    {"request_id": request.request_id}
                )
                if debug_doc:
                    return (
                        False,
                        None,
                        f"DM request found but current user (ID: {receiver_id}) is not authorized to perform this action. Request belongs to sender: {debug_doc.get('sender_id')} and receiver: {debug_doc.get('receiver_id')}",
                    )
                else:
                    return (
                        False,
                        None,
                        f"DM request not found with ID: {request.request_id}",
                    )

            # Check if request is already responded to (except for block/unblock actions)
            if (
                request.action not in ["unblock", "block"]
                and dm_request_doc["status"] != DMRequestStatus.PENDING
            ):
                return False, None, "DM request has already been responded to"

            # Special check: block action only works on pending or accepted requests
            if request.action == "block" and dm_request_doc["status"] not in [
                DMRequestStatus.PENDING,
                DMRequestStatus.ACCEPTED,
            ]:
                return False, None, "Cannot block this request in its current status"

            now = datetime.now(timezone.utc)

            # Handle different actions
            if request.action == "reject":
                # Delete the DM request completely (as if it never happened)
                await self.dm_requests_collection.delete_one(
                    {"request_id": request.request_id}
                )

                response = RespondToDMRequestResponse(
                    success=True,
                    dm_request=None,  # No request to return since it's deleted
                    message="DM request rejected and removed successfully",
                )

            else:
                # Map action strings to DMRequestStatus enum values
                action_mapping = {
                    "accept": DMRequestStatus.ACCEPTED,
                    "block": DMRequestStatus.BLOCKED,
                    "unblock": DMRequestStatus.ACCEPTED,  # Unblock sets status back to accepted
                }

                if request.action not in action_mapping:
                    return (
                        False,
                        None,
                        f"Invalid action: {request.action}. Must be 'accept', 'reject', 'block', or 'unblock'",
                    )

                new_status = action_mapping[request.action]

                update_data = {
                    "status": new_status,
                    "responded_at": now,
                    "updated_at": now,
                }

                await self.dm_requests_collection.update_one(
                    {"request_id": request.request_id}, {"$set": update_data}
                )

                # Handle block/unblock actions
                if request.action == "block":
                    # Determine who is blocking whom
                    if dm_request_doc["receiver_id"] == receiver_id:
                        # Current user is receiver, blocking the sender
                        blocker_id = receiver_id
                        blocked_id = dm_request_doc["sender_id"]
                    else:
                        # Current user is sender, blocking the receiver
                        blocker_id = receiver_id
                        blocked_id = dm_request_doc["receiver_id"]

                    # Create a block record
                    block_data = {
                        "blocker_id": blocker_id,
                        "blocked_id": blocked_id,
                        "club_id": dm_request_doc["club_id"],
                        "reason": f"Blocked via DM request response",
                        "created_at": now,
                    }
                    await self.dm_blocks_collection.insert_one(block_data)

                elif request.action == "unblock":
                    # Determine who is unblocking whom
                    if dm_request_doc["receiver_id"] == receiver_id:
                        # Current user is receiver, unblocking the sender
                        blocker_id = receiver_id
                        blocked_id = dm_request_doc["sender_id"]
                    else:
                        # Current user is sender, unblocking the receiver
                        blocker_id = receiver_id
                        blocked_id = dm_request_doc["receiver_id"]

                    # Remove block record
                    await self.dm_blocks_collection.delete_one(
                        {
                            "blocker_id": blocker_id,
                            "blocked_id": blocked_id,
                            "club_id": dm_request_doc["club_id"],
                        }
                    )

                # Get updated request
                updated_doc = await self.dm_requests_collection.find_one(
                    {"request_id": request.request_id}
                )
                dm_request = DMRequest(**updated_doc)

                # Create appropriate response message
                if request.action == "unblock":
                    message = "User unblocked successfully"
                else:
                    message = f"DM request {request.action}ed successfully"

                response = RespondToDMRequestResponse(
                    success=True, dm_request=dm_request, message=message
                )

                # Send friend request response notification to the original sender
                if request.action in ["accept", "reject"]:
                    try:
                        from services.notifications.notification_service import (
                            send_notification_to_users,
                            filter_users_by_notification_preference,
                            get_collections,
                        )

                        # Get the original sender ID from the DM request
                        original_sender_id = dm_request_doc.get("sender_id")
                        if original_sender_id:
                            db_user_ids = [uid for uid in [original_sender_id] if uid and uid != receiver_id]

                            if db_user_ids:
                                # Filter by friend request alerts preference
                                enabled_user_ids = await filter_users_by_notification_preference(
                                    db_user_ids,
                                    "friend_request_alerts"
                                )
                                enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]

                                # Get users with active tokens
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

                                push_user_ids = [
                                    uid for uid in users_with_tokens if uid in enabled_user_ids
                                ]

                                # Get responder details
                                responder_name = current_user.get("full_name", "Someone")

                                if request.action == "accept":
                                    title = f"Friend Request Accepted!"
                                    body = f"{responder_name} accepted your friend request"
                                else:  # reject
                                    title = f"Friend Request Declined"
                                    body = f"{responder_name} declined your friend request"

                                # Get club name_based_id
                                club_id_from_doc = dm_request_doc.get("club_id")
                                name_based_id = club_id_from_doc
                                if club_id_from_doc:
                                    try:
                                        club = await self.clubs_collection.find_one(
                                            {"_id": ObjectId(club_id_from_doc)}
                                        )
                                        if club:
                                            name_based_id = club.get("name_based_id", club_id_from_doc)
                                    except Exception as e:
                                        logger.warning(f"Failed to fetch club for name_based_id: {e}")
                                        name_based_id = club_id_from_doc

                                notification_data = {
                                    "request_id": request.request_id,
                                    "sender_id": original_sender_id,
                                    "sender_name": dm_request_doc.get("sender_full_name", "User"),
                                    "receiver_id": receiver_id,
                                    "receiver_name": responder_name,
                                    "club_id": name_based_id,
                                    "club_name": dm_request_doc.get("club_name", "Club"),
                                    "action": f"friend_request_{request.action}ed",
                                    "response_action": request.action
                                }

                                notification_result = await send_notification_to_users(
                                    user_ids=push_user_ids,
                                    title=title,
                                    body=body,
                                    notification_type="friend_request",
                                    data=notification_data,
                                    click_action=f"club/{name_based_id}/dm-requests",
                                    priority="normal",
                                    all_user_ids=db_user_ids,
                                )
                                logger.info(f"✅ Friend request {request.action} notification stored for user {original_sender_id}: {notification_result}")

                                if not push_user_ids:
                                    logger.info(f"ℹ️ User {original_sender_id} has friend request alerts disabled or no active tokens")
                            else:
                                logger.info("ℹ️ No valid recipients found for friend request response notification")
                    except Exception as e:
                        logger.error(f"⚠️ Failed to send friend request response notification: {e}")

            return True, response, None

        except Exception as e:
            logger.error(f"Error responding to DM request: {e}")
            return False, None, f"Failed to respond to DM request: {str(e)}"

    async def get_dm_requests(
        self, request: GetDMRequestsRequest, current_user: dict
    ) -> Tuple[bool, Optional[GetDMRequestsResponse], Optional[str]]:
        """Get DM requests for a user in a specific club"""
        try:
            user_id = current_user["user_id"]

            # Get club information by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"

            # Check club access
            has_access, _ = await check_club_access(user_id, request.club_id)
            if not has_access:
                return False, None, "Access denied to club"

            # Build query - use club ObjectId for database query
            query = {
                "club_id": str(club["_id"]),  # Use ObjectId from club document
                "$or": [{"sender_id": user_id}, {"receiver_id": user_id}],
            }

            if request.status:
                query["status"] = request.status

            # Calculate pagination
            skip = (request.page - 1) * request.page_size

            # Get requests with block status information
            requests_cursor = (
                self.dm_requests_collection.find(query)
                .sort("created_at", -1)
                .skip(skip)
                .limit(request.page_size)
            )
            requests = []
            async for doc in requests_cursor:
                # Add block status information for action buttons
                other_user_id = (
                    doc["sender_id"]
                    if doc["receiver_id"] == user_id
                    else doc["receiver_id"]
                )

                # Check if current user has blocked the other user
                block_record = await self.dm_blocks_collection.find_one(
                    {
                        "blocker_id": user_id,
                        "blocked_id": other_user_id,
                        "club_id": str(club["_id"]),
                    }
                )

                # Check if other user has blocked current user
                blocked_by_other = await self.dm_blocks_collection.find_one(
                    {
                        "blocker_id": other_user_id,
                        "blocked_id": user_id,
                        "club_id": str(club["_id"]),
                    }
                )

                # Create enhanced request object
                request_dict = doc.copy()
                request_dict["block_status"] = {
                    "is_blocked_by_me": block_record is not None,
                    "is_blocked_by_other": blocked_by_other is not None,
                    "can_block": not block_record
                    and doc["status"] in ["pending", "accepted"],
                    "can_unblock": block_record is not None,
                    "other_user_id": other_user_id,
                }

                requests.append(DMRequest(**request_dict))

            # Get total count
            total_count = await self.dm_requests_collection.count_documents(query)

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            response = GetDMRequestsResponse(
                success=True,
                requests=requests,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                message="DM requests retrieved successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting DM requests: {e}")
            return False, None, f"Failed to get DM requests: {str(e)}"

    async def block_user(
        self, request: BlockUserRequest, current_user: dict
    ) -> Tuple[bool, Optional[BlockUserResponse], Optional[str]]:
        """Block a user from sending DMs"""
        try:
            blocker_id = current_user["user_id"]

            # Check club access
            has_access, _ = await check_club_access(blocker_id, request.club_id)
            if not has_access:
                return False, None, "Access denied to club"

            # Check if user exists
            user = await self.users_collection.find_one(
                {"_id": ObjectId(request.user_id)}
            )
            if not user:
                return False, None, "User not found"

            # Fetch club to determine name_based_id for notifications
            club_doc = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            club_name_based_id = (
                club_doc.get("name_based_id", request.club_id) if club_doc else request.club_id
            )

            # Check if already blocked
            existing_block = await self.dm_blocks_collection.find_one(
                {
                    "blocker_id": blocker_id,
                    "blocked_id": request.user_id,
                    "club_id": request.club_id,
                }
            )
            if existing_block:
                return False, None, "User is already blocked"

            # Create block record
            now = datetime.now(timezone.utc)
            block_data = {
                "blocker_id": blocker_id,
                "blocked_id": request.user_id,
                "club_id": request.club_id,
                "reason": request.reason,
                "created_at": now,
            }

            await self.dm_blocks_collection.insert_one(block_data)

            # Reject any pending DM requests from this user
            await self.dm_requests_collection.update_many(
                {
                    "sender_id": request.user_id,
                    "receiver_id": blocker_id,
                    "club_id": request.club_id,
                    "status": DMRequestStatus.PENDING,
                },
                {
                    "$set": {
                        "status": DMRequestStatus.REJECTED,
                        "responded_at": now,
                        "updated_at": now,
                    }
                },
            )

            response = BlockUserResponse(
                success=True,
                blocked_user_id=request.user_id,
                message="User blocked successfully",
            )
            
            # Send DM block notification to the blocked user
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )

                # Get blocked user's details for notification (optional)
                blocked_user = await self.users_collection.find_one({"_id": ObjectId(request.user_id)})
                if blocked_user:
                    db_user_ids = [uid for uid in [request.user_id] if uid and uid != blocker_id]

                    if db_user_ids:
                        # Filter by DM block alerts preference
                        enabled_user_ids = await filter_users_by_notification_preference(
                            db_user_ids,
                            "dm_block_alerts"
                        )
                        enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]

                        # Fetch active tokens
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

                        push_user_ids = [
                            uid for uid in users_with_tokens if uid in enabled_user_ids
                        ]

                        # Get blocker user details
                        blocker_user = await self.users_collection.find_one({"_id": ObjectId(blocker_id)})
                        blocker_name = blocker_user.get("full_name", "Someone") if blocker_user else "Someone"

                        title = f"You've Been Blocked!"
                        body = f"{blocker_name} has blocked you from sending DMs"

                        notification_data = {
                            "blocked_user_id": request.user_id,
                            "blocker_id": blocker_id,
                            "blocker_name": blocker_name,
                            "club_id": club_name_based_id,
                            "reason": request.reason,
                            "action": "block"
                        }

                        notification_result = await send_notification_to_users(
                            user_ids=push_user_ids,
                            title=title,
                            body=body,
                            notification_type="dm_block",
                            data=notification_data,
                            click_action="dm/conversations",
                            priority="normal",
                            all_user_ids=db_user_ids,
                        )
                        logger.info(f"✅ DM block notification stored for user {request.user_id}: {notification_result}")

                        if not push_user_ids:
                            logger.info(f"ℹ️ User {request.user_id} has DM block alerts disabled or no active tokens")
                    else:
                        logger.info("ℹ️ No valid recipients found for DM block notification")
                else:
                    logger.info(f"ℹ️ Blocked user {request.user_id} not found for notification")

            except Exception as e:
                logger.error(f"⚠️ Failed to send DM block notification: {e}")

            return True, response, None

        except Exception as e:
            logger.error(f"Error blocking user: {e}")
            return False, None, f"Failed to block user: {str(e)}"

    async def unblock_user(
        self, request: UnblockUserRequest, current_user: dict
    ) -> Tuple[bool, Optional[UnblockUserResponse], Optional[str]]:
        """Unblock a user"""
        try:
            unblocker_id = current_user["user_id"]

            # Check club access
            has_access, _ = await check_club_access(unblocker_id, request.club_id)
            if not has_access:
                return False, None, "Access denied to club"

            # Fetch club to determine name_based_id for notifications
            club_doc = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            club_name_based_id = (
                club_doc.get("name_based_id", request.club_id) if club_doc else request.club_id
            )

            # Remove block record
            result = await self.dm_blocks_collection.delete_one(
                {
                    "blocker_id": unblocker_id,
                    "blocked_id": request.user_id,
                    "club_id": request.club_id,
                }
            )

            if result.deleted_count == 0:
                return False, None, "User is not blocked"

            response = UnblockUserResponse(
                success=True,
                unblocked_user_id=request.user_id,
                message="User unblocked successfully",
            )
            
            # Send DM unblock notification to the unblocked user
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )

                # Get unblocked user's details for notification
                unblocked_user = await self.users_collection.find_one({"_id": ObjectId(request.user_id)})
                if unblocked_user:
                    db_user_ids = [uid for uid in [request.user_id] if uid and uid != unblocker_id]

                    if db_user_ids:
                        # Filter by DM block alerts preference
                        enabled_user_ids = await filter_users_by_notification_preference(
                            db_user_ids,
                            "dm_block_alerts"
                        )
                        enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]

                        # Fetch users with active tokens
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

                        push_user_ids = [
                            uid for uid in users_with_tokens if uid in enabled_user_ids
                        ]

                        # Get unblocker user details
                        unblocker_user = await self.users_collection.find_one({"_id": ObjectId(unblocker_id)})
                        unblocker_name = unblocker_user.get("full_name", "Someone") if unblocker_user else "Someone"

                        title = f"You've Been Unblocked!"
                        body = f"{unblocker_name} has unblocked you from DMs"

                        notification_data = {
                            "unblocked_user_id": request.user_id,
                            "unblocker_id": unblocker_id,
                            "unblocker_name": unblocker_name,
                            "club_id": club_name_based_id,
                            "action": "unblock"
                        }

                        notification_result = await send_notification_to_users(
                            user_ids=push_user_ids,
                            title=title,
                            body=body,
                            notification_type="dm_block",
                            data=notification_data,
                            click_action="dm/conversations",
                            priority="normal",
                            all_user_ids=db_user_ids,
                        )
                        logger.info(f"✅ DM unblock notification stored for user {request.user_id}: {notification_result}")

                        if not push_user_ids:
                            logger.info(f"ℹ️ User {request.user_id} has DM block alerts disabled or no active tokens")
                    else:
                        logger.info("ℹ️ No valid recipients found for DM unblock notification")
                else:
                    logger.info(f"ℹ️ Unblocked user {request.user_id} not found for notification")

            except Exception as e:
                logger.error(f"⚠️ Failed to send DM unblock notification: {e}")

            return True, response, None

        except Exception as e:
            logger.error(f"Error unblocking user: {e}")
            return False, None, f"Failed to unblock user: {str(e)}"

    async def get_blocked_users(
        self, club_id: str, current_user: dict
    ) -> Tuple[bool, Optional[GetBlockedUsersResponse], Optional[str]]:
        """Get list of blocked users"""
        try:
            user_id = current_user["user_id"]

            # Check club access
            has_access, _ = await check_club_access(user_id, club_id)
            if not has_access:
                return False, None, "Access denied to club"

            # Get blocked users
            blocked_cursor = self.dm_blocks_collection.find(
                {"blocker_id": user_id, "club_id": club_id}
            ).sort("created_at", -1)

            blocked_users = []
            async for block_doc in blocked_cursor:
                # Get user details
                user = await self.users_collection.find_one(
                    {"_id": ObjectId(block_doc["blocked_id"])}
                )
                if user:
                    blocked_users.append(
                        {
                            "user_id": block_doc["blocked_id"],
                            "username": user.get("username", "Unknown"),
                            "full_name": user.get("full_name", "Unknown"),
                            "avatar_url": user.get("avatar_url"),
                            "blocked_at": block_doc["created_at"],
                            "reason": block_doc.get("reason"),
                        }
                    )

            response = GetBlockedUsersResponse(
                success=True,
                blocked_users=blocked_users,
                total_count=len(blocked_users),
                message="Blocked users retrieved successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting blocked users: {e}")
            return False, None, f"Failed to get blocked users: {str(e)}"

    async def send_dm_message(
        self, request: SendDMMessageRequest, current_user: dict
    ) -> Tuple[bool, Optional[SendDMMessageResponse], Optional[str]]:
        """Send a direct message"""
        try:
            sender_id = current_user["user_id"]

            # Check if users are the same
            if sender_id == request.receiver_id:
                return False, None, "Cannot send DM to yourself"

            # Get club information by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"

            # Check if sender has access to the club
            sender_has_access, _ = await check_club_access(sender_id, request.club_id)

            # Check if receiver has access to the club
            receiver_has_access, _ = await check_club_access(
                request.receiver_id, request.club_id
            )

            # Both users must be club members to DM
            if not sender_has_access:
                return False, None, "You must be a member of this club to send DMs"

            if not receiver_has_access:
                return (
                    False,
                    None,
                    "Receiver must be a member of this club to receive DMs",
                )

            # Check if users can DM each other (have accepted request and not blocked)
            can_dm, error_message = await self.can_users_dm(
                sender_id, request.receiver_id, request.club_id
            )
            if not can_dm:
                return False, None, error_message

            # Get receiver details
            receiver = await self.users_collection.find_one(
                {"_id": ObjectId(request.receiver_id)}
            )
            if not receiver:
                return False, None, "Receiver user not found"

            # Get club details by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"
            club_name_based_id = club.get("name_based_id", request.club_id)

            # Create DM message
            dm_message_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            # Create message content
            message_content = MessageContent(text=request.content, mentions=[])

            dm_message_data = {
                "dm_message_id": dm_message_id,
                "sender_id": sender_id,
                "sender_username": current_user.get("username", "Unknown"),
                "sender_full_name": current_user.get("full_name", "Unknown"),
                "sender_avatar": current_user.get("avatar_url"),
                "receiver_id": request.receiver_id,
                "receiver_username": receiver.get("username", "Unknown"),
                "receiver_full_name": receiver.get("full_name", "Unknown"),
                "receiver_avatar": receiver.get("avatar_url"),
                "club_id": str(club["_id"]),
                "club_name": club.get("name", "Unknown Club"),
                "content": message_content.dict(),
                "message_type": request.message_type,
                "reactions": [],
                "reply_to_dm_message_id": request.reply_to_dm_message_id,
                "edited_at": None,
                "created_at": now,
                "updated_at": now,
            }

            await self.dm_messages_collection.insert_one(dm_message_data)

            # Send push notification to receiver
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )

                db_user_ids = [uid for uid in [request.receiver_id] if uid and uid != sender_id]

                if db_user_ids:
                    # Filter by message alerts preference
                    enabled_user_ids = await filter_users_by_notification_preference(
                        db_user_ids,
                        "message_alerts"
                    )
                    enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]

                    # Fetch active tokens
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

                    push_user_ids = [
                        uid for uid in users_with_tokens if uid in enabled_user_ids
                    ]

                    # Create notification content
                    title = f"New Direct Message!"
                    body = f"{current_user.get('full_name', 'Someone')} sent you a message"

                    # Truncate message content for notification
                    message_preview = request.content[:100] + "..." if len(request.content) > 100 else request.content

                    notification_data = {
                        "dm_message_id": dm_message_id,
                        "club_id": club_name_based_id,
                        "club_name": club.get("name", "Club"),
                        "sender_id": sender_id,
                        "sender_name": current_user.get("full_name", "Unknown"),
                        "sender_avatar": current_user.get("avatar_url"),
                        "receiver_id": request.receiver_id,
                        "message_preview": message_preview,
                        "msg_type": request.message_type,  # Note: use msg_type instead of message_type (Firebase restriction)
                        "push_type": "chat_message",
                        # Chat status flags for DM messages
                        "is_dm": "true",  # This is a DM
                        "is_chat_open": "true",  # Chat stays open for DMs
                        "is_dm_chat_open": "false"  # DM chat window closes when notification arrives
                    }

                    notification_result = await send_notification_to_users(
                        user_ids=push_user_ids,
                        title=title,
                        body=body,
                        notification_type="club_message",
                        data=notification_data,
                        click_action=f"club/{club_name_based_id}/dm/{sender_id}",
                        priority="high",  # DMs are high priority
                        all_user_ids=db_user_ids,
                    )
                    logger.info(f"✅ DM notification stored for receiver {request.receiver_id}: {notification_result}")

                    if not push_user_ids:
                        logger.info(f"ℹ️ Receiver {request.receiver_id} has message alerts disabled or no active tokens")
                else:
                    logger.info("ℹ️ No valid recipients found for DM notification")

            except Exception as e:
                logger.error(f"⚠️ Failed to send DM notification: {e}")
                # Don't fail the DM send if notification fails

            # Create response
            dm_message = DMMessage(**dm_message_data)
            response = SendDMMessageResponse(
                success=True,
                dm_message_id=dm_message_id,
                dm_message=dm_message,
                message="DM sent successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error sending DM message: {e}")
            return False, None, f"Failed to send DM message: {str(e)}"

    async def get_dm_messages(
        self, request: GetDMMessagesRequest, current_user: dict
    ) -> Tuple[bool, Optional[GetDMMessagesResponse], Optional[str]]:
        """Get DM messages between two users (excluding thread messages)"""
        try:
            user_id = current_user["user_id"]

            # Check club access
            has_access, _ = await check_club_access(user_id, request.club_id)
            if not has_access:
                return False, None, "Access denied to club"

            # Get club information by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"

            # Check if there's a DM request (accepted or blocked)
            dm_request = await self.dm_requests_collection.find_one(
                {
                    "$or": [
                        {
                            "sender_id": user_id,
                            "receiver_id": request.user_id,
                            "club_id": str(club["_id"]),
                        },
                        {
                            "sender_id": request.user_id,
                            "receiver_id": user_id,
                            "club_id": str(club["_id"]),
                        },
                    ],
                    "status": {
                        "$in": [DMRequestStatus.ACCEPTED, DMRequestStatus.BLOCKED]
                    },
                }
            )
            if not dm_request:
                return False, None, "No DM request found"

            # Build query - exclude thread messages (replies) from main DM message list
            query = {
                "$or": [
                    {
                        "sender_id": user_id,
                        "receiver_id": request.user_id,
                        "club_id": str(club["_id"]),
                    },
                    {
                        "sender_id": request.user_id,
                        "receiver_id": user_id,
                        "club_id": str(club["_id"]),
                    },
                ],
                "reply_to_dm_message_id": None,  # Only show parent messages, not thread replies
            }

            # Add search filter if provided
            if request.search and request.search.strip():
                search_term = request.search.strip()
                # Escape special regex characters
                escaped_search_term = re.escape(search_term)
                query["content.text"] = {"$regex": escaped_search_term, "$options": "i"}

            # Calculate pagination - fetch latest first from DB
            skip = (request.page - 1) * request.page_size

            # Get messages in descending order (latest first from DB)
            messages_cursor = (
                self.dm_messages_collection.find(query)
                .sort("created_at", -1)
                .skip(skip)
                .limit(request.page_size)
            )
            messages = []
            async for doc in messages_cursor:
                dm_message = await self.document_to_dm_message(doc)
                if dm_message:
                    messages.append(dm_message)

            # Reverse messages to show oldest first (since we fetched latest first from DB)
            messages.reverse()

            # Get total count
            total_count = await self.dm_messages_collection.count_documents(query)

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            response = GetDMMessagesResponse(
                success=True,
                messages=messages,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                message="DM messages retrieved successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting DM messages: {e}")
            return False, None, f"Failed to get DM messages: {str(e)}"

    async def get_dm_conversations(
        self, request: GetDMConversationsRequest, current_user: dict
    ) -> Tuple[bool, Optional[GetDMConversationsResponse], Optional[str]]:
        """Get DM conversations for a user in a club"""
        try:
            user_id = current_user["user_id"]

            # Check club access
            has_access, _ = await check_club_access(user_id, request.club_id)
            if not has_access:
                return False, None, "Access denied to club"

            # Get club information by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"

            # Get all accepted DM requests for this user in this club
            dm_requests = await self.dm_requests_collection.find(
                {
                    "$or": [
                        {"sender_id": user_id, "club_id": str(club["_id"])},
                        {"receiver_id": user_id, "club_id": str(club["_id"])},
                    ],
                    "status": DMRequestStatus.ACCEPTED,
                }
            ).to_list(None)

            # Get unique conversation partners
            conversation_partners = set()
            for req in dm_requests:
                if req["sender_id"] == user_id:
                    conversation_partners.add(req["receiver_id"])
                else:
                    conversation_partners.add(req["sender_id"])

            # Get last message and unread count for each conversation
            conversations = []
            for partner_id in conversation_partners:
                # Get last message
                last_message_doc = await self.dm_messages_collection.find_one(
                    {
                        "$or": [
                            {
                                "sender_id": user_id,
                                "receiver_id": partner_id,
                                "club_id": str(club["_id"]),
                            },
                            {
                                "sender_id": partner_id,
                                "receiver_id": user_id,
                                "club_id": str(club["_id"]),
                            },
                        ]
                    },
                    sort=[("created_at", -1)],
                )

                # Get unread count (messages sent to current user)
                unread_count = await self.dm_messages_collection.count_documents(
                    {
                        "sender_id": partner_id,
                        "receiver_id": user_id,
                        "club_id": str(club["_id"]),
                        "read_at": {
                            "$exists": False
                        },  # Assuming we'll add read_at field later
                    }
                )

                # Get partner details
                partner = await self.users_collection.find_one(
                    {"_id": ObjectId(partner_id)}
                )
                if partner:
                    last_message = (
                        DMMessage(**last_message_doc) if last_message_doc else None
                    )

                    conversations.append(
                        DMConversation(
                            user_id=partner_id,
                            username=partner.get("username", "Unknown"),
                            full_name=partner.get("full_name", "Unknown"),
                            avatar=partner.get("avatar_url"),
                            last_message=last_message,
                            unread_count=unread_count,
                            last_message_at=(
                                last_message.created_at if last_message else None
                            ),
                        )
                    )

            # Sort by last message time
            conversations.sort(
                key=lambda x: x.last_message_at or datetime.min, reverse=True
            )

            # Calculate pagination
            total_count = len(conversations)
            start_idx = (request.page - 1) * request.page_size
            end_idx = start_idx + request.page_size
            paginated_conversations = conversations[start_idx:end_idx]

            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            response = GetDMConversationsResponse(
                success=True,
                conversations=paginated_conversations,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                message="DM conversations retrieved successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting DM conversations: {e}")
            return False, None, f"Failed to get DM conversations: {str(e)}"

    async def pin_dm_message(
        self, message_id: str, user_id: str, reason: Optional[str] = None
    ) -> Tuple[bool, Optional[DMMessage], Optional[str]]:
        """Pin a DM message"""
        try:
            # Get the message
            message_doc = await self.dm_messages_collection.find_one(
                {"dm_message_id": message_id}
            )
            if not message_doc:
                return False, None, "DM message not found"

            # Check if user is part of this conversation
            if user_id not in [message_doc["sender_id"], message_doc["receiver_id"]]:
                return (
                    False,
                    None,
                    "You can only pin messages in your own conversations",
                )

            # Check if message is already pinned
            if message_doc.get("pinned", False):
                return False, None, "Message is already pinned"

            # Get user details
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False, None, "User not found"

            # Update message with pin information
            now = datetime.now(timezone.utc)
            update_data = {
                "pinned": True,
                "pinned_by": user_id,
                "pinned_by_username": user.get("username", "Unknown"),
                "pinned_at": now,
                "pin_reason": reason,
                "updated_at": now,
            }

            await self.dm_messages_collection.update_one(
                {"dm_message_id": message_id}, {"$set": update_data}
            )

            # Get updated message
            updated_doc = await self.dm_messages_collection.find_one(
                {"dm_message_id": message_id}
            )
            dm_message = DMMessage(**updated_doc)

            return True, dm_message, None

        except Exception as e:
            logger.error(f"Error pinning DM message: {e}")
            return False, None, f"Failed to pin DM message: {str(e)}"

    async def unpin_dm_message(
        self, message_id: str, user_id: str
    ) -> Tuple[bool, Optional[str]]:
        """Unpin a DM message"""
        try:
            # Get the message
            message_doc = await self.dm_messages_collection.find_one(
                {"dm_message_id": message_id}
            )
            if not message_doc:
                return False, "DM message not found"

            # Check if user is part of this conversation
            if user_id not in [message_doc["sender_id"], message_doc["receiver_id"]]:
                return False, "You can only unpin messages in your own conversations"

            # Check if message is pinned
            if not message_doc.get("pinned", False):
                return False, "Message is not pinned"

            # Update message to remove pin information
            now = datetime.now(timezone.utc)
            update_data = {
                "pinned": False,
                "pinned_by": None,
                "pinned_by_username": None,
                "pinned_at": None,
                "pin_reason": None,
                "updated_at": now,
            }

            await self.dm_messages_collection.update_one(
                {"dm_message_id": message_id}, {"$set": update_data}
            )

            return True, None

        except Exception as e:
            logger.error(f"Error unpinning DM message: {e}")
            return False, f"Failed to unpin DM message: {str(e)}"

    async def get_dm_pinned_messages(
        self, user_id: str, club_id: str, page: int = 1, page_size: int = 20
    ) -> Tuple[bool, Optional[GetDMPinnedMessagesResponse], Optional[str]]:
        """Get pinned DM messages for a user in a club"""
        try:
            # Get club information by name_based_id
            club = await self.clubs_collection.find_one({"name_based_id": club_id})
            if not club:
                return False, None, "Club not found"

            # Build query for pinned messages in conversations involving this user
            query = {
                "club_id": str(club["_id"]),
                "pinned": True,
                "$or": [{"sender_id": user_id}, {"receiver_id": user_id}],
            }

            # Calculate pagination
            skip = (page - 1) * page_size

            # Get total count
            total_count = await self.dm_messages_collection.count_documents(query)

            # Get pinned messages
            messages_cursor = (
                self.dm_messages_collection.find(query)
                .sort("pinned_at", -1)
                .skip(skip)
                .limit(page_size)
            )
            messages = []
            async for doc in messages_cursor:
                messages.append(DMMessage(**doc))

            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1

            response = GetDMPinnedMessagesResponse(
                success=True,
                pinned_messages=messages,
                total_count=total_count,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                message="Pinned DM messages retrieved successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting pinned DM messages: {e}")
            return False, None, f"Failed to get pinned DM messages: {str(e)}"

    async def get_connected_dm_users(
        self, request: GetConnectedDMUsersRequest, current_user: dict
    ) -> Tuple[bool, Optional[GetConnectedDMUsersResponse], Optional[str]]:
        """Get connected DM users for the current user in a club with last message info and optional search - ULTRA OPTIMIZED VERSION"""
        import time

        start_time = time.time()
        print(
            f"🚀 [CONNECTED DM USERS] Starting optimization for user: {current_user['user_id']}"
        )

        try:
            user_id = current_user["user_id"]

            # Step 1: Club access and lookup - OPTIMIZED
            step_start = time.time()
            has_access, _ = await check_club_access(user_id, request.club_id)
            if not has_access:
                return False, None, "Access denied to club"

            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"

            club_object_id = str(club["_id"])
            print(
                f"⏱️ [CONNECTED DM USERS] Club lookup: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 2: Get connected users with simplified approach - ULTRA OPTIMIZED
            step_start = time.time()

            # Get all DM requests for this user in this club (accepted only for now)
            dm_requests = await self.dm_requests_collection.find(
                {
                    "$or": [
                        {"sender_id": user_id, "club_id": club_object_id},
                        {"receiver_id": user_id, "club_id": club_object_id},
                    ],
                    "status": DMRequestStatus.ACCEPTED,
                }
            ).to_list(None)

            print(
                f"⏱️ [CONNECTED DM USERS] DM requests fetch: {(time.time() - step_start)*1000:.2f}ms"
            )

            if not dm_requests:
                # Return empty response if no DM connections
                response = GetConnectedDMUsersResponse(
                    success=True,
                    connected_users=[],
                    total_count=0,
                    page=request.page,
                    page_size=request.page_size,
                    total_pages=0,
                    has_next=False,
                    has_previous=False,
                    message="No connected DM users found",
                )
                return True, response, None

            # Step 3: Extract partner user IDs - OPTIMIZED
            step_start = time.time()
            partner_ids = []
            for dm_request in dm_requests:
                partner_id = (
                    dm_request["receiver_id"]
                    if dm_request["sender_id"] == user_id
                    else dm_request["sender_id"]
                )
                partner_ids.append(partner_id)

            # Remove duplicates
            partner_ids = list(set(partner_ids))
            print(
                f"⏱️ [CONNECTED DM USERS] Partner ID extraction: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 4: Get user details in bulk - OPTIMIZED
            step_start = time.time()
            user_object_ids = [
                ObjectId(uid) for uid in partner_ids if ObjectId.is_valid(uid)
            ]
            users_cursor = self.users_collection.find(
                {"_id": {"$in": user_object_ids}},
                {"_id": 1, "username": 1, "full_name": 1, "avatar_url": 1},
            )
            users_data = await users_cursor.to_list(None)
            user_lookup = {str(doc["_id"]): doc for doc in users_data}
            print(
                f"⏱️ [CONNECTED DM USERS] User data fetch: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 5: Get last messages and unread counts in bulk - ULTRA OPTIMIZED
            step_start = time.time()
            last_messages = {}
            unread_counts = {}

            # Use aggregation pipeline to get last messages for all conversations at once
            if partner_ids:
                # Build match conditions for all conversations
                match_conditions = []
                for partner_id in partner_ids:
                    match_conditions.extend(
                        [
                            {
                                "sender_id": user_id,
                                "receiver_id": partner_id,
                                "club_id": club_object_id,
                            },
                            {
                                "sender_id": partner_id,
                                "receiver_id": user_id,
                                "club_id": club_object_id,
                            },
                        ]
                    )

                # Aggregation pipeline to get last message for each conversation
                pipeline = [
                    {"$match": {"$or": match_conditions}},
                    {"$sort": {"created_at": -1}},
                    {
                        "$group": {
                            "_id": {
                                "$cond": {
                                    "if": {"$eq": ["$sender_id", user_id]},
                                    "then": "$receiver_id",
                                    "else": "$sender_id",
                                }
                            },
                            "last_message": {"$first": "$$ROOT"},
                        }
                    },
                ]

                last_message_results = await self.dm_messages_collection.aggregate(
                    pipeline
                ).to_list(None)

                for result in last_message_results:
                    partner_id = result["_id"]
                    last_messages[partner_id] = result["last_message"]

                # Get unread counts in bulk using aggregation
                unread_pipeline = [
                    {
                        "$match": {
                            "sender_id": {"$in": partner_ids},
                            "receiver_id": user_id,
                            "club_id": club_object_id,
                            "read_at": None,
                        }
                    },
                    {"$group": {"_id": "$sender_id", "unread_count": {"$sum": 1}}},
                ]

                unread_results = await self.dm_messages_collection.aggregate(
                    unread_pipeline
                ).to_list(None)

                for result in unread_results:
                    sender_id = result["_id"]
                    unread_counts[sender_id] = result["unread_count"]

                # Set default unread count of 0 for users with no unread messages
                for partner_id in partner_ids:
                    if partner_id not in unread_counts:
                        unread_counts[partner_id] = 0

            print(
                f"⏱️ [CONNECTED DM USERS] Last messages & unread counts: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 6: Get blocking status in bulk - ULTRA OPTIMIZED
            step_start = time.time()
            blocking_data = {}

            # Get all blocking records for this user in this club
            blocks_cursor = self.dm_blocks_collection.find(
                {
                    "$or": [
                        {"blocker_id": user_id, "club_id": club_object_id},
                        {"blocked_id": user_id, "club_id": club_object_id},
                    ]
                }
            )
            all_blocks = await blocks_cursor.to_list(None)

            # Process blocking data
            for block in all_blocks:
                if block["blocker_id"] == user_id:
                    # User blocked someone
                    blocked_id = block["blocked_id"]
                    if blocked_id not in blocking_data:
                        blocking_data[blocked_id] = {
                            "blocked_by_me": True,
                            "blocked_at_me": block.get("created_at"),
                        }
                    else:
                        blocking_data[blocked_id]["blocked_by_me"] = True
                        blocking_data[blocked_id]["blocked_at_me"] = block.get(
                            "created_at"
                        )
                else:
                    # User was blocked by someone
                    blocker_id = block["blocker_id"]
                    if blocker_id not in blocking_data:
                        blocking_data[blocker_id] = {
                            "blocked_by_other": True,
                            "blocked_at_other": block.get("created_at"),
                        }
                    else:
                        blocking_data[blocker_id]["blocked_by_other"] = True
                        blocking_data[blocker_id]["blocked_at_other"] = block.get(
                            "created_at"
                        )

            print(
                f"⏱️ [CONNECTED DM USERS] Blocking data fetch: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 7: Get current user's DM chat open status for this club - OPTIMIZED
            step_start = time.time()
            current_user_doc = await self.users_collection.find_one(
                {"_id": ObjectId(user_id)},
                {"chat_open_clubs": 1}
            )
            
            is_dm_chat_open = True  # Default
            if current_user_doc and "chat_open_clubs" in current_user_doc:
                for club_status in current_user_doc["chat_open_clubs"]:
                    if club_status.get("club_id") == request.club_id:
                        is_dm_chat_open = club_status.get("is_dm_chat_open", True)
                        break
            
            print(
                f"⏱️ [CONNECTED DM USERS] DM chat status fetch: {(time.time() - step_start)*1000:.2f}ms"
            )
            
            # Step 8: Build response data - OPTIMIZED
            step_start = time.time()
            all_connected_users = []

            for partner_id in partner_ids:
                user_data = user_lookup.get(partner_id, {})
                last_message = last_messages.get(partner_id)
                unread_count = unread_counts.get(partner_id, 0)
                blocking_info = blocking_data.get(partner_id, {})

                # Apply search filter if provided
                if request.search and request.search.strip():
                    search_term = request.search.strip().lower()
                    username = user_data.get("username", "").lower()
                    full_name = user_data.get("full_name", "").lower()
                    if search_term not in username and search_term not in full_name:
                        continue

                # Determine status and blocking details
                blocked_by_me = blocking_info.get("blocked_by_me", False)
                blocked_by_other = blocking_info.get("blocked_by_other", False)

                if blocked_by_me and blocked_by_other:
                    status = "mutual_block"
                    blocked_by = "mutual"
                    blocked_at = blocking_info.get("blocked_at_me")
                elif blocked_by_me:
                    status = "blocked_by_me"
                    blocked_by = "me"
                    blocked_at = blocking_info.get("blocked_at_me")
                elif blocked_by_other:
                    status = "blocked_by_other"
                    blocked_by = "other"
                    blocked_at = blocking_info.get("blocked_at_other")
                else:
                    status = "active"
                    blocked_by = None
                    blocked_at = None

                # Handle timezone for timestamps
                last_message_timestamp = None
                if last_message and last_message.get("created_at"):
                    last_message_timestamp = last_message["created_at"]
                    if last_message_timestamp.tzinfo is None:
                        last_message_timestamp = last_message_timestamp.replace(
                            tzinfo=timezone.utc
                        )

                if blocked_at and blocked_at.tzinfo is None:
                    blocked_at = blocked_at.replace(tzinfo=timezone.utc)

                # Ensure sort_timestamp is timezone-aware
                sort_timestamp = (
                    last_message_timestamp
                    if last_message_timestamp
                    else datetime.min.replace(tzinfo=timezone.utc)
                )

                user_info = {
                    "user_id": partner_id,
                    "username": user_data.get("username", "Unknown"),
                    "full_name": user_data.get("full_name", "Unknown"),
                    "avatar_url": user_data.get("avatar_url"),
                    "last_message": (
                        last_message.get("content", {}).get("text")
                        if last_message
                        else None
                    ),
                    "last_message_timestamp": last_message_timestamp,
                    "last_message_sender_id": (
                        last_message.get("sender_id") if last_message else None
                    ),
                    "last_message_sender_username": (
                        last_message.get("sender_username", "Unknown")
                        if last_message
                        else "Unknown"
                    ),
                    "last_message_sender_full_name": (
                        last_message.get("sender_full_name", "Unknown")
                        if last_message
                        else "Unknown"
                    ),
                    "unread_count": unread_count,
                    "status": status,
                    "blocked_by": blocked_by,
                    "blocked_at": blocked_at,
                    "sort_timestamp": sort_timestamp,
                    "is_dm_chat_open": is_dm_chat_open,
                }

                all_connected_users.append(user_info)

            # Sort by last message timestamp (descending)
            all_connected_users.sort(key=lambda x: x["sort_timestamp"], reverse=True)

            print(
                f"⏱️ [CONNECTED DM USERS] Response building: {(time.time() - step_start)*1000:.2f}ms"
            )

            # Step 9: Convert to ConnectedDMUser objects and apply pagination - OPTIMIZED
            step_start = time.time()
            connected_users = []

            for user_data in all_connected_users:
                connected_user = ConnectedDMUser(
                    user_id=user_data["user_id"],
                    username=user_data.get("username", "Unknown"),
                    full_name=user_data.get("full_name", "Unknown"),
                    avatar_url=user_data.get("avatar_url"),
                    last_message=user_data.get("last_message"),
                    last_message_timestamp=user_data.get("last_message_timestamp"),
                    last_message_sender_id=user_data.get("last_message_sender_id"),
                    last_message_sender_username=user_data.get(
                        "last_message_sender_username", "Unknown"
                    ),
                    last_message_sender_full_name=user_data.get(
                        "last_message_sender_full_name", "Unknown"
                    ),
                    unread_count=user_data.get("unread_count", 0),
                    status=user_data.get("status", "active"),
                    blocked_by=user_data.get("blocked_by"),
                    blocked_at=user_data.get("blocked_at"),
                    is_dm_chat_open=user_data.get("is_dm_chat_open", True),
                )
                connected_users.append(connected_user)

            # Apply pagination
            total_count = len(connected_users)
            start_idx = (request.page - 1) * request.page_size
            end_idx = start_idx + request.page_size
            paginated_users = connected_users[start_idx:end_idx]

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            # Create response message
            if request.search and request.search.strip():
                message = f"Found {total_count} connected DM users matching '{request.search.strip()}'"
            else:
                message = f"Found {total_count} connected DM users"

            response = GetConnectedDMUsersResponse(
                success=True,
                connected_users=paginated_users,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                message=message,
            )

            print(
                f"⏱️ [CONNECTED DM USERS] Final processing: {(time.time() - step_start)*1000:.2f}ms"
            )

            total_time = (time.time() - start_time) * 1000
            print(f"🚀 [CONNECTED DM USERS] TOTAL TIME: {total_time:.2f}ms")
            print(
                f"📊 [CONNECTED DM USERS] Results: {len(paginated_users)} users returned"
            )

            logger.info(
                f"Successfully retrieved {len(paginated_users)} connected DM users (page {request.page}/{total_pages})"
            )
            return True, response, None

        except Exception as e:
            logger.error(f"Error getting connected DM users: {e}")
            return False, None, f"Failed to get connected DM users: {str(e)}"

    async def send_dm_thread_message(
        self, request: SendDMThreadMessageRequest, current_user: dict
    ) -> Tuple[bool, Optional[SendDMThreadMessageResponse], Optional[str]]:
        """Send a DM thread message (reply to a parent DM message)"""
        try:
            sender_id = current_user["user_id"]

            # Check if users are the same
            if sender_id == request.receiver_id:
                return False, None, "Cannot send DM to yourself"

            # Get club information by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"

            # Check if sender has access to the club
            sender_has_access, _ = await check_club_access(sender_id, request.club_id)

            # Check if receiver has access to the club
            receiver_has_access, _ = await check_club_access(
                request.receiver_id, request.club_id
            )

            # Both users must be club members to DM
            if not sender_has_access:
                return False, None, "You must be a member of this club to send DMs"

            if not receiver_has_access:
                return (
                    False,
                    None,
                    "Receiver must be a member of this club to receive DMs",
                )

            # Check if users can DM each other (have accepted request and not blocked)
            can_dm, error_message = await self.can_users_dm(
                sender_id, request.receiver_id, request.club_id
            )
            if not can_dm:
                return False, None, error_message

            # Verify the parent DM message exists and belongs to the conversation
            parent_message = await self.dm_messages_collection.find_one(
                {
                    "dm_message_id": request.parent_dm_message_id,
                    "club_id": str(club["_id"]),
                    "$or": [
                        {"sender_id": sender_id, "receiver_id": request.receiver_id},
                        {"sender_id": request.receiver_id, "receiver_id": sender_id},
                    ],
                }
            )

            if not parent_message:
                return False, None, "Parent DM message not found or access denied"

            # Get receiver details
            receiver = await self.users_collection.find_one(
                {"_id": ObjectId(request.receiver_id)}
            )
            if not receiver:
                return False, None, "Receiver user not found"

            # Create DM thread message
            dm_message_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            # Create message content
            message_content = MessageContent(text=request.content, mentions=[])

            dm_message_data = {
                "dm_message_id": dm_message_id,
                "sender_id": sender_id,
                "sender_username": current_user.get("username", "Unknown"),
                "sender_full_name": current_user.get("full_name", "Unknown"),
                "sender_avatar": current_user.get("avatar_url"),
                "receiver_id": request.receiver_id,
                "receiver_username": receiver.get("username", "Unknown"),
                "receiver_full_name": receiver.get("full_name", "Unknown"),
                "receiver_avatar": receiver.get("avatar_url"),
                "club_id": str(club["_id"]),
                "club_name": club.get("name", "Unknown Club"),
                "content": message_content.dict(),
                "message_type": request.message_type,
                "reactions": [],
                "reply_to_dm_message_id": request.parent_dm_message_id,  # This makes it a thread reply
                "edited_at": None,
                "pinned": False,
                "pinned_by": None,
                "pinned_by_username": None,
                "pinned_at": None,
                "pin_reason": None,
                "created_at": now,
                "updated_at": now,
            }

            await self.dm_messages_collection.insert_one(dm_message_data)

            # Get thread count for the parent message
            thread_count = await self.dm_messages_collection.count_documents(
                {
                    "reply_to_dm_message_id": request.parent_dm_message_id,
                    "club_id": str(club["_id"]),
                }
            )

            # Create response
            dm_message = DMMessage(**dm_message_data)
            response = SendDMThreadMessageResponse(
                success=True,
                dm_message_id=dm_message_id,
                dm_message=dm_message,
                parent_dm_message_id=request.parent_dm_message_id,
                thread_count=thread_count,
                message="DM thread message sent successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error sending DM thread message: {e}")
            return False, None, f"Failed to send DM thread message: {str(e)}"

    async def get_dm_thread_count(self, parent_dm_message_id: str, club_id: str) -> int:
        """Get count of thread messages for a parent DM message"""
        query = {
            "reply_to_dm_message_id": parent_dm_message_id,
            "club_id": club_id,
        }

        count = await self.dm_messages_collection.count_documents(query)
        return count

    async def get_dm_thread_info(self, parent_dm_message_id: str, club_id: str) -> dict:
        """Get thread count and last 3 reply users info for a parent DM message"""
        query = {
            "reply_to_dm_message_id": parent_dm_message_id,
            "club_id": club_id,
        }

        # Get thread count
        thread_count = await self.dm_messages_collection.count_documents(query)

        # Get last 3 thread replies with user info
        last_replies_cursor = (
            self.dm_messages_collection.find(
                query,
                {
                    "sender_id": 1,
                    "sender_username": 1,
                    "sender_full_name": 1,
                    "sender_avatar": 1,
                    "created_at": 1,
                },
            )
            .sort("created_at", -1)
            .limit(3)
        )

        last_replies = await last_replies_cursor.to_list(3)

        # Format reply users info
        reply_users = []
        for reply in last_replies:
            reply_users.append(
                {
                    "user_id": reply.get("sender_id"),
                    "username": reply.get("sender_username"),
                    "full_name": reply.get("sender_full_name"),
                    "avatar_url": reply.get("sender_avatar"),
                }
            )

        return {"thread_count": thread_count, "last_reply_users": reply_users}

    async def get_bulk_dm_thread_info(
        self, parent_dm_message_ids: List[str], club_id: str
    ) -> Dict[str, dict]:
        """
        Get thread info for multiple parent DM messages in bulk - OPTIMIZED VERSION
        This replaces N individual calls to get_dm_thread_info with a single optimized query
        """
        bulk_start_time = time.time()

        try:
            if not parent_dm_message_ids:
                return {}

            print(
                f"⏱️ [BULK DM THREAD INFO] Starting for {len(parent_dm_message_ids)} messages"
            )

            # Get all thread replies for all parent messages in one query
            thread_replies_query = {
                "reply_to_dm_message_id": {"$in": parent_dm_message_ids},
                "club_id": club_id,
            }

            # Use optimized aggregation pipeline for better performance
            pipeline = [
                {"$match": thread_replies_query},
                # Sort by created_at first for better performance
                {"$sort": {"created_at": -1}},
                {
                    "$group": {
                        "_id": "$reply_to_dm_message_id",
                        "count": {"$sum": 1},
                        "replies": {
                            "$push": {
                                "sender_id": "$sender_id",
                                "sender_username": "$sender_username",
                                "sender_full_name": "$sender_full_name",
                                "sender_avatar": "$sender_avatar",
                                "created_at": "$created_at",
                            }
                        },
                    }
                },
                {
                    "$project": {
                        "_id": 1,
                        "count": 1,
                        # Take first 3 since they're already sorted
                        "last_3_replies": {"$slice": ["$replies", 3]},
                    }
                },
            ]

            # Execute aggregation
            thread_results = await self.dm_messages_collection.aggregate(
                pipeline
            ).to_list(length=None)

            print(
                f"⏱️ [BULK DM THREAD INFO] Aggregation completed in {(time.time() - bulk_start_time)*1000:.2f}ms"
            )

            # Process results into the expected format
            thread_info_data = {}

            for result in thread_results:
                parent_message_id = result["_id"]
                thread_count = result["count"]
                last_replies = result["last_3_replies"]

                # Format reply users info (same format as individual method)
                reply_users = []
                for reply in last_replies:
                    reply_users.append(
                        {
                            "user_id": reply.get("sender_id"),
                            "username": reply.get("sender_username"),
                            "full_name": reply.get("sender_full_name"),
                            "avatar_url": reply.get("sender_avatar"),
                        }
                    )

                thread_info_data[parent_message_id] = {
                    "thread_count": thread_count,
                    "last_reply_users": reply_users,
                }

            # Add empty entries for parent messages that have no replies
            for parent_message_id in parent_dm_message_ids:
                if parent_message_id not in thread_info_data:
                    thread_info_data[parent_message_id] = {
                        "thread_count": 0,
                        "last_reply_users": [],
                    }

            total_time = (time.time() - bulk_start_time) * 1000
            print(f"⏱️ [BULK DM THREAD INFO] Completed in {total_time:.2f}ms")

            return thread_info_data

        except Exception as e:
            total_time = (time.time() - bulk_start_time) * 1000
            print(f"⏱️ [BULK DM THREAD INFO] Error after {total_time:.2f}ms: {e}")
            logger.error(f"Error getting bulk DM thread info: {e}")

            # Return empty data for all parent messages on error
            return {
                parent_message_id: {"thread_count": 0, "last_reply_users": []}
                for parent_message_id in parent_dm_message_ids
            }

    async def get_dm_thread_messages(
        self, request: GetDMThreadMessagesRequest, current_user: dict
    ) -> Tuple[bool, Optional[GetDMThreadMessagesResponse], Optional[str]]:
        """Get DM thread messages for a parent DM message"""
        try:
            sender_id = current_user["user_id"]

            # Check if users are the same
            if sender_id == request.receiver_id:
                return False, None, "Cannot get DM messages with yourself"

            # Get club information by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"

            # Check if sender has access to the club
            sender_has_access, _ = await check_club_access(sender_id, request.club_id)

            # Check if receiver has access to the club
            receiver_has_access, _ = await check_club_access(
                request.receiver_id, request.club_id
            )

            # Both users must be club members to access DMs
            if not sender_has_access:
                return False, None, "You must be a member of this club to access DMs"

            if not receiver_has_access:
                return (
                    False,
                    None,
                    "Receiver must be a member of this club to access DMs",
                )

            # Verify the parent DM message exists and belongs to the conversation
            parent_message = await self.dm_messages_collection.find_one(
                {
                    "dm_message_id": request.parent_dm_message_id,
                    "club_id": str(club["_id"]),
                    "$or": [
                        {"sender_id": sender_id, "receiver_id": request.receiver_id},
                        {"sender_id": request.receiver_id, "receiver_id": sender_id},
                    ],
                }
            )

            if not parent_message:
                return False, None, "Parent DM message not found or access denied"

            # Get thread messages (replies to the parent message)
            skip = (request.page - 1) * request.page_size

            query = {
                "reply_to_dm_message_id": request.parent_dm_message_id,
                "club_id": str(club["_id"]),
            }

            # Get thread messages with pagination
            cursor = (
                self.dm_messages_collection.find(query)
                .sort("created_at", 1)
                .skip(skip)
                .limit(request.page_size + 1)
            )
            thread_docs = await cursor.to_list(length=request.page_size + 1)

            # Check if there are more messages
            has_more = len(thread_docs) > request.page_size
            if has_more:
                thread_docs = thread_docs[: request.page_size]

            # Convert to DMMessage objects
            thread_messages = []
            for doc in thread_docs:
                # Convert ObjectId to string for club_id
                if "club_id" in doc and isinstance(doc["club_id"], ObjectId):
                    doc["club_id"] = str(doc["club_id"])
                dm_message = await self.document_to_dm_message(doc)
                if dm_message:
                    thread_messages.append(dm_message)

            # Get total count of thread messages
            total_count = await self.dm_messages_collection.count_documents(query)

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            response = GetDMThreadMessagesResponse(
                success=True,
                parent_dm_message_id=request.parent_dm_message_id,
                thread_messages=thread_messages,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                message="DM thread messages retrieved successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting DM thread messages: {e}")
            return False, None, f"Failed to get DM thread messages: {str(e)}"

    async def get_dm_messages_with_thread_counts(
        self, request: GetDMMessagesRequest, current_user: dict
    ) -> Tuple[bool, Optional[dict], Optional[str]]:
        """Get DM messages with thread counts and reply user information (excluding thread messages)"""
        try:
            user_id = current_user["user_id"]

            # Check club access
            has_access, _ = await check_club_access(user_id, request.club_id)
            if not has_access:
                return False, None, "Access denied to club"

            # Get club information by name_based_id
            club = await self.clubs_collection.find_one(
                {"name_based_id": request.club_id}
            )
            if not club:
                return False, None, "Club not found"

            # Check if there's a DM request (accepted or blocked)
            dm_request = await self.dm_requests_collection.find_one(
                {
                    "$or": [
                        {
                            "sender_id": user_id,
                            "receiver_id": request.user_id,
                            "club_id": str(club["_id"]),
                        },
                        {
                            "sender_id": request.user_id,
                            "receiver_id": user_id,
                            "club_id": str(club["_id"]),
                        },
                    ],
                    "status": {
                        "$in": [DMRequestStatus.ACCEPTED, DMRequestStatus.BLOCKED]
                    },
                }
            )
            if not dm_request:
                return False, None, "No DM request found"

            # Build query - exclude thread messages (replies) from main DM message list
            query = {
                "$or": [
                    {
                        "sender_id": user_id,
                        "receiver_id": request.user_id,
                        "club_id": str(club["_id"]),
                    },
                    {
                        "sender_id": request.user_id,
                        "receiver_id": user_id,
                        "club_id": str(club["_id"]),
                    },
                ],
                "reply_to_dm_message_id": None,  # Only show parent messages, not thread replies
            }

            # Add search filter if provided
            if request.search and request.search.strip():
                search_term = request.search.strip()
                # Escape special regex characters
                escaped_search_term = re.escape(search_term)
                query["content.text"] = {"$regex": escaped_search_term, "$options": "i"}

            # Calculate pagination - fetch latest first from DB
            skip = (request.page - 1) * request.page_size

            # Get messages in descending order (latest first from DB)
            messages_cursor = (
                self.dm_messages_collection.find(query)
                .sort("created_at", -1)
                .skip(skip)
                .limit(request.page_size)
            )
            messages_docs = await messages_cursor.to_list(length=request.page_size)

            # Convert to DMMessage objects first
            messages = []
            for doc in messages_docs:
                dm_message = await self.document_to_dm_message(doc)
                if dm_message:
                    messages.append(dm_message)

            # Get all parent message IDs that need thread info
            parent_message_ids = []
            for message in messages:
                if (
                    not message.reply_to_dm_message_id
                ):  # Only parent messages need thread info
                    parent_message_ids.append(message.dm_message_id)

            print(
                f"⏱️ [DM SERVICE] Found {len(parent_message_ids)} parent messages needing thread info"
            )

            # Use bulk thread info method to get all thread data in one query
            bulk_thread_start = time.time()
            bulk_thread_info = await self.get_bulk_dm_thread_info(
                parent_message_ids, str(club["_id"])
            )
            print(
                f"⏱️ [DM SERVICE] Bulk thread info fetched in: {(time.time() - bulk_thread_start)*1000:.2f}ms"
            )

            # Build response with thread info
            messages_with_thread_counts = []
            for message in messages:
                message_dict = message.dict()

                # Add thread info if this is a parent message
                if (
                    not message.reply_to_dm_message_id
                    and message.dm_message_id in bulk_thread_info
                ):
                    thread_info = bulk_thread_info[message.dm_message_id]
                    message_dict["thread_count"] = thread_info["thread_count"]
                    message_dict["last_reply_users"] = thread_info["last_reply_users"]
                else:
                    # For reply messages or messages without thread info
                    message_dict["thread_count"] = 0
                    message_dict["last_reply_users"] = []

                messages_with_thread_counts.append(message_dict)

            # Reverse messages to show oldest first (since we fetched latest first from DB)
            messages_with_thread_counts.reverse()

            # Get total count
            total_count = await self.dm_messages_collection.count_documents(query)

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            response = {
                "success": True,
                "messages": messages_with_thread_counts,
                "total_count": total_count,
                "page": request.page,
                "page_size": request.page_size,
                "total_pages": total_pages,
                "has_next": has_next,
                "has_previous": has_previous,
                "message": "DM messages with thread counts retrieved successfully",
            }

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting DM messages with thread counts: {e}")
            return (
                False,
                None,
                f"Failed to get DM messages with thread counts: {str(e)}",
            )

    async def document_to_dm_message(self, doc: dict) -> Optional[DMMessage]:
        """Convert MongoDB document to DMMessage object with proper timezone handling"""

        if not doc:
            return None

        try:
            # Parse content
            content_data = doc.get("content", {})
            mentions_data = content_data.get("mentions", [])

            mentions = []
            for mention_data in mentions_data:
                mentions.append(UserMention(**mention_data))

            content = MessageContent(
                text=content_data.get("text", ""), mentions=mentions
            )

            # Parse reactions (will be implemented in reaction service)
            reactions = []  # TODO: Parse reactions

            # Handle datetime fields - ensure they are timezone-aware UTC
            created_at = doc["created_at"]
            updated_at = doc["updated_at"]
            edited_at = doc.get("edited_at")
            pinned_at = doc.get("pinned_at")

            # If datetime is naive (no timezone), assume it's UTC
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if updated_at and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if edited_at and edited_at.tzinfo is None:
                edited_at = edited_at.replace(tzinfo=timezone.utc)
            if pinned_at and pinned_at.tzinfo is None:
                pinned_at = pinned_at.replace(tzinfo=timezone.utc)

            return DMMessage(
                dm_message_id=doc["dm_message_id"],
                sender_id=doc["sender_id"],
                sender_username=doc["sender_username"],
                sender_full_name=doc["sender_full_name"],
                sender_avatar=doc.get("sender_avatar"),
                receiver_id=doc["receiver_id"],
                receiver_username=doc["receiver_username"],
                receiver_full_name=doc["receiver_full_name"],
                receiver_avatar=doc.get("receiver_avatar"),
                club_id=doc["club_id"],
                club_name=doc["club_name"],
                content=content,
                message_type=MessageType(doc["message_type"]),
                reactions=reactions,
                reply_to_dm_message_id=doc.get("reply_to_dm_message_id"),
                edited_at=edited_at,
                pinned=doc.get("pinned", False),
                pinned_by=doc.get("pinned_by"),
                pinned_by_username=doc.get("pinned_by_username"),
                pinned_at=pinned_at,
                pin_reason=doc.get("pin_reason"),
                created_at=created_at,
                updated_at=updated_at,
            )

        except Exception as e:
            logger.error(f"Error converting document to DMMessage: {e}")
            return None


# Global DM service instance
dm_service = DMService()
