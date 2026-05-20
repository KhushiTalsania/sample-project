import logging
from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    Query,
)
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Optional
from datetime import datetime, timezone
from bson import ObjectId

from .models import (
    SendMessageRequest,
    EditMessageRequest,
    PinMessageRequest,
    MuteUserRequest,
    MuteUserResponse,
    CreateThreadRequest,
    CreateThreadResponse,
    SendThreadReplyRequest,
    EditDMMessageRequest,
    EditDMMessageResponse,
    DeleteDMMessageRequest,
    DeleteDMMessageResponse,
    # DM Request Models
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
    # DM Message Models
    SendDMMessageRequest,
    SendDMMessageResponse,
    GetDMMessagesRequest,
    GetDMConversationsRequest,
    GetDMConversationsResponse,
    # DM Thread Message Models
    SendDMThreadMessageRequest,
    SendDMThreadMessageResponse,
    GetDMThreadMessagesRequest,
    GetDMThreadMessagesResponse,
    # DM Pin/Unpin Models
    PinDMMessageRequest,
    # Connected DM Users Models
    GetConnectedDMUsersRequest,
    GetConnectedDMUsersResponse,
    # User Status Models
    UserClubStatusResponse,
    ClubMemberStatusResponse,
    # Paginated Role-based Models
    ClubCaptainsResponse,
    ClubModeratorsResponse,
    ClubMembersResponse,
)
from .auth import (
    get_current_user,
    require_chat_access,
    require_moderator_access,
    require_unmuted_access,
    check_locker_room_access,
    UserRole,
    get_chat_user,
    check_club_access,
)
from .message_service import message_service
from .moderation_service import moderation_service
from .thread_service import thread_service

# Import Socket.IO manager for real-time broadcasting
from core.socket import socket_manager
from .db import get_messages_collection, get_user_collection
from .dm_service import dm_service
from .club_detail_service import club_detail_service

router = APIRouter(tags=["Chat"])

# Setup logging
logger = logging.getLogger(__name__)


def create_response(status_code: int, status: str, message: str, data=None):
    """Create a common response body with status code"""
    logger.debug(
        f"Creating API response - Status: {status_code}, Type: {status}, Message: {message}"
    )

    # Use jsonable_encoder to handle datetime and other non-JSON serializable objects
    encoded_data = jsonable_encoder(data) if data is not None else None

    return JSONResponse(
        status_code=status_code,
        content={"status": status, "message": message, "data": encoded_data},
    )


# Locker Room Access
@router.get("/clubs/{club_id}/access")
async def check_club_access(
    club_id: str, current_user: dict = Depends(get_current_user)
):
    """Check if user has access to club locker room"""
    try:
        # Get access response (now returns JSONResponse directly)
        access_response = await check_locker_room_access(club_id, current_user)

        # If access_response is already a JSONResponse, return it directly
        if hasattr(access_response, "body"):
            # Extract the JSON content from the response
            import json

            response_content = json.loads(access_response.body.decode())
            access_data = response_content.get("data", {})

            # If user has access, track the visit
            if access_data.get("has_access", False):
                try:
                    from .db import get_user_access_collection

                    user_access_collection = get_user_access_collection()
                    now = datetime.utcnow()

                    await user_access_collection.update_one(
                        {"user_id": current_user["user_id"], "club_id": club_id},
                        {"$set": {"last_visited": now, "updated_at": now}},
                        upsert=True,
                    )
                    logger.info(
                        f"Tracked visit for user {current_user['user_id']} in club {club_id}"
                    )
                except Exception as e:
                    logger.error(f"Error tracking visit: {e}")

            return access_response
        else:
            # Fallback for old format (should not happen with updated auth.py)
            logger.warning("Unexpected response format from check_locker_room_access")
            return create_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Unexpected response format",
                data=None,
            )

    except HTTPException as e:
        logger.warning(f"HTTP error checking club access: {e.detail}")
        return create_response(e.status_code, "error", e.detail, None)
    except Exception as e:
        logger.error(f"Error checking club access: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None,
        )


# Message Management
@router.get("/clubs/{club_id}/messages/latest")
async def get_latest_messages(club_id: str, chat_user=Depends(require_chat_access)):
    """Get the latest 5 messages for a club based on created_at timestamp"""
    try:
        # Get latest 5 messages directly from database, sorted by created_at descending
        messages_collection = get_messages_collection()

        # Query for latest messages, excluding thread replies and deleted messages
        latest_messages_docs = (
            await messages_collection.find(
                {
                    "club_id": club_id,
                    "is_deleted": False,
                    "reply_to_message_id": None,  # Only show parent messages, not thread replies
                }
            )
            .sort("created_at", -1)
            .limit(5)
            .to_list(5)
        )

        # Batch fetch user info (username, full_name, avatar_url) from users table
        from bson import ObjectId

        sender_ids = set()
        for doc in latest_messages_docs:
            if doc.get("sender_id"):
                sender_ids.add(doc.get("sender_id"))

        user_info_map = {}
        if sender_ids:
            users_collection = get_user_collection()
            users = await users_collection.find(
                {"_id": {"$in": [ObjectId(sid) for sid in sender_ids if sid]}},
                {"_id": 1, "username": 1, "full_name": 1, "avatar_url": 1},
            ).to_list(None)
            user_info_map = {
                str(user["_id"]): {
                    "username": user.get("username", "Unknown"),
                    "full_name": user.get("full_name", "Unknown User"),
                    "avatar_url": user.get("avatar_url"),
                }
                for user in users
            }

        # Convert documents to ChatMessage objects with updated user info
        messages = []
        for doc in latest_messages_docs:
            # Update sender info from users table
            sender_id = doc.get("sender_id")
            if sender_id and sender_id in user_info_map:
                user_info = user_info_map[sender_id]
                doc["sender_username"] = user_info["username"]
                doc["sender_full_name"] = user_info["full_name"]
                doc["sender_avatar"] = user_info["avatar_url"]

            chat_message = await message_service.document_to_chat_message(doc)
            if chat_message:
                messages.append(chat_message)

        # Sort messages back to chronological order (oldest first) for display
        messages.sort(key=lambda x: x.created_at)

        response_data = {
            "club_id": club_id,
            "messages": [message.dict() for message in messages],
            "total_returned": len(messages),
            "has_more": False,  # This endpoint only returns latest 5
        }

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message=f"Retrieved {len(messages)} latest messages",
            data=response_data,
        )

    except HTTPException as e:
        # Handle HTTP exceptions (like access denied, etc.)
        logger.warning(
            f"HTTP error getting latest messages for club {club_id}: {e.detail}"
        )
        return create_response(
            status_code=e.status_code, status="error", message=e.detail, data=None
        )
    except Exception as e:
        logger.error(f"Error getting latest messages for club {club_id}: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to retrieve latest messages: {str(e)}",
            data=None,
        )


@router.post("/clubs/{club_id}/messages")
async def send_message(
    club_id: str,
    message_request: SendMessageRequest,
    chat_user=Depends(require_unmuted_access),
):
    """Send a message to club chat"""
    try:
        # Track the user's visit to this club when they send a message
        try:
            from .db import get_user_access_collection

            user_access_collection = get_user_access_collection()
            now = datetime.now(timezone.utc)

            await user_access_collection.update_one(
                {"user_id": chat_user.user_id, "club_id": club_id},
                {
                    "$set": {
                        "last_visited": now,
                        "updated_at": now,
                        "user_id": chat_user.user_id,
                        "club_id": club_id,
                    }
                },
                upsert=True,
            )
            print(
                f"🔍 Tracked message activity for user {chat_user.user_id} in club {club_id} at {now}"
            )
        except Exception as e:
            print(f"Error tracking message activity: {e}")

        # Ensure club_id matches
        message_request.club_id = club_id

        # Create message
        message = await message_service.create_message(
            sender=chat_user,
            club_id=club_id,
            content=message_request.content,
            message_type=message_request.message_type,
            reply_to_message_id=message_request.reply_to_message_id,
        )

        # Broadcast new message to all connected users in real-time
        try:
            # Create message data for broadcasting
            message_data = {
                "message_id": message.message_id,
                "club_id": message.club_id,
                "sender_id": message.sender_id,
                "sender_username": message.sender_username,
                "sender_full_name": message.sender_full_name,
                "sender_avatar": message.sender_avatar,
                "content": (
                    message.content.dict()
                    if hasattr(message.content, "dict")
                    else message.content
                ),
                "message_type": message.message_type,
                "reply_to_message_id": message.reply_to_message_id,
                "created_at": (
                    message.created_at.isoformat()
                    if hasattr(message.created_at, "isoformat")
                    else str(message.created_at)
                ),
                "updated_at": (
                    message.updated_at.isoformat()
                    if hasattr(message.updated_at, "isoformat")
                    else str(message.updated_at)
                ),
            }
            print(f"message_data: {message_data}")
            # Emit to frontend
            await socket_manager.sio.emit(
                        "live_score_update",
                        {
                            "club_id": "club_name_based_id",
                            "match_id": "match_id",
                            "live_scores": "live_scores",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        room="club_name_based_id",
                    )
            print(f"message_data: {message_data} emitted")
            # Broadcast to all connected users
            await socket_manager.sio.emit(
                "club_new_message",
                {
                    "club_id": club_id,
                    "message": message_data,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )


            print(
                f"📢 Broadcasted new message to all connected users: {message.message_id}"
            )

        except Exception as e:
            print(f"⚠️ Error broadcasting message: {e}")
            # Don't fail the API call if broadcasting fails

        return create_response(
            201,
            "success",
            "Message sent successfully",
            {"message": message.dict() if hasattr(message, "dict") else message},
        )

    except HTTPException as e:
        # Handle HTTP exceptions (like muted users, access denied, etc.)
        logger.warning(f"HTTP error sending message: {e.detail}")
        return create_response(e.status_code, "error", e.detail, None)
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return create_response(500, "error", f"Failed to send message: {str(e)}", None)


@router.get("/clubs/{club_id}/messages")
async def get_message_history(
    club_id: str,
    q: Optional[str] = Query(None, description="Search query (optional)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    before_message_id: Optional[str] = Query(None),
    include_thread_counts: bool = Query(
        False,
        description="Include thread info (count + last 3 reply users) for each message",
    ),
    chat_user=Depends(require_chat_access),
):
    """Get message history for club chat with optional search and thread info (count + last 3 reply users)"""
    import time

    print(f"🚀 [ROUTE] Starting get_message_history for club: {club_id}")
    route_start_time = time.time()

    try:
        # Step 1: Message history retrieval
        step_start = time.time()
        if q and q.strip():
            print(f"⏱️ [ROUTE] Using search functionality")
            history = await message_service.search_messages(
                club_id=club_id, search_query=q.strip(), page=page, page_size=page_size
            )
        else:
            print(f"⏱️ [ROUTE] Using regular message history")
            history = await message_service.get_message_history(
                club_id=club_id,
                page=page,
                page_size=page_size,
                before_message_id=before_message_id,
            )
        print(
            f"⏱️ [ROUTE] Message history retrieval: {(time.time() - step_start)*1000:.2f}ms"
        )

        # Step 2: Thread info processing (if requested) - OPTIMIZED BULK VERSION
        if include_thread_counts:
            step_start = time.time()
            print(
                f"⏱️ [ROUTE] Starting OPTIMIZED bulk thread processing for {len(history.messages)} messages"
            )

            # Clear thread cache for fresh data
            message_service._thread_cache.clear()

            # Get all parent message IDs that need thread info
            parent_message_ids = []
            for message in history.messages:
                if (
                    not message.reply_to_message_id
                ):  # Only parent messages need thread info
                    parent_message_ids.append(message.message_id)

            print(
                f"⏱️ [ROUTE] Found {len(parent_message_ids)} parent messages needing thread info"
            )

            # Use bulk thread info method to get all thread data in one query
            bulk_thread_start = time.time()
            bulk_thread_info = await message_service.get_bulk_thread_info(
                parent_message_ids, club_id
            )
            print(
                f"⏱️ [ROUTE] Bulk thread info fetched in: {(time.time() - bulk_thread_start)*1000:.2f}ms"
            )

            # Build response with thread info
            messages_with_thread_counts = []
            for message in history.messages:
                message_dict = message.dict()

                # Add thread info if this is a parent message
                if (
                    not message.reply_to_message_id
                    and message.message_id in bulk_thread_info
                ):
                    thread_info = bulk_thread_info[message.message_id]
                    message_dict["thread_count"] = thread_info["thread_count"]
                    message_dict["last_reply_users"] = thread_info["last_reply_users"]
                else:
                    # For reply messages or messages without thread info
                    message_dict["thread_count"] = 0
                    message_dict["last_reply_users"] = []

                messages_with_thread_counts.append(message_dict)

            print(
                f"⏱️ [ROUTE] OPTIMIZED thread processing completed: {(time.time() - step_start)*1000:.2f}ms"
            )

            response_data = {
                "club_id": club_id,
                "page": page,
                "page_size": page_size,
                "messages": messages_with_thread_counts,
                "total_count": history.total_count,
                "has_more": history.has_more,
                "next_cursor": history.next_cursor,
            }
        else:
            response_data = {
                "club_id": club_id,
                "page": page,
                "page_size": page_size,
                "messages": history.messages,
                "total_count": history.total_count,
                "has_more": history.has_more,
                "next_cursor": history.next_cursor,
            }

        # Step 3: Response building
        step_start = time.time()
        # Include search query in response if provided
        if q and q.strip():
            response_data["search_query"] = q.strip()
        print(f"⏱️ [ROUTE] Response building: {(time.time() - step_start)*1000:.2f}ms")

        total_route_time = (time.time() - route_start_time) * 1000
        print(f"🚀 [ROUTE] TOTAL ROUTE TIME: {total_route_time:.2f}ms")

        return create_response(
            200, "success", "Message history retrieved successfully", response_data
        )

    except HTTPException as e:
        # Handle HTTP exceptions (like access denied, etc.)
        logger.warning(f"HTTP error getting message history: {e.detail}")
        return create_response(e.status_code, "error", e.detail, None)
    except Exception as e:
        logger.error(f"Error getting message history: {e}")
        return create_response(
            500, "error", f"Failed to retrieve message history: {str(e)}", None
        )


@router.put("/messages/{message_id}")
async def edit_message(
    message_id: str,
    edit_request: EditMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    """Edit a message - only the sender can edit their own message"""

    # Get message to determine club
    message = await message_service.get_message_by_id(message_id)
    if not message:
        return create_response(404, "error", "Message not found")

    # Check if the current user is the sender of the message
    if message.sender_id != current_user["user_id"]:
        return create_response(403, "error", "You can only edit your own messages")

    # Check chat access
    chat_user = await get_chat_user(current_user, message.club_id)

    # Edit message
    updated_message = await message_service.edit_message(
        message_id=message_id, new_content=edit_request.new_content, editor=chat_user
    )

    if not updated_message:
        return create_response(403, "error", "Cannot edit this message")

    # Broadcast edit event to all connected users in real-time
    try:
        # Create message data for broadcasting
        message_data = {
            "message_id": updated_message.message_id,
            "club_id": updated_message.club_id,
            "sender_id": updated_message.sender_id,
            "sender_username": updated_message.sender_username,
            "sender_full_name": updated_message.sender_full_name,
            "sender_avatar": updated_message.sender_avatar,
            "content": (
                updated_message.content.dict()
                if hasattr(updated_message.content, "dict")
                else updated_message.content
            ),
            "message_type": updated_message.message_type,
            "reply_to_message_id": updated_message.reply_to_message_id,
            "created_at": (
                updated_message.created_at.isoformat()
                if hasattr(updated_message.created_at, "isoformat")
                else str(updated_message.created_at)
            ),
            "updated_at": (
                updated_message.updated_at.isoformat()
                if hasattr(updated_message.updated_at, "isoformat")
                else str(updated_message.updated_at)
            ),
            "edited_at": (
                updated_message.edited_at.isoformat()
                if hasattr(updated_message.edited_at, "isoformat")
                else str(updated_message.edited_at)
            ),
        }

        # Broadcast to all connected users
        await socket_manager.sio.emit(
            "club_message_edited",
            {
                "club_id": message.club_id,
                "message": message_data,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        print(
            f"📢 Broadcasted message edit to all connected users: {updated_message.message_id}"
        )

    except Exception as e:
        print(f"⚠️ Error broadcasting message edit: {e}")
        # Don't fail the API call if broadcasting fails

    return create_response(
        200, "success", "Message edited successfully", {"message": updated_message}
    )


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: str, current_user: dict = Depends(get_current_user)
):
    """Delete a message with hierarchical permissions"""

    # Get message to determine club
    message = await message_service.get_message_by_id(message_id)
    if not message:
        return create_response(404, "error", "Message not found")

    # Check chat access
    chat_user = await get_chat_user(current_user, message.club_id)

    # Check if user can delete this message based on hierarchical permissions
    can_delete = False
    error_message = ""

    # If user is the sender, they can always delete their own message
    if message.sender_id == current_user["user_id"]:
        can_delete = True
    else:
        # Check hierarchical permissions
        if chat_user.role == UserRole.CAPTAIN:
            # Captain can delete any message
            can_delete = True
        elif chat_user.role == UserRole.MODERATOR:
            # Moderator can delete member messages but not captain messages
            if message.sender_role == UserRole.MEMBER:
                can_delete = True
            else:
                error_message = "Moderators cannot delete captain or moderator messages"
        else:
            # Members can only delete their own messages
            error_message = "You can only delete your own messages"

    if not can_delete:
        return create_response(
            403,
            "error",
            error_message or "You don't have permission to delete this message",
        )

    # Delete message
    success = await message_service.delete_message(message_id, chat_user)

    if not success:
        return create_response(403, "error", "Cannot delete this message")

    # Broadcast delete event to all connected users in real-time
    try:
        # Create message data for broadcasting
        message_data = {
            "message_id": message_id,
            "club_id": message.club_id,
            "deleted_by": chat_user.user_id,
            "deleted_by_username": chat_user.username,
            "deleted_by_full_name": chat_user.full_name,
            "deleted_at": datetime.utcnow().isoformat(),
        }

        # Broadcast to all connected users
        await socket_manager.sio.emit(
            "club_message_deleted",
            {
                "club_id": message.club_id,
                "message": message_data,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        print(f"📢 Broadcasted message deletion to all connected users: {message_id}")

    except Exception as e:
        print(f"⚠️ Error broadcasting message deletion: {e}")
        # Don't fail the API call if broadcasting fails

    return create_response(200, "success", "Message deleted successfully")


# Pinned Messages
@router.get("/clubs/{club_id}/pinned-messages")
async def get_pinned_messages(club_id: str, chat_user=Depends(require_chat_access)):
    """Get pinned messages for club"""

    pinned_messages = await moderation_service.get_pinned_messages(club_id)
    return create_response(
        200,
        "success",
        "Pinned messages retrieved successfully",
        {
            "club_id": club_id,
            "pinned_messages": pinned_messages,
            "count": len(pinned_messages),
        },
    )


@router.post("/messages/{message_id}/pin")
async def pin_message(
    message_id: str,
    pin_request: PinMessageRequest,
    club_id: str = Query(..., description="Club ID"),
    current_user: dict = Depends(get_current_user),
):
    """Pin a message (moderator/captain only)"""

    # Check if user has moderator access
    chat_user = await get_chat_user(current_user, club_id)
    if chat_user.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
        return create_response(403, "error", "Moderator or captain access required")

    updated_message = await moderation_service.pin_message(
        message_id=message_id, moderator=chat_user, reason=pin_request.reason
    )
    print(f"🔍 Updated message: {updated_message}")

    if not updated_message:
        return create_response(404, "error", "Message not found or cannot pin")

    # Broadcast pin event to all connected users in real-time
    try:
        # Create message data for broadcasting
        message_data = {
            "message_id": updated_message.message_id,
            "club_id": updated_message.club_id,
            "sender_id": updated_message.sender_id,
            "sender_username": updated_message.sender_username,
            "sender_full_name": updated_message.sender_full_name,
            "sender_avatar": updated_message.sender_avatar,
            "content": (
                updated_message.content.dict()
                if hasattr(updated_message.content, "dict")
                else updated_message.content
            ),
            "message_type": updated_message.message_type,
            "reply_to_message_id": updated_message.reply_to_message_id,
            "created_at": (
                updated_message.created_at.isoformat()
                if hasattr(updated_message.created_at, "isoformat")
                else str(updated_message.created_at)
            ),
            "updated_at": (
                updated_message.updated_at.isoformat()
                if hasattr(updated_message.updated_at, "isoformat")
                else str(updated_message.updated_at)
            ),
            "pinned_by": chat_user.user_id,
            "pinned_by_username": chat_user.username,
            "pinned_by_full_name": chat_user.full_name,
            "pinned_at": datetime.utcnow().isoformat(),
            "pin_reason": pin_request.reason,
        }

        # Broadcast to all connected users
        await socket_manager.sio.emit(
            "club_message_pinned",
            {
                "club_id": club_id,
                "message": message_data,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        print(
            f"📢 Broadcasted message pin to all connected users: {updated_message.message_id}"
        )

    except Exception as e:
        print(f"⚠️ Error broadcasting message pin: {e}")
        # Don't fail the API call if broadcasting fails

    return create_response(
        200,
        "success",
        "Message pinned successfully",
        {"pinned_message": updated_message},
    )


@router.delete("/messages/{message_id}/pin")
async def unpin_message(
    message_id: str,
    club_id: str = Query(..., description="Club ID"),
    current_user: dict = Depends(get_current_user),
):
    """Unpin a message (moderator/captain only)"""

    # Check if user has moderator access
    chat_user = await get_chat_user(current_user, club_id)
    if chat_user.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
        return create_response(403, "error", "Moderator or captain access required")

    success = await moderation_service.unpin_message(message_id, chat_user)

    if not success:
        return create_response(404, "error", "Message not found or not pinned")

    # Broadcast unpin event to all connected users in real-time
    try:
        # Get the message to include in the broadcast
        message = await message_service.get_message_by_id(message_id)

        # Create message data for broadcasting
        message_data = {
            "message_id": message_id,
            "club_id": club_id,
            "sender_id": message.sender_id if message else None,
            "sender_username": message.sender_username if message else None,
            "sender_full_name": message.sender_full_name if message else None,
            "sender_avatar": message.sender_avatar if message else None,
            "content": (
                message.content.dict()
                if message and hasattr(message.content, "dict")
                else message.content if message else None
            ),
            "message_type": message.message_type if message else None,
            "reply_to_message_id": message.reply_to_message_id if message else None,
            "created_at": (
                message.created_at.isoformat()
                if message and hasattr(message.created_at, "isoformat")
                else str(message.created_at) if message else None
            ),
            "updated_at": (
                message.updated_at.isoformat()
                if message and hasattr(message.updated_at, "isoformat")
                else str(message.updated_at) if message else None
            ),
            "unpinned_by": chat_user.user_id,
            "unpinned_by_username": chat_user.username,
            "unpinned_by_full_name": chat_user.full_name,
            "unpinned_at": datetime.utcnow().isoformat(),
        }

        # Broadcast to all connected users
        await socket_manager.sio.emit(
            "club_message_unpinned",
            {
                "club_id": club_id,
                "message": message_data,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        print(f"📢 Broadcasted message unpin to all connected users: {message_id}")

    except Exception as e:
        print(f"⚠️ Error broadcasting message unpin: {e}")
        # Don't fail the API call if broadcasting fails

    return create_response(200, "success", "Message unpinned successfully")


# User Moderation
@router.post("/clubs/{club_id}/mute-user", response_model=MuteUserResponse)
async def mute_user(
    club_id: str,
    mute_request: MuteUserRequest,
    moderator=Depends(require_moderator_access),
):
    """Mute a user in club (moderator/captain only)"""

    result = await moderation_service.mute_user_in_club(
        target_user_id=mute_request.user_id,
        club_id=club_id,
        moderator=moderator,
        reason=mute_request.reason,
        duration_hours=mute_request.duration_hours,
    )

    # Broadcast user muted event to all connected users in real-time
    if result.success:
        try:
            # Create user muted data for broadcasting
            user_muted_data = {
                "user_id": mute_request.user_id,
                "club_id": club_id,
                "muted_by": moderator.user_id,
                "muted_by_username": moderator.username,
                "muted_by_full_name": moderator.full_name,
                "reason": mute_request.reason,
                "duration_hours": mute_request.duration_hours,
                "muted_until": (
                    result.muted_until.isoformat()
                    if result.muted_until and hasattr(result.muted_until, "isoformat")
                    else str(result.muted_until) if result.muted_until else None
                ),
                "muted_at": datetime.utcnow().isoformat(),
            }

            # Broadcast to all connected users
            await socket_manager.sio.emit(
                "user_muted",
                {
                    "club_id": club_id,
                    "user_muted": user_muted_data,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            print(
                f"📢 Broadcasted user muted event to all connected users: {mute_request.user_id} in club {club_id}"
            )

        except Exception as e:
            print(f"⚠️ Error broadcasting user muted event: {e}")
            # Don't fail the API call if broadcasting fails

    return result


@router.post("/clubs/{club_id}/mute-all-users")
async def mute_all_users(
    club_id: str,
    reason: Optional[str] = None,
    duration_hours: Optional[int] = None,
    moderator=Depends(require_moderator_access),
):
    """Mute all members in club with detailed user information (moderator/captain only)"""

    result = await moderation_service.mute_all_users_in_club(
        club_id=club_id,
        moderator=moderator,
        reason=reason,
        duration_hours=duration_hours,
    )
    print(f"🔍 Result: {result}")

    # Broadcast all users muted event to all connected users in real-time
    if result.get("muted_count", 0) > 0:
        try:
            # Create all users muted data for broadcasting
            # Handle datetime serialization for muted_users
            muted_users_serialized = []
            if result.get("muted_users"):
                for user in result["muted_users"]:
                    user_data = {
                        "user_id": user.get("user_id"),
                        "full_name": user.get("full_name"),
                        "email": user.get("email"),
                        "avatar_url": user.get("avatar_url"),
                        "muted_until": (
                            user.get("muted_until").isoformat()
                            if user.get("muted_until")
                            and hasattr(user.get("muted_until"), "isoformat")
                            else (
                                str(user.get("muted_until"))
                                if user.get("muted_until")
                                else None
                            )
                        ),
                    }
                    muted_users_serialized.append(user_data)

            all_users_muted_data = {
                "club_id": club_id,
                "muted_by": moderator.user_id,
                "muted_by_username": moderator.username,
                "muted_by_full_name": moderator.full_name,
                "reason": reason,
                "duration_hours": duration_hours,
                "muted_count": result.get("muted_count", 0),
                "muted_users": muted_users_serialized,
                "muted_at": datetime.utcnow().isoformat(),
            }

            # Broadcast to all connected users
            await socket_manager.sio.emit(
                "all_users_muted",
                {
                    "club_id": club_id,
                    "all_users_muted": all_users_muted_data,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            print(
                f"📢 Broadcasted all users muted event to all connected users: {result.get('muted_count', 0)} users in club {club_id}"
            )

        except Exception as e:
            print(f"⚠️ Error broadcasting all users muted event: {e}")
            # Don't fail the API call if broadcasting fails

    return create_response(
        200,
        "success",
        result["message"],
        {
            "club_id": club_id,
            "muted_count": result.get("muted_count", 0),
            "muted_users": result.get("muted_users", []),
            "reason": reason,
            "duration_hours": duration_hours,
        },
    )


@router.post("/clubs/{club_id}/unmute-user", response_model=MuteUserResponse)
async def unmute_user(
    club_id: str, user_id: str, moderator=Depends(require_moderator_access)
):
    """Unmute a user in club (moderator/captain only)"""

    result = await moderation_service.unmute_user_in_club(
        target_user_id=user_id, club_id=club_id, moderator=moderator
    )

    # Broadcast user unmuted event to all connected users in real-time
    if result.success:
        try:
            # Create user unmuted data for broadcasting
            user_unmuted_data = {
                "user_id": user_id,
                "club_id": club_id,
                "unmuted_by": moderator.user_id,
                "unmuted_by_username": moderator.username,
                "unmuted_by_full_name": moderator.full_name,
                "unmuted_at": datetime.utcnow().isoformat(),
            }

            # Broadcast to all connected users
            await socket_manager.sio.emit(
                "user_unmuted",
                {
                    "club_id": club_id,
                    "user_unmuted": user_unmuted_data,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            print(
                f"📢 Broadcasted user unmuted event to all connected users: {user_id} in club {club_id}"
            )

        except Exception as e:
            print(f"⚠️ Error broadcasting user unmuted event: {e}")
            # Don't fail the API call if broadcasting fails

    return result


@router.post("/clubs/{club_id}/unmute-all-users")
async def unmute_all_users(club_id: str, moderator=Depends(require_moderator_access)):
    """Unmute all members in club (moderator/captain only)"""

    result = await moderation_service.unmute_all_users_in_club(
        club_id=club_id, moderator=moderator
    )

    # Broadcast all users unmuted event to all connected users in real-time
    if result.get("unmuted_count", 0) > 0:
        try:
            # Create all users unmuted data for broadcasting
            all_users_unmuted_data = {
                "club_id": club_id,
                "unmuted_by": moderator.user_id,
                "unmuted_by_username": moderator.username,
                "unmuted_by_full_name": moderator.full_name,
                "unmuted_count": result.get("unmuted_count", 0),
                "unmuted_at": datetime.utcnow().isoformat(),
            }

            # Broadcast to all connected users
            await socket_manager.sio.emit(
                "all_users_unmuted",
                {
                    "club_id": club_id,
                    "all_users_unmuted": all_users_unmuted_data,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            print(
                f"📢 Broadcasted all users unmuted event to all connected users: {result.get('unmuted_count', 0)} users in club {club_id}"
            )

        except Exception as e:
            print(f"⚠️ Error broadcasting all users unmuted event: {e}")
            # Don't fail the API call if broadcasting fails

    return create_response(
        200,
        "success",
        result["message"],
        {"club_id": club_id, "unmuted_count": result.get("unmuted_count", 0)},
    )


@router.get("/clubs/{club_id}/muted-users")
async def get_muted_users(club_id: str, moderator=Depends(require_moderator_access)):
    """Get list of muted users in club with user details (moderator/captain only)"""

    muted_users = await moderation_service.get_muted_users(club_id)
    return create_response(
        200,
        "success",
        "Muted users with details retrieved successfully",
        {"club_id": club_id, "muted_users": muted_users, "count": len(muted_users)},
    )


@router.get("/clubs/{club_id}/mentionable-users")
async def get_mentionable_users(
    club_id: str,
    chat_user=Depends(require_chat_access),
):
    """Get list of users that can be mentioned in club chat with optimized performance and proper categorization"""
    import time

    route_start_time = time.time()
    print(f"🚀 [MENTIONABLE USERS ROUTE] Starting for club: {club_id}")

    try:
        # Use ultra-fast method to get properly categorized users
        service_start = time.time()
        optimized_data = await user_status_service.get_mentionable_users_ultra_fast(
            club_id
        )
        print(
            f"⏱️ [MENTIONABLE USERS ROUTE] Service call: {(time.time() - service_start)*1000:.2f}ms"
        )

        # Combine all users for the original response format
        combine_start = time.time()
        all_mentionable_users = []
        all_mentionable_users.extend(optimized_data.get("captain", []))
        all_mentionable_users.extend(optimized_data.get("moderators", []))
        all_mentionable_users.extend(optimized_data.get("members", []))
        print(
            f"⏱️ [MENTIONABLE USERS ROUTE] Data combining: {(time.time() - combine_start)*1000:.2f}ms"
        )

        response_data = {
            "club_id": club_id,
            "mentionable_users": all_mentionable_users,
            "count": len(all_mentionable_users),
        }

        total_route_time = (time.time() - route_start_time) * 1000
        print(
            f"🚀 [MENTIONABLE USERS ROUTE] TOTAL ROUTE TIME: {total_route_time:.2f}ms"
        )

        return create_response(
            200, "success", "Mentionable users retrieved successfully", response_data
        )

    except Exception as e:
        logger.error(f"Error getting mentionable users: {e}")
        return create_response(
            500, "error", f"Failed to retrieve mentionable users: {str(e)}"
        )


@router.get("/clubs/{club_id}/messages/{message_id}/thread")
async def get_thread_messages(
    club_id: str,
    message_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of messages per page"),
    chat_user=Depends(require_chat_access),
):
    """Get thread messages for a parent message"""

    try:
        thread_messages, total_count, has_more = (
            await message_service.get_thread_messages(
                parent_message_id=message_id,
                club_id=club_id,
                page=page,
                page_size=page_size,
            )
        )

        # Convert ChatMessage objects to dictionaries for proper serialization
        thread_messages_dict = []
        for message in thread_messages:
            if message:
                thread_messages_dict.append(message.dict())

        return create_response(
            200,
            "success",
            "Thread messages retrieved successfully",
            {
                "club_id": club_id,
                "parent_message_id": message_id,
                "page": page,
                "page_size": page_size,
                "thread_messages": thread_messages_dict,
                "total_count": total_count,
                "has_more": has_more,
            },
        )

    except Exception as e:
        logger.error(f"Error retrieving thread messages: {e}")
        return create_response(
            500, "error", f"Failed to retrieve thread messages: {str(e)}"
        )


@router.post("/clubs/{club_id}/messages/{parent_message_id}/thread")
async def send_thread_reply(
    club_id: str,
    parent_message_id: str,
    thread_request: SendThreadReplyRequest,
    chat_user=Depends(require_unmuted_access),
):
    """Send a reply message in a thread"""
    try:
        # Verify the parent message exists and belongs to the club
        parent_message = await message_service.get_message_by_id(parent_message_id)
        if not parent_message or parent_message.club_id != club_id:
            return create_response(404, "error", "Parent message not found")

        # Create thread reply message
        thread_message = await message_service.create_message(
            sender=chat_user,
            club_id=club_id,
            content=thread_request.content,
            message_type=thread_request.message_type,
            reply_to_message_id=parent_message_id,  # This makes it a thread reply
        )

        # Broadcast thread reply event to all connected users in real-time
        try:
            # Create message data for broadcasting
            message_data = {
                "message_id": thread_message.message_id,
                "club_id": thread_message.club_id,
                "sender_id": thread_message.sender_id,
                "sender_username": thread_message.sender_username,
                "sender_full_name": thread_message.sender_full_name,
                "sender_avatar": thread_message.sender_avatar,
                "content": (
                    thread_message.content.dict()
                    if hasattr(thread_message.content, "dict")
                    else thread_message.content
                ),
                "message_type": thread_message.message_type,
                "reply_to_message_id": thread_message.reply_to_message_id,
                "created_at": (
                    thread_message.created_at.isoformat()
                    if hasattr(thread_message.created_at, "isoformat")
                    else str(thread_message.created_at)
                ),
                "updated_at": (
                    thread_message.updated_at.isoformat()
                    if hasattr(thread_message.updated_at, "isoformat")
                    else str(thread_message.updated_at)
                ),
            }

            # Broadcast to all connected users
            await socket_manager.sio.emit(
                "club_thread_reply",
                {
                    "club_id": club_id,
                    "parent_message_id": parent_message_id,
                    "message": message_data,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            print(
                f"📢 Broadcasted thread reply to all connected users: {thread_message.message_id}"
            )

        except Exception as e:
            print(f"⚠️ Error broadcasting thread reply: {e}")
            # Don't fail the API call if broadcasting fails

        # Get updated thread count
        thread_count = await message_service.get_thread_count(
            parent_message_id, club_id
        )

        return create_response(
            201,
            "success",
            "Thread reply sent successfully",
            {
                "message": (
                    thread_message.dict()
                    if hasattr(thread_message, "dict")
                    else thread_message
                ),
                "parent_message_id": parent_message_id,
                "thread_count": thread_count,
            },
        )

    except HTTPException as e:
        # Handle HTTP exceptions (like muted users, access denied, etc.)
        logger.warning(f"HTTP error sending thread reply: {e.detail}")
        return create_response(e.status_code, "error", e.detail, None)
    except Exception as e:
        logger.error(f"Error sending thread reply: {e}")
        return create_response(
            500, "error", f"Failed to send thread reply: {str(e)}", None
        )


# Thread Routes
@router.post("/threads/create", response_model=CreateThreadResponse)
async def create_thread(
    request: CreateThreadRequest, current_user: dict = Depends(get_current_user)
):
    """Create a new thread from a parent message"""
    success, response, error = await thread_service.create_thread(request, current_user)

    if not success:
        return create_response(400, "error", error)

    # Broadcast thread created event to all connected users in real-time
    try:
        # Create thread data for broadcasting
        thread_data = {
            "thread_id": response.thread_id,
            "club_id": request.club_id,
            "parent_message_id": request.parent_message_id,
            "title": request.title,
            "created_by": current_user["user_id"],
            "created_by_username": current_user.get(
                "username", current_user["full_name"]
            ),
            "created_by_full_name": current_user["full_name"],
            "status": "active",
            "message_count": 0,
            "created_at": datetime.utcnow().isoformat(),
        }

        # Broadcast to all connected users
        await socket_manager.sio.emit(
            "club_thread_created",
            {
                "club_id": request.club_id,
                "thread": thread_data,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        print(
            f"📢 Broadcasted thread creation to all connected users: {response.thread_id}"
        )

    except Exception as e:
        print(f"⚠️ Error broadcasting thread creation: {e}")
        # Don't fail the API call if broadcasting fails

    return create_response(
        201, "success", "Thread created successfully", response.dict()
    )


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return create_response(
        200,
        "success",
        "Service is healthy",
        {
            "status": "healthy",
            "service": "betting_chat_service",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


# ============================================================================
# DM REQUEST ROUTES
# ============================================================================


@router.post("/dm/requests", response_model=CreateDMRequestResponse)
async def create_dm_request(
    request: CreateDMRequestRequest, current_user: dict = Depends(get_current_user)
):
    """
    Send a DM request to another user

    This endpoint allows users to send a direct message request to another user within a club.
    The receiver must accept the request before direct messaging can begin.
    """
    success, response, error = await dm_service.create_dm_request(request, current_user)

    if not success:
        return create_response(400, "error", error)

    return create_response(
        201, "success", "DM request sent successfully", response.dict()
    )


@router.post(
    "/dm/requests/{request_id}/respond", response_model=RespondToDMRequestResponse
)
async def respond_to_dm_request(
    request_id: str,
    request: RespondToDMRequestRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Respond to a DM request (accept/reject/block/unblock)

    This endpoint allows users to respond to incoming DM requests with different actions.

    Actions:
    - accept: Accept the DM request (status: accepted)
    - reject: Reject and DELETE the DM request completely (as if never sent)
    - block: Block the sender (status: blocked)
    - unblock: Unblock the sender (status: accepted)
    """
    # Ensure request_id matches
    request.request_id = request_id
    success, response, error = await dm_service.respond_to_dm_request(
        request, current_user
    )

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200, "success", "DM request responded successfully", response.dict()
    )


@router.get("/dm/requests", response_model=GetDMRequestsResponse)
async def get_dm_requests(
    club_id: str = Query(..., description="Club ID (required)"),
    status: Optional[str] = Query(
        "all", description="Filter by status (all/pending/accepted/rejected/blocked)"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """
    Get DM requests for the current user in a specific club

    This endpoint retrieves all DM requests (sent and received) for the current user in the specified club,
    with optional filtering by status. Only club members can access this endpoint.
    """
    from .models import DMRequestStatus
    from .auth import check_club_access

    # Verify user is a member of the club
    has_access, access_details = await check_club_access(
        current_user["user_id"], club_id
    )
    if not has_access:
        return create_response(
            403, "error", "You must be a member of this club to view DM requests"
        )

    # Parse status filter
    status_filter = None
    if status and status != "all":
        try:
            status_filter = DMRequestStatus(status)
        except ValueError:
            return create_response(
                400,
                "error",
                f"Invalid status: {status}. Valid values are: all, pending, accepted, rejected, blocked",
            )

    request = GetDMRequestsRequest(
        club_id=club_id, status=status_filter, page=page, page_size=page_size
    )

    success, response, error = await dm_service.get_dm_requests(request, current_user)

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200, "success", "DM requests retrieved successfully", response.dict()
    )


@router.get("/clubs/{club_id}/dm/requests")
async def get_club_dm_requests(
    club_id: str,
    status: str = Query(
        "all", description="Filter by status (all/pending/accepted/rejected/blocked)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: dict = Depends(get_current_user),
):
    """
    Get DM requests for the current user in a specific club with enhanced filtering

    This endpoint retrieves all DM requests (sent and received) for the current user in the specified club,
    with filtering by status. Only club members can access this endpoint.

    Status options:
    - all: All requests (default)
    - pending: Requests waiting for response
    - accepted: Accepted requests
    - rejected: Rejected requests
    - blocked: Blocked requests
    """
    from .models import DMRequestStatus
    from .auth import check_club_access

    # Verify user is a member of the club
    has_access, access_details = await check_club_access(
        current_user["user_id"], club_id
    )
    if not has_access:
        return create_response(
            403, "error", "You must be a member of this club to view DM requests"
        )

    # Parse status filter
    status_filter = None
    if status and status != "all":
        try:
            status_filter = DMRequestStatus(status)
        except ValueError:
            return create_response(
                400,
                "error",
                f"Invalid status: {status}. Valid values are: all, pending, accepted, rejected, blocked",
            )

    request = GetDMRequestsRequest(
        club_id=club_id, status=status_filter, page=page, page_size=page_size
    )

    success, response, error = await dm_service.get_dm_requests(request, current_user)

    if not success:
        return create_response(400, "error", error)

    # Add additional information to response
    response_data = response.dict()
    response_data["club_id"] = club_id
    response_data["user_role"] = access_details.get("role", "member")
    response_data["filter_status"] = status

    return create_response(
        200, "success", "DM requests retrieved successfully", response_data
    )


@router.post("/dm/block", response_model=BlockUserResponse)
async def block_user(
    request: BlockUserRequest, current_user: dict = Depends(get_current_user)
):
    """Block a user from sending DMs"""
    success, response, error = await dm_service.block_user(request, current_user)

    if not success:
        return create_response(400, "error", error)

    return create_response(200, "success", "User blocked successfully", response.dict())


@router.post("/dm/unblock", response_model=UnblockUserResponse)
async def unblock_user(
    request: UnblockUserRequest, current_user: dict = Depends(get_current_user)
):
    """Unblock a user"""
    success, response, error = await dm_service.unblock_user(request, current_user)

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200, "success", "User unblocked successfully", response.dict()
    )


@router.get("/dm/blocked-users", response_model=GetBlockedUsersResponse)
async def get_blocked_users(
    club_id: str = Query(..., description="Club ID"),
    current_user: dict = Depends(get_current_user),
):
    """Get list of blocked users"""
    success, response, error = await dm_service.get_blocked_users(club_id, current_user)

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200, "success", "Blocked users retrieved successfully", response.dict()
    )


# ============================================================================
# DM MESSAGE ROUTES
# ============================================================================


@router.post("/dm/messages", response_model=SendDMMessageResponse)
async def send_dm_message(
    request: SendDMMessageRequest, current_user: dict = Depends(get_current_user)
):
    """
    Send a direct message

    This endpoint allows users to send direct messages to other users after a DM request has been accepted.
    """
    success, response, error = await dm_service.send_dm_message(request, current_user)

    if not success:
        return create_response(400, "error", error)

    # Broadcast DM message event to all connected users in real-time
    try:
        # Create DM message data for broadcasting
        dm_message_data = {
            "dm_message_id": response.dm_message.dm_message_id,
            "sender_id": response.dm_message.sender_id,
            "sender_username": current_user.get("username", current_user["full_name"]),
            "sender_full_name": current_user["full_name"],
            "sender_avatar": current_user.get("avatar_url"),
            "receiver_id": response.dm_message.receiver_id,
            "club_id": response.dm_message.club_id,
            "content": (
                response.dm_message.content.dict()
                if hasattr(response.dm_message.content, "dict")
                else response.dm_message.content
            ),
            "message_type": response.dm_message.message_type,
            "reply_to_dm_message_id": response.dm_message.reply_to_dm_message_id,
            "created_at": (
                response.dm_message.created_at.isoformat()
                if hasattr(response.dm_message.created_at, "isoformat")
                else str(response.dm_message.created_at)
            ),
            "updated_at": (
                response.dm_message.updated_at.isoformat()
                if hasattr(response.dm_message.updated_at, "isoformat")
                else str(response.dm_message.updated_at)
            ),
        }

        # Send socket event only to receiver (not all users)
        # Find receiver's socket_id from connected users
        receiver_socket_ids = []
        for socket_id, user_data in socket_manager.connected_users.items():
            if user_data.get("user_id") == response.dm_message.receiver_id:
                receiver_socket_ids.append(socket_id)
        
        # Also send to sender so they can see their message in real-time
        sender_socket_ids = []
        for socket_id, user_data in socket_manager.connected_users.items():
            if user_data.get("user_id") == response.dm_message.sender_id:
                sender_socket_ids.append(socket_id)
        
        # Send to both receiver and sender only
        target_socket_ids = list(set(receiver_socket_ids + sender_socket_ids))
        
        if target_socket_ids:
            for socket_id in target_socket_ids:
                await socket_manager.sio.emit(
                    "dm_message_sent",
                    {
                        "club_id": request.club_id,
                        "dm_message": dm_message_data,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    room=socket_id,
                )
            logger.info(
                f"📢 Sent DM message socket event to {len(target_socket_ids)} connected user(s): {response.dm_message.dm_message_id}"
            )
        else:
            logger.info(
                f"ℹ️ No connected users found for DM message: {response.dm_message.dm_message_id}"
            )

    except Exception as e:
        logger.error(f"⚠️ Error broadcasting DM message: {e}")
        # Don't fail the API call if broadcasting fails

    # NOTE: Push notification is already sent in dm_service.send_dm_message()
    # No need to send it again here to avoid duplicate notifications

    return create_response(201, "success", "DM sent successfully", response.dict())


@router.get("/dm/messages")
async def get_dm_messages(
    user_id: str = Query(..., description="User ID to get messages with"),
    club_id: str = Query(..., description="Club ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    before_message_id: Optional[str] = Query(
        None, description="Get messages before this ID"
    ),
    search: Optional[str] = Query(
        None, description="Search query to filter messages by content"
    ),
    include_thread_counts: bool = Query(
        True,
        description="Include thread info (count + last 3 reply users) for each message",
    ),
    current_user: dict = Depends(get_current_user),
):
    """Get DM messages between two users with search functionality and optional thread info

    Returns messages in chronological order (oldest first, newest last) - 1st, 2nd, 3rd, 4th, 5th.
    Supports searching messages by content text.
    Excludes thread messages (replies) from main DM message list.
    When include_thread_counts is True, each message includes thread_count and last_reply_users (max 3).
    """
    request = GetDMMessagesRequest(
        user_id=user_id,
        club_id=club_id,
        page=page,
        page_size=page_size,
        before_message_id=before_message_id,
        search=search,
    )

    if include_thread_counts:
        # Use the new method with thread counts
        success, response, error = await dm_service.get_dm_messages_with_thread_counts(
            request, current_user
        )

        if not success:
            return create_response(400, "error", error)

        return create_response(
            200,
            "success",
            "DM messages with thread counts retrieved successfully",
            response,
        )
    else:
        # Use the original method without thread counts
        success, response, error = await dm_service.get_dm_messages(
            request, current_user
        )

        if not success:
            return create_response(400, "error", error)

        return create_response(
            200, "success", "DM messages retrieved successfully", response.dict()
        )


@router.get("/dm/conversations", response_model=GetDMConversationsResponse)
async def get_dm_conversations(
    club_id: str = Query(..., description="Club ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """Get DM conversations for the current user in a club"""
    request = GetDMConversationsRequest(club_id=club_id, page=page, page_size=page_size)

    success, response, error = await dm_service.get_dm_conversations(
        request, current_user
    )

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200, "success", "DM conversations retrieved successfully", response.dict()
    )


# DM Pin/Unpin APIs
@router.post("/dm/messages/{message_id}/pin")
async def pin_dm_message(
    message_id: str,
    pin_request: PinDMMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    """Pin a DM message"""
    user_id = current_user["user_id"]

    success, dm_message, error = await dm_service.pin_dm_message(
        message_id=message_id, user_id=user_id, reason=pin_request.reason
    )

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200,
        "success",
        "DM message pinned successfully",
        {"dm_message": dm_message.dict()},
    )


@router.delete("/dm/messages/{message_id}/pin")
async def unpin_dm_message(
    message_id: str, current_user: dict = Depends(get_current_user)
):
    """Unpin a DM message"""
    user_id = current_user["user_id"]

    success, error = await dm_service.unpin_dm_message(
        message_id=message_id, user_id=user_id
    )

    if not success:
        return create_response(400, "error", error)

    return create_response(200, "success", "DM message unpinned successfully")


@router.get("/dm/pinned-messages")
async def get_dm_pinned_messages(
    user_id: str = Query(..., description="User ID to get pinned messages for"),
    club_id: str = Query(..., description="Club ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: dict = Depends(get_current_user),
):
    """Get pinned DM messages for a user in a club"""
    # Verify the user is requesting their own pinned messages or is part of the conversation
    if current_user["user_id"] != user_id:
        return create_response(
            403, "error", "You can only view your own pinned messages"
        )

    success, response, error = await dm_service.get_dm_pinned_messages(
        user_id=user_id, club_id=club_id, page=page, page_size=page_size
    )

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200, "success", "Pinned DM messages retrieved successfully", response.dict()
    )


@router.put("/dm/messages/{dm_message_id}", response_model=EditDMMessageResponse)
async def edit_dm_message(
    dm_message_id: str,
    request: EditDMMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    """Edit a DM message (only by sender)"""
    try:
        # Ensure dm_message_id matches
        request.dm_message_id = dm_message_id

        success, response, error = await dm_service.edit_dm_message(
            request, current_user
        )

        if not success:
            return create_response(400, "error", error)

        # Broadcast DM message edit event to all connected users in real-time
        try:
            # Create DM message data for broadcasting
            dm_message_data = {
                "dm_message_id": response.dm_message.dm_message_id,
                "sender_id": response.dm_message.sender_id,
                "sender_username": current_user.get(
                    "username", current_user["full_name"]
                ),
                "sender_full_name": current_user["full_name"],
                "sender_avatar": current_user.get("avatar_url"),
                "receiver_id": response.dm_message.receiver_id,
                "club_id": response.dm_message.club_id,
                "content": (
                    response.dm_message.content.dict()
                    if hasattr(response.dm_message.content, "dict")
                    else response.dm_message.content
                ),
                "message_type": response.dm_message.message_type,
                "reply_to_dm_message_id": response.dm_message.reply_to_dm_message_id,
                "created_at": (
                    response.dm_message.created_at.isoformat()
                    if hasattr(response.dm_message.created_at, "isoformat")
                    else str(response.dm_message.created_at)
                ),
                "updated_at": (
                    response.dm_message.updated_at.isoformat()
                    if hasattr(response.dm_message.updated_at, "isoformat")
                    else str(response.dm_message.updated_at)
                ),
                "edited_at": datetime.utcnow().isoformat(),
            }

            # Broadcast to all connected users
            await socket_manager.sio.emit(
                "dm_message_edited",
                {
                    "club_id": response.dm_message.club_id,
                    "dm_message": dm_message_data,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            print(
                f"📢 Broadcasted DM message edit to all connected users: {response.dm_message.dm_message_id}"
            )

        except Exception as e:
            print(f"⚠️ Error broadcasting DM message edit: {e}")
            # Don't fail the API call if broadcasting fails

        return create_response(
            200, "success", "DM message edited successfully", response.dict()
        )

    except Exception as e:
        logger.error(f"Error editing DM message: {e}")
        return create_response(500, "error", f"Failed to edit DM message: {str(e)}")


@router.delete("/dm/messages/{dm_message_id}", response_model=DeleteDMMessageResponse)
async def delete_dm_message(
    dm_message_id: str, current_user: dict = Depends(get_current_user)
):
    """Delete a DM message (only by sender)"""
    try:
        # Get DM message data before deletion for broadcasting
        dm_message_data = None
        try:
            from .db import get_dm_messages_collection

            dm_messages_collection = get_dm_messages_collection()
            dm_message_doc = await dm_messages_collection.find_one(
                {"dm_message_id": dm_message_id}
            )
            if dm_message_doc:
                dm_message_data = {
                    "dm_message_id": dm_message_doc["dm_message_id"],
                    "sender_id": dm_message_doc["sender_id"],
                    "sender_username": current_user.get(
                        "username", current_user["full_name"]
                    ),
                    "sender_full_name": current_user["full_name"],
                    "sender_avatar": current_user.get("avatar_url"),
                    "receiver_id": dm_message_doc["receiver_id"],
                    "club_id": dm_message_doc["club_id"],
                    "content": dm_message_doc.get("content", {}),
                    "message_type": dm_message_doc.get("message_type", "text"),
                    "reply_to_dm_message_id": dm_message_doc.get(
                        "reply_to_dm_message_id"
                    ),
                    "created_at": (
                        dm_message_doc["created_at"].isoformat()
                        if hasattr(dm_message_doc["created_at"], "isoformat")
                        else str(dm_message_doc["created_at"])
                    ),
                    "deleted_by": current_user["user_id"],
                    "deleted_by_username": current_user.get(
                        "username", current_user["full_name"]
                    ),
                    "deleted_by_full_name": current_user["full_name"],
                    "deleted_at": datetime.utcnow().isoformat(),
                }
        except Exception as e:
            print(f"⚠️ Error getting DM message data for broadcast: {e}")

        request = DeleteDMMessageRequest(dm_message_id=dm_message_id)

        success, response, error = await dm_service.delete_dm_message(
            request, current_user
        )

        if not success:
            return create_response(400, "error", error)

        # Broadcast DM message delete event to all connected users in real-time
        if dm_message_data:
            try:
                # Broadcast to all connected users
                await socket_manager.sio.emit(
                    "dm_message_deleted",
                    {
                        "club_id": dm_message_data["club_id"],
                        "dm_message": dm_message_data,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

                print(
                    f"📢 Broadcasted DM message deletion to all connected users: {dm_message_id}"
                )

            except Exception as e:
                print(f"⚠️ Error broadcasting DM message deletion: {e}")
                # Don't fail the API call if broadcasting fails

        return create_response(
            200, "success", "DM message deleted successfully", response.dict()
        )

    except Exception as e:
        logger.error(f"Error deleting DM message: {e}")
        return create_response(500, "error", f"Failed to delete DM message: {str(e)}")


@router.get("/dm/can-message/{user_id}")
async def can_message_user(
    user_id: str,
    club_id: str = Query(..., description="Club ID"),
    current_user: dict = Depends(get_current_user),
):
    """Check if current user can send DMs to another user"""
    try:
        sender_id = current_user["user_id"]

        # Check if users can DM each other
        can_dm, message = await dm_service.can_users_dm(sender_id, user_id, club_id)

        return create_response(
            200,
            "success",
            "DM permission checked successfully",
            {
                "can_message": can_dm,
                "message": message,
                "user_id": user_id,
                "club_id": club_id,
            },
        )

    except Exception as e:
        logger.error(f"Error checking DM permission: {e}")
        return create_response(500, "error", f"Failed to check DM permission: {str(e)}")


@router.post("/dm/connected-users", response_model=GetConnectedDMUsersResponse)
async def get_connected_dm_users(
    request: GetConnectedDMUsersRequest, current_user: dict = Depends(get_current_user)
):
    """
    Get connected DM users for the current user in a club with pagination and search

    This endpoint returns a list of users that the current user has active DM conversations with
    in the specified club. The response includes:
    - User details (ID, username, full name, avatar)
    - Last message content and timestamp
    - Last message sender information
    - Unread message count
    - Results sorted by last message timestamp (descending)
    - Optional search filtering by username or full name

    Request body should include:
    - club_id: Club name_based_id (required)
    - search: Optional search query to filter users by username or full name (default: empty)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 20, max: 100)

    The current user is automatically determined from the authentication token.
    """
    try:
        success, response, error = await dm_service.get_connected_dm_users(
            request, current_user
        )

        if not success:
            return create_response(400, "error", error)

        return create_response(
            200, "success", "Connected DM users retrieved successfully", response.dict()
        )

    except Exception as e:
        logger.error(f"Error getting connected DM users: {e}")
        return create_response(
            500, "error", f"Failed to get connected DM users: {str(e)}"
        )


# DM Thread Message APIs
@router.post("/dm/thread/messages", response_model=SendDMThreadMessageResponse)
async def send_dm_thread_message(
    request: SendDMThreadMessageRequest, current_user: dict = Depends(get_current_user)
):
    """
    Send a DM thread message (reply to a parent DM message)

    This endpoint allows users to reply to existing DM messages, creating a thread conversation.
    The parent DM message must exist and both users must have access to it.

    Request body should include:
    - receiver_id: User ID of the message receiver (required)
    - club_id: Club name_based_id (required)
    - content: Message content (required, 1-2000 characters)
    - message_type: Type of message (default: text)
    - parent_dm_message_id: ID of the parent DM message to reply to (required)

    The current user is automatically determined from the authentication token.
    """
    try:
        print(f"Sending DM thread message: {request}")
        success, response, error = await dm_service.send_dm_thread_message(
            request, current_user
        )

        if not success:
            return create_response(400, "error", error)

        # Broadcast DM thread message event to all connected users in real-time
        try:
            # Create DM thread message data for broadcasting
            dm_thread_message_data = {
                "dm_thread_message_id": response.dm_message.dm_message_id,
                "sender_id": response.dm_message.sender_id,
                "sender_username": current_user.get(
                    "username", current_user["full_name"]
                ),
                "sender_full_name": current_user["full_name"],
                "sender_avatar": current_user.get("avatar_url"),
                "receiver_id": response.dm_message.receiver_id,
                "club_id": response.dm_message.club_id,
                "parent_dm_message_id": response.parent_dm_message_id,
                "content": (
                    response.dm_message.content.dict()
                    if hasattr(response.dm_message.content, "dict")
                    else response.dm_message.content
                ),
                "message_type": response.dm_message.message_type,
                "created_at": (
                    response.dm_message.created_at.isoformat()
                    if hasattr(response.dm_message.created_at, "isoformat")
                    else str(response.dm_message.created_at)
                ),
                "updated_at": (
                    response.dm_message.updated_at.isoformat()
                    if hasattr(response.dm_message.updated_at, "isoformat")
                    else str(response.dm_message.updated_at)
                ),
            }

            # Send socket event only to receiver and sender (not all users)
            # Find receiver's socket_id from connected users
            receiver_socket_ids = []
            for socket_id, user_data in socket_manager.connected_users.items():
                if user_data.get("user_id") == response.dm_message.receiver_id:
                    receiver_socket_ids.append(socket_id)
            
            # Also send to sender so they can see their message in real-time
            sender_socket_ids = []
            for socket_id, user_data in socket_manager.connected_users.items():
                if user_data.get("user_id") == response.dm_message.sender_id:
                    sender_socket_ids.append(socket_id)
            
            # Send to both receiver and sender only
            target_socket_ids = list(set(receiver_socket_ids + sender_socket_ids))
            
            if target_socket_ids:
                for socket_id in target_socket_ids:
                    await socket_manager.sio.emit(
                        "dm_thread_message_sent",
                        {
                            "club_id": request.club_id,
                            "dm_thread_message": dm_thread_message_data,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        room=socket_id,
                    )
                logger.info(
                    f"📢 Sent DM thread message socket event to {len(target_socket_ids)} connected user(s): {response.dm_message.dm_message_id}"
                )
            else:
                logger.info(
                    f"ℹ️ No connected users found for DM thread message: {response.dm_message.dm_message_id}"
                )

        except Exception as e:
            logger.error(f"⚠️ Error broadcasting DM thread message: {e}")
            # Don't fail the API call if broadcasting fails

        # Send push notification to receiver (only once)
        try:
            from services.notifications.notification_service import send_notification_to_users
            from .db import get_club_collection
            
            # Get club information to get club name
            clubs_collection = get_club_collection()
            club = await clubs_collection.find_one({"name_based_id": request.club_id})
            club_name = club.get("name", "Club") if club else "Club"
            
            # Create notification content
            title = f"New Direct Message Reply!"
            body = f"{current_user.get('full_name', 'Someone')} replied to your message"
            
            # Truncate message content for notification
            message_preview = request.content[:100] + "..." if len(request.content) > 100 else request.content
            
            notification_data = {
                "dm_message_id": response.dm_message.dm_message_id,
                "parent_dm_message_id": response.parent_dm_message_id,
                "club_id": request.club_id,  # name_based_id
                "club_name": club_name,
                "sender_id": response.dm_message.sender_id,
                "sender_name": current_user.get("full_name", "Unknown"),
                "sender_avatar": current_user.get("avatar_url"),
                "receiver_id": response.dm_message.receiver_id,
                "message_preview": message_preview,
                "msg_type": request.message_type,
                "push_type": "chat_message",
                "is_dm": "true",
                "is_chat_open": "true",
                "is_dm_chat_open": "false"
            }
            
            notification_result = await send_notification_to_users(
                user_ids=[response.dm_message.receiver_id],
                title=title,
                body=body,
                notification_type="club_message",
                data=notification_data,
                click_action=f"club/{request.club_id}/dm/{response.dm_message.sender_id}",
                priority="high"
            )
            logger.info(f"✅ DM thread notification sent to receiver {response.dm_message.receiver_id}: {notification_result}")
                
        except Exception as e:
            logger.error(f"⚠️ Failed to send DM thread notification: {e}")
            # Don't fail the DM send if notification fails

        return create_response(
            201, "success", "DM thread message sent successfully", response.dict()
        )

    except Exception as e:
        logger.error(f"Error sending DM thread message: {e}")
        return create_response(
            500, "error", f"Failed to send DM thread message: {str(e)}"
        )


@router.get("/dm/thread/messages", response_model=GetDMThreadMessagesResponse)
async def get_dm_thread_messages(
    receiver_id: str = Query(..., description="User ID to get thread messages with"),
    club_id: str = Query(..., description="Club ID"),
    parent_dm_message_id: str = Query(
        ..., description="Parent DM message ID to get thread for"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """
    Get DM thread messages for a parent DM message

    This endpoint retrieves all thread messages (replies) for a specific parent DM message.
    Both users must have access to the parent message and be members of the club.

    Query parameters:
    - receiver_id: User ID to get thread messages with (required)
    - club_id: Club name_based_id (required)
    - parent_dm_message_id: Parent DM message ID to get thread for (required)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 50, max: 100)

    The current user is automatically determined from the authentication token.
    """
    try:
        request = GetDMThreadMessagesRequest(
            receiver_id=receiver_id,
            club_id=club_id,
            parent_dm_message_id=parent_dm_message_id,
            page=page,
            page_size=page_size,
        )

        success, response, error = await dm_service.get_dm_thread_messages(
            request, current_user
        )

        if not success:
            return create_response(400, "error", error)

        return create_response(
            200, "success", "DM thread messages retrieved successfully", response.dict()
        )

    except Exception as e:
        logger.error(f"Error getting DM thread messages: {e}")
        return create_response(
            500, "error", f"Failed to get DM thread messages: {str(e)}"
        )


# Member Clubs Latest Messages API
@router.get("/member/clubs/latest-messages")
async def get_member_clubs_latest_messages(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(
        "latest_message",
        pattern="^(latest_message|club_name|join_date)$",
        description="Sort by latest_message, club_name, or join_date",
    ),
    current_user: dict = Depends(get_current_user),
):
    """Get latest messages from all clubs a member has joined"""
    user_id = current_user["user_id"]

    success, response, error = await message_service.get_member_clubs_latest_messages(
        user_id=user_id, page=page, page_size=page_size, sort_by=sort_by
    )

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200, "success", "Member clubs latest messages retrieved successfully", response
    )


# Club Detail Page API
@router.get("/clubs/{club_id}/details")
async def get_club_details(
    club_id: str, current_user: dict = Depends(get_current_user)
):
    """Get detailed club information based on user role and track visit"""
    user_id = current_user["user_id"]

    # Track the user's visit to this club
    try:
        from .db import get_user_access_collection

        user_access_collection = get_user_access_collection()
        now = datetime.utcnow()

        # Update or create user access record with last visited time
        await user_access_collection.update_one(
            {"user_id": user_id, "club_id": club_id},
            {
                "$set": {
                    "last_visited": now,
                    "updated_at": now,
                    "user_id": user_id,
                    "club_id": club_id,
                }
            },
            upsert=True,
        )
        print(f"🔍 Tracked visit for user {user_id} to club {club_id} at {now}")
    except Exception as e:
        print(f"Error tracking club visit: {e}")

    success, response, error = await club_detail_service.get_club_details(
        club_id=club_id, user_id=user_id
    )

    if not success:
        return create_response(400, "error", error)

    return create_response(
        200, "success", "Club details retrieved successfully", response.dict()
    )


# Last Visited Club Chat Room API
@router.get("/user/last-visited-club")
async def get_last_visited_club(current_user: dict = Depends(get_current_user)):
    """Get the last visited club chat room for the current user based on their role"""

    user_id = current_user["user_id"]
    user_role = current_user.get("role", "Member")

    try:
        # Get user's club memberships and access records
        from .db import (
            get_club_memberships_collection,
            get_user_access_collection,
            get_club_collection,
        )

        memberships_collection = get_club_memberships_collection()
        user_access_collection = get_user_access_collection()
        clubs_collection = get_club_collection()

        last_visited_club_id = None
        last_activity_time = None

        # Get user access records to find last visited clubs
        access_records = (
            await user_access_collection.find({"user_id": user_id})
            .sort("last_visited", -1)
            .to_list(None)
        )

        print(f"🔍 Access records found: {len(access_records)}")
        for record in access_records:
            print(
                f"🔍 Record: club_id={record.get('club_id')}, last_visited={record.get('last_visited')}"
            )

        # Get the most recently visited club (regardless of which club it is)
        if access_records:
            for record in access_records:
                if record.get("last_visited"):
                    last_visited_club_id = record.get("club_id")
                    last_activity_time = record.get("last_visited")
                    print(
                        f"🔍 Found visited club: {last_visited_club_id} at {last_activity_time}"
                    )
                    break
                else:
                    print(f"🔍 Record has no last_visited: {record.get('club_id')}")

        # If no visited clubs found, get last joined club based on role
        if not last_visited_club_id:
            if user_role == "Captain":
                # For captain, get the last club they created
                captain_clubs = (
                    await clubs_collection.find({"captain_id": user_id})
                    .sort("created_at", -1)
                    .limit(1)
                    .to_list(None)
                )

                if captain_clubs:
                    last_visited_club_id = captain_clubs[0].get("name_based_id")

            elif user_role == "Moderator":
                # For moderator, get the last club they joined as moderator
                moderator_clubs = (
                    await clubs_collection.find({"moderators.user_id": user_id})
                    .sort("created_at", -1)
                    .limit(1)
                    .to_list(None)
                )

                if moderator_clubs:
                    last_visited_club_id = moderator_clubs[0].get("name_based_id")

            else:  # Member
                # For member, get the last club they joined
                member_clubs = (
                    await memberships_collection.find(
                        {
                            "user_id": user_id,
                            "subscription_status": {
                                "$in": ["active", "trial", "paid", "subscribed"]
                            },
                        }
                    )
                    .sort("created_at", -1)
                    .limit(1)
                    .to_list(None)
                )

                if member_clubs:
                    club_id = member_clubs[0].get("club_id")
                    # Get club name_based_id
                    club = await clubs_collection.find_one({"_id": ObjectId(club_id)})
                    if club:
                        last_visited_club_id = club.get("name_based_id")

        # If still no club found, try to get any club the user has access to
        if not last_visited_club_id:
            print(f"🔍 No visited clubs found, checking user's accessible clubs...")
            # Check clubs the user has access to
            all_clubs = (
                await clubs_collection.find(
                    {
                        "$or": [
                            {"paid_members.user_id": user_id},
                            {"members.user_id": user_id},
                            {"captain_id": user_id},
                            {"moderators.user_id": user_id},
                        ]
                    }
                )
                .sort("created_at", -1)
                .limit(1)
                .to_list(None)
            )

            print(f"🔍 Found {len(all_clubs)} accessible clubs")
            if all_clubs:
                last_visited_club_id = all_clubs[0].get("name_based_id")
                print(f"🔍 Using fallback club: {last_visited_club_id}")

        if not last_visited_club_id:
            return create_response(404, "error", "No clubs found for user")

        return create_response(
            200,
            "success",
            "Last visited club retrieved successfully",
            {
                "club_id": last_visited_club_id,
                "user_role": user_role,
                "user_email": current_user.get("email"),
                "last_activity_time": last_activity_time,
                "is_visited": last_activity_time is not None,
            },
        )

    except Exception as e:
        print(f"Error getting last visited club: {e}")
        return create_response(500, "error", f"Internal server error: {str(e)}")


# Manual Visit Tracking API (for testing)
@router.post("/clubs/{club_id}/track-visit")
async def track_club_visit_manual(
    club_id: str, current_user: dict = Depends(get_current_user)
):
    """Manually track a user's visit to a club (for testing purposes)"""

    user_id = current_user["user_id"]

    try:
        # Check if user has access to the club
        has_access, access_details = await check_club_access(user_id, club_id)
        if not has_access:
            return create_response(403, "error", "Access denied to club")

        # Update or create user access record with last visited time
        from .db import get_user_access_collection

        user_access_collection = get_user_access_collection()

        now = datetime.utcnow()

        await user_access_collection.update_one(
            {"user_id": user_id, "club_id": club_id},
            {
                "$set": {
                    "last_visited": now,
                    "updated_at": now,
                    "user_id": user_id,
                    "club_id": club_id,
                }
            },
            upsert=True,
        )

        print(
            f"🔍 Manually tracked visit for user {user_id} to club {club_id} at {now}"
        )

        return create_response(
            200,
            "success",
            "Club visit tracked successfully",
            {
                "club_id": club_id,
                "user_id": user_id,
                "visited_at": now.isoformat(),
                "message": "Visit tracked successfully",
            },
        )

    except Exception as e:
        print(f"Error tracking club visit: {e}")
        return create_response(500, "error", f"Internal server error: {str(e)}")


# ============================================================================
# USER STATUS IN CLUB ROUTES
# ============================================================================

from .user_status_service import UserStatusService

# Initialize user status service
user_status_service = UserStatusService()


@router.get("/clubs/{club_id}/user-status", response_model=UserClubStatusResponse)
async def get_user_status_in_club(
    club_id: str, current_user: dict = Depends(get_current_user)
):
    """
    Get the current status of the logged-in user in a specific club chat room

    Args:
        club_id: Club ID to get status for
        current_user: Current authenticated user

    Returns:
        UserClubStatusResponse with user status details
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            return create_response(401, "error", "User not authenticated")

        success, response, error = await user_status_service.get_user_status_in_club(
            user_id, club_id
        )

        if not success:
            return create_response(400, "error", error or "Failed to get user status")

        return response

    except Exception as e:
        print(f"Error getting user status in club: {e}")
        return create_response(500, "error", f"Internal server error: {str(e)}")


@router.get("/clubs/{club_id}/members-status", response_model=ClubMemberStatusResponse)
async def get_all_members_status_in_club(
    club_id: str, current_user: dict = Depends(get_current_user)
):
    """
    Get status of all members in a club chat room

    Args:
        club_id: Club ID to get members status for
        current_user: Current authenticated user

    Returns:
        ClubMemberStatusResponse with all members status details
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            return create_response(401, "error", "User not authenticated")

        success, response, error = (
            await user_status_service.get_all_members_status_in_club(club_id, user_id)
        )

        if not success:
            return create_response(
                400, "error", error or "Failed to get members status"
            )

        return response

    except Exception as e:
        print(f"Error getting members status in club: {e}")
        return create_response(500, "error", f"Internal server error: {str(e)}")


@router.get(
    "/clubs/{club_id}/user/{target_user_id}/status",
    response_model=UserClubStatusResponse,
)
async def get_specific_user_status_in_club(
    club_id: str, target_user_id: str, current_user: dict = Depends(get_current_user)
):
    """
    Get status of a specific user in a club chat room

    Args:
        club_id: Club ID to get status for
        target_user_id: Target user ID to get status for
        current_user: Current authenticated user

    Returns:
        UserClubStatusResponse with target user status details
    """
    try:
        current_user_id = current_user.get("user_id")
        if not current_user_id:
            return create_response(401, "error", "User not authenticated")

        # Check if current user has access to this club
        success, response, error = await user_status_service.get_user_status_in_club(
            current_user_id, club_id
        )

        if not success:
            return create_response(
                400, "error", error or "You don't have access to this club"
            )

        # Get target user status
        success, response, error = await user_status_service.get_user_status_in_club(
            target_user_id, club_id
        )

        if not success:
            return create_response(
                400, "error", error or "Failed to get target user status"
            )

        return response

    except Exception as e:
        print(f"Error getting specific user status in club: {e}")
        return create_response(500, "error", f"Internal server error: {str(e)}")


# ========================================
# PAGINATED ROLE-BASED MEMBER APIS
# ========================================


@router.get("/clubs/{club_id}/captains", response_model=ClubCaptainsResponse)
async def get_club_captains(
    club_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=10, ge=1, le=100, description="Number of items per page"
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Get captains of a club with pagination - OPTIMIZED VERSION

    Args:
        club_id: Club ID to get captains for
        page: Page number (1-based)
        page_size: Number of items per page (max 100)
        current_user: Current authenticated user

    Returns:
        ClubCaptainsResponse with paginated captains data
    """
    import time

    start_time = time.time()
    step_start_time = time.time()

    try:
        print(f"⏱️ [CAPTAINS API] Starting captains API for club: {club_id}")

        # Step 1: Authentication check
        user_id = current_user.get("user_id")
        if not user_id:
            print(
                f"⏱️ [CAPTAINS API] Auth check failed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            return create_response(401, "error", "User not authenticated")

        print(
            f"⏱️ [CAPTAINS API] Auth check completed in {(time.time() - step_start_time)*1000:.2f}ms"
        )
        step_start_time = time.time()

        # Step 2: Call service method
        success, response, error = (
            await user_status_service.get_club_captains_with_pagination(
                club_id, user_id, page, page_size
            )
        )

        print(
            f"⏱️ [CAPTAINS API] Service call completed in {(time.time() - step_start_time)*1000:.2f}ms"
        )
        step_start_time = time.time()

        if not success:
            print(
                f"⏱️ [CAPTAINS API] Service failed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            return create_response(400, "error", error or "Failed to get captains")

        # Step 3: Return response
        total_time = (time.time() - start_time) * 1000
        print(f"⏱️ [CAPTAINS API] Total API time: {total_time:.2f}ms")

        return response

    except Exception as e:
        total_time = (time.time() - start_time) * 1000
        print(f"⏱️ [CAPTAINS API] Error after {total_time:.2f}ms: {e}")
        print(f"Error getting club captains: {e}")
        return create_response(500, "error", f"Internal server error: {str(e)}")


@router.get("/clubs/{club_id}/moderators", response_model=ClubModeratorsResponse)
async def get_club_moderators(
    club_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=10, ge=1, le=100, description="Number of items per page"
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Get moderators of a club with pagination

    Args:
        club_id: Club ID to get moderators for
        page: Page number (1-based)
        page_size: Number of items per page (max 100)
        current_user: Current authenticated user

    Returns:
        ClubModeratorsResponse with paginated moderators data
    """
    import time

    start_time = time.time()
    step_start_time = time.time()

    try:
        print(f"⏱️ [MODERATORS API] Starting moderators API for club: {club_id}")

        # Step 1: Authentication check
        user_id = current_user.get("user_id")
        if not user_id:
            print(
                f"⏱️ [MODERATORS API] Auth check failed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            return create_response(401, "error", "User not authenticated")

        print(
            f"⏱️ [MODERATORS API] Auth check completed in {(time.time() - step_start_time)*1000:.2f}ms"
        )
        step_start_time = time.time()

        # Step 2: Call service method
        success, response, error = (
            await user_status_service.get_club_moderators_with_pagination(
                club_id, user_id, page, page_size
            )
        )

        print(
            f"⏱️ [MODERATORS API] Service call completed in {(time.time() - step_start_time)*1000:.2f}ms"
        )
        step_start_time = time.time()

        if not success:
            print(
                f"⏱️ [MODERATORS API] Service failed in {(time.time() - step_start_time)*1000:.2f}ms"
            )
            return create_response(400, "error", error or "Failed to get moderators")

        # Step 3: Return response
        total_time = (time.time() - start_time) * 1000
        print(f"⏱️ [MODERATORS API] Total API time: {total_time:.2f}ms")

        return response

    except Exception as e:
        total_time = (time.time() - start_time) * 1000
        print(f"⏱️ [MODERATORS API] Error after {total_time:.2f}ms: {e}")
        print(f"Error getting club moderators: {e}")
        return create_response(500, "error", f"Internal server error: {str(e)}")


@router.get("/clubs/{club_id}/members", response_model=ClubMembersResponse)
async def get_club_members(
    club_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=10, ge=1, le=100, description="Number of items per page"
    ),
    search: Optional[str] = Query(default=None, description="Search members by full name"),
    current_user: dict = Depends(get_current_user),
):
    """
    Get members of a club with pagination and optional search filtering (excludes captains and moderators)

    Args:
        club_id: Club ID to get members for
        page: Page number (1-based)
        page_size: Number of items per page (max 100)
        search: Optional search term to filter members by full name
        current_user: Current authenticated user

    Returns:
        ClubMembersResponse with paginated members data
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            return create_response(401, "error", "User not authenticated")

        success, response, error = (
            await user_status_service.get_club_members_with_pagination(
                club_id, user_id, page, page_size, search
            )
        )

        if not success:
            return create_response(400, "error", error or "Failed to get members")

        return response

    except Exception as e:
        print(f"Error getting club members: {e}")
        return create_response(500, "error", f"Internal server error: {str(e)}")


# Socket.IO endpoints removed - use main app endpoints instead
