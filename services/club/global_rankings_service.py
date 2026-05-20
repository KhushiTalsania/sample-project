"""
Global Rankings Service

This service provides global rankings functionality for all club captains and moderators
across all clubs, showing their performance statistics including win rates, total picks,
and total wins.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from bson import ObjectId
import logging
from pydantic import BaseModel, Field
from enum import Enum

logger = logging.getLogger(__name__)


class RankingType(str, Enum):
    GLOBAL = "global"
    CLUB = "club"


class TimePeriod(str, Enum):
    ALL_TIME = "all_time"
    LAST_30_DAYS = "last_30_days"
    LAST_7_DAYS = "last_7_days"
    LAST_3_MONTHS = "last_3_months"


class PickType(str, Enum):
    ALL_TYPES = "all_types"
    SINGLE = "single"
    PARLAY = "parlay"


class RankIcon(str, Enum):
    CROWN = "crown"
    DIAMOND = "diamond"
    SHIELD = "shield"
    MEDAL = "medal"
    STAR = "star"


class UserRanking(BaseModel):
    rank: int = Field(..., description="User's rank position")
    rank_icon: RankIcon = Field(..., description="Icon representing the rank")
    user_id: str = Field(..., description="User's ID")
    user_name: str = Field(..., description="User's full name")
    user_avatar: Optional[str] = Field(None, description="User's avatar URL")
    user_role: str = Field(..., description="User's role (Captain/Moderator)")
    club_name: str = Field(..., description="Club name the user belongs to")
    total_picks: int = Field(..., description="Total number of picks made")
    win_rate: float = Field(..., description="Win percentage")
    total_wins: int = Field(..., description="Total number of wins")
    total_losses: int = Field(..., description="Total number of losses")
    total_pending: int = Field(..., description="Total number of pending picks")
    profit_loss: float = Field(default=0.0, description="Total profit/loss")


class GlobalRankingsResponse(BaseModel):
    success: bool = Field(..., description="Success status")
    message: str = Field(..., description="Response message")
    data: Dict[str, Any] = Field(..., description="Rankings data")
    filters: Dict[str, Any] = Field(..., description="Applied filters")
    pagination: Dict[str, Any] = Field(..., description="Pagination information")


class GlobalRankingsService:
    """Service for managing global rankings across all clubs"""
    
    def __init__(self):
        from core.database.collections import get_collections
        from .db import get_club_collection, get_user_collection
        
        self.collections = get_collections()
        self.clubs_collection = get_club_collection()  # Use the same function as existing routes
        self.club_picks_collection = self.collections.get_club_picks_collection()
        self.users_collection = get_user_collection()  # Use the same function as existing routes

    async def get_global_rankings(
        self,
        ranking_type: RankingType = RankingType.GLOBAL,
        time_period: TimePeriod = TimePeriod.ALL_TIME,
        pick_type: PickType = PickType.ALL_TYPES,
        top_limit: int = 100,
        page: int = 1,
        page_size: int = 20
    ) -> GlobalRankingsResponse:
        """
        Get global rankings for club captains and moderators
        
        Args:
            ranking_type: Type of ranking (global or club-specific)
            time_period: Time period for filtering picks
            pick_type: Type of picks to include
            top_limit: Maximum number of users to rank
            page: Page number for pagination
            page_size: Number of items per page
            
        Returns:
            GlobalRankingsResponse with rankings data
        """
        try:
            logger.info(f"Getting global rankings with filters: {ranking_type}, {time_period}, {pick_type}")
            
            # Calculate date range based on time period
            date_filter = self._get_date_filter(time_period)
            
            # Build pick filter
            pick_filter = self._build_pick_filter(date_filter, pick_type)
            
            # Get all picks with the applied filters
            picks_cursor = self.club_picks_collection.find(pick_filter)
            
            # Aggregate statistics by user
            user_stats = await self._aggregate_user_stats(picks_cursor)
            
            # Get all captains and moderators from clubs (including those with no picks)
            all_captains_moderators = await self._get_all_captains_and_moderators()
            
            # Merge pick stats with all captains/moderators
            combined_stats = self._merge_user_stats(user_stats, all_captains_moderators)
            
            # Get user details and club information
            rankings = await self._build_rankings(combined_stats, ranking_type)
            
            # Apply pagination
            total_count = len(rankings)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_rankings = rankings[start_idx:end_idx]
            
            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_prev = page > 1
            
            response_data = {
                "rankings": paginated_rankings,
                "total_count": total_count,
                "top_performers": rankings[:3] if len(rankings) >= 3 else rankings
            }
            
            filters = {
                "ranking_type": ranking_type.value,
                "time_period": time_period.value,
                "pick_type": pick_type.value,
                "top_limit": top_limit
            }
            
            pagination = {
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_count": total_count,
                "has_next": has_next,
                "has_prev": has_prev
            }
            
            return GlobalRankingsResponse(
                success=True,
                message="Global rankings retrieved successfully",
                data=response_data,
                filters=filters,
                pagination=pagination
            )
            
        except Exception as e:
            logger.error(f"Error getting global rankings: {e}")
            return GlobalRankingsResponse(
                success=False,
                message=f"Error retrieving rankings: {str(e)}",
                data={},
                filters={},
                pagination={}
            )

    def _get_date_filter(self, time_period: TimePeriod) -> Dict[str, Any]:
        """Get date filter based on time period"""
        now = datetime.utcnow()
        
        if time_period == TimePeriod.ALL_TIME:
            return {}
        elif time_period == TimePeriod.LAST_7_DAYS:
            start_date = now - timedelta(days=7)
        elif time_period == TimePeriod.LAST_30_DAYS:
            start_date = now - timedelta(days=30)
        elif time_period == TimePeriod.LAST_3_MONTHS:
            start_date = now - timedelta(days=90)
        else:
            return {}
        
        return {
            "date_submitted": {
                "$gte": start_date
            }
        }

    def _build_pick_filter(self, date_filter: Dict[str, Any], pick_type: PickType) -> Dict[str, Any]:
        """Build the complete filter for picks"""
        filter_dict = {
            "submitted_by_id": {"$exists": True, "$ne": None},
            "outcome": {"$in": ["win", "loss", "pending"]}  # Exclude cancelled/void picks
        }
        
        # Add date filter
        if date_filter:
            filter_dict.update(date_filter)
        
        # Add pick type filter
        if pick_type != PickType.ALL_TYPES:
            filter_dict["pick_type"] = pick_type.value
        
        return filter_dict

    async def _aggregate_user_stats(self, picks_cursor) -> Dict[str, Dict[str, Any]]:
        """Aggregate statistics by user from picks cursor"""
        user_stats = {}
        
        async for pick in picks_cursor:
            user_id = pick.get("submitted_by_id")
            if not user_id:
                continue
            
            if user_id not in user_stats:
                user_stats[user_id] = {
                    "total_picks": 0,
                    "total_wins": 0,
                    "total_losses": 0,
                    "total_pending": 0,
                    "total_profit_loss": 0.0,
                    "club_ids": set()
                }
            
            stats = user_stats[user_id]
            stats["total_picks"] += 1
            
            # Track club IDs
            club_id = pick.get("club_id")
            if club_id:
                stats["club_ids"].add(club_id)
            
            # Count outcomes
            outcome = pick.get("outcome", "pending")
            if outcome == "win":
                stats["total_wins"] += 1
            elif outcome == "loss":
                stats["total_losses"] += 1
            elif outcome == "pending":
                stats["total_pending"] += 1
            
            # Calculate profit/loss
            profit_loss = pick.get("profit_loss", 0.0)
            if profit_loss:
                stats["total_profit_loss"] += profit_loss
        
        # Convert sets to lists for JSON serialization
        for user_id in user_stats:
            user_stats[user_id]["club_ids"] = list(user_stats[user_id]["club_ids"])
        
        return user_stats

    async def _get_all_captains_and_moderators(self) -> Dict[str, Dict[str, Any]]:
        """Get all captains and moderators from all clubs, including those with no picks"""
        all_users = {}
        
        try:
            # First, let's check total clubs in collection
            total_clubs_in_db = await self.clubs_collection.count_documents({})
            print(f"Total clubs in database: {total_clubs_in_db}")
            
            # Check clubs with different statuses
            approved_clubs = await self.clubs_collection.count_documents({"status": "approved"})
            print(f"Approved clubs: {approved_clubs}")
            
            active_clubs = await self.clubs_collection.count_documents({"is_active": True})
            print(f"Active clubs (is_active=True): {active_clubs}")
            
            # Use the same query pattern as the working get_clubs function
            query = {"status": "approved"}  # Same as build_filter_query function
            print(f"Using query: {query}")
            
            clubs_cursor = self.clubs_collection.find(query)
            print(f"Clubs cursor: {clubs_cursor}")
            
            # Count total clubs first
            total_clubs = await self.clubs_collection.count_documents(query)
            print(f"Total approved clubs found: {total_clubs}")
            
            # If no approved clubs found, try with is_active
            if total_clubs == 0:
                print("No approved clubs found, trying with is_active=True")
                query = {"is_active": True}
                clubs_cursor = self.clubs_collection.find(query)
                total_clubs = await self.clubs_collection.count_documents(query)
                print(f"Total active clubs found: {total_clubs}")
            
            # If still no clubs, try without any filters
            if total_clubs == 0:
                print("No active/approved clubs found, trying all clubs")
                query = {}
                clubs_cursor = self.clubs_collection.find(query)
                total_clubs = await self.clubs_collection.count_documents(query)
                print(f"Total clubs found (no filters): {total_clubs}")
            
            async for club in clubs_cursor:
                club_id = str(club["_id"])
                club_name = club.get("name", "Unknown Club")
                print(f"Processing club: {club_name} (ID: {club_id})")
                
                # Add captain
                captain_id = club.get("captain_id")
                print(f"  Captain ID: {captain_id}")
                if captain_id:
                    if captain_id not in all_users:
                        all_users[captain_id] = {
                            "total_picks": 0,
                            "total_wins": 0,
                            "total_losses": 0,
                            "total_pending": 0,
                            "total_profit_loss": 0.0,
                            "club_ids": set(),
                            "is_captain": True,
                            "is_moderator": False
                        }
                    all_users[captain_id]["club_ids"].add(club_id)
                    print(f"  Added captain: {captain_id}")
                
                # Add moderators
                moderators = club.get("detailed_moderators", [])
                print(f"  Moderators found: {len(moderators)}")
                for moderator in moderators:
                    moderator_id = moderator.get("user_id")
                    print(f"    Moderator ID: {moderator_id}")
                    if moderator_id:
                        if moderator_id not in all_users:
                            all_users[moderator_id] = {
                                "total_picks": 0,
                                "total_wins": 0,
                                "total_losses": 0,
                                "total_pending": 0,
                                "total_profit_loss": 0.0,
                                "club_ids": set(),
                                "is_captain": False,
                                "is_moderator": True
                            }
                        all_users[moderator_id]["club_ids"].add(club_id)
                        print(f"    Added moderator: {moderator_id}")
            
            # Convert sets to lists for JSON serialization
            for user_id in all_users:
                all_users[user_id]["club_ids"] = list(all_users[user_id]["club_ids"])
            
            logger.info(f"Found {len(all_users)} total captains and moderators across all clubs")
            return all_users
            
        except Exception as e:
            logger.error(f"Error getting all captains and moderators: {e}")
            return {}

    def _merge_user_stats(self, pick_stats: Dict[str, Dict[str, Any]], all_users: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Merge pick statistics with all captains/moderators"""
        merged_stats = {}
        
        # Start with all captains and moderators (with default stats)
        for user_id, user_info in all_users.items():
            merged_stats[user_id] = {
                "total_picks": 0,
                "total_wins": 0,
                "total_losses": 0,
                "total_pending": 0,
                "total_profit_loss": 0.0,
                "club_ids": user_info["club_ids"],
                "is_captain": user_info["is_captain"],
                "is_moderator": user_info["is_moderator"]
            }
        
        # Overlay pick statistics for users who have picks
        for user_id, pick_stat in pick_stats.items():
            if user_id in merged_stats:
                merged_stats[user_id].update(pick_stat)
        
        return merged_stats

    async def _get_club_captains_and_moderators(self, club_id: str) -> Dict[str, Dict[str, Any]]:
        """Get all captains and moderators for a specific club"""
        club_users = {}
        
        try:
            # Get the specific club
            club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                return club_users
            
            # Add captain
            captain_id = club.get("captain_id")
            if captain_id:
                club_users[captain_id] = {
                    "total_picks": 0,
                    "total_wins": 0,
                    "total_losses": 0,
                    "total_pending": 0,
                    "total_profit_loss": 0.0,
                    "club_ids": [club_id],
                    "is_captain": True,
                    "is_moderator": False
                }
            
            # Add moderators
            moderators = club.get("detailed_moderators", [])
            for moderator in moderators:
                moderator_id = moderator.get("user_id")
                if moderator_id:
                    club_users[moderator_id] = {
                        "total_picks": 0,
                        "total_wins": 0,
                        "total_losses": 0,
                        "total_pending": 0,
                        "total_profit_loss": 0.0,
                        "club_ids": [club_id],
                        "is_captain": False,
                        "is_moderator": True
                    }
            
            logger.info(f"Found {len(club_users)} captains and moderators for club {club_id}")
            return club_users
            
        except Exception as e:
            logger.error(f"Error getting club captains and moderators for club {club_id}: {e}")
            return {}

    async def _build_rankings(self, user_stats: Dict[str, Dict[str, Any]], ranking_type: RankingType) -> List[UserRanking]:
        """Build rankings list with user details"""
        rankings = []
        
        for user_id, stats in user_stats.items():
            try:
                # Get user details
                user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
                if not user:
                    continue
                
                # Get club details
                club_info = await self._get_user_club_info(user_id, stats["club_ids"], ranking_type)
                
                # Calculate win rate
                total_resolved = stats["total_wins"] + stats["total_losses"]
                win_rate = (stats["total_wins"] / total_resolved * 100) if total_resolved > 0 else 0.0
                
                # Create ranking entry
                ranking = UserRanking(
                    rank=0,  # Will be set after sorting
                    rank_icon=self._get_rank_icon(0),  # Will be set after sorting
                    user_id=user_id,
                    user_name=user.get("full_name", "Unknown User"),
                    user_avatar=user.get("avatar_url"),
                    user_role=user.get("role", "Member"),
                    club_name=club_info["club_name"],
                    total_picks=stats["total_picks"],
                    win_rate=round(win_rate, 1),
                    total_wins=stats["total_wins"],
                    total_losses=stats["total_losses"],
                    total_pending=stats["total_pending"],
                    profit_loss=round(stats["total_profit_loss"], 2)
                )
                
                rankings.append(ranking)
                
            except Exception as e:
                logger.error(f"Error building ranking for user {user_id}: {e}")
                continue
        
        # Sort rankings by win rate (descending), then by total wins (descending)
        # Users with no picks (all zeros) will be sorted to the end
        rankings.sort(key=lambda x: (x.win_rate, x.total_wins), reverse=True)
        
        # Assign ranks and icons
        for i, ranking in enumerate(rankings):
            ranking.rank = i + 1
            ranking.rank_icon = self._get_rank_icon(i + 1)
        
        return rankings

    async def _get_user_club_info(self, user_id: str, club_ids: List[str], ranking_type: RankingType) -> Dict[str, str]:
        """Get club information for a user"""
        if not club_ids:
            return {"club_name": "No Club"}
        
        try:
            if ranking_type == RankingType.GLOBAL:
                # For global rankings, show the club with most picks or first club
                club_info = {"club_name": "Multiple Clubs"}
                
                # Try to get the primary club (where user is captain or has most activity)
                for club_id in club_ids:
                    club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                    if club:
                        if club.get("captain_id") == user_id:
                            club_info["club_name"] = club.get("name", "Unknown Club")
                            break
                        elif club_info["club_name"] == "Multiple Clubs":
                            club_info["club_name"] = club.get("name", "Unknown Club")
            else:
                # For club-specific rankings, get the specific club name
                club_id = club_ids[0] if club_ids else None
                if club_id:
                    club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                    club_info = {"club_name": club.get("name", "Unknown Club") if club else "Unknown Club"}
                else:
                    club_info = {"club_name": "No Club"}
            
            return club_info
            
        except Exception as e:
            logger.error(f"Error getting club info for user {user_id}: {e}")
            return {"club_name": "Unknown Club"}

    def _get_rank_icon(self, rank: int) -> RankIcon:
        """Get rank icon based on position"""
        if rank == 1:
            return RankIcon.CROWN
        elif rank == 2:
            return RankIcon.DIAMOND
        elif rank == 3:
            return RankIcon.SHIELD
        elif rank <= 10:
            return RankIcon.MEDAL
        else:
            return RankIcon.STAR

    async def get_club_rankings(
        self,
        club_id: str,
        time_period: TimePeriod = TimePeriod.ALL_TIME,
        pick_type: PickType = PickType.ALL_TYPES,
        page: int = 1,
        page_size: int = 20
    ) -> GlobalRankingsResponse:
        """
        Get rankings for a specific club
        
        Args:
            club_id: ID of the club
            time_period: Time period for filtering picks
            pick_type: Type of picks to include
            page: Page number for pagination
            page_size: Number of items per page
            
        Returns:
            GlobalRankingsResponse with club-specific rankings
        """
        try:
            # Verify club exists
            club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                return GlobalRankingsResponse(
                    success=False,
                    message="Club not found",
                    data={},
                    filters={},
                    pagination={}
                )
            
            # Get date filter
            date_filter = self._get_date_filter(time_period)
            
            # Build pick filter with club constraint
            pick_filter = self._build_pick_filter(date_filter, pick_type)
            pick_filter["club_id"] = club_id
            
            # Get picks for this club
            picks_cursor = self.club_picks_collection.find(pick_filter)
            
            # Aggregate statistics by user
            user_stats = await self._aggregate_user_stats(picks_cursor)
            
            # Get all captains and moderators for this specific club
            club_captains_moderators = await self._get_club_captains_and_moderators(club_id)
            
            # Merge pick stats with all captains/moderators for this club
            combined_stats = self._merge_user_stats(user_stats, club_captains_moderators)
            
            # Build rankings
            rankings = await self._build_rankings(combined_stats, RankingType.CLUB)
            
            # Apply pagination
            total_count = len(rankings)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_rankings = rankings[start_idx:end_idx]
            
            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_prev = page > 1
            
            response_data = {
                "rankings": paginated_rankings,
                "total_count": total_count,
                "top_performers": rankings[:3] if len(rankings) >= 3 else rankings,
                "club_info": {
                    "club_id": club_id,
                    "club_name": club.get("name", "Unknown Club")
                }
            }
            
            filters = {
                "ranking_type": "club",
                "club_id": club_id,
                "time_period": time_period.value,
                "pick_type": pick_type.value
            }
            
            pagination = {
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_count": total_count,
                "has_next": has_next,
                "has_prev": has_prev
            }
            
            return GlobalRankingsResponse(
                success=True,
                message=f"Club rankings for {club.get('name', 'Unknown Club')} retrieved successfully",
                data=response_data,
                filters=filters,
                pagination=pagination
            )
            
        except Exception as e:
            logger.error(f"Error getting club rankings for club {club_id}: {e}")
            return GlobalRankingsResponse(
                success=False,
                message=f"Error retrieving club rankings: {str(e)}",
                data={},
                filters={},
                pagination={}
            )


# Global service instance
global_rankings_service = GlobalRankingsService()
