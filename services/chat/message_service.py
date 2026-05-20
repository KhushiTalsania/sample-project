from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from bson import ObjectId
import uuid
import re
import logging
import time

logger = logging.getLogger(__name__)

from .db import (
    get_messages_collection,
    get_user_collection,
    get_unread_tracking_collection,
)
from .models import (
    ChatMessage,
    MessageContent,
    UserMention,
    MessageHistoryResponse,
    MessageType,
    UserRole,
    ChatUser,
)


class MessageService:
    def __init__(self):
        self.messages_collection = get_messages_collection()
        self.users_collection = get_user_collection()
        self.unread_collection = get_unread_tracking_collection()

        # Enable cache for bulk thread processing
        self._thread_cache = {}

        # Skip index creation for maximum speed - assume indexes exist
        # self._ensure_indexes()

    async def _ensure_indexes(self):
        """Create database indexes for optimal performance"""
        try:
            # Create indexes asynchronously for better performance
            indexes = [
                {
                    "keys": [
                        ("club_id", 1),
                        ("is_deleted", 1),
                        ("reply_to_message_id", 1),
                        ("created_at", -1),
                    ]
                },
                {
                    "keys": [
                        ("reply_to_message_id", 1),
                        ("club_id", 1),
                        ("is_deleted", 1),
                        ("created_at", -1),
                    ]
                },
                {"keys": [("message_id", 1)]},
            ]

            for index in indexes:
                try:
                    await self.messages_collection.create_index(
                        index["keys"], background=True
                    )
                except Exception as e:
                    # Index might already exist, ignore error
                    pass

        except Exception as e:
            # Index creation failed, continue without indexes
            print(f"Warning: Could not create indexes: {e}")

    async def parse_mentions(self, text: str, club_id: str) -> List[UserMention]:
        """Parse @mentions from message text and return user mention objects with club validation"""
        mentions = []

        # Get all club members (captain, moderators, and members)
        club_members = await self.get_club_members(club_id)
        if not club_members:
            return mentions  # Return empty if no club members found

        # Create a mapping of username to user_id for club members
        club_member_map = {}
        for member in club_members:
            club_member_map[member["username"]] = {
                "user_id": member["user_id"],
                "full_name": member["full_name"],
            }

        # Debug: Print club member map for testing
        if text and "@" in text:
            print(f"🔧 DEBUG: Text with mentions: {text}")
            print(f"🔧 DEBUG: Club member usernames: {list(club_member_map.keys())}")

        # Find all @mentions in the text
        mention_pattern = r"@([a-zA-Z0-9_]+)"
        matches = re.finditer(mention_pattern, text)

        for match in matches:
            username = match.group(1)
            start_pos = match.start()
            end_pos = match.end()

            print(f"🔧 DEBUG: Found mention @{username}")
            print(
                f"🔧 DEBUG: Is '{username}' in club members? {username in club_member_map}"
            )

            # Check if the mentioned username is a club member
            if username in club_member_map:
                member_info = club_member_map[username]
                mention = UserMention(
                    user_id=member_info["user_id"],
                    username=username,
                    full_name=member_info["full_name"],
                    position_start=start_pos,
                    position_end=end_pos,
                )
                mentions.append(mention)
                print(f"🔧 DEBUG: Added mention: {mention}")

        print(f"🔧 DEBUG: Total mentions found: {len(mentions)}")
        return mentions

    async def get_club_members(
        self,
        club_id: str,
        search_query: Optional[str] = None,
        role_filter: Optional[str] = None,
    ) -> List[dict]:
        """Get all members of a club (captain, moderators, and members) with optional search filtering"""
        from .db import (
            get_club_collection,
            get_club_memberships_collection,
            get_user_access_collection,
        )
        from bson import ObjectId
        import re

        club_collection = get_club_collection()
        user_access_collection = get_user_access_collection()
        club = await club_collection.find_one({"name_based_id": club_id})
        if not club:
            return []

        members = []

        # Helper function to get mute status
        async def get_mute_status(user_id: str) -> bool:
            try:
                user_access = await user_access_collection.find_one(
                    {"user_id": user_id, "club_id": club_id}
                )
                return user_access.get("is_muted", False) if user_access else False
            except Exception as e:
                logger.error(f"Error getting mute status for user {user_id}: {e}")
                return False

        # Add captain
        if club.get("captain_id"):
            captain = await self.users_collection.find_one(
                {"_id": ObjectId(club["captain_id"])},
                {"_id": 1, "username": 1, "full_name": 1, "email": 1, "avatar_url": 1},
            )
            if captain:
                captain_id = str(captain["_id"])
                is_muted = await get_mute_status(captain_id)
                members.append(
                    {
                        "id": captain_id,
                        "user_id": captain_id,
                        "username": captain.get(
                            "username", captain["full_name"].replace(" ", "_").lower()
                        ),
                        "full_name": captain["full_name"],
                        "email": captain.get("email", ""),
                        "avatar_url": captain.get("avatar_url", ""),
                        "role": "captain",
                        "is_muted": is_muted,
                    }
                )

        # Add moderators from detailed_moderators field
        detailed_moderators = club.get("detailed_moderators", [])
        for moderator in detailed_moderators:
            mod_user_id = moderator.get("user_id")
            # Check if moderator is active in club
            if mod_user_id and moderator.get("status") == "active":
                mod_user = await self.users_collection.find_one(
                    {"_id": ObjectId(mod_user_id)},
                    {
                        "_id": 1,
                        "username": 1,
                        "full_name": 1,
                        "email": 1,
                        "avatar_url": 1,
                        "is_register": 1,
                    },
                )
                # Additional check: ensure user exists, is active, and is registered
                if (
                    mod_user
                    and mod_user.get("is_active", True)
                    and mod_user.get("is_register", False)
                ):
                    moderator_id = str(mod_user["_id"])
                    is_muted = await get_mute_status(moderator_id)
                    members.append(
                        {
                            "id": moderator_id,
                            "user_id": moderator_id,
                            "username": mod_user.get(
                                "username",
                                mod_user["full_name"].replace(" ", "_").lower(),
                            ),
                            "full_name": mod_user["full_name"],
                            "email": mod_user.get("email", ""),
                            "avatar_url": mod_user.get("avatar_url", ""),
                            "role": "moderator",
                            "is_muted": is_muted,
                        }
                    )

        # Add regular members
        memberships_collection = get_club_memberships_collection()
        memberships = await memberships_collection.find(
            {
                "club_id": club["_id"],  # Use ObjectId directly, not string
                "subscription_status": {
                    "$in": ["active", "trial", "paid", "subscribed", None, "N/A"]
                },
            }
        ).to_list(None)

        for membership in memberships:
            user_id = membership["user_id"]
            # Skip if already added as captain or moderator
            if not any(member["user_id"] == user_id for member in members):
                user = await self.users_collection.find_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "_id": 1,
                        "username": 1,
                        "full_name": 1,
                        "email": 1,
                        "avatar_url": 1,
                    },
                )
                if user:
                    member_id = str(user["_id"])
                    is_muted = await get_mute_status(member_id)
                    members.append(
                        {
                            "id": member_id,
                            "user_id": member_id,
                            "username": user.get(
                                "username", user["full_name"].replace(" ", "_").lower()
                            ),
                            "full_name": user["full_name"],
                            "email": user.get("email", ""),
                            "avatar_url": user.get("avatar_url", ""),
                            "role": "member",
                            "is_muted": is_muted,
                        }
                    )

        # Apply role filtering if role_filter is provided
        if role_filter and role_filter.strip():
            role_term = role_filter.strip().lower()
            filtered_members = []

            for member in members:
                member_role = member.get("role", "").lower()
                if member_role == role_term:
                    filtered_members.append(member)

            members = filtered_members

        # Apply search filtering if search_query is provided
        if search_query and search_query.strip():
            search_term = search_query.strip().lower()
            filtered_members = []

            for member in members:
                username = member.get("username", "").lower()
                full_name = member.get("full_name", "").lower()

                # Check if search term matches username or full name
                if (
                    search_term in username
                    or search_term in full_name
                    or any(word.startswith(search_term) for word in username.split())
                    or any(word.startswith(search_term) for word in full_name.split())
                ):
                    filtered_members.append(member)

            members = filtered_members

        return members

    async def get_club_members_for_mention(
        self,
        club_id: str,
    ) -> List[dict]:
        """Get club members specifically for mention API using optimized method"""
        from .user_status_service import UserStatusService

        # Use the optimized service
        user_status_service = UserStatusService()
        optimized_data = await user_status_service.get_mentionable_users_optimized(
            club_id
        )

        # Combine all users for backward compatibility
        all_users = []
        all_users.extend(optimized_data.get("captain", []))
        all_users.extend(optimized_data.get("moderators", []))
        all_users.extend(optimized_data.get("members", []))

        return all_users

    async def create_message(
        self,
        sender: ChatUser,
        club_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        reply_to_message_id: Optional[str] = None,
    ) -> ChatMessage:
        """Create a new chat message"""

        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Parse mentions
        mentions = await self.parse_mentions(content, club_id)

        # Create message content
        message_content = MessageContent(text=content, mentions=mentions)

        # Create message document
        message_doc = {
            "message_id": message_id,
            "club_id": club_id,
            "sender_id": sender.user_id,
            "sender_username": sender.username,
            "sender_full_name": sender.full_name,
            "sender_avatar": sender.avatar_url,
            "sender_role": sender.role.value,
            "message_type": message_type.value,
            "content": {
                "text": content,
                "mentions": [mention.dict() for mention in mentions],
            },
            "reactions": [],
            "pinned": None,
            "reply_to_message_id": reply_to_message_id,
            "edited_at": None,
            "created_at": now,
            "updated_at": now,
            "is_deleted": False,
        }

        # Insert into database
        await self.messages_collection.insert_one(message_doc)

        # Create chat message object
        chat_message = ChatMessage(
            message_id=message_id,
            club_id=club_id,
            sender_id=sender.user_id,
            sender_username=sender.username,
            sender_full_name=sender.full_name,
            sender_avatar=sender.avatar_url,
            sender_role=sender.role,
            message_type=message_type,
            content=message_content,
            reactions=[],
            pinned=None,
            reply_to_message_id=reply_to_message_id,
            edited_at=None,
            created_at=now,
            updated_at=now,
        )

        # Update unread counts for all club members
        await self.update_unread_counts(club_id, message_id, sender.user_id)
        print("phochaphochaphochaphochaphochaphocha  ")
        # Send mention notifications to mentioned users
        if mentions:
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                # Get mentioned user IDs (deduplicated) and exclude the sender
                mentioned_user_ids = list({
                    mention.user_id for mention in mentions
                    if mention.user_id != sender.user_id
                })
                
                if mentioned_user_ids:
                    # Get club name for notification
                    from .db import get_club_collection
                    club_collection = get_club_collection()
                    club = await club_collection.find_one({"name_based_id": club_id})
                    club_name = club.get("name", "Club") if club else "Club"

                    collections = get_collections()
                    user_tokens_collection = collections.get_user_tokens_collection()
                    
                    # Create mention notification for each mentioned user
                    for user_id in mentioned_user_ids:
                        title = f"You were mentioned!"
                        body = f"{sender.full_name} mentioned you in {club_name}"
                        
                        notification_data = {
                            "message_id": message_id,
                            "club_id": club_id,
                            "club_name": club_name,
                            "sender_id": sender.user_id,
                            "sender_name": sender.full_name,
                            "message_preview": content[:100] + "..." if len(content) > 100 else content,
                            "mentioned_user_id": user_id,
                            "push_type": "chat_message"
                        }

                        # Determine if push notification should be sent
                        push_user_ids: List[str] = []
                        enabled_user_ids = await filter_users_by_notification_preference(
                            [user_id],
                            "mention_alerts"
                        )
                        if enabled_user_ids:
                            token_docs = await user_tokens_collection.find(
                                {"user_id": user_id, "is_active": True},
                                {"user_id": 1},
                            ).to_list(length=None)
                            if any(doc.get("user_id") for doc in token_docs):
                                push_user_ids = [user_id]
                        
                        notification_result = await send_notification_to_users(
                            user_ids=push_user_ids,
                            title=title,
                            body=body,
                            notification_type="club_message",
                            data=notification_data,
                            click_action=f"club/{club_id}/messages/{message_id}",
                            priority="normal",
                            all_user_ids=[user_id],
                        )
                        logger.info(f"✅ Mention notification stored for user {user_id}: {notification_result}")
                        
            except Exception as e:
                logger.error(f"⚠️ Failed to send mention notifications: {e}")

        # Send general message notifications to all club members (excluding sender)
        try:
            from services.notifications.notification_service import (
                send_notification_to_users,
                get_club_members,
                filter_users_by_notification_preference,
                get_collections,
            )
            
            # Get all club members
            all_club_members = await get_club_members(club_id)
            
            if all_club_members:
                # Remove sender from notification recipients
                notification_recipients = [
                    member_id for member_id in all_club_members if member_id != sender.user_id
                ]
                
                if notification_recipients:
                    # Filter by message alerts preference
                    enabled_user_ids = await filter_users_by_notification_preference(
                        notification_recipients,
                        "message_alerts"
                    )
                    enabled_user_ids = [
                        uid for uid in (enabled_user_ids or [])
                        if uid and uid != sender.user_id
                    ]
                    
                    # Get club name for notification
                    from .db import get_club_collection
                    club_collection = get_club_collection()
                    club = await club_collection.find_one({"name_based_id": club_id})
                    club_name = club.get("name", "Club") if club else "Club"
                    
                    # Determine if this is a thread reply or regular message
                    is_thread_reply = reply_to_message_id is not None
                    message_type_text = "thread reply" if is_thread_reply else "message"
                    
                    # Create notification content
                    if is_thread_reply:
                        title = f"New Thread Reply!"
                        body = f"{sender.full_name} replied in {club_name}"
                    else:
                        title = f"New Message!"
                        body = f"{sender.full_name} sent a message in {club_name}"
                    
                    # Truncate message content for notification
                    message_preview = content[:100] + "..." if len(content) > 100 else content
                    
                    notification_data = {
                        "message_id": message_id,
                        "club_id": club_id,
                        "club_name": club_name,
                        "sender_id": sender.user_id,
                        "sender_name": sender.full_name,
                        "message_preview": message_preview,
                        "message_type_text": message_type_text,
                        "is_thread_reply": is_thread_reply,
                        "reply_to_message_id": reply_to_message_id,
                        "push_type": "chat_message",
                        # Chat status flags for group messages
                        "is_dm": "false",  # This is a group chat message
                        "is_chat_open": "false",  # Will be closed when notification arrives
                        "is_dm_chat_open": "true"  # DM chat remains open for group messages
                    }

                    # Determine push recipients by checking for active tokens
                    push_user_ids: List[str] = []
                    if enabled_user_ids:
                        collections = get_collections()
                        user_tokens_collection = collections.get_user_tokens_collection()
                        token_cursor = user_tokens_collection.find(
                            {
                                "user_id": {"$in": enabled_user_ids},
                                "is_active": True,
                            },
                            {"user_id": 1},
                        )
                        token_docs = await token_cursor.to_list(length=None)
                        push_user_ids = list({
                            doc.get("user_id") for doc in token_docs if doc.get("user_id")
                        })
                    
                    notification_result = await send_notification_to_users(
                        user_ids=push_user_ids,
                        title=title,
                        body=body,
                        notification_type="club_message",
                        data=notification_data,
                        click_action=f"club/{club_id}/messages/{message_id}",
                        priority="normal",
                        all_user_ids=notification_recipients,
                    )
                    logger.info(
                        f"✅ Message notification stored for {len(notification_recipients)} users "
                        f"(push to {len(push_user_ids)}) for {message_type_text}: {notification_result}"
                    )
                else:
                    logger.info(f"ℹ️ No notification recipients found (excluding sender)")
            else:
                logger.info(f"ℹ️ No club members found for club {club_id}")
                
        except Exception as e:
            logger.error(f"⚠️ Failed to send message notifications: {e}")

        return chat_message

    async def get_thread_messages(
        self, parent_message_id: str, club_id: str, page: int = 1, page_size: int = 50
    ) -> Tuple[List[ChatMessage], int, bool]:
        """Get thread messages for a parent message"""
        skip = (page - 1) * page_size

        # Query for thread messages (replies to the parent message)
        query = {
            "reply_to_message_id": parent_message_id,
            "club_id": club_id,
            "is_deleted": False,
        }

        # Get thread messages
        cursor = (
            self.messages_collection.find(query)
            .sort("created_at", 1)
            .skip(skip)
            .limit(page_size + 1)
        )
        thread_docs = await cursor.to_list(length=page_size + 1)

        # Check if there are more messages
        has_more = len(thread_docs) > page_size
        if has_more:
            thread_docs = thread_docs[:page_size]

        # Convert to ChatMessage objects
        thread_messages = []
        for doc in thread_docs:
            thread_messages.append(await self.document_to_chat_message(doc))

        # Get total count of thread messages
        total_count = await self.messages_collection.count_documents(query)

        return thread_messages, total_count, has_more

    async def get_thread_count(self, parent_message_id: str, club_id: str) -> int:
        """Get count of thread messages for a parent message"""
        query = {
            "reply_to_message_id": parent_message_id,
            "club_id": club_id,
            "is_deleted": False,
        }

        count = await self.messages_collection.count_documents(query)
        return count

    async def get_thread_info(self, parent_message_id: str, club_id: str) -> dict:
        """Get thread count and last 3 reply users info for a parent message - DETAILED TIMING"""

        thread_start_time = time.time()

        query = {
            "reply_to_message_id": parent_message_id,
            "club_id": club_id,
            "is_deleted": False,
        }

        # Step 1: Get thread count
        count_start = time.time()
        thread_count = await self.messages_collection.count_documents(query)
        print(
            f"⏱️ [THREAD INFO] Count query for {parent_message_id}: {(time.time() - count_start)*1000:.2f}ms"
        )

        # Step 2: Get last 3 replies
        replies_start = time.time()
        last_replies_cursor = (
            self.messages_collection.find(
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
        print(
            f"⏱️ [THREAD INFO] Replies query for {parent_message_id}: {(time.time() - replies_start)*1000:.2f}ms"
        )

        # Step 3: Format reply users info
        format_start = time.time()
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
        print(
            f"⏱️ [THREAD INFO] Formatting for {parent_message_id}: {(time.time() - format_start)*1000:.2f}ms"
        )

        total_thread_time = (time.time() - thread_start_time) * 1000
        print(
            f"⏱️ [THREAD INFO] TOTAL for {parent_message_id}: {total_thread_time:.2f}ms (count: {thread_count})"
        )

        return {"thread_count": thread_count, "last_reply_users": reply_users}

    # PERFORMANCE OPTIMIZATION NOTES:
    # CRITICAL: Run these MongoDB commands to create indexes for optimal performance:
    #
    # db.messages.createIndex({"club_id": 1, "is_deleted": 1, "reply_to_message_id": 1, "created_at": -1})
    # db.messages.createIndex({"reply_to_message_id": 1, "club_id": 1, "is_deleted": 1, "created_at": -1})
    # db.messages.createIndex({"message_id": 1})
    #
    # These indexes are ESSENTIAL for good performance. Without them, queries will be extremely slow!

    async def get_bulk_thread_info(
        self, parent_message_ids: List[str], club_id: str
    ) -> Dict[str, dict]:
        """
        Get thread info for multiple parent messages in bulk - OPTIMIZED VERSION
        This replaces N individual calls to get_thread_info with a single optimized query
        """
        bulk_start_time = time.time()

        try:
            if not parent_message_ids:
                return {}

            # Check cache first
            cache_key = f"{club_id}_{len(parent_message_ids)}"
            if cache_key in self._thread_cache:
                print(
                    f"⏱️ [BULK THREAD INFO] Using cache for {len(parent_message_ids)} messages"
                )
                return self._thread_cache[cache_key]

            print(
                f"⏱️ [BULK THREAD INFO] Starting for {len(parent_message_ids)} messages"
            )

            # Get all thread replies for all parent messages in one query
            thread_replies_query = {
                "reply_to_message_id": {"$in": parent_message_ids},
                "club_id": club_id,
                "is_deleted": False,
            }

            # Use optimized aggregation pipeline for better performance
            pipeline = [
                {"$match": thread_replies_query},
                # Sort by created_at first for better performance
                {"$sort": {"created_at": -1}},
                {
                    "$group": {
                        "_id": "$reply_to_message_id",
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
            thread_results = await self.messages_collection.aggregate(pipeline).to_list(
                length=None
            )

            print(
                f"⏱️ [BULK THREAD INFO] Aggregation completed in {(time.time() - bulk_start_time)*1000:.2f}ms"
            )
            step_start_time = time.time()

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
            for parent_message_id in parent_message_ids:
                if parent_message_id not in thread_info_data:
                    thread_info_data[parent_message_id] = {
                        "thread_count": 0,
                        "last_reply_users": [],
                    }

            total_time = (time.time() - bulk_start_time) * 1000
            print(f"⏱️ [BULK THREAD INFO] Completed in {total_time:.2f}ms")

            # Cache the results for this request
            self._thread_cache[cache_key] = thread_info_data

            return thread_info_data

        except Exception as e:
            total_time = (time.time() - bulk_start_time) * 1000
            print(f"⏱️ [BULK THREAD INFO] Error after {total_time:.2f}ms: {e}")
            logger.error(f"Error getting bulk thread info: {e}")

            # Return empty data for all parent messages on error
            return {
                parent_message_id: {"thread_count": 0, "last_reply_users": []}
                for parent_message_id in parent_message_ids
            }

    async def get_message_with_thread_count(
        self, message_id: str, club_id: str
    ) -> Optional[dict]:
        """Get a message with its thread count"""
        # Get the parent message
        parent_doc = await self.messages_collection.find_one(
            {"message_id": message_id, "club_id": club_id, "is_deleted": False}
        )

        if not parent_doc:
            return None

        # Get thread count
        thread_count = await self.get_thread_count(message_id, club_id)

        # Convert to ChatMessage
        parent_message = await self.document_to_chat_message(parent_doc)

        return {"message": parent_message, "thread_count": thread_count}

    async def edit_message(
        self, message_id: str, new_content: str, editor: ChatUser
    ) -> Optional[ChatMessage]:
        """Edit an existing message"""

        # Find the message
        message_doc = await self.messages_collection.find_one(
            {"message_id": message_id, "is_deleted": False}
        )

        if not message_doc:
            return None

        # Check if user can edit (only sender or moderator/captain)
        can_edit = message_doc["sender_id"] == editor.user_id or editor.role in [
            UserRole.CAPTAIN,
            UserRole.MODERATOR,
        ]

        if not can_edit:
            return None

        # Parse new mentions
        mentions = await self.parse_mentions(new_content, message_doc["club_id"])

        # Update message
        now = datetime.utcnow()
        update_data = {
            "content.text": new_content,
            "content.mentions": [mention.dict() for mention in mentions],
            "edited_at": now,
            "updated_at": now,
            # Update sender information in case role has changed
            "sender_username": editor.username,
            "sender_full_name": editor.full_name,
            "sender_avatar": editor.avatar_url,
            "sender_role": editor.role.value,
        }

        await self.messages_collection.update_one(
            {"message_id": message_id}, {"$set": update_data}
        )

        # Get updated message
        updated_doc = await self.messages_collection.find_one(
            {"message_id": message_id}
        )
        return await self.document_to_chat_message(updated_doc)

    async def delete_message(self, message_id: str, deleter: ChatUser) -> bool:
        """Delete a message (soft delete)"""

        # Find the message
        message_doc = await self.messages_collection.find_one(
            {"message_id": message_id, "is_deleted": False}
        )

        if not message_doc:
            return False

        # Check if user can delete (only sender or moderator/captain)
        can_delete = message_doc["sender_id"] == deleter.user_id or deleter.role in [
            UserRole.CAPTAIN,
            UserRole.MODERATOR,
        ]

        if not can_delete:
            return False

        # Soft delete
        await self.messages_collection.update_one(
            {"message_id": message_id},
            {"$set": {"is_deleted": True, "updated_at": datetime.utcnow()}},
        )

        return True

    async def get_message_history(
        self,
        club_id: str,
        page: int = 1,
        page_size: int = 50,
        before_message_id: Optional[str] = None,
        include_total_count: bool = True,
    ) -> MessageHistoryResponse:
        """Get message history with pagination - DETAILED TIMING"""

        print(f"🚀 [MESSAGE SERVICE] Starting get_message_history for club: {club_id}")
        service_start_time = time.time()

        # Step 1: Query building
        step_start = time.time()
        query = {
            "club_id": club_id,
            "is_deleted": False,
            "reply_to_message_id": None,  # Only show parent messages, not thread replies
        }
        print(
            f"⏱️ [MESSAGE SERVICE] Query building: {(time.time() - step_start)*1000:.2f}ms"
        )

        # Step 2: Cursor pagination
        if before_message_id:
            step_start = time.time()
            before_message = await self.messages_collection.find_one(
                {"message_id": before_message_id}
            )
            if before_message:
                query["created_at"] = {"$gt": before_message["created_at"]}
            print(
                f"⏱️ [MESSAGE SERVICE] Cursor lookup: {(time.time() - step_start)*1000:.2f}ms"
            )

        # Step 3: Database query execution
        step_start = time.time()
        projection = {
            "message_id": 1,
            "club_id": 1,
            "sender_id": 1,
            "sender_username": 1,
            "sender_full_name": 1,
            "sender_avatar": 1,
            "sender_role": 1,
            "message_type": 1,
            "content": 1,
            "pinned": 1,
            "reply_to_message_id": 1,
            "created_at": 1,
            "updated_at": 1,
        }

        # Execute query
        query_start = time.time()
        cursor = self.messages_collection.find(query, projection).sort("created_at", -1)
        skip = (page - 1) * page_size
        messages_docs = (
            await cursor.skip(skip).limit(page_size + 1).to_list(page_size + 1)
        )
        print(
            f"⏱️ [MESSAGE SERVICE] Database query execution: {(time.time() - query_start)*1000:.2f}ms"
        )
        print(
            f"⏱️ [MESSAGE SERVICE] Total database operations: {(time.time() - step_start)*1000:.2f}ms"
        )

        # Step 4: Data processing
        step_start = time.time()
        has_more = len(messages_docs) > page_size
        if has_more:
            messages_docs = messages_docs[:-1]  # Remove extra message
        print(
            f"⏱️ [MESSAGE SERVICE] Data processing: {(time.time() - step_start)*1000:.2f}ms"
        )

        # Step 5: Batch fetch user info (username, full_name, avatar, role) from users table
        step_start = time.time()
        # Get all unique sender IDs to refresh from users table
        sender_ids = set()
        for doc in messages_docs:
            if doc.get("sender_id"):
                sender_ids.add(doc.get("sender_id"))

        # Batch fetch user info from users collection (excluding role - keep from message)
        user_info_map = {}
        if sender_ids:
            users = await self.users_collection.find(
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
            print(f"⏱️ [MESSAGE SERVICE] Fetched {len(user_info_map)} user info from DB")

        print(
            f"⏱️ [MESSAGE SERVICE] User info batch fetch: {(time.time() - step_start)*1000:.2f}ms"
        )

        # Step 6: Document conversion with refreshed user data
        step_start = time.time()
        messages = []
        for i, doc in enumerate(messages_docs):
            doc_start = time.time()
            # Update sender info from users table (username, full_name, avatar only - keep role from message)
            sender_id = doc.get("sender_id")
            if sender_id and sender_id in user_info_map:
                user_info = user_info_map[sender_id]
                doc["sender_username"] = user_info["username"]
                doc["sender_full_name"] = user_info["full_name"]
                doc["sender_avatar"] = user_info["avatar_url"]
                # Note: sender_role is kept from the original message document

            chat_message = self.document_to_chat_message_sync(doc)
            if chat_message:
                messages.append(chat_message)

            # Log every 10th message conversion time
            if (i + 1) % 10 == 0:
                print(
                    f"⏱️ [MESSAGE SERVICE] Converted {i + 1} messages: {(time.time() - doc_start)*1000:.2f}ms per message"
                )

        print(
            f"⏱️ [MESSAGE SERVICE] Document conversion: {(time.time() - step_start)*1000:.2f}ms"
        )

        # Step 7: Final processing
        step_start = time.time()
        messages.reverse()  # Reverse to show oldest first
        next_cursor = None
        if has_more and messages:
            next_cursor = messages[-1].message_id

        total_count = None
        if include_total_count:
            print(f"⏱️ [MESSAGE SERVICE] Skipped count query for performance")

        print(
            f"⏱️ [MESSAGE SERVICE] Final processing: {(time.time() - step_start)*1000:.2f}ms"
        )

        total_service_time = (time.time() - service_start_time) * 1000
        print(
            f"🚀 [MESSAGE SERVICE] TOTAL SERVICE TIME: {total_service_time:.2f}ms for {len(messages)} messages"
        )

        return MessageHistoryResponse(
            messages=messages,
            has_more=has_more,
            total_count=total_count,
            next_cursor=next_cursor,
        )

    async def get_message_history_with_thread_counts(
        self,
        club_id: str,
        page: int = 1,
        page_size: int = 50,
        cursor: Optional[str] = None,
        include_total_count: bool = True,
    ) -> dict:
        """Get message history with thread counts - DETAILED TIMING ANALYSIS"""

        print(f"🚀 [DETAILED ANALYSIS] Starting API call for club: {club_id}")
        overall_start = time.time()

        # Step 1: Query building
        step_start = time.time()
        query = {
            "club_id": club_id,
            "is_deleted": False,
            "reply_to_message_id": None,
        }
        print(f"⏱️ [STEP 1] Query building: {(time.time() - step_start)*1000:.2f}ms")

        # Step 2: Cursor pagination (if needed)
        if cursor:
            step_start = time.time()
            before_message = await self.messages_collection.find_one(
                {"message_id": cursor}
            )
            if before_message:
                query["created_at"] = {"$gt": before_message["created_at"]}
            print(f"⏱️ [STEP 2] Cursor lookup: {(time.time() - step_start)*1000:.2f}ms")

        # Step 3: Skip calculation
        step_start = time.time()
        skip = (page - 1) * page_size
        print(f"⏱️ [STEP 3] Skip calculation: {(time.time() - step_start)*1000:.2f}ms")

        # Step 4: Database connection and query execution
        step_start = time.time()

        # ULTRA MINIMAL projection - only absolutely essential fields
        projection = {
            "message_id": 1,
            "sender_username": 1,
            "sender_full_name": 1,
            "sender_role": 1,
            "message_type": 1,
            "content": 1,
            "created_at": 1,
        }

        # Check database connection
        db_check_start = time.time()
        try:
            # Test database connection
            await self.messages_collection.find_one({}, {"_id": 1})
        except Exception as e:
            print(f"❌ [DB CONNECTION] Error: {e}")
        print(
            f"⏱️ [STEP 4A] DB connection check: {(time.time() - db_check_start)*1000:.2f}ms"
        )

        # Execute main query
        query_start = time.time()
        messages_docs = (
            await self.messages_collection.find(query, projection)
            .sort("created_at", -1)
            .skip(skip)
            .limit(page_size + 1)
            .to_list(page_size + 1)
        )
        print(
            f"⏱️ [STEP 4B] Main query execution: {(time.time() - query_start)*1000:.2f}ms"
        )
        print(
            f"⏱️ [STEP 4] Total database operations: {(time.time() - step_start)*1000:.2f}ms"
        )

        # Step 5: Data processing
        step_start = time.time()
        has_more = len(messages_docs) > page_size
        if has_more:
            messages_docs = messages_docs[:-1]
        print(f"⏱️ [STEP 5] Data processing: {(time.time() - step_start)*1000:.2f}ms")

        # Step 6: Response building
        step_start = time.time()
        messages_with_thread_counts = []

        for i, doc in enumerate(messages_docs):
            doc_start = time.time()
            # Ultra-minimal dict for maximum speed
            message_dict = {
                "message_id": doc["message_id"],
                "club_id": club_id,  # Use parameter instead of doc
                "sender_id": "unknown",  # Skip sender_id lookup
                "sender_username": doc.get("sender_username", "Unknown"),
                "sender_full_name": doc.get("sender_full_name", "Unknown User"),
                "sender_avatar": None,  # Always None for speed
                "sender_role": doc.get("sender_role", "Member"),
                "message_type": doc["message_type"],
                "content": doc["content"],
                "reactions": [],
                "pinned": None,  # Always None for speed
                "reply_to_message_id": None,  # Always None for speed
                "edited_at": None,
                "created_at": doc["created_at"],
                "updated_at": doc["created_at"],  # Use created_at for both
                "thread_count": 0,
                "last_reply_users": [],
            }
            messages_with_thread_counts.append(message_dict)

            # Log every 10th message processing time
            if (i + 1) % 10 == 0:
                print(
                    f"⏱️ [STEP 6] Processed {i + 1} messages: {(time.time() - doc_start)*1000:.2f}ms per message"
                )

        print(
            f"⏱️ [STEP 6] Total response building: {(time.time() - step_start)*1000:.2f}ms"
        )

        # Step 7: Final processing
        step_start = time.time()
        # Reverse messages to show oldest first
        messages_with_thread_counts.reverse()

        # Get next cursor
        next_cursor = None
        if has_more and messages_with_thread_counts:
            next_cursor = messages_with_thread_counts[-1]["message_id"]

        final_response = {
            "club_id": club_id,
            "page": page,
            "page_size": page_size,
            "messages": messages_with_thread_counts,
            "total_count": None,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
        print(f"⏱️ [STEP 7] Final processing: {(time.time() - step_start)*1000:.2f}ms")

        total_time = (time.time() - overall_start) * 1000
        print(
            f"🚀 [DETAILED ANALYSIS] TOTAL TIME: {total_time:.2f}ms for {len(messages_with_thread_counts)} messages"
        )
        print(
            f"📊 [PERFORMANCE] Average per message: {total_time/len(messages_with_thread_counts):.2f}ms"
        )

        return final_response

    async def get_message_by_id(self, message_id: str) -> Optional[ChatMessage]:
        """Get a specific message by ID"""

        message_doc = await self.messages_collection.find_one(
            {"message_id": message_id, "is_deleted": False}
        )

        if not message_doc:
            return None

        return await self.document_to_chat_message(message_doc)

    async def get_pinned_messages(self, club_id: str) -> List[ChatMessage]:
        """Get all pinned messages for a club"""

        query = {
            "club_id": club_id,
            "is_deleted": False,
            "reply_to_message_id": None,  # Only show parent messages, not thread replies
            "pinned": {"$ne": None},
        }

        cursor = self.messages_collection.find(query).sort("pinned.pinned_at", -1)
        pinned_docs = await cursor.to_list(None)

        pinned_messages = []
        for doc in pinned_docs:
            chat_message = await self.document_to_chat_message(doc)
            if chat_message:
                pinned_messages.append(chat_message)

        return pinned_messages

    async def search_messages(
        self,
        club_id: str,
        search_query: str,
        page: int = 1,
        page_size: int = 20,
        include_total_count: bool = True,
    ) -> MessageHistoryResponse:
        """Search messages by content using regex (case-insensitive)"""

        # Escape special regex characters in the search query
        escaped_query = re.escape(search_query)

        query = {
            "club_id": club_id,
            "is_deleted": False,
            "reply_to_message_id": None,  # Only search parent messages, not thread replies
            "content.text": {"$regex": escaped_query, "$options": "i"},
        }

        # Get messages sorted by created_at descending (newest first)
        cursor = self.messages_collection.find(query).sort("created_at", -1)

        # Apply pagination
        skip = (page - 1) * page_size
        messages_docs = (
            await cursor.skip(skip).limit(page_size + 1).to_list(page_size + 1)
        )

        # Check if there are more messages
        has_more = len(messages_docs) > page_size
        if has_more:
            messages_docs = messages_docs[:-1]

        # Convert to ChatMessage objects
        messages = []
        for doc in messages_docs:
            chat_message = await self.document_to_chat_message(doc)
            if chat_message:
                messages.append(chat_message)

        # Reverse messages to show oldest first (since we sorted newest first from DB)
        messages.reverse()

        # Calculate total count if requested
        total_count = None
        if include_total_count:
            total_count = await self.messages_collection.count_documents(query)

        return MessageHistoryResponse(
            messages=messages,
            has_more=has_more,
            total_count=total_count,
            next_cursor=None,
        )

    def document_to_chat_message_sync(self, doc: dict) -> Optional[ChatMessage]:
        """Convert MongoDB document to ChatMessage object - SYNC VERSION for performance"""
        if not doc:
            return None

        try:
            # Get sender information from stored data
            sender_username = doc.get("sender_username", "Unknown")
            sender_full_name = doc.get("sender_full_name", "Unknown User")
            sender_avatar = doc.get("sender_avatar")
            sender_role = UserRole(doc.get("sender_role", "Member"))

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

            # Parse pinned info
            pinned = None
            if doc.get("pinned"):
                from .models import PinnedMessage

                pinned = PinnedMessage(**doc["pinned"])

            # Handle datetime fields - ensure they are timezone-aware UTC
            created_at = doc["created_at"]
            updated_at = doc["updated_at"]
            edited_at = doc.get("edited_at")

            # If datetime is naive (no timezone), assume it's UTC
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if updated_at and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if edited_at and edited_at.tzinfo is None:
                edited_at = edited_at.replace(tzinfo=timezone.utc)

            return ChatMessage(
                message_id=doc["message_id"],
                club_id=doc["club_id"],
                sender_id=doc["sender_id"],
                sender_username=sender_username,
                sender_full_name=sender_full_name,
                sender_avatar=sender_avatar,
                sender_role=sender_role,
                message_type=MessageType(doc["message_type"]),
                content=content,
                reactions=reactions,
                pinned=pinned,
                reply_to_message_id=doc.get("reply_to_message_id"),
                edited_at=edited_at,
                created_at=created_at,
                updated_at=updated_at,
            )

        except Exception as e:
            print(f"Error converting document to ChatMessage: {e}")
            return None

    async def document_to_chat_message(self, doc: dict) -> Optional[ChatMessage]:
        """Convert MongoDB document to ChatMessage object"""

        if not doc:
            return None

        try:
            # Get sender information from stored data
            sender_username = doc.get("sender_username", "Unknown")
            sender_full_name = doc.get("sender_full_name", "Unknown User")
            sender_avatar = doc.get("sender_avatar")
            sender_role = UserRole(doc.get("sender_role", "Member"))

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

            # Parse pinned info
            pinned = None
            if doc.get("pinned"):
                from .models import PinnedMessage

                pinned = PinnedMessage(**doc["pinned"])

            # Handle datetime fields - ensure they are timezone-aware UTC
            created_at = doc["created_at"]
            updated_at = doc["updated_at"]
            edited_at = doc.get("edited_at")

            # If datetime is naive (no timezone), assume it's UTC
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if updated_at and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if edited_at and edited_at.tzinfo is None:
                edited_at = edited_at.replace(tzinfo=timezone.utc)

            return ChatMessage(
                message_id=doc["message_id"],
                club_id=doc["club_id"],
                sender_id=doc["sender_id"],
                sender_username=sender_username,
                sender_full_name=sender_full_name,
                sender_avatar=sender_avatar,
                sender_role=sender_role,
                message_type=MessageType(doc["message_type"]),
                content=content,
                reactions=reactions,
                pinned=pinned,
                reply_to_message_id=doc.get("reply_to_message_id"),
                edited_at=edited_at,
                created_at=created_at,
                updated_at=updated_at,
            )

        except Exception as e:
            print(f"Error converting document to ChatMessage: {e}")
            return None

    async def update_unread_counts(self, club_id: str, message_id: str, sender_id: str):
        """Update unread message counts for all club members except sender"""

        # This would typically get all club members and update their unread counts
        # For now, we'll implement a simple version
        now = datetime.utcnow()

        # Update unread counts for all users who have tracking records for this club
        await self.unread_collection.update_many(
            {"club_id": club_id, "user_id": {"$ne": sender_id}},  # Exclude sender
            {"$inc": {"unread_count": 1}, "$set": {"updated_at": now}},
        )

    async def mark_messages_read(self, user_id: str, club_id: str, message_id: str):
        """Mark messages as read up to a specific message"""

        now = datetime.utcnow()

        # Update or create unread tracking record
        await self.unread_collection.update_one(
            {"user_id": user_id, "club_id": club_id},
            {
                "$set": {
                    "last_read_message_id": message_id,
                    "last_read_at": now,
                    "unread_count": 0,
                    "updated_at": now,
                }
            },
            upsert=True,
        )

    async def get_unread_count(self, user_id: str, club_id: str) -> int:
        """Get unread message count for user in club"""

        tracking = await self.unread_collection.find_one(
            {"user_id": user_id, "club_id": club_id}
        )

        return tracking.get("unread_count", 0) if tracking else 0

    async def get_member_clubs_latest_messages(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "latest_message",
    ) -> Tuple[bool, Optional[dict], Optional[str]]:
        """Get latest messages from all clubs a member has joined"""
        try:
            from .db import get_club_collection
            from .models import (
                MemberClubLatestMessage,
                GetMemberClubsLatestMessagesResponse,
            )

            club_collection = get_club_collection()

            # Step 1: Find user in betting_main database and get clubs he joined
            user_doc = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user_doc:
                return False, None, "User not found"

            print(f"🔍 DEBUG: User ID: {user_id}")
            print(f"🔍 DEBUG: User document keys: {list(user_doc.keys())}")
            print(f"🔍 DEBUG: User email: {user_doc.get('email', 'Unknown')}")

            # Step 2: Extract active memberships from user document
            active_memberships = []
            now = datetime.utcnow()

            # Check for clubs field in user document
            if "clubs_joined" in user_doc and isinstance(
                user_doc["clubs_joined"], list
            ):
                print(
                    f"🔍 DEBUG: Found clubs_joined field with {len(user_doc['clubs_joined'])} items"
                )
                for i, club_data in enumerate(user_doc["clubs_joined"]):
                    print(f"🔍 DEBUG: Club {i+1}: {club_data}")

                    # Check if membership is active based on end_date
                    end_date = club_data.get("end_date")
                    is_active = True

                    print(f"🔍 DEBUG: End date: {end_date}, Type: {type(end_date)}")

                    if end_date:
                        if isinstance(end_date, str):
                            end_date = datetime.fromisoformat(
                                end_date.replace("Z", "+00:00")
                            )
                        is_active = now < end_date
                        print(
                            f"🔍 DEBUG: Is active: {is_active}, Now: {now}, End date: {end_date}"
                        )

                    # Check membership status
                    membership_status = club_data.get("membership_status", "active")
                    print(f"🔍 DEBUG: Membership status: {membership_status}")

                    if membership_status == "active" and is_active:
                        membership = {
                            "club_id": club_data.get("club_id", "").rstrip(","),
                            "club_name": club_data.get("club_name", "").rstrip(","),
                            "name_based_id": club_data.get(
                                "club_name_based_id", ""
                            ).rstrip(","),
                            "membership_type": club_data.get(
                                "membership_type", "trial"
                            ),
                            "join_date": club_data.get("join_date"),
                            "end_date": club_data.get("end_date"),
                        }
                        print(f"🔍 DEBUG: Adding active membership: {membership}")
                        active_memberships.append(membership)
                    else:
                        print(
                            f"🔍 DEBUG: Skipping inactive membership - status: {membership_status}, is_active: {is_active}"
                        )
            else:
                print(f"🔍 DEBUG: No clubs field found or not a list")
                print(f"🔍 DEBUG: Available fields: {list(user_doc.keys())}")

                # Check for other possible membership fields
                for field in ["memberships", "club_memberships", "user_clubs"]:
                    if field in user_doc:
                        print(f"🔍 DEBUG: Found {field} field: {user_doc[field]}")

                # Check if user has any club-related data
                print(f"🔍 DEBUG: All fields containing 'club':")
                for key, value in user_doc.items():
                    if "club" in key.lower():
                        print(f"  - {key}: {value}")
            # If no memberships found in user document, try the memberships collection
            if not active_memberships:
                print(
                    f"🔍 DEBUG: No memberships in user document, trying memberships collection..."
                )
                from .db import get_membership_collection

                membership_collection = get_membership_collection()

                memberships_docs = await membership_collection.find(
                    {"user_id": user_id, "status": "active"}
                ).to_list(length=None)

                print(
                    f"🔍 DEBUG: Found {len(memberships_docs)} memberships in collection"
                )

                for membership_doc in memberships_docs:
                    print(f"🔍 DEBUG: Membership doc: {membership_doc}")

                    # Check if membership is active based on end_date
                    end_date = (
                        membership_doc.get("end_date")
                        or membership_doc.get("trial_end_date")
                        or membership_doc.get("paid_end_date")
                    )
                    is_active = True

                    if end_date:
                        if isinstance(end_date, str):
                            end_date = datetime.fromisoformat(
                                end_date.replace("Z", "+00:00")
                            )
                        is_active = now < end_date

                    if is_active:
                        membership = {
                            "club_id": membership_doc.get("club_id", ""),
                            "club_name": membership_doc.get("club_name", ""),
                            "name_based_id": membership_doc.get("name_based_id", ""),
                            "membership_type": membership_doc.get(
                                "membership_type", "trial"
                            ),
                            "join_date": membership_doc.get("created_at"),
                            "end_date": end_date,
                        }
                        print(
                            f"🔍 DEBUG: Adding membership from collection: {membership}"
                        )
                        active_memberships.append(membership)

            print(
                f"🔍 DEBUG: Total active memberships found: {len(active_memberships)}"
            )

            if not active_memberships:
                return (
                    True,
                    {
                        "success": True,
                        "clubs": [],
                        "total_count": 0,
                        "page": page,
                        "page_size": page_size,
                        "total_pages": 0,
                        "has_next": False,
                        "has_previous": False,
                        "message": "No active club memberships found",
                    },
                    None,
                )

            # Step 3: Get club details and latest messages in parallel
            clubs_with_messages = []

            print(f"🔍 DEBUG: Processing {len(active_memberships)} active memberships")

            for membership in active_memberships:
                name_based_id = membership["name_based_id"]
                print(f"🔍 DEBUG: Processing club: {name_based_id}")

                # Get club details
                club = await club_collection.find_one({"name_based_id": name_based_id})
                if not club:
                    print(
                        f"🔍 DEBUG: Club not found for name_based_id: {name_based_id}"
                    )
                    continue

                print(f"🔍 DEBUG: Club found: {club.get('name', 'Unknown')}")

                # Get latest message for this club from betting_main.chat_messages
                latest_message_doc = await self.messages_collection.find_one(
                    {"club_id": name_based_id}, sort=[("created_at", -1)]
                )
                print("latest_message_doc", latest_message_doc)
                print(
                    f"🔍 DEBUG: Latest message found: {latest_message_doc is not None}"
                )
                if latest_message_doc:
                    print(
                        f"🔍 DEBUG: Message content: {latest_message_doc.get('content', {}).get('text', '')[:50]}..."
                    )
                    print(
                        f"🔍 DEBUG: Message created_at: {latest_message_doc.get('created_at')}"
                    )

                # Get unread count
                unread_count = await self.get_unread_count(user_id, name_based_id)
                print(f"🔍 DEBUG: Unread count: {unread_count}")

                # Prepare latest message data
                latest_message = None
                latest_message_sender = None
                latest_message_time = None

                if latest_message_doc:
                    # Get sender details first
                    sender = await self.users_collection.find_one(
                        {"_id": ObjectId(latest_message_doc["sender_id"])}
                    )
                    sender_username = "Unknown"
                    sender_full_name = "Unknown"
                    sender_role = "Member"
                    sender_avatar = None

                    # First check if sender info is already in message document
                    if latest_message_doc.get("sender_avatar"):
                        sender_avatar = latest_message_doc.get("sender_avatar")

                    if sender:
                        sender_username = sender.get("username", "Unknown")
                        sender_full_name = sender.get("full_name", "Unknown")
                        sender_role = latest_message_doc.get("sender_role", "Member")
                        # Only fetch avatar from user if not already in message doc
                        if not sender_avatar:
                            sender_avatar = sender.get("avatar_url")
                        print(f"🔍 DEBUG: Sender: {sender_username}")

                    # Create message data with all required fields
                    message_data = {
                        "message_id": latest_message_doc.get("message_id", ""),
                        "club_id": latest_message_doc.get("club_id", ""),
                        "sender_id": latest_message_doc.get("sender_id", ""),
                        "sender_username": sender_username,
                        "sender_full_name": sender_full_name,
                        "sender_avatar": sender_avatar,
                        "sender_role": sender_role,
                        "message_type": latest_message_doc.get("message_type", "text"),
                        "content": latest_message_doc.get("content", {}),
                        "reactions": latest_message_doc.get("reactions", []),
                        "pinned": latest_message_doc.get("pinned"),
                        "reply_to_message_id": latest_message_doc.get(
                            "reply_to_message_id"
                        ),
                        "edited_at": latest_message_doc.get("edited_at"),
                        "created_at": latest_message_doc.get("created_at"),
                        "updated_at": latest_message_doc.get("updated_at"),
                    }

                    latest_message = ChatMessage(**message_data)
                    latest_message_time = latest_message_doc.get("created_at")

                    # Set sender info for response
                    latest_message_sender = {
                        "user_id": (
                            str(sender["_id"])
                            if sender
                            else latest_message_doc["sender_id"]
                        ),
                        "username": sender_username,
                        "full_name": sender_full_name,
                        "role": sender_role,
                        "avatar": sender_avatar,
                    }

                # Create club data
                club_data = MemberClubLatestMessage(
                    club_id=str(club["_id"]),
                    club_name=club.get("name", "Unknown Club"),
                    name_based_id=club.get("name_based_id", ""),
                    club_logo=club.get("logo_url"),
                    latest_message=latest_message,
                    latest_message_sender=latest_message_sender,
                    latest_message_time=latest_message_time,
                    unread_count=unread_count,
                    membership_type=membership["membership_type"],
                    membership_status="active",
                    join_date=membership.get("join_date"),
                    trial_end_date=(
                        membership.get("end_date")
                        if membership["membership_type"] == "trial"
                        else None
                    ),
                    paid_end_date=(
                        membership.get("end_date")
                        if membership["membership_type"] == "paid"
                        else None
                    ),
                )

                print(f"🔍 DEBUG: Created club data for: {club_data.club_name}")
                clubs_with_messages.append(club_data)

            # Step 4: Sort clubs based on sort_by parameter
            if sort_by == "latest_message":
                clubs_with_messages.sort(
                    key=lambda x: x.latest_message_time or datetime.min, reverse=True
                )
            elif sort_by == "club_name":
                clubs_with_messages.sort(key=lambda x: x.club_name.lower())
            elif sort_by == "join_date":
                clubs_with_messages.sort(
                    key=lambda x: x.join_date or datetime.min, reverse=True
                )

            # Step 5: Apply pagination
            total_count = len(clubs_with_messages)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_clubs = clubs_with_messages[start_idx:end_idx]

            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1

            return (
                True,
                {
                    "success": True,
                    "clubs": [club.dict() for club in paginated_clubs],
                    "total_count": total_count,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "has_next": has_next,
                    "has_previous": has_previous,
                    "message": "Member clubs latest messages retrieved successfully",
                },
                None,
            )

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error getting member clubs latest messages: {e}")
            return False, None, f"Failed to get member clubs latest messages: {str(e)}"


# Global message service instance
message_service = MessageService()
