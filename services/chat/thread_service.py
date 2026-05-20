from typing import List, Optional, Tuple
from datetime import datetime, timezone
import uuid
import logging

from .db import (
    get_threads_collection,
    get_thread_messages_collection,
    get_messages_collection,
)
from .models import (
    Thread,
    ThreadMessage,
    CreateThreadRequest,
    CreateThreadResponse,
    SendThreadMessageRequest,
    SendThreadMessageResponse,
    GetThreadsRequest,
    GetThreadsResponse,
    GetThreadMessagesRequest,
    GetThreadMessagesResponse,
    UpdateThreadRequest,
    UpdateThreadResponse,
    DeleteThreadRequest,
    DeleteThreadResponse,
    ReplyToThreadMessageRequest,
    ReplyToThreadMessageResponse,
    GetThreadMessageRepliesRequest,
    GetThreadMessageRepliesResponse,
    ThreadStatus,
    UserRole,
    MessageType,
    MessageContent,
    UserMention,
)
from .auth import check_club_access, get_chat_user

logger = logging.getLogger(__name__)


class ThreadService:
    def __init__(self):
        self.threads_collection = get_threads_collection()
        self.thread_messages_collection = get_thread_messages_collection()
        self.messages_collection = get_messages_collection()

    async def create_thread(
        self, request: CreateThreadRequest, user_data: dict
    ) -> Tuple[bool, CreateThreadResponse, Optional[str]]:
        """Create a new thread from a parent message"""
        try:
            # Check if user has access to the club
            has_access, access_details = await check_club_access(
                user_data["user_id"], request.club_id
            )
            if not has_access:
                return False, None, "Access denied to club"

            # Verify parent message exists
            parent_message = await self.messages_collection.find_one(
                {"message_id": request.parent_message_id, "club_id": request.club_id}
            )

            if not parent_message:
                return False, None, "Parent message not found"

            # Check if thread already exists for this message
            existing_thread = await self.threads_collection.find_one(
                {"parent_message_id": request.parent_message_id}
            )

            if existing_thread:
                return False, None, "Thread already exists for this message"

            # Create thread
            thread_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            thread_doc = {
                "thread_id": thread_id,
                "club_id": request.club_id,
                "parent_message_id": request.parent_message_id,
                "title": request.title,
                "created_by": user_data["user_id"],
                "created_by_username": user_data["username"],
                "created_by_full_name": user_data["full_name"],
                "status": ThreadStatus.ACTIVE.value,
                "message_count": 0,
                "last_message_at": None,
                "last_message_by": None,
                "last_message_by_username": None,
                "created_at": now,
                "updated_at": now,
            }

            await self.threads_collection.insert_one(thread_doc)

            # Create initial thread message
            thread_message_id = str(uuid.uuid4())

            # Parse mentions for the initial message
            mentions = await self._parse_mentions(
                request.initial_message, request.club_id
            )

            thread_message_doc = {
                "thread_message_id": thread_message_id,
                "thread_id": thread_id,
                "club_id": request.club_id,
                "sender_id": user_data["user_id"],
                "sender_username": user_data["username"],
                "sender_full_name": user_data["full_name"],
                "sender_avatar": user_data.get("avatar_url"),
                "sender_role": access_details["role"].value,
                "message_type": MessageType.TEXT.value,
                "content": {
                    "text": request.initial_message,
                    "mentions": [mention.dict() for mention in mentions],
                },
                "reactions": [],
                "reply_to_thread_message_id": None,
                "edited_at": None,
                "created_at": now,
                "updated_at": now,
            }

            await self.thread_messages_collection.insert_one(thread_message_doc)

            # Update thread with initial message info
            await self.threads_collection.update_one(
                {"thread_id": thread_id},
                {
                    "$set": {
                        "message_count": 1,
                        "last_message_at": now,
                        "last_message_by": user_data["user_id"],
                        "last_message_by_username": user_data["username"],
                        "updated_at": now,
                    }
                },
            )

            # Create response objects
            thread = Thread(**thread_doc)
            thread_message = ThreadMessage(**thread_message_doc)

            response = CreateThreadResponse(
                success=True,
                thread_id=thread_id,
                thread=thread,
                message="Thread created successfully",
            )

            logger.info(
                f"Thread created: {thread_id} for message {request.parent_message_id}"
            )
            return True, response, None

        except Exception as e:
            logger.error(f"Error creating thread: {e}")
            return False, None, f"Failed to create thread: {str(e)}"

    async def send_thread_message(
        self, request: SendThreadMessageRequest, user_data: dict
    ) -> Tuple[bool, SendThreadMessageResponse, Optional[str]]:
        """Send a message to a thread"""
        try:
            # Check if user has access to the club
            has_access, access_details = await check_club_access(
                user_data["user_id"], request.club_id
            )
            if not has_access:
                return False, None, "Access denied to club"

            # Verify thread exists and is active
            thread = await self.threads_collection.find_one(
                {"thread_id": request.thread_id, "club_id": request.club_id}
            )

            if not thread:
                return False, None, "Thread not found"

            if thread["status"] != ThreadStatus.ACTIVE.value:
                return False, None, "Thread is not active"

            # Create thread message
            thread_message_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            # Parse mentions
            mentions = await self._parse_mentions(request.content, request.club_id)

            thread_message_doc = {
                "thread_message_id": thread_message_id,
                "thread_id": request.thread_id,
                "club_id": request.club_id,
                "sender_id": user_data["user_id"],
                "sender_username": user_data["username"],
                "sender_full_name": user_data["full_name"],
                "sender_avatar": user_data.get("avatar_url"),
                "sender_role": access_details["role"].value,
                "message_type": request.message_type.value,
                "content": {
                    "text": request.content,
                    "mentions": [mention.dict() for mention in mentions],
                },
                "reactions": [],
                "reply_to_thread_message_id": request.reply_to_thread_message_id,
                "edited_at": None,
                "created_at": now,
                "updated_at": now,
            }

            await self.thread_messages_collection.insert_one(thread_message_doc)

            # Update thread with new message info
            await self.threads_collection.update_one(
                {"thread_id": request.thread_id},
                {
                    "$inc": {"message_count": 1},
                    "$set": {
                        "last_message_at": now,
                        "last_message_by": user_data["user_id"],
                        "last_message_by_username": user_data["username"],
                        "updated_at": now,
                    },
                },
            )

            # Create response
            thread_message = ThreadMessage(**thread_message_doc)

            response = SendThreadMessageResponse(
                success=True,
                thread_message_id=thread_message_id,
                thread_message=thread_message,
                message="Message sent successfully",
            )

            logger.info(
                f"Thread message sent: {thread_message_id} in thread {request.thread_id}"
            )
            return True, response, None

        except Exception as e:
            logger.error(f"Error sending thread message: {e}")
            return False, None, f"Failed to send message: {str(e)}"

    async def get_threads(
        self, request: GetThreadsRequest, user_data: dict
    ) -> Tuple[bool, GetThreadsResponse, Optional[str]]:
        """Get threads for a club with pagination"""
        try:
            # Check if user has access to the club
            has_access, access_details = await check_club_access(
                user_data["user_id"], request.club_id
            )
            if not has_access:
                return False, None, "Access denied to club"

            # Build query
            query = {"club_id": request.club_id}
            if request.status:
                query["status"] = request.status.value

            # Build sort
            sort_field = "created_at"
            if request.sort_by == "last_message":
                sort_field = "last_message_at"
            elif request.sort_by == "message_count":
                sort_field = "message_count"

            sort_direction = -1  # DESCENDING

            # Calculate pagination
            skip = (request.page - 1) * request.page_size

            # Get total count
            total_count = await self.threads_collection.count_documents(query)

            # Get threads
            cursor = (
                self.threads_collection.find(query)
                .sort(sort_field, sort_direction)
                .skip(skip)
                .limit(request.page_size)
            )
            threads_docs = await cursor.to_list(length=request.page_size)

            # Convert to Thread objects
            threads = [Thread(**doc) for doc in threads_docs]

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            response = GetThreadsResponse(
                success=True,
                threads=threads,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting threads: {e}")
            return False, None, f"Failed to get threads: {str(e)}"

    async def get_thread_messages(
        self, request: GetThreadMessagesRequest, user_data: dict
    ) -> Tuple[bool, GetThreadMessagesResponse, Optional[str]]:
        """Get messages for a specific thread with pagination"""
        try:
            # Check if user has access to the club
            has_access, access_details = await check_club_access(
                user_data["user_id"], request.club_id
            )
            if not has_access:
                return False, None, "Access denied to club"

            # Verify thread exists
            thread = await self.threads_collection.find_one(
                {"thread_id": request.thread_id, "club_id": request.club_id}
            )

            if not thread:
                return False, None, "Thread not found"

            # Calculate pagination
            skip = (request.page - 1) * request.page_size

            # Get total count
            total_count = await self.thread_messages_collection.count_documents(
                {"thread_id": request.thread_id}
            )

            # Get messages
            cursor = (
                self.thread_messages_collection.find({"thread_id": request.thread_id})
                .sort("created_at", 1)
                .skip(skip)
                .limit(request.page_size)
            )

            messages_docs = await cursor.to_list(length=request.page_size)

            # Convert to ThreadMessage objects
            messages = [ThreadMessage(**doc) for doc in messages_docs]

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            response = GetThreadMessagesResponse(
                success=True,
                thread=Thread(**thread),
                messages=messages,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting thread messages: {e}")
            return False, None, f"Failed to get thread messages: {str(e)}"

    async def update_thread(
        self, request: UpdateThreadRequest, user_data: dict
    ) -> Tuple[bool, UpdateThreadResponse, Optional[str]]:
        """Update thread title or status"""
        try:
            # Check if user has access to the club
            has_access, access_details = await check_club_access(
                user_data["user_id"], request.club_id
            )
            if not has_access:
                return False, None, "Access denied to club"

            # Verify thread exists
            thread = await self.threads_collection.find_one(
                {"thread_id": request.thread_id, "club_id": request.club_id}
            )

            if not thread:
                return False, None, "Thread not found"

            # Check if user is thread creator or moderator/captain
            if thread["created_by"] != user_data["user_id"] and access_details[
                "role"
            ] not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
                return False, None, "Insufficient permissions to update thread"

            # Build update data
            update_data = {"updated_at": datetime.now(timezone.utc)}
            if request.title is not None:
                update_data["title"] = request.title
            if request.status is not None:
                update_data["status"] = request.status.value

            # Update thread
            await self.threads_collection.update_one(
                {"thread_id": request.thread_id}, {"$set": update_data}
            )

            # Get updated thread
            updated_thread = await self.threads_collection.find_one(
                {"thread_id": request.thread_id}
            )

            response = UpdateThreadResponse(
                success=True,
                thread=Thread(**updated_thread),
                message="Thread updated successfully",
            )

            logger.info(f"Thread updated: {request.thread_id}")
            return True, response, None

        except Exception as e:
            logger.error(f"Error updating thread: {e}")
            return False, None, f"Failed to update thread: {str(e)}"

    async def delete_thread(
        self, request: DeleteThreadRequest, user_data: dict
    ) -> Tuple[bool, DeleteThreadResponse, Optional[str]]:
        """Delete a thread and all its messages"""
        try:
            # Check if user has access to the club
            has_access, access_details = await check_club_access(
                user_data["user_id"], request.club_id
            )
            if not has_access:
                return False, None, "Access denied to club"

            # Verify thread exists
            thread = await self.threads_collection.find_one(
                {"thread_id": request.thread_id, "club_id": request.club_id}
            )

            if not thread:
                return False, None, "Thread not found"

            # Check if user is thread creator or moderator/captain
            if thread["created_by"] != user_data["user_id"] and access_details[
                "role"
            ] not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
                return False, None, "Insufficient permissions to delete thread"

            # Delete thread messages
            await self.thread_messages_collection.delete_many(
                {"thread_id": request.thread_id}
            )

            # Delete thread
            await self.threads_collection.delete_one({"thread_id": request.thread_id})

            response = DeleteThreadResponse(
                success=True, message="Thread deleted successfully"
            )

            logger.info(f"Thread deleted: {request.thread_id}")
            return True, response, None

        except Exception as e:
            logger.error(f"Error deleting thread: {e}")
            return False, None, f"Failed to delete thread: {str(e)}"

    async def _parse_mentions(self, text: str, club_id: str) -> List[UserMention]:
        """Parse @mentions from message text and return user mention objects"""
        mentions = []

        # Find all @mentions in the text
        mention_pattern = r"@(\w+)"
        import re

        matches = re.finditer(mention_pattern, text)

        for match in matches:
            username = match.group(1)
            start_pos = match.start()
            end_pos = match.end()

            # Find user by username (you might need to adjust this based on your user schema)
            from .db import get_user_collection

            users_collection = get_user_collection()

            user = await users_collection.find_one(
                {
                    "$or": [
                        {"username": username},
                        {"full_name": {"$regex": f"^{username}$", "$options": "i"}},
                    ]
                }
            )

            if user:
                mention = UserMention(
                    user_id=str(user["_id"]),
                    username=username,
                    full_name=user["full_name"],
                    position_start=start_pos,
                    position_end=end_pos,
                )
                mentions.append(mention)

        return mentions

    async def reply_to_thread_message(
        self, request: ReplyToThreadMessageRequest, current_user: dict
    ) -> Tuple[bool, Optional[ReplyToThreadMessageResponse], Optional[str]]:
        """Reply to a specific thread message"""
        try:
            # Check club access
            has_access, access_details = await check_club_access(
                current_user["user_id"], request.club_id
            )
            if not has_access:
                return False, None, "Access denied to club"

            # Verify thread exists and user has access
            thread = await self.threads_collection.find_one(
                {"thread_id": request.thread_id, "club_id": request.club_id}
            )
            if not thread:
                return False, None, "Thread not found"

            # Get the message being replied to
            reply_to_message = await self.thread_messages_collection.find_one(
                {
                    "thread_message_id": request.reply_to_thread_message_id,
                    "thread_id": request.thread_id,
                    "club_id": request.club_id,
                }
            )
            if not reply_to_message:
                return False, None, "Message to reply to not found"

            # Calculate reply depth
            reply_depth = reply_to_message.get("reply_depth", 0) + 1
            if reply_depth > 5:  # Limit nesting depth
                return False, None, "Maximum reply depth exceeded"

            # Get user details
            chat_user = await get_chat_user(current_user["user_id"], access_details)
            if not chat_user:
                return False, None, "User not found"

            # Create thread message
            thread_message_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            # Create message content
            message_content = MessageContent(text=request.content, mentions=[])

            thread_message_data = {
                "thread_message_id": thread_message_id,
                "thread_id": request.thread_id,
                "club_id": request.club_id,
                "sender_id": chat_user.user_id,
                "sender_username": chat_user.username,
                "sender_full_name": chat_user.full_name,
                "sender_avatar": chat_user.avatar_url,
                "sender_role": chat_user.role,
                "message_type": request.message_type,
                "content": message_content.dict(),
                "reactions": [],
                "reply_to_thread_message_id": request.reply_to_thread_message_id,
                "reply_to_message_content": reply_to_message.get("content", {}).get(
                    "text", ""
                )[
                    :100
                ],  # Preview
                "reply_to_sender_username": reply_to_message.get("sender_username", ""),
                "reply_depth": reply_depth,
                "created_at": now,
                "updated_at": now,
            }

            # Insert thread message
            await self.thread_messages_collection.insert_one(thread_message_data)

            # Update thread's last message info
            await self.threads_collection.update_one(
                {"thread_id": request.thread_id},
                {
                    "$set": {
                        "last_message_at": now,
                        "last_message_by": chat_user.user_id,
                        "last_message_by_username": chat_user.username,
                        "updated_at": now,
                    },
                    "$inc": {"message_count": 1},
                },
            )

            # Create response
            thread_message = ThreadMessage(**thread_message_data)
            reply_to_thread_message = ThreadMessage(**reply_to_message)

            response = ReplyToThreadMessageResponse(
                success=True,
                thread_message_id=thread_message_id,
                thread_message=thread_message,
                reply_to_message=reply_to_thread_message,
                message="Reply sent successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error replying to thread message: {e}")
            return False, None, f"Failed to send reply: {str(e)}"

    async def get_thread_message_replies(
        self, request: GetThreadMessageRepliesRequest, current_user: dict
    ) -> Tuple[bool, Optional[GetThreadMessageRepliesResponse], Optional[str]]:
        """Get replies to a specific thread message"""
        try:
            # Check club access
            has_access, access_details = await check_club_access(
                current_user["user_id"], request.club_id
            )
            if not has_access:
                return False, None, "Access denied to club"

            # Verify thread exists
            thread = await self.threads_collection.find_one(
                {"thread_id": request.thread_id, "club_id": request.club_id}
            )
            if not thread:
                return False, None, "Thread not found"

            # Verify parent message exists
            parent_message = await self.thread_messages_collection.find_one(
                {
                    "thread_message_id": request.thread_message_id,
                    "thread_id": request.thread_id,
                    "club_id": request.club_id,
                }
            )
            if not parent_message:
                return False, None, "Parent message not found"

            # Calculate pagination
            skip = (request.page - 1) * request.page_size

            # Get replies
            replies_cursor = (
                self.thread_messages_collection.find(
                    {
                        "reply_to_thread_message_id": request.thread_message_id,
                        "thread_id": request.thread_id,
                        "club_id": request.club_id,
                    }
                )
                .sort("created_at", 1)
                .skip(skip)
                .limit(request.page_size)
            )

            replies = []
            async for reply in replies_cursor:
                replies.append(ThreadMessage(**reply))

            # Get total count
            total_count = await self.thread_messages_collection.count_documents(
                {
                    "reply_to_thread_message_id": request.thread_message_id,
                    "thread_id": request.thread_id,
                    "club_id": request.club_id,
                }
            )

            # Calculate pagination info
            total_pages = (total_count + request.page_size - 1) // request.page_size
            has_next = request.page < total_pages
            has_previous = request.page > 1

            response = GetThreadMessageRepliesResponse(
                success=True,
                replies=replies,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous,
                message="Replies retrieved successfully",
            )

            return True, response, None

        except Exception as e:
            logger.error(f"Error getting thread message replies: {e}")
            return False, None, f"Failed to get replies: {str(e)}"


# Create service instance
thread_service = ThreadService()
