import re
from typing import List, Tuple, Optional
from datetime import datetime, timezone
from bson import ObjectId

from .db import get_database
from .models import (
    UserMention,
    MessageContent,
    ChatMessage,
    MessageType,
)
from .auth import get_chat_user


class MentionService:
    def __init__(self):
        self.db = get_database()
        # Use auth database for users collection
        import os

        auth_db_name = os.getenv("AUTH_DATABASE_NAME", "betting_main")
        club_db_name = os.getenv("CLUB_DATABASE_NAME", "betting_main")

        auth_client = self.db.client
        auth_db = auth_client[auth_db_name]
        club_db = auth_client[club_db_name]

        self.users_collection = auth_db["users"]
        self.messages_collection = self.db["messages"]
        self.club_collection = club_db["clubs"]  # Use club database for clubs

    def extract_mentions(self, text: str) -> List[Tuple[str, int, int]]:
        """Extract mentions from text using @username pattern"""
        mentions = []
        # Pattern to match @username or @email
        # Updated to handle email addresses and other formats
        pattern = r"@([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|[a-zA-Z0-9_]+)"

        for match in re.finditer(pattern, text):
            username = match.group(1)
            start_pos = match.start()
            end_pos = match.end()
            mentions.append((username, start_pos, end_pos))

        return mentions

    async def resolve_mentions(
        self, text: str, club_id: str
    ) -> Tuple[str, List[UserMention]]:
        """Resolve mentions in text and return processed text with mention objects"""
        mentions = self.extract_mentions(text)
        resolved_mentions = []
        processed_text = text
        print(f"🔍 Resolving mentions for club_id: {club_id}")

        # Use club collection from club database
        print(f"🔍 Club collection: {self.club_collection}")

        # First, get the club document
        try:
            club = await self.club_collection.find_one({"_id": ObjectId(club_id)})
            print(f"🔍 Found club: {club is not None}")
        except Exception as e:
            print(f"❌ Error finding club: {e}")
            club = None

        if not club:
            print(f"❌ Club not found: {club_id}")
            return processed_text, resolved_mentions

        # Get members from club
        members = club.get("members", [])
        print(f"🔍 Found {len(members)} members in club")

        # Debug: Show available members
        print("📋 Available members for mentions:")
        for i, member in enumerate(members):
            print(
                f"  {i+1}. {member.get('full_name')} (email: {member.get('email')}, username: {member.get('username')})"
            )

        # Sort mentions by position (reverse order to avoid index shifting)
        mentions.sort(key=lambda x: x[1], reverse=True)
        print(f"🔍 Found mentions: {mentions}")

        for username, start_pos, end_pos in mentions:
            print(f"🔍 Looking for user: {username}")

            # Search for member in the members array with more flexible matching
            member = None
            search_term = username.lower()

            for m in members:
                full_name = m.get("full_name", "").lower()
                email = m.get("email", "").lower()
                username_field = m.get("username", "").lower()

                print(
                    f"    Comparing with: full_name='{full_name}', email='{email}', username='{username_field}'"
                )

                # Try exact match first
                if (
                    search_term == full_name
                    or search_term == email
                    or search_term == username_field
                ):
                    member = m
                    print(f"✅ Found member (exact match): {member.get('full_name')}")
                    break

                # Try partial match (contains)
                if (
                    search_term in full_name
                    or search_term in email
                    or search_term in username_field
                ):
                    member = m
                    print(f"✅ Found member (partial match): {member.get('full_name')}")
                    break

                # For email addresses, try matching just the username part
                if "@" in search_term:
                    email_username = search_term.split("@")[0]
                    if (
                        email_username == full_name
                        or email_username == username_field
                        or email_username in full_name
                        or email_username in username_field
                    ):
                        member = m
                        print(
                            f"✅ Found member (email username match): {member.get('full_name')}"
                        )
                        break

            if member:
                # Create mention object
                mention = UserMention(
                    user_id=member["user_id"],
                    username=member.get("username", member.get("full_name", username)),
                    full_name=member.get("full_name", member.get("username", username)),
                    position_start=start_pos,
                    position_end=end_pos,
                )
                resolved_mentions.append(mention)
                print(
                    f"✅ Created mention for user: {member.get('full_name', username)}"
                )
            else:
                # Remove invalid mention from text
                processed_text = processed_text[:start_pos] + processed_text[end_pos:]
                print(f"❌ Member not found in club: {username}")
                print(f"💡 Available members: {[m.get('full_name') for m in members]}")

        return processed_text, resolved_mentions

    async def create_message_with_mentions(
        self,
        user_data: dict,
        club_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        reply_to_message_id: Optional[str] = None,
        file_attachments: List[str] = None,
    ) -> ChatMessage:
        """Create a message with resolved mentions"""

        # Resolve mentions
        processed_text, mentions = await self.resolve_mentions(content, club_id)

        # Create message content
        message_content = MessageContent(
            text=processed_text,
            mentions=mentions,
            file_attachments=file_attachments or [],
        )

        # Get user info
        chat_user = await get_chat_user(user_data, club_id)

        # Create message
        message = ChatMessage(
            message_id=str(ObjectId()),  # Generate new ObjectId
            club_id=club_id,
            sender_id=user_data["user_id"],
            sender_username=user_data["username"],
            sender_full_name=user_data.get("full_name", user_data["username"]),
            sender_avatar=user_data.get("avatar_url"),
            sender_role=chat_user.role,
            message_type=message_type,
            content=message_content,
            reactions=[],
            pinned=None,
            reply_to_message_id=reply_to_message_id,
            edited_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        return message

    async def save_message_with_mentions(self, message: ChatMessage) -> str:
        """Save message to database and return message ID"""

        # Convert to dict for database storage
        message_dict = message.dict()
        message_dict["_id"] = ObjectId(message.message_id)

        # Save to database
        await self.messages_collection.insert_one(message_dict)

        return message.message_id

    async def get_mentioned_users(self, message_id: str) -> List[dict]:
        """Get users mentioned in a message"""
        message = await self.messages_collection.find_one({"_id": ObjectId(message_id)})
        if not message:
            return []

        mentions = message.get("content", {}).get("mentions", [])
        mentioned_user_ids = [mention["user_id"] for mention in mentions]

        if not mentioned_user_ids:
            return []

        # Get club to find member details using club database
        club_id = message.get("club_id")

        if not club_id:
            return []

        club = await self.club_collection.find_one({"_id": ObjectId(club_id)})
        if not club:
            return []

        # Get user details from club's members array
        users = []
        for user_id in mentioned_user_ids:
            for member in club.get("members", []):
                if member.get("user_id") == user_id:
                    users.append(
                        {
                            "user_id": member["user_id"],
                            "username": member.get(
                                "username", member.get("full_name", "Unknown")
                            ),
                            "full_name": member.get(
                                "full_name", member.get("username", "Unknown")
                            ),
                            "avatar_url": member.get("avatar_url"),
                        }
                    )
                    break

        return users

    async def send_mention_notifications(
        self, message: ChatMessage, socket_manager=None
    ):
        """Send notifications to mentioned users (socket_manager moved to core/socket)"""
        if not message.content.mentions:
            return

        mentioned_user_ids = [mention.user_id for mention in message.content.mentions]

        # Get club to find member details for notifications using club database
        club = await self.club_collection.find_one({"_id": ObjectId(message.club_id)})

        if not club:
            return

        # Send notification to each mentioned user
        for user_id in mentioned_user_ids:
            # Find member details in club
            member = None
            for m in club.get("members", []):
                if m.get("user_id") == user_id:
                    member = m
                    break

            if member and socket_manager:
                await socket_manager.send_to_user(
                    user_id,
                    "mention_notification",
                    {
                        "message_id": message.message_id,
                        "club_id": message.club_id,
                        "sender_username": message.sender_username,
                        "sender_full_name": message.sender_full_name,
                        "content": message.content.text,
                        "mentioned_at": datetime.now(timezone.utc).isoformat(),
                    },
                )


# Global mention service instance
mention_service = MentionService()
