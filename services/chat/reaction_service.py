from typing import List, Optional
from datetime import datetime
import uuid

from .db import get_messages_collection
from .models import (
    MessageReaction, ReactionType, ChatUser
)
from .message_service import message_service

class ReactionService:
    def __init__(self):
        self.messages_collection = get_messages_collection()
    
    async def add_reaction(
        self, 
        message_id: str, 
        user: ChatUser, 
        reaction_type: ReactionType, 
        content: str
    ) -> Optional[MessageReaction]:
        """Add a reaction to a message"""
        
        # Find the message
        message_doc = await self.messages_collection.find_one({
            "message_id": message_id,
            "is_deleted": False
        })
        
        if not message_doc:
            return None
        
        # Check if user already has this reaction on this message
        existing_reactions = message_doc.get("reactions", [])
        user_existing_reaction = None
        
        for reaction in existing_reactions:
            if (reaction["user_id"] == user.user_id and 
                reaction["content"] == content and 
                reaction["reaction_type"] == reaction_type.value):
                user_existing_reaction = reaction
                break
        
        # If user already has this exact reaction, remove it (toggle behavior)
        if user_existing_reaction:
            await self.remove_reaction(message_id, user.user_id, user_existing_reaction["reaction_id"])
            return None
        
        # Create new reaction
        reaction_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        reaction = MessageReaction(
            reaction_id=reaction_id,
            user_id=user.user_id,
            username=user.username,
            reaction_type=reaction_type,
            content=content,
            created_at=now
        )
        
        # Add reaction to message
        await self.messages_collection.update_one(
            {"message_id": message_id},
            {
                "$push": {"reactions": reaction.dict()},
                "$set": {"updated_at": now}
            }
        )
        
        return reaction
    
    async def remove_reaction(
        self, 
        message_id: str, 
        user_id: str, 
        reaction_id: str
    ) -> bool:
        """Remove a reaction from a message"""
        
        result = await self.messages_collection.update_one(
            {"message_id": message_id},
            {
                "$pull": {
                    "reactions": {
                        "reaction_id": reaction_id,
                        "user_id": user_id
                    }
                },
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        
        return result.modified_count > 0
    
    async def get_message_reactions(self, message_id: str) -> List[MessageReaction]:
        """Get all reactions for a message"""
        
        message_doc = await self.messages_collection.find_one({
            "message_id": message_id,
            "is_deleted": False
        })
        
        if not message_doc:
            return []
        
        reactions = []
        for reaction_data in message_doc.get("reactions", []):
            try:
                reaction = MessageReaction(**reaction_data)
                reactions.append(reaction)
            except Exception as e:
                print(f"Error parsing reaction: {e}")
                continue
        
        return reactions
    
    async def get_reaction_summary(self, message_id: str) -> dict:
        """Get reaction summary with counts grouped by content"""
        
        reactions = await self.get_message_reactions(message_id)
        
        summary = {}
        for reaction in reactions:
            key = f"{reaction.reaction_type}:{reaction.content}"
            
            if key not in summary:
                summary[key] = {
                    "reaction_type": reaction.reaction_type,
                    "content": reaction.content,
                    "count": 0,
                    "users": []
                }
            
            summary[key]["count"] += 1
            summary[key]["users"].append({
                "user_id": reaction.user_id,
                "username": reaction.username
            })
        
        return list(summary.values())
    
    async def get_user_reaction_on_message(
        self, 
        message_id: str, 
        user_id: str
    ) -> List[MessageReaction]:
        """Get all reactions by a specific user on a message"""
        
        reactions = await self.get_message_reactions(message_id)
        user_reactions = [r for r in reactions if r.user_id == user_id]
        
        return user_reactions
    
    async def validate_reaction_content(
        self, 
        reaction_type: ReactionType, 
        content: str
    ) -> bool:
        """Validate reaction content based on type"""
        
        if reaction_type == ReactionType.EMOJI:
            # Basic emoji validation (Unicode emoji ranges)
            # This is a simplified check - you might want more robust validation
            return len(content) <= 10 and any(
                ord(char) >= 0x1F600 for char in content  # Emoji Unicode range start
            )
        
        elif reaction_type == ReactionType.GIF:
            # Basic GIF URL validation
            return (
                content.startswith(('http://', 'https://')) and
                (content.endswith('.gif') or 'giphy.com' in content or 'tenor.com' in content)
            )
        
        return False
    
    async def get_popular_reactions(self, club_id: str, limit: int = 10) -> List[dict]:
        """Get most popular reactions in a club"""
        
        pipeline = [
            {
                "$match": {
                    "club_id": club_id,
                    "is_deleted": False,
                    "reactions": {"$exists": True, "$ne": []}
                }
            },
            {"$unwind": "$reactions"},
            {
                "$group": {
                    "_id": {
                        "type": "$reactions.reaction_type",
                        "content": "$reactions.content"
                    },
                    "count": {"$sum": 1},
                    "last_used": {"$max": "$reactions.created_at"}
                }
            },
            {"$sort": {"count": -1, "last_used": -1}},
            {"$limit": limit}
        ]
        
        results = await self.messages_collection.aggregate(pipeline).to_list(limit)
        
        popular_reactions = []
        for result in results:
            popular_reactions.append({
                "reaction_type": result["_id"]["type"],
                "content": result["_id"]["content"],
                "usage_count": result["count"],
                "last_used": result["last_used"]
            })
        
        return popular_reactions
    
    async def remove_all_user_reactions_from_message(
        self, 
        message_id: str, 
        user_id: str
    ) -> int:
        """Remove all reactions by a user from a message"""
        
        result = await self.messages_collection.update_one(
            {"message_id": message_id},
            {
                "$pull": {"reactions": {"user_id": user_id}},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        
        return result.modified_count
    
    async def get_recent_reactions_by_user(
        self, 
        user_id: str, 
        limit: int = 20
    ) -> List[dict]:
        """Get recent reactions made by a user across all clubs"""
        
        pipeline = [
            {
                "$match": {
                    "reactions.user_id": user_id,
                    "is_deleted": False
                }
            },
            {"$unwind": "$reactions"},
            {
                "$match": {"reactions.user_id": user_id}
            },
            {
                "$project": {
                    "message_id": 1,
                    "club_id": 1,
                    "reaction": "$reactions",
                    "message_content": "$content.text"
                }
            },
            {"$sort": {"reaction.created_at": -1}},
            {"$limit": limit}
        ]
        
        results = await self.messages_collection.aggregate(pipeline).to_list(limit)
        
        recent_reactions = []
        for result in results:
            recent_reactions.append({
                "message_id": result["message_id"],
                "club_id": result["club_id"],
                "reaction": result["reaction"],
                "message_preview": result["message_content"][:50] + "..." if len(result["message_content"]) > 50 else result["message_content"]
            })
        
        return recent_reactions

# Predefined popular emojis for quick access
POPULAR_EMOJIS = [
    "👍", "👎", "❤️", "😂", "😮", "😢", "😡", "🎉", "🔥", "💯",
    "👏", "🙏", "💪", "✅", "❌", "⭐", "💎", "🚀", "💰", "🏆"
]

# Popular GIF categories/sources
POPULAR_GIF_SOURCES = [
    "https://media.giphy.com/media/excited/giphy.gif",
    "https://media.giphy.com/media/thumbs-up/giphy.gif", 
    "https://media.giphy.com/media/celebration/giphy.gif",
    "https://media.giphy.com/media/mind-blown/giphy.gif",
    "https://media.giphy.com/media/applause/giphy.gif"
]

# Global reaction service instance
reaction_service = ReactionService() 