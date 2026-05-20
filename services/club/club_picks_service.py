"""
Club Picks Service - Handle submission and management of picks/bets by captains and moderators
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict
from bson import ObjectId
from fastapi import HTTPException, status, UploadFile
import logging
import os
import base64
import json
import re
import uuid
import math
from pathlib import Path
from core.database.collections import get_collections

logger = logging.getLogger(__name__)

# Helper function to get current UTC time in ISO format
def now_iso():
    return datetime.now(timezone.utc).isoformat() + "Z"

# OpenAI import
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not installed. Slip upload feature will not work.")


class ClubPicksService:
    """Service for managing club picks/bets"""
    
    def __init__(self):
        self.collections = get_collections()
        self.picks_collection = self.collections.get_club_picks_collection()
        self.clubs_collection = self.collections.get_clubs_collection()
        self.memberships_collection = self.collections.get_club_memberships_collection()
        self.users_collection = self.collections.get_users_collection()
        
        # OpenAI configuration
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if self.openai_api_key and OPENAI_AVAILABLE:
            self.openai_client = OpenAI(api_key=self.openai_api_key)
        else:
            self.openai_client = None
        
        # Upload directory for slips
        self.upload_dir = Path("uploads/betting_slips")
        self.upload_dir.mkdir(parents=True, exist_ok=True)
    
    async def verify_captain_or_moderator(self, user_id: str, club_id: str) -> Dict:
        """
        Verify if user is a captain or moderator of the club
        
        Args:
            user_id: User ID to verify
            club_id: Club name-based ID
            
        Returns:
            Dict with user role and club info
            
        Raises:
            HTTPException if user is not authorized
        """
        # Find club by name_based_id
        club = await self.clubs_collection.find_one({"name_based_id": club_id})
        
        if not club:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Club not found"
            )
        
        # Check if user is the captain
        if club.get("captain_id") == user_id:
            return {
                "role": "captain",
                "club": club,
                "user_id": user_id
            }
        
        # Check if user is a moderator of this club
        # Moderators are stored in the club document
        moderators = club.get("detailed_moderators", [])
        print(f"moderators: {moderators}")
        is_moderator = any(mod.get("user_id") == user_id for mod in moderators if isinstance(mod, dict))
        print(f"is_moderator: {is_moderator}")
        if is_moderator:
            return {
                "role": "moderator",
                "club": club,
                "user_id": user_id
            }
        
        # User is neither captain nor moderator
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only captains and moderators can submit picks for this club"
        )
    
    async def create_pick(
        self,
        user_id: str,
        club_id: str,
        sport: Optional[str] = None,
        league: Optional[str] = None,
        pick_entity_type: Optional[str] = None,
        team1: Optional[str] = None,
        team2: Optional[str] = None,
        player_name: Optional[str] = None,
        match_datetime: Optional[datetime] = None,
        platform: Optional[str] = None,
        pick_type: str = None,
        status: str = "pending",
        reasoning: Optional[str] = None,
        result: Optional[str] = None,
        bet_logo: Optional[str] = None,
        bet_source: Optional[str] = None,
        bet_on_team: Optional[str] = None,
        player_id: Optional[str] = None,
        home_team_id: Optional[str] = None,
        away_team_id: Optional[str] = None,
        bet_on_team_id: Optional[str] = None,
        league_id: Optional[str] = None,
        match_id: Optional[str] = None,
        parlay_picks: Optional[List[Dict]] = None,
        home_logo: Optional[str] = None,
        away_logo: Optional[str] = None
    ) -> Dict:
        """
        Create a new pick/bet submission
        
        Args:
            user_id: ID of the user submitting the pick
            club_id: Club name-based ID
            bet_source: Source of the bet ("live-support" or "manual-entry")
            sport: Sport name (e.g., "Basketball", "Football")
            league: League name (e.g., "NBA", "NFL")
            pick_entity_type: Whether pick is for team or player
            team1: First team name (required if pick_entity_type is "team")
            team2: Second team name (required if pick_entity_type is "team")
            player_name: Player name (required if pick_entity_type is "player")
            bet_on_team: Which team the bet is on (required if bet_source is "manual-entry" and pick_entity_type is "team")
            player_id: Optional player ID from sports API
            league_id: Optional league ID from sports API
            match_id: Optional match ID from sports API
            match_datetime: Date and time when the match/game will happen
            platform: Betting platform (e.g., "DraftKings", "FanDuel")
            pick_type: Type of pick (Moneyline, Parlay, Prop, Over/Under, Spread)
            status: Status of the pick (pending or completed)
            reasoning: Optional reasoning for the pick
            result: Result of the pick (win/loss) - required if status is completed
            bet_logo: Optional URL of the bet logo/image
            parlay_picks: Optional list of parlay picks (required when pick_type is "Parlay")
            
        Returns:
            Dict containing the created pick
            
        Raises:
            HTTPException if validation fails
        """
        # Verify user is captain or moderator
        auth_info = await self.verify_captain_or_moderator(user_id, club_id)
        
        # Validate entity type fields (skip validation if pick_type is "Parlay")
        if pick_type and pick_type.lower() != "parlay":
            if pick_entity_type == "team":
                if not team1 or not team2:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Both team1 and team2 are required when pick_entity_type is 'team'"
                    )
            elif pick_entity_type == "player":
                if not player_name:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="player_name is required when pick_entity_type is 'player'"
                    )
        
        # Normalize status and result to lowercase (case-insensitive handling)
        if status:
            status = status.lower()
        if result:
            result = result.lower()
        
        # Validate result is provided if status is completed
        if status == "completed" and not result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Result (win/loss) is required when status is 'completed'"
            )
        
        # Validate result value if provided
        if result and result not in ["win", "loss"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Result must be either 'win' or 'loss'"
            )
        
        # Ensure match_datetime is properly formatted (only for non-Parlay picks)
        if pick_type and pick_type.lower() != "parlay":
            if isinstance(match_datetime, str):
                # If it's a string, try to parse it as datetime
                try:
                    match_datetime = datetime.fromisoformat(match_datetime.replace('Z', '+00:00'))
                except ValueError:
                    # If parsing fails, use current time as fallback
                    match_datetime = datetime.now(timezone.utc)
            elif match_datetime is None:
                # If no match_datetime provided, use current time
                match_datetime = datetime.now(timezone.utc)
        # For Parlay picks, match_datetime can be None (it's in parlay_picks)
        
        # Normalize sport to lowercase (validation should already handle this, but ensure consistency)
        sport_lower = sport.lower().strip() if sport else sport
        
        # Validate parlay_picks if provided (for parlay type picks)
        if pick_type and pick_type.lower() == "parlay" and parlay_picks:
            for idx, parlay_pick in enumerate(parlay_picks):
                # Ensure parlay_status is set to "pending" by default
                if "parlay_status" not in parlay_pick or not parlay_pick.get("parlay_status"):
                    parlay_pick["parlay_status"] = "pending"
                
                # Normalize parlay_status to lowercase
                if parlay_pick.get("parlay_status"):
                    parlay_pick["parlay_status"] = parlay_pick["parlay_status"].lower()
                
                # Validate parlay_status value
                if parlay_pick.get("parlay_status") not in ["pending", "completed"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"parlay_status must be either 'pending' or 'completed' for parlay pick {idx + 1}"
                    )
                
                # If parlay_status is "completed", parlay_result is required
                if parlay_pick.get("parlay_status") == "completed":
                    if not parlay_pick.get("parlay_result"):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"parlay_result is required when parlay_status is 'completed' for parlay pick {idx + 1}"
                        )
                    # Normalize parlay_result to lowercase
                    parlay_result = parlay_pick.get("parlay_result", "").lower()
                    if parlay_result not in ["win", "loss"]:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"parlay_result must be either 'win' or 'loss' for parlay pick {idx + 1}"
                        )
                    parlay_pick["parlay_result"] = parlay_result
                elif parlay_pick.get("parlay_result"):
                    # If parlay_status is not "completed" but parlay_result is provided, normalize it
                    parlay_result = parlay_pick.get("parlay_result", "").lower()
                    if parlay_result not in ["win", "loss"]:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"parlay_result must be either 'win' or 'loss' for parlay pick {idx + 1}"
                        )
                    parlay_pick["parlay_result"] = parlay_result
        
        # Create pick document
        pick_data = {
            "club_id": club_id,
            "club_object_id": auth_info["club"]["_id"],
            "club_name": auth_info["club"].get("name"),
            "submitted_by": user_id,
            "submitted_by_role": auth_info["role"],
            "bet_source": bet_source,
            "sport": sport_lower,
            "league": league,
            "pick_entity_type": pick_entity_type,
            "team1": team1 if pick_entity_type == "team" else None,
            "team2": team2 if pick_entity_type == "team" else None,
            "player_name": player_name if pick_entity_type == "player" else None,
            "bet_on_team": bet_on_team,
            "player_id": player_id,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "bet_on_team_id": bet_on_team_id,
            "league_id": league_id,
            "match_id": match_id,
            "match_datetime": match_datetime,
            "platform": platform,
            "pick_type": pick_type,
            "status": status,
            "reasoning": reasoning,
            "result": result if status == "completed" else None,
            "bet_logo": bet_logo,
            "parlay_picks": parlay_picks,
            "home_logo": home_logo,
            "away_logo": away_logo,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "is_active": True
        }
        
        # Insert into database
        result_insert = await self.picks_collection.insert_one(pick_data)
        
        if not result_insert.inserted_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create pick"
            )
        
        logger.info(f"Pick created successfully by {auth_info['role']} {user_id} for club {club_id}")
        
        # Send new pick notification to club members
        try:
            from services.notifications.notification_service import (
                send_notification_to_users,
                get_club_members,
                filter_users_by_notification_preference,
                get_collections,
            )
            
            # Get submitted by name for notification
            submitted_by_name = auth_info.get("user_name", "Captain/Moderator")
            
            # Create pick title for notification
            if pick_entity_type == "team":
                pick_title = f"{team1} vs {team2}"
            else:
                pick_title = f"{player_name} ({sport})"
            
            # Get club members and notification preferences
            all_club_members = await get_club_members(club_id)
            enabled_user_ids = await filter_users_by_notification_preference(
                all_club_members, "new_pick_alerts"
            )

            collections = get_collections()
            user_tokens_collection = collections.get_user_tokens_collection()

            users_with_tokens: List[str] = []
            if enabled_user_ids:
                token_cursor = user_tokens_collection.find(
                    {"user_id": {"$in": enabled_user_ids}, "is_active": True},
                    {"user_id": 1},
                )
                token_docs = await token_cursor.to_list(length=None)
                users_with_tokens = list({doc.get("user_id") for doc in token_docs if doc.get("user_id")})

            # Build DB and push recipient lists (exclude creator)
            db_user_ids = [uid for uid in all_club_members if uid != user_id]
            enabled_user_ids = [uid for uid in enabled_user_ids if uid != user_id]
            push_user_ids = [uid for uid in users_with_tokens if uid != user_id]

            if db_user_ids:
                title = f"New Pick Posted!"
                body = f"{submitted_by_name} has posted a new pick: {pick_title}"
                
                notification_data = {
                    "pick_id": str(result_insert.inserted_id),
                    "club_id": club_id,
                    "submitted_by": submitted_by_name,
                    "pick_title": pick_title,
                    "sport": sport,
                    "league": league
                }
                
                notification_result = await send_notification_to_users(
                    user_ids=push_user_ids,
                    title=title,
                    body=body,
                    notification_type="club_new_pick",
                    data=notification_data,
                    click_action=f"club/{club_id}/picks/{str(result_insert.inserted_id)}",
                    priority="normal",
                    all_user_ids=db_user_ids
                )
                logger.info(f"New pick notification sent for pick {str(result_insert.inserted_id)}: {notification_result}")
            else:
                logger.info(f"No users with new pick alerts found for club {club_id}")
                
        except Exception as e:
            logger.error(f"Failed to send new pick notification for pick {str(result_insert.inserted_id)}: {e}")
        
        # Return the created pick with ID
        pick_data["_id"] = str(result_insert.inserted_id)
        return pick_data
    
    async def get_picks_by_club(
        self,
        club_id: str,
        status_filter: Optional[str] = None,
        pick_type_filter: Optional[str] = None,
        bet_source_filter: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> Dict:
        """
        Get all picks for a specific club
        
        Args:
            club_id: Club name-based ID
            status_filter: Optional status filter (pending/completed)
            pick_type_filter: Optional pick type filter (moneyline, parlay, spread, etc.)
            bet_source_filter: Optional bet source filter (e.g., live-support, manual-entry)
            limit: Maximum number of picks to return
            skip: Number of picks to skip (for pagination)
            
        Returns:
            Dict containing picks list and total count
        """
        # Build query
        query = {
            "club_id": club_id,
            "is_active": True
        }
        
        if status_filter:
            query["status"] = status_filter
        
        if pick_type_filter:
            query["pick_type"] = pick_type_filter

        if bet_source_filter:
            query["bet_source"] = bet_source_filter
        
        # Get total count
        total_count = await self.picks_collection.count_documents(query)
        
        # Get picks with pagination
        cursor = self.picks_collection.find(query)
        cursor = cursor.sort("created_at", -1).skip(skip).limit(limit)
        picks = await cursor.to_list(length=limit)
        
        # Convert ObjectId to string
        submitted_by_ids = set()
        for pick in picks:
            pick["_id"] = str(pick["_id"])
            if "club_object_id" in pick:
                pick["club_object_id"] = str(pick["club_object_id"])
            
            submitted_by_value = pick.get("submitted_by")
            if isinstance(submitted_by_value, ObjectId):
                submitted_by_value = str(submitted_by_value)
                pick["submitted_by"] = submitted_by_value
            elif submitted_by_value is not None:
                submitted_by_value = str(submitted_by_value)
                pick["submitted_by"] = submitted_by_value
            
            if submitted_by_value:
                submitted_by_ids.add(submitted_by_value)
        
        submitted_by_names: Dict[str, str] = {}
        submitted_object_ids = [
            ObjectId(submitted_id)
            for submitted_id in submitted_by_ids
            if ObjectId.is_valid(submitted_id)
        ]
        
        if submitted_object_ids:
            users_cursor = self.users_collection.find(
                {"_id": {"$in": submitted_object_ids}},
                {
                    "full_name": 1,
                    "first_name": 1,
                    "last_name": 1,
                    "email": 1,
                },
            )
            users = await users_cursor.to_list(length=len(submitted_object_ids))
            
            for user in users:
                full_name = user.get("full_name")
                if not full_name:
                    first_name = user.get("first_name", "")
                    last_name = user.get("last_name", "")
                    full_name = f"{first_name} {last_name}".strip()
                if not full_name:
                    full_name = user.get("email")
                submitted_by_names[str(user["_id"])] = full_name or "Unknown"
        
        for pick in picks:
            submitted_by_value = pick.get("submitted_by")
            if not submitted_by_value:
                continue
            pick["submitted_by_id"] = submitted_by_value
            display_name = submitted_by_names.get(submitted_by_value)
            if display_name:
                pick["submitted_by_name"] = display_name
                pick["submitted_by"] = display_name
            else:
                pick["submitted_by_name"] = submitted_by_value
        
        return {
            "picks": picks,
            "total": total_count,
            "limit": limit,
            "skip": skip
        }
    
    async def get_pick_by_id(self, pick_id: str) -> Dict:
        """
        Get a specific pick by ID
        
        Args:
            pick_id: Pick ID
            
        Returns:
            Dict containing pick data
            
        Raises:
            HTTPException if pick not found
        """
        if not ObjectId.is_valid(pick_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid pick ID format"
            )
        
        pick = await self.picks_collection.find_one({
            "_id": ObjectId(pick_id),
            "is_active": True
        })
        
        if not pick:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pick not found"
            )
        
        # Convert ObjectId to string
        pick["_id"] = str(pick["_id"])
        if "club_object_id" in pick:
            pick["club_object_id"] = str(pick["club_object_id"])
        
        return pick
    
    async def update_pick(
        self,
        pick_id: str,
        user_id: str,
        update_data: Dict
    ) -> Dict:
        """
        Update a pick
        
        Args:
            pick_id: Pick ID to update
            user_id: User ID performing the update
            update_data: Data to update
            
        Returns:
            Dict containing updated pick
            
        Raises:
            HTTPException if pick not found or user not authorized
        """
        if not ObjectId.is_valid(pick_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid pick ID format"
            )
        
        # Get existing pick
        pick = await self.picks_collection.find_one({
            "_id": ObjectId(pick_id),
            "is_active": True
        })
        
        if not pick:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pick not found"
            )
        
        # Verify user is captain or moderator of the club
        await self.verify_captain_or_moderator(user_id, pick["club_id"])
        
        # Normalize status and result to lowercase (case-insensitive handling)
        if "status" in update_data and update_data["status"]:
            update_data["status"] = update_data["status"].lower()
        if "result" in update_data and update_data["result"]:
            update_data["result"] = update_data["result"].lower()
        
        # Validate result if status is being changed to completed
        if update_data.get("status") == "completed" and not update_data.get("result"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Result (win/loss) is required when status is 'completed'"
            )
        
        # Validate result value if provided
        if "result" in update_data and update_data["result"] not in ["win", "loss", None]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Result must be either 'win' or 'loss'"
            )
        
        # Validate parlay_picks if provided (for parlay type picks)
        if "parlay_picks" in update_data and update_data["parlay_picks"]:
            parlay_picks = update_data["parlay_picks"]
            existing_parlay_picks = pick.get("parlay_picks", [])
            
            # If updating parlay picks, merge with existing ones for partial updates
            # Check if this is a partial update (only status/result fields) or full update
            is_partial_update = False
            for parlay_pick in parlay_picks:
                # Check if parlay pick has only status/result fields (partial update)
                has_only_status_fields = (
                    "parlay_status" in parlay_pick or "parlay_result" in parlay_pick
                ) and not any(key in parlay_pick for key in ["market_type", "sport", "league", "team1", "team2", "player_name", "bet_for", "match_datetime"])
                
                if has_only_status_fields:
                    is_partial_update = True
                    break
            
            if is_partial_update:
                # Partial update: merge status/result with existing parlay picks by index
                if len(parlay_picks) != len(existing_parlay_picks):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"For partial updates, you must provide updates for all {len(existing_parlay_picks)} parlay picks. Use index to specify which pick to update, or provide all picks."
                    )
                
                # Merge partial updates with existing parlay picks
                merged_parlay_picks = []
                for idx, update_pick in enumerate(parlay_picks):
                    if idx >= len(existing_parlay_picks):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Parlay pick index {idx} is out of range. Only {len(existing_parlay_picks)} parlay picks exist."
                        )
                    
                    existing_pick = existing_parlay_picks[idx].copy()
                    # Merge only the provided fields
                    if "parlay_status" in update_pick:
                        existing_pick["parlay_status"] = update_pick["parlay_status"]
                    if "parlay_result" in update_pick:
                        existing_pick["parlay_result"] = update_pick["parlay_result"]
                    
                    merged_parlay_picks.append(existing_pick)
                
                update_data["parlay_picks"] = merged_parlay_picks
                parlay_picks = merged_parlay_picks
            else:
                # Full update: validate parlay_picks array length
                if len(parlay_picks) < 2:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="parlay_picks must have at least 2 picks"
                    )
                if len(parlay_picks) > 10:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="parlay_picks can have at most 10 picks"
                    )
            
            # Validate each parlay pick
            for idx, parlay_pick in enumerate(parlay_picks):
                # Ensure parlay_status is set to "pending" by default if not provided
                if "parlay_status" not in parlay_pick or not parlay_pick.get("parlay_status"):
                    parlay_pick["parlay_status"] = "pending"
                
                # Normalize parlay_status to lowercase
                if parlay_pick.get("parlay_status"):
                    parlay_pick["parlay_status"] = parlay_pick["parlay_status"].lower()
                
                # Validate parlay_status value
                if parlay_pick.get("parlay_status") not in ["pending", "completed"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"parlay_status must be either 'pending' or 'completed' for parlay pick {idx + 1}"
                    )
                
                # If parlay_status is "completed", parlay_result is required
                if parlay_pick.get("parlay_status") == "completed":
                    if not parlay_pick.get("parlay_result"):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"parlay_result is required when parlay_status is 'completed' for parlay pick {idx + 1}"
                        )
                    # Normalize parlay_result to lowercase
                    parlay_result = parlay_pick.get("parlay_result", "").lower()
                    if parlay_result not in ["win", "loss"]:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"parlay_result must be either 'win' or 'loss' for parlay pick {idx + 1}"
                        )
                    parlay_pick["parlay_result"] = parlay_result
                elif parlay_pick.get("parlay_result"):
                    # If parlay_status is not "completed" but parlay_result is provided, normalize it
                    parlay_result = parlay_pick.get("parlay_result", "").lower()
                    if parlay_result not in ["win", "loss"]:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"parlay_result must be either 'win' or 'loss' for parlay pick {idx + 1}"
                        )
                    parlay_pick["parlay_result"] = parlay_result
        
        # Add updated timestamp
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        # Check if we're updating the pick outcome (from pending to win/loss)
        old_status = pick.get("status", "pending")
        new_status = update_data.get("status", old_status)
        new_result = update_data.get("result")
        
        is_outcome_update = (
            old_status != "completed" and 
            new_status == "completed" and 
            new_result in ["win", "loss"]
        )
        
        # Update the pick
        result = await self.picks_collection.update_one(
            {"_id": ObjectId(pick_id)},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            logger.warning(f"No changes made to pick {pick_id}")
        
        # Get and return updated pick
        updated_pick = await self.get_pick_by_id(pick_id)
        print(is_outcome_update,"is_outcome_update")
        
        # Send pick outcome notification if this is an outcome update
        if is_outcome_update:
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    get_club_members,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    get_club_members,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                # Get submitted by name from user details
                submitted_by_id = pick.get("submitted_by")
                submitted_by_name = "Unknown"
                
                if submitted_by_id:
                    # Try to get user name from users collection
                    users_collection = self.clubs_collection.database.users
                    user = await users_collection.find_one({"_id": ObjectId(submitted_by_id)})
                    if user:
                        submitted_by_name = user.get("full_name", user.get("email", "Unknown"))
                # print("idhr phocha")
                # Create pick title from available data
                pick_title = f"{pick.get('sport', 'Sport')} Pick"
                if pick.get("team1") and pick.get("team2"):
                    pick_title = f"{pick.get('team1')} vs {pick.get('team2')}"
                elif pick.get("player_name"):
                    pick_title = f"{pick.get('player_name')} - {pick.get('sport', 'Sport')}"
                print(pick["club_id"],'pick["club_id"]')
                # Get club members who have pick outcome alerts enabled
                all_club_members = await get_club_members(pick["club_id"])
                print(all_club_members,"all_club_members")
                from services.notifications.notification_service import (
                    get_collections
                )
                collections = get_collections()
                user_tokens_collection = collections.get_user_tokens_collection()

                # Determine users with preference enabled
                enabled_user_ids = await filter_users_by_notification_preference(
                    all_club_members,
                    "pick_outcome_alerts"
                )

                # Identify users who currently have at least one active device token
                users_with_tokens = []
                if enabled_user_ids:
                    token_cursor = user_tokens_collection.find(
                        {
                            "user_id": {"$in": enabled_user_ids},
                            "is_active": True
                        },
                        {"user_id": 1}
                    )
                    token_users = await token_cursor.to_list(length=None)
                    users_with_tokens = list({token_doc.get("user_id") for token_doc in token_users})
                print(enabled_user_ids,"user_ids")
                # Build DB and push recipient lists (exclude updater)
                db_user_ids = [uid for uid in all_club_members if uid != user_id]
                enabled_user_ids = [uid for uid in enabled_user_ids if uid != user_id]
                push_user_ids = [uid for uid in users_with_tokens if uid != user_id]
                
                if db_user_ids:
                    # Prepare notification content
                    if new_result.lower() in ["win", "won"]:
                        title = "🎉 Pick Won!"
                        body = f"{pick_title} - submitted by {submitted_by_name} has resulted in a WIN!"
                    elif new_result.lower() in ["loss", "lost"]:
                        title = "😔 Pick Lost"
                        body = f"{pick_title} - submitted by {submitted_by_name} has resulted in a LOSS"
                    else:
                        logger.warning(f"Unknown outcome: {new_result}")
                        return updated_pick
                    
                    # Prepare notification data
                    notification_data = {
                        "pick_id": pick_id,
                        "club_id": pick["club_id"],
                        "outcome": new_result.lower(),
                        "submitted_by": submitted_by_name,
                        "pick_title": pick_title
                    }
                    
                    # Send notification using the unified function
                    notification_result = await send_notification_to_users(
                        user_ids=push_user_ids,
                        title=title,
                        body=body,
                        notification_type="club_pick_outcome",
                        data=notification_data,
                        click_action=f"club/{pick['club_id']}/picks/{pick_id}",
                        priority="high",
                        all_user_ids=db_user_ids
                    )
                    
                    logger.info(f"Pick outcome notification sent for pick {pick_id}: {notification_result}")
                else:
                    logger.info(f"No users with pick outcome alerts found for club {pick['club_id']}")
                
            except Exception as e:
                logger.error(f"Failed to send pick outcome notification for pick {pick_id}: {e}")
                # Don't fail the pick update if notification fails
        
        logger.info(f"Pick {pick_id} updated by user {user_id}")
        
        return updated_pick
    
    async def delete_pick(self, pick_id: str, user_id: str) -> bool:
        """
        Soft delete a pick (set is_active to False)
        
        Args:
            pick_id: Pick ID to delete
            user_id: User ID performing the deletion
            
        Returns:
            bool indicating success
            
        Raises:
            HTTPException if pick not found or user not authorized
        """
        if not ObjectId.is_valid(pick_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid pick ID format"
            )
        
        # Get existing pick
        pick = await self.picks_collection.find_one({
            "_id": ObjectId(pick_id),
            "is_active": True
        })
        
        if not pick:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pick not found"
            )
        
        # Verify user is captain or moderator of the club
        await self.verify_captain_or_moderator(user_id, pick["club_id"])
        
        # Soft delete
        result = await self.picks_collection.update_one(
            {"_id": ObjectId(pick_id)},
            {
                "$set": {
                    "is_active": False,
                    "deleted_at": datetime.now(timezone.utc),
                    "deleted_by": user_id
                }
            }
        )
        
        logger.info(f"Pick {pick_id} deleted by user {user_id}")
        
        return result.modified_count > 0
    
#     async def analyze_betting_slip(
#         self,
#         user_id: str,
#         club_id: str,
#         pick_entity_type: str,
#         slip_image: UploadFile
#     ) -> Dict:
#         """
#         Analyze a betting slip image using OpenAI Vision API and extract pick details
        
#         Args:
#             user_id: ID of the user uploading the slip
#             club_id: Club name-based ID
#             pick_entity_type: Whether pick is for team or player
#             slip_image: Uploaded image file
            
#         Returns:
#             Dict containing extracted pick details and saved image path
            
#         Raises:
#             HTTPException if validation or analysis fails
#         """
#         # Verify user is captain or moderator
#         auth_info = await self.verify_captain_or_moderator(user_id, club_id)
        
#         # Check if OpenAI is available
#         if not self.openai_client:
#             raise HTTPException(
#                 status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
#                 detail="OpenAI service is not configured. Please contact administrator."
#             )
        
#         try:
#             # Read and encode image
#             image_content = await slip_image.read()
#             base64_image = base64.b64encode(image_content).decode('utf-8')
            
#             # Save the slip image
#             import uuid
#             file_extension = Path(slip_image.filename).suffix or '.jpg'
#             unique_filename = f"{uuid.uuid4()}{file_extension}"
#             file_path = self.upload_dir / unique_filename
            
#             with open(file_path, 'wb') as f:
#                 f.write(image_content)
            
#             logger.info(f"Saved betting slip to: {file_path}")
            
#             # Prepare OpenAI prompt based on pick_entity_type
#             if pick_entity_type == "team":
#                 entity_instruction = """
#                 - "team1": First team name
#                 - "team2": Second team name
#                 - "player_name": null
#                 """
#             else:  # player
#                 entity_instruction = """
#                 - "team1": null
#                 - "team2": null
#                 - "player_name": Player name
#                 """
            
#             # Create OpenAI API call with Vision (new v1.0+ syntax)
#             response = self.openai_client.chat.completions.create(
#                 model="gpt-4o",
#                 messages=[
#                     {
#                         "role": "system",
#                         "content": "You are an expert at analyzing betting slips and extracting structured data. Always respond with valid JSON only, no additional text."
#                     },
#                     {
#                         "role": "user",
#                         "content": [
#                             {
#                                 "type": "text",
#                                 "text": f"""Analyze this betting slip image and extract the following information in JSON format:

# {{
#   "sport": "Sport name (e.g., Football, Basketball, Baseball, Soccer, etc.)",
#   "league": "League name (e.g., NFL, NBA, MLB, EPL, etc.)",
#   {entity_instruction}
#   "match_datetime": "Match date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ)",
#   "platform": "Betting platform name (e.g., DraftKings, FanDuel, BetMGM, etc.)",
#   "pick_type": "Type of bet (moneyline, parlay, prop, over_under, spread, teaser, futures, live_bet, round_robin, if_bet, reverse, straight_bet, total, alternative_spread, alternative_total, same_game_parlay, or other)",
#   "status": "pending or completed",
#   "reasoning": "Brief reasoning or odds information visible on the slip"
# }}

# Important:
# - Extract ONLY the information visible on the slip
# - Use null for any field not clearly visible
# - Ensure match_datetime is in valid ISO 8601 format
# - For status, use "pending" if the bet hasn't been settled, "completed" if it has been settled
# - Return ONLY valid JSON, no additional explanation or text
# """
#                             },
#                             {
#                                 "type": "image_url",
#                                 "image_url": {
#                                     "url": f"data:image/jpeg;base64,{base64_image}"
#                                 }
#                             }
#                         ]
#                     }
#                 ],
#                 max_tokens=500,
#                 temperature=0.1
#             )
            
#             # Parse OpenAI response (new v1.0+ syntax)
#             ai_response = response.choices[0].message.content.strip()
#             logger.info(f"OpenAI Response: {ai_response}")
            
#             # Clean response (remove markdown code blocks if present)
#             if ai_response.startswith("```json"):
#                 ai_response = ai_response[7:]
#             if ai_response.startswith("```"):
#                 ai_response = ai_response[3:]
#             if ai_response.endswith("```"):
#                 ai_response = ai_response[:-3]
#             ai_response = ai_response.strip()
            
#             # Parse JSON response
#             extracted_data = json.loads(ai_response)
            
#             # Add metadata
#             extracted_data["club_id"] = club_id
#             extracted_data["pick_entity_type"] = pick_entity_type
#             extracted_data["slip_image_url"] = f"/uploads/betting_slips/{unique_filename}"
#             extracted_data["slip_image_path"] = str(file_path)
#             extracted_data["submitted_by"] = user_id
#             extracted_data["submitted_by_role"] = auth_info["role"]
#             extracted_data["club_name"] = auth_info["club"].get("name")
            
#             logger.info(f"Successfully extracted data from betting slip: {extracted_data}")
            
#             return extracted_data
            
#         except json.JSONDecodeError as e:
#             logger.error(f"Failed to parse OpenAI response as JSON: {e}")
#             raise HTTPException(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 detail="Failed to parse betting slip data. Please try again or enter details manually."
#             )
#         except Exception as e:
#             logger.error(f"Error analyzing betting slip: {e}")
#             raise HTTPException(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 detail=f"Failed to analyze betting slip: {str(e)}"
#             )



    async def analyze_betting_slip(
        self,
        user_id: str,
        club_id: str,
        pick_entity_type: str,
        slip_image: UploadFile
    ) -> dict:
        """
        Analyze a betting slip image using OpenAI Vision API and extract pick details.
        """

        # Verify role
        auth_info = await self.verify_captain_or_moderator(user_id, club_id)

        # Check if OpenAI client exists
        if not self.openai_client:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenAI service not configured."
            )

        try:
            # Read + save image
            image_content = await slip_image.read()
            base64_image = base64.b64encode(image_content).decode("utf-8")

            file_extension = Path(slip_image.filename).suffix or ".jpg"
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = self.upload_dir / unique_filename
            with open(file_path, "wb") as f:
                f.write(image_content)
            logger.info(f"Saved betting slip: {file_path}")

            # Entity instruction
            entity_instruction = (
                '- "team1": First team name\n- "team2": Second team name\n- "player_name": null'
                if pick_entity_type == "team"
                else '- "team1": null\n- "team2": null\n- "player_name": Player name'
            )

            # 🔥 Strong JSON-enforcing prompt
            prompt_text = f"""
    You are an expert sports data analyst. Analyze the following betting slip image and extract data in **strict JSON** only — no explanations, markdown, or text before/after the JSON.

    Return EXACTLY this JSON structure:

    {{
    "sport": "Sport name (e.g., Basketball, Football, etc.)",
    "league": "League or tournament name",
    {entity_instruction},
    "match_datetime": "YYYY-MM-DDTHH:MM:SSZ or with timezone offset if visible",
    "platform": "Source or betting platform name",
    "pick_type": "Type of bet (moneyline, parlay, prop, spread, total, final_result, etc.)",
    "status": "pending or completed",
    "reasoning": "Brief explanation or odds information from the slip"
    }}

    ### Rules
    - Respond ONLY with JSON, no prose, no Markdown.
    - If you are unsure about a field, use null.
    - For completed games (like 'FINAL' shown), set status = "completed".
    - For visible score, include it in reasoning.
    """

            # OpenAI Vision call
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You extract structured JSON data from sports betting slips. Always return valid JSON only."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }
                ],
                max_tokens=600,
                temperature=0.0
            )

            ai_response = response.choices[0].message.content.strip()
            logger.info(f"Raw OpenAI Response: {ai_response}")

            # 🧹 Clean response (strip code fences or text)
            ai_response = re.sub(r"^```(?:json)?|```$", "", ai_response, flags=re.MULTILINE).strip()

            # 🧩 Try parsing JSON safely
            try:
                extracted_data = json.loads(ai_response)
            except json.JSONDecodeError:
                # fallback: extract JSON block manually
                match = re.search(r"\{[\s\S]*\}", ai_response)
                if match:
                    extracted_data = json.loads(match.group())
                else:
                    raise

            # ✅ Add metadata
            extracted_data.update({
                "club_id": club_id,
                "pick_entity_type": pick_entity_type,
                "slip_image_url": f"/uploads/betting_slips/{unique_filename}",
                "slip_image_path": str(file_path),
                "submitted_by": user_id,
                "submitted_by_role": auth_info["role"],
                "club_name": auth_info["club"].get("name"),
            })

            logger.info(f"✅ Extracted betting slip data: {extracted_data}")
            return extracted_data

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            # Return blank fields instead of error
            blank_data = {
                "sport": None,
                "league": None,
                "team1": None,
                "team2": None,
                "player_name": None,
                "match_datetime": None,
                "platform": None,
                "pick_type": None,
                "status": "pending",
                "reasoning": None,
                "club_id": club_id,
                "pick_entity_type": pick_entity_type,
                "slip_image_url": f"/uploads/betting_slips/{unique_filename}",
                "slip_image_path": str(file_path),
                "submitted_by": user_id,
                "submitted_by_role": auth_info["role"],
                "club_name": auth_info["club"].get("name"),
                "parse_error": True,
                "error_message": "Failed to parse betting slip data. Please fill in the details manually."
            }
            logger.warning(f"⚠️ Returning blank fields due to parse error")
            return blank_data
        except Exception as e:
            logger.error(f"Error analyzing betting slip: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Betting slip analysis failed: {str(e)}"
            )

    async def enhance_reasoning_text(
        self,
        reasoning: str
    ) -> Dict:
        """
        Enhance reasoning text using OpenAI API.
        
        Args:
            reasoning: Original reasoning text to enhance
            
        Returns:
            Dict containing original reasoning and enhanced reasoning
            
        Raises:
            HTTPException if OpenAI is not available or enhancement fails
        """
        # Check if OpenAI is available
        if not OPENAI_AVAILABLE or not self.openai_client:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenAI service is not available. Please configure OPENAI_API_KEY in environment variables."
            )
        
        # Validate reasoning text is not empty
        if not reasoning or not reasoning.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reasoning text cannot be empty"
            )
        
        try:
            # Create prompt for OpenAI to enhance the text while preserving meaning
            prompt = f"""Enhance the following text by fixing grammar, spelling, and improving readability.
            The meaning must remain exactly the same, but the text should be more professional and clear.
            Generate a well-written version that maintains all the original information and intent.
            
            Original text:
            {reasoning}
            
            Return ONLY the enhanced text without any explanations, quotes, or additional commentary."""
            
            # Call OpenAI API with temperature to generate variations
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional text editor that enhances text quality while preserving meaning. Return only the enhanced text, nothing else."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=1000,
                temperature=0.7  # Use temperature to generate different variations while keeping meaning
            )
            
            enhanced_reasoning = response.choices[0].message.content.strip()
            
            # Clean up any quotes or formatting that OpenAI might add
            enhanced_reasoning = enhanced_reasoning.strip('"').strip("'").strip()
            
            # Validate enhanced text is not empty
            if not enhanced_reasoning:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Enhanced reasoning text is empty. Please try again."
                )
            
            logger.info(f"Original reasoning: {reasoning[:100]}...")
            logger.info(f"Enhanced reasoning: {enhanced_reasoning[:100]}...")
            
            return {
                "original_reasoning": reasoning,
                "enhanced_reasoning": enhanced_reasoning
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error enhancing reasoning: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to enhance reasoning: {str(e)}"
            )
    
    async def get_club_picks_statistics(self, club_id: str) -> Dict:
        """
        Get statistics for club picks
        
        Args:
            club_id: Club name-based ID
            
        Returns:
            Dict containing statistics
        """
        # Build base query
        base_query = {
            "club_id": club_id,
            "is_active": True
        }
        
        # Total picks
        total_picks = await self.picks_collection.count_documents(base_query)
        
        # Pending picks
        pending_picks = await self.picks_collection.count_documents({
            **base_query,
            "status": "pending"
        })
        
        # Completed picks
        completed_picks = await self.picks_collection.count_documents({
            **base_query,
            "status": "completed"
        })
        
        # Wins
        wins = await self.picks_collection.count_documents({
            **base_query,
            "status": "completed",
            "result": "win"
        })
        
        # Losses
        losses = await self.picks_collection.count_documents({
            **base_query,
            "status": "completed",
            "result": "loss"
        })
        
        # Calculate win percentage
        win_percentage = (wins / completed_picks * 100) if completed_picks > 0 else 0.0
        
        return {
            "club_id": club_id,
            "total_picks": total_picks,
            "pending_picks": pending_picks,
            "completed_picks": completed_picks,
            "wins": wins,
            "losses": losses,
            "win_percentage": round(win_percentage, 2)
        }
    
    async def get_club_leaderboard(self, club_id: str, user_id: str) -> Dict:
        """
        Get leaderboard for a specific club showing captain and moderators performance
        
        Args:
            club_id: Club name-based ID
            user_id: User ID requesting the leaderboard (for authorization)
            
        Returns:
            Dict containing leaderboard data
            
        Raises:
            HTTPException if club not found or user not authorized
        """
        # Get club details
        club = await self.clubs_collection.find_one({"name_based_id": club_id})
        
        if not club:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Club not found"
            )
        
        # Check if user has access using centralized role determination
        from .my_clubs_service import MyClubsService
        my_clubs_service = MyClubsService()
        
        user_role = await my_clubs_service._determine_user_role_in_club(user_id, str(club["_id"]))
        logger.info(f"User {user_id} has role '{user_role}' in club {club_id}")
        
        # Check if user has access (is captain, moderator, or member of the club)
        has_access = user_role in ["Captain", "Moderator", "Member"]
        
        if not has_access:
            logger.warning(f"User {user_id} denied access to leaderboard for club {club_id} - role: {user_role}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only club members, captains, and moderators can view the leaderboard"
            )
        
        # Get users collection for user details
        from .db import get_user_collection
        users_collection = get_user_collection()
        
        # Get captain and moderators from club
        captain_id = club.get("captain_id")
        moderators = club.get("moderators", [])
        detailed_moderators = club.get("detailed_moderators", [])
        
        # Build list of participants (captain + moderators)
        participants = []
        added_user_ids = set()
        
        # Add captain
        if captain_id:
            participants.append({
                "user_id": captain_id,
                "role": "captain"
            })
            added_user_ids.add(captain_id)
        
        # Add moderators from moderators array
        for mod in moderators:
            if isinstance(mod, dict) and mod.get("user_id"):
                # Only include active moderators
                if mod.get("status") == "active" and mod.get("user_id") not in added_user_ids:
                    participants.append({
                        "user_id": mod.get("user_id"),
                        "role": "moderator"
                    })
                    added_user_ids.add(mod.get("user_id"))
        
        # Add moderators from detailed_moderators array
        for mod in detailed_moderators:
            if isinstance(mod, dict) and mod.get("user_id"):
                # Only include active moderators who haven't been added yet
                if mod.get("status") == "active" and mod.get("user_id") not in added_user_ids:
                    participants.append({
                        "user_id": mod.get("user_id"),
                        "role": "moderator"
                    })
                    added_user_ids.add(mod.get("user_id"))
        
        # Calculate stats for each participant
        leaderboard_data = []
        
        for participant in participants:
            participant_user_id = participant["user_id"]
            participant_role = participant["role"]
            
            # Get user details from users collection
            user = await users_collection.find_one({"_id": ObjectId(participant_user_id)})
            
            if not user:
                continue  # Skip if user not found
            
            # Get picks statistics for this user in this club
            base_query = {
                "club_id": club_id,
                "submitted_by": participant_user_id,
                "is_active": True
            }
            
            total_picks = await self.picks_collection.count_documents(base_query)
            
            pending = await self.picks_collection.count_documents({
                **base_query,
                "status": "pending"
            })
            
            wins = await self.picks_collection.count_documents({
                **base_query,
                "status": "completed",
                "result": "win"
            })
            
            losses = await self.picks_collection.count_documents({
                **base_query,
                "status": "completed",
                "result": "loss"
            })
            
            completed = wins + losses
            win_percentage = (wins / total_picks * 100) if total_picks > 0 else 0.0
            
            leaderboard_data.append({
                "user_id": participant_user_id,
                "full_name": user.get("full_name", "Unknown"),
                "user_role": participant_role,
                "total_picks": total_picks,
                "wins": wins,
                "losses": losses,
                "pending": pending,
                "win_percentage": round(win_percentage, 2),
                "avatar_url": user.get("avatar_url")
            })
        
        # Sort by win percentage (descending), then by wins (descending), then by total picks (descending)
        leaderboard_data.sort(key=lambda x: (-x["win_percentage"], -x["wins"], -x["total_picks"]))
        
        # Add rank with tie-breaking logic
        # Users with same total_picks, win_percentage, and wins get the same rank
        current_rank = 1
        for idx, entry in enumerate(leaderboard_data):
            if idx > 0:
                prev_entry = leaderboard_data[idx - 1]
                # Check if current entry has same stats as previous entry
                if (entry["total_picks"] == prev_entry["total_picks"] and
                    entry["win_percentage"] == prev_entry["win_percentage"] and
                    entry["wins"] == prev_entry["wins"]):
                    # Same stats, same rank
                    entry["rank"] = prev_entry["rank"]
                else:
                    # Different stats, new rank (skip positions for ties)
                    current_rank = idx + 1
                    entry["rank"] = current_rank
            else:
                # First entry always gets rank 1
                entry["rank"] = 1
        
        return {
            "club_id": club_id,
            "club_name": club.get("name", ""),
            "total_participants": len(leaderboard_data),
            "leaderboard": leaderboard_data
        }
    
    async def get_global_leaderboard(self, page: int = 1, limit: int = 20, search: str = None) -> Dict:
        """
        Get global leaderboard showing all captains and moderators from all clubs
        
        Shows ALL active captains and moderators across all active clubs,
        even if they haven't submitted any picks (will show 0s).
        
        Args:
            page: Page number
            limit: Items per page
            search: Optional search term to filter by club name or user full name
            
        Returns:
            Dict containing global leaderboard data with pagination
        """
        from .db import get_user_collection
        users_collection = get_user_collection()
        
        logger.info("Starting global leaderboard generation")
        
        # Get all clubs using single optimized query
        clubs_pipeline = [
            {
                "$match": {
                    "$or": [
                        {"status": "approved"},
                        {"is_active": True},
                        {"status": {"$exists": False}},
                        {"is_active": {"$exists": False}}
                    ]
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "name_based_id": 1,
                    "name": 1,
                    "captain_id": 1,
                    "moderators": 1,
                    "detailed_moderators": 1
                }
            }
        ]
        
        clubs_cursor = self.clubs_collection.aggregate(clubs_pipeline)
        clubs = await clubs_cursor.to_list(length=None)
        
        logger.info(f"Found {len(clubs)} clubs for global leaderboard")
        
        # Create club lookup dictionary for quick access
        clubs_dict = {}
        for club in clubs:
            club_id = club.get("name_based_id")
            if club_id:
                clubs_dict[club_id] = {
                    "name": club.get("name", ""),
                    "captain_id": club.get("captain_id"),
                    "detailed_moderators": club.get("detailed_moderators", [])
                }
        
        # Get ALL users who have submitted picks (not just captains/moderators)
        # This ensures users who submitted picks are included even if they're not captains/moderators
        picks_pipeline = [
            {
                "$match": {
                    "is_active": True
                }
            },
            {
                "$group": {
                    "_id": {
                        "submitted_by": "$submitted_by",
                        "club_id": "$club_id"
                    },
                    "total_picks": {"$sum": 1},
                    "wins": {
                        "$sum": {
                            "$cond": [
                                {"$and": [
                                    {"$eq": ["$status", "completed"]},
                                    {"$eq": ["$result", "win"]}
                                ]}, 1, 0
                            ]
                        }
                    },
                    "losses": {
                        "$sum": {
                            "$cond": [
                                {"$and": [
                                    {"$eq": ["$status", "completed"]},
                                    {"$eq": ["$result", "loss"]}
                                ]}, 1, 0
                            ]
                        }
                    }
                }
            }
        ]
        
        picks_cursor = self.picks_collection.aggregate(picks_pipeline)
        picks_stats = await picks_cursor.to_list(length=None)
        
        logger.info(f"Found {len(picks_stats)} user-club combinations with picks")
        
        # Build all_participants from picks data
        all_participants = []
        picks_dict = {}
        unique_user_ids = set()
        
        for stat in picks_stats:
            user_id = stat["_id"]["submitted_by"]
            club_id = stat["_id"]["club_id"]
            
            # Get club info
            club_info = clubs_dict.get(club_id)
            if not club_info:
                # Club not found in approved clubs, skip
                continue
            
            club_name = club_info["name"]
            
            # Determine user role in this club
            user_role = "member"  # Default
            if user_id == club_info["captain_id"]:
                user_role = "captain"
            else:
                # Check if user is a moderator
                for mod in club_info["detailed_moderators"]:
                    if isinstance(mod, dict) and mod.get("user_id") == user_id and mod.get("status") == "active":
                        user_role = "moderator"
                        break
            
            # Add participant
            all_participants.append({
                "user_id": user_id,
                "role": user_role,
                "club_id": club_id,
                "club_name": club_name
            })
            
            # Store picks stats
            picks_dict[f"{user_id}_{club_id}"] = {
                "total_picks": stat["total_picks"],
                "wins": stat["wins"],
                "losses": stat["losses"]
            }
            
            unique_user_ids.add(user_id)
        
        logger.info(f"Total participants found: {len(all_participants)}")
        logger.info(f"Unique user IDs: {len(unique_user_ids)}")
        
        # Batch fetch users
        users_cursor = users_collection.find(
            {"_id": {"$in": [ObjectId(uid) for uid in unique_user_ids]}},
            {"_id": 1, "full_name": 1, "avatar_url": 1}
        )
        users = await users_cursor.to_list(length=None)
        users_dict = {str(user["_id"]): user for user in users}
        
        logger.info(f"Fetched {len(users)} user details")
        
        # Build leaderboard data
        leaderboard_data = []
        
        for participant in all_participants:
            user_id = participant["user_id"]
            user = users_dict.get(user_id)
            
            if not user:
                logger.warning(f"User not found: {user_id}")
                continue
            
            # Get stats from aggregation result
            stats_key = f"{user_id}_{participant['club_id']}"
            stats = picks_dict.get(stats_key, {"total_picks": 0, "wins": 0, "losses": 0})
            
            total_picks = stats["total_picks"]
            wins = stats["wins"]
            losses = stats["losses"]
            completed = wins + losses
            win_percentage = (wins / total_picks * 100) if total_picks > 0 else 0.0
            
            # Only include users with at least 1 pick (exclude 0 picks)
            if total_picks > 0:
                entry_data = {
                    "user_id": user_id,
                    "full_name": user.get("full_name", "Unknown"),
                    "user_role": participant["role"],
                    "club_id": participant["club_id"],
                    "club_name": participant["club_name"],
                    "total_picks": total_picks,
                    "wins": wins,
                    "losses": losses,
                    "win_percentage": round(win_percentage, 2),
                    "avatar_url": user.get("avatar_url")
                }
                
                leaderboard_data.append(entry_data)
        
        logger.info(f"Total leaderboard entries created: {len(leaderboard_data)}")
        
        # Apply search filter if provided (case-insensitive)
        if search and search.strip():
            search_term = search.strip().lower()
            total_before_filter = len(leaderboard_data)
            logger.info(f"Applying search filter: '{search}' (normalized: '{search_term}') to {total_before_filter} entries")
            filtered_data = []
            
            for entry in leaderboard_data:
                # Normalize strings: convert to lowercase and strip whitespace
                club_name = (entry.get("club_name") or "").strip().lower()
                full_name = (entry.get("full_name") or "").strip().lower()
                
                # Check if search term is contained in club name or full name
                club_name_match = search_term in club_name
                full_name_match = search_term in full_name
                
                if club_name_match or full_name_match:
                    filtered_data.append(entry)
                    logger.debug(f"✓ Match - Club: '{club_name}' | User: '{full_name}'")
            
            leaderboard_data = filtered_data
            logger.info(f"Global leaderboard search: '{search}' - {len(filtered_data)} of {total_before_filter} entries matched")
        
        # Sort by wins (descending) first, then by total_picks (descending) for tie-breaking
        # Win percentage is ignored in sorting - only wins and total_picks matter
        leaderboard_data.sort(key=lambda x: (-x["wins"], -x["total_picks"]))
        
        # Add rank with tie-breaking logic BEFORE pagination (Dense Ranking)
        # Users with same wins and total_picks get the same rank
        # Next different user gets the next sequential rank (e.g., 1, 1, 1, 2, 3...)
        current_rank = 1
        for idx, entry in enumerate(leaderboard_data):
            if idx > 0:
                prev_entry = leaderboard_data[idx - 1]
                # Check if current entry has same wins and total_picks as previous entry
                if (entry["wins"] == prev_entry["wins"] and
                    entry["total_picks"] == prev_entry["total_picks"]):
                    # Same stats, same rank
                    entry["rank"] = prev_entry["rank"]
                else:
                    # Different stats, increment rank by 1 (dense ranking)
                    current_rank += 1
                    entry["rank"] = current_rank
            else:
                # First entry always gets rank 1
                entry["rank"] = 1
        
        # Apply pagination AFTER ranking
        total_count = len(leaderboard_data)
        skip = (page - 1) * limit
        paginated_data = leaderboard_data[skip:skip + limit]
        
        total_pages = math.ceil(total_count / limit) if limit > 0 else 0
        
        logger.info(f"Final result: {total_count} total participants, {len(paginated_data)} on page {page}")
        
        return {
            "total_participants": total_count,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "leaderboard": paginated_data
        }
    
    async def get_clubwise_leaderboard(self, user_id: str, page: int = 1, limit: int = 20, search: str = None) -> Dict:
        """
        Get clubwise leaderboard showing rankings from clubs the user is part of
        
        Args:
            user_id: User ID requesting the leaderboard
            page: Page number
            limit: Items per page
            search: Optional search term to filter by club name or user full name
            
        Returns:
            Dict containing clubwise leaderboard data with pagination
        """
        from .db import get_user_collection
        users_collection = get_user_collection()
        
        logger.info(f"Starting clubwise leaderboard generation for user {user_id}")
        
        # Find user's clubs - check all possible roles
        user_clubs_data = []
        
        # 1. Find clubs where user is captain
        captain_clubs = await self.clubs_collection.find({"captain_id": user_id}).to_list(length=None)
        user_clubs_data.extend(captain_clubs)
        logger.info(f"Found {len(captain_clubs)} clubs where user is captain")
        
        # 2. Find clubs where user is moderator
        moderator_clubs = await self.clubs_collection.find({
            "$or": [
                {"moderators.user_id": user_id, "moderators.status": "active"},
                {"detailed_moderators.user_id": user_id, "detailed_moderators.status": "active"}
            ]
        }).to_list(length=None)
        user_clubs_data.extend(moderator_clubs)
        logger.info(f"Found {len(moderator_clubs)} clubs where user is moderator")
        
        # 3. Find clubs where user is a member (from members array)
        member_clubs = await self.clubs_collection.find({
            "members.user_id": user_id
        }).to_list(length=None)
        user_clubs_data.extend(member_clubs)
        logger.info(f"Found {len(member_clubs)} clubs where user is in members array")
        
        # 4. Find clubs where user is a paid member (from paid_members array)
        paid_member_clubs = await self.clubs_collection.find({
            "paid_members.user_id": user_id
        }).to_list(length=None)
        user_clubs_data.extend(paid_member_clubs)
        logger.info(f"Found {len(paid_member_clubs)} clubs where user is in paid_members array")
        
        # 5. Find clubs from memberships collection
        memberships = await self.memberships_collection.find({
            "user_id": user_id,
            "subscription_status": "active"
        }).to_list(length=None)
        
        if memberships:
            membership_club_ids = [ObjectId(m.get("club_id")) for m in memberships]
            membership_clubs_cursor = self.clubs_collection.find({
                "_id": {"$in": membership_club_ids}
            })
            membership_clubs = await membership_clubs_cursor.to_list(length=None)
            user_clubs_data.extend(membership_clubs)
            logger.info(f"Found {len(membership_clubs)} clubs from memberships collection")
        
        # Remove duplicates and format
        unique_clubs = {}
        for club in user_clubs_data:
            club_id = club.get("name_based_id")
            if club_id and club_id not in unique_clubs:
                # Check if club is active
                club_status = club.get("status", "")
                club_is_active = club.get("is_active", True)
                
                # Include club if it's active (approved, active, or no status field)
                if (club_status == "approved" or club_is_active or 
                    club_status == "active" or not club_status):
                    unique_clubs[club_id] = {
                        "club_id": club_id,
                        "club_name": club.get("name"),
                        "club_logo_url": club.get("logo_url"),
                        "club_data": club
                    }
        
        user_clubs = list(unique_clubs.values())
        
        logger.info(f"Found {len(user_clubs)} unique active clubs for user {user_id}")
        
        # Log club details for debugging
        for i, club in enumerate(user_clubs[:3]):  # Log first 3 clubs
            logger.info(f"Club {i+1}: {club['club_name']} (ID: {club['club_id']})")
        
        # Create club lookup dictionary for quick access
        clubs_dict = {}
        club_ids_list = []
        for user_club in user_clubs:
            club_id = user_club["club_id"]
            club_data = user_club["club_data"]
            club_ids_list.append(club_id)
            clubs_dict[club_id] = {
                "name": user_club["club_name"],
                "logo_url": user_club["club_logo_url"],
                "captain_id": club_data.get("captain_id"),
                "detailed_moderators": club_data.get("detailed_moderators", [])
            }
        
        # Get ALL users who have submitted picks in user's clubs (not just captains/moderators)
        # This ensures all users who submitted picks are included
        picks_pipeline = [
            {
                "$match": {
                    "is_active": True,
                    "club_id": {"$in": club_ids_list}  # Only picks from user's clubs
                }
            },
            {
                "$group": {
                    "_id": {
                        "submitted_by": "$submitted_by",
                        "club_id": "$club_id"
                    },
                    "total_picks": {"$sum": 1},
                    "wins": {
                        "$sum": {
                            "$cond": [
                                {"$and": [
                                    {"$eq": ["$status", "completed"]},
                                    {"$eq": ["$result", "win"]}
                                ]}, 1, 0
                            ]
                        }
                    },
                    "losses": {
                        "$sum": {
                            "$cond": [
                                {"$and": [
                                    {"$eq": ["$status", "completed"]},
                                    {"$eq": ["$result", "loss"]}
                                ]}, 1, 0
                            ]
                        }
                    }
                }
            }
        ]
        
        picks_cursor = self.picks_collection.aggregate(picks_pipeline)
        picks_stats = await picks_cursor.to_list(length=None)
        
        logger.info(f"Found {len(picks_stats)} user-club combinations with picks in user's clubs")
        
        # Build all_participants from picks data
        all_participants = []
        picks_dict = {}
        unique_user_ids = set()
        
        for stat in picks_stats:
            pick_user_id = stat["_id"]["submitted_by"]
            club_id = stat["_id"]["club_id"]
            
            # Get club info
            club_info = clubs_dict.get(club_id)
            if not club_info:
                # Club not found, skip
                continue
            
            club_name = club_info["name"]
            club_logo_url = club_info["logo_url"]
            
            # Determine user role in this club
            user_role = "member"  # Default
            if pick_user_id == club_info["captain_id"]:
                user_role = "captain"
            else:
                # Check if user is a moderator
                for mod in club_info["detailed_moderators"]:
                    if isinstance(mod, dict) and mod.get("user_id") == pick_user_id and mod.get("status") == "active":
                        user_role = "moderator"
                        break
            
            # Add participant
            all_participants.append({
                "user_id": pick_user_id,
                "role": user_role,
                "club_id": club_id,
                "club_name": club_name,
                "club_logo_url": club_logo_url
            })
            
            # Store picks stats
            picks_dict[f"{pick_user_id}_{club_id}"] = {
                "total_picks": stat["total_picks"],
                "wins": stat["wins"],
                "losses": stat["losses"]
            }
            
            unique_user_ids.add(pick_user_id)
        
        logger.info(f"Total participants found: {len(all_participants)}")
        logger.info(f"Unique user IDs: {len(unique_user_ids)}")
        
        # Batch fetch users
        users_cursor = users_collection.find(
            {"_id": {"$in": [ObjectId(uid) for uid in unique_user_ids]}},
            {"_id": 1, "full_name": 1, "avatar_url": 1}
        )
        users = await users_cursor.to_list(length=None)
        users_dict = {str(user["_id"]): user for user in users}
        
        logger.info(f"Fetched {len(users)} user details")
        
        # Build leaderboard data
        leaderboard_data = []
        
        for participant in all_participants:
            user_id_participant = participant["user_id"]
            user = users_dict.get(user_id_participant)
            
            if not user:
                continue
            
            # Get stats from aggregation result
            stats_key = f"{user_id_participant}_{participant['club_id']}"
            stats = picks_dict.get(stats_key, {"total_picks": 0, "wins": 0, "losses": 0})
            
            total_picks = stats["total_picks"]
            wins = stats["wins"]
            losses = stats["losses"]
            completed = wins + losses
            win_percentage = (wins / total_picks * 100) if total_picks > 0 else 0.0
            
            # Only include users with at least 1 pick (exclude 0 picks)
            if total_picks > 0:
                leaderboard_data.append({
                    "club_id": participant["club_id"],
                    "club_name": participant["club_name"],
                    "club_logo_url": participant["club_logo_url"],
                    "user_id": user_id_participant,
                    "full_name": user.get("full_name", "Unknown"),
                    "user_role": participant["role"],
                    "total_picks": total_picks,
                    "wins": wins,
                    "losses": losses,
                    "win_percentage": round(win_percentage, 2),
                    "avatar_url": user.get("avatar_url")
                })
        
        # Apply search filter if provided (case-insensitive)
        if search and search.strip():
            search_term = search.strip().lower()
            total_before_filter = len(leaderboard_data)
            logger.info(f"Applying search filter: '{search}' (normalized: '{search_term}') to {total_before_filter} entries")
            filtered_data = []
            print(leaderboard_data,"leaderboard_dataleaderboard_dataleaderboard_data")
            for entry in leaderboard_data:
                # Normalize strings: convert to lowercase and strip whitespace
                club_name = (entry.get("club_name") or "").strip().lower()
                full_name = (entry.get("full_name") or "").strip().lower()
                
                # Check if search term is contained in club name or full name
                club_name_match = search_term in club_name
                full_name_match = search_term in full_name
                
                if club_name_match or full_name_match:
                    filtered_data.append(entry)
                    logger.debug(f"✓ Match - Club: '{club_name}' | User: '{full_name}'")
            
            leaderboard_data = filtered_data
            logger.info(f"Clubwise leaderboard search: '{search}' - {len(filtered_data)} of {total_before_filter} entries matched")
        
        # Sort by wins (descending) first, then by total_picks (descending) for tie-breaking
        # Win percentage is ignored in sorting - only wins and total_picks matter
        leaderboard_data.sort(key=lambda x: (-x["wins"], -x["total_picks"]))
        
        # Add rank with tie-breaking logic BEFORE pagination (Dense Ranking)
        # Users with same wins and total_picks get the same rank
        # Next different user gets the next sequential rank (e.g., 1, 1, 1, 2, 3...)
        current_rank = 1
        for idx, entry in enumerate(leaderboard_data):
            if idx > 0:
                prev_entry = leaderboard_data[idx - 1]
                # Check if current entry has same wins and total_picks as previous entry
                if (entry["wins"] == prev_entry["wins"] and
                    entry["total_picks"] == prev_entry["total_picks"]):
                    # Same stats, same rank
                    entry["rank"] = prev_entry["rank"]
                else:
                    # Different stats, increment rank by 1 (dense ranking)
                    current_rank += 1
                    entry["rank"] = current_rank
            else:
                # First entry always gets rank 1
                entry["rank"] = 1
        
        # Apply pagination AFTER ranking
        total_count = len(leaderboard_data)
        skip = (page - 1) * limit
        paginated_data = leaderboard_data[skip:skip + limit]
        
        total_pages = math.ceil(total_count / limit) if limit > 0 else 0
        
        logger.info(f"Final result: {total_count} total participants, {len(paginated_data)} on page {page}")
        
        return {
            "user_id": user_id,
            "total_clubs": len(user_clubs),
            "total_participants": total_count,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "leaderboard": paginated_data
        }


# Singleton instance
_service_instance = None

def reset_club_picks_service():
    """Reset the singleton instance (useful for testing/reloading)"""
    global _service_instance
    _service_instance = None
    logger.info("Reset ClubPicksService singleton instance")

def get_club_picks_service() -> ClubPicksService:
    """Get singleton instance of ClubPicksService"""
    global _service_instance
    
    # Always check if instance exists and has required methods
    if _service_instance is None:
        _service_instance = ClubPicksService()
        logger.info("Created new ClubPicksService instance")
    else:
        # Check for required method - if missing, recreate instance
        try:
            if not hasattr(_service_instance, 'enhance_reasoning_text'):
                logger.warning("ClubPicksService instance missing enhance_reasoning_text method, recreating...")
                _service_instance = ClubPicksService()
                logger.info("Recreated ClubPicksService instance with enhance_reasoning_text method")
        except Exception as e:
            logger.error(f"Error checking service instance: {e}, recreating...")
            _service_instance = ClubPicksService()
    
    return _service_instance

